"""
Norwegian EHL hockey scraper.

Hämtar matcher och händelser från NIF-proxy:
  https://sf34-terminlister-prod-app.azurewebsites.net/

Proxy-endpoints som används:
  wise/tournaments                               → turneringslista (Wisehockey IDs + NIF originId)
  ta/TournamentMatches/?tournamentId={originId}  → matchlista per turnering (NIF match-IDs)
  ta/Match?matchId={nifId}                       → matchdetaljer
  icehockey/Match/Goals/{nifId}                  → mål
  icehockey/Match/Penalties/{nifId}              → straff
  icehockey/Match/Players/{nifId}                → spelarprestationer per match
  ta/TournamentStandings/?tournamentId={originId} → tabeller

OBS: Wisehockey tracking-data (shifts, momentum, period-stats) är EJ tillgänglig
via denna proxy – de endpoints returnerar "Tournament X not found in Wisehockey API".
Befintlig historisk data (match_id 1-1775) är i Wisehockey-format; ny data (NIF-IDs
~7 000 000+) kan samexistera i samma tabeller utan ID-konflikter.
"""
from __future__ import annotations

import os
import time
from typing import Any

import pandas as pd
import requests

PROXY = "https://sf34-terminlister-prod-app.azurewebsites.net"

# Wisehockey team slug → NIF org name fragment (för att normalisera lagnamn)
NIF_TEAM_NAME_MAP: dict[str, str] = {
    "IF Frisk Asker Hockey": "friskasker",
    "Frisk Asker": "friskasker",
    "Grüner Hockey": "gruner",
    "Grüner": "gruner",
    "Lillehammer IHK": "lillehammer",
    "Manglerud Star IK": "manglerud",
    "Manglerud Star": "manglerud",
    "Ringerike IHK": "ringerike",
    "Sparta Warriors": "sparta",
    "Stavanger Ishockeyklubb": "stavanger",
    "Stjernen Hockey": "stjernen",
    "Storhamar Hockey": "storhamar",
    "Storhamar": "storhamar",
    "Vålerenga Ishockey": "valerenga",
    "Vålerenga": "valerenga",
    "Comet Halden": "comet",
    "Comet": "comet",
    "Lørenskog IHK": "lorenskog",
    "Lørenskog": "lorenskog",
    "Narvik Hockey": "narvik",
    "Nidaros Hockey": "nidaros",
}

# NIF phase/type → Wisehockey phase string
NIF_PHASE_MAP: dict[str, str] = {
    "EHL": "Regular",
}


def _slug_from_name(name: str) -> str:
    """Försöker mappa NIF-lagnamn till team-slug."""
    for nif_name, slug in NIF_TEAM_NAME_MAP.items():
        if nif_name.lower() in name.lower() or name.lower() in nif_name.lower():
            return slug
    # Fallback: rensa organisationsnamn
    return name.lower().replace(" ", "_").replace("ø", "o").replace("å", "a").replace("æ", "ae")


class NorAPI:
    def __init__(self):
        self.base = PROXY
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "User-Agent": "Mozilla/5.0",
        })

    def _get(self, path: str, params: dict | None = None, retries: int = 3) -> Any:
        url = f"{self.base}/{path.lstrip('/')}"
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=30)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    return None
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except Exception:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise

    def get_tournaments(self) -> list[dict]:
        """Returnerar lista med {id, name, originId, group, year, tournamentType}."""
        data = self._get("wise/tournaments")
        if isinstance(data, dict):
            return data.get("tournaments", [])
        return data or []

    def get_tournament_matches(self, origin_id: int) -> list[dict]:
        """Returnerar NIF-matchlista för en turnering (tournamentId = originId)."""
        data = self._get("ta/TournamentMatches/", {"tournamentId": origin_id})
        if not data:
            return []
        return data.get("matches", [])

    def get_match(self, nif_match_id: int) -> dict | None:
        return self._get(f"ta/Match", {"matchId": nif_match_id})

    def get_goals(self, nif_match_id: int) -> list[dict]:
        data = self._get(f"icehockey/Match/Goals/{nif_match_id}")
        return data if isinstance(data, list) else []

    def get_penalties(self, nif_match_id: int) -> list[dict]:
        data = self._get(f"icehockey/Match/Penalties/{nif_match_id}")
        return data if isinstance(data, list) else []

    def get_players(self, nif_match_id: int) -> list[dict]:
        data = self._get(f"icehockey/Match/Players/{nif_match_id}")
        return data if isinstance(data, list) else []

    def get_standings(self, origin_id: int) -> list[dict]:
        data = self._get("ta/TournamentStandings/", {"tournamentId": origin_id})
        if not data:
            return []
        return data.get("standings", data.get("teamStandings", []))


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_matches(nif_matches: list[dict], tournament: dict) -> pd.DataFrame:
    """
    Konverterar NIF-matchlista till matches-DataFrame med samma schema som
    den befintliga Wisehockey-baserade matches.parquet.
    """
    tid = tournament["id"]
    t_name = tournament["name"]
    year = int(tournament.get("year", 0)) if tournament.get("year") else None
    phase = "Regular"
    if "Playoff" in t_name:
        phase = "Playoffs"
    elif "Qualifier" in t_name or "Qualifier" in t_name:
        phase = "Qualifiers"
    elif "Practice" in t_name:
        phase = "Practice"

    rows = []
    for m in nif_matches:
        # Hoppa över icke-avslutade matcher
        if m.get("matchResult") is None:
            continue
        result = m["matchResult"]
        if result.get("matchEndResult") in (None, "", "0-0") and result.get("homeGoals", 0) == 0 and result.get("awayGoals", 0) == 0:
            # Troligtvis ej spelad
            pass

        home_org = m.get("hometeamOrgName", m.get("hometeam", ""))
        away_org = m.get("awayteamOrgName", m.get("awayteam", ""))
        home_slug = _slug_from_name(home_org)
        away_slug = _slug_from_name(away_org)

        rows.append({
            "match_id": m["matchId"],
            "team_slug": home_slug,   # primärt lag-perspektiv = hemmalagets slug
            "match_date": m.get("matchDate"),
            "end_time": m.get("lastChangeDate"),
            "home_team_id": m.get("hometeamId"),
            "home_team_name": home_org,
            "away_team_id": m.get("awayteamId"),
            "away_team_name": away_org,
            "home_goals": result.get("homeGoals", 0),
            "away_goals": result.get("awayGoals", 0),
            "status": "Finished" if result.get("matchEndResult") else "Upcoming",
            "game_time": 3600,         # NIF ger ej sekunder
            "has_statistics": bool(result.get("matchEndResult")),
            "tournament_id": tid,
            "tournament_name": t_name,
            "season_year": year,
            "season_phase": phase,
        })
    return pd.DataFrame(rows)


def parse_goal_events(goals: list[dict], match_id: int) -> pd.DataFrame:
    rows = []
    for i, g in enumerate(goals):
        period_id = g.get("periodId", 0)
        period_num = {200050: 1, 51: 2, 52: 3, 200053: 4}.get(period_id, period_id)
        rows.append({
            "event_id": match_id * 1000 + i,       # syntetiskt event_id
            "match_id": match_id,
            "team_slug": _slug_from_name(g.get("teamName", "")),
            "timestamp": None,
            "match_time": int(g.get("periodTime", 0)) if g.get("periodTime") else None,
            "period": period_num,
            "team_id": g.get("orgId"),
            "team_name": g.get("teamName", ""),
            "home_goals": None,
            "away_goals": None,
            "goal_type": g.get("goalType"),
            "scorer_id": g.get("personId"),
            "scorer_name": f"{g.get('firstName','')} {g.get('lastName','')}".strip(),
            "assist1_id": g.get("firstAssistPersonId"),
            "assist1_name": f"{g.get('firstAssistFirstName','')} {g.get('firstAssistLastName','')}".strip() or None,
            "assist2_id": g.get("secondAssistPersonId"),
            "assist2_name": f"{g.get('secondAssistFirstName','')} {g.get('secondAssistLastName','')}".strip() or None,
        })
    return pd.DataFrame(rows)


def parse_penalty_events(penalties: list[dict], match_id: int) -> pd.DataFrame:
    rows = []
    for i, p in enumerate(penalties):
        rows.append({
            "event_id": match_id * 1000 + 500 + i,  # syntetiskt, offset 500 för att undvika krock med mål
            "match_id": match_id,
            "team_slug": _slug_from_name(p.get("teamName", "")),
            "timestamp": None,
            "match_time": p.get("servingStartTime"),
            "period": None,
            "team_id": p.get("orgId"),
            "team_name": p.get("teamName", ""),
            "duration_minutes": p.get("severityMinutes", 0),
            "reason": p.get("infractionType"),
            "info": p.get("severityType"),
            "is_team_or_official": False,
            "player_id": p.get("personId"),
            "player_name": f"{p.get('firstName','')} {p.get('lastName','')}".strip(),
        })
    return pd.DataFrame(rows)


def parse_match_lineup(players: list[dict], match_id: int) -> pd.DataFrame:
    """
    Mappar icehockey/Match/Players → match_lineup.
    Håller sig till samma kolumner som befintlig Wisehockey-baserad match_lineup
    för att MotherDuck-upserterna ska fungera utan schema-konflikter.
    """
    rows = []
    for p in players:
        rows.append({
            "match_id": match_id,
            "team_slug": _slug_from_name(p.get("teamName", "")),
            "side": None,       # NIF ger ej home/away per spelare
            "player_id": p.get("personId"),
            "first_name": p.get("firstName", ""),
            "last_name": p.get("lastName", ""),
            "jersey": p.get("shirtNo", 0),
            "role": None,
            "line_number": 0,
            "height": 0,
            "weight": 0,
            "date_of_birth": None,
            "handedness": None,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Public scrape interface
# ---------------------------------------------------------------------------

def scrape_new_matches(
    known_match_ids: set[int],
    tournament_year: int | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Hämtar nya avslutade matcher (NIF-IDs) som ej finns i known_match_ids.

    Args:
        known_match_ids: match-IDs som redan finns i MotherDuck – hoppa över dessa.
        tournament_year: om satt (t.ex. 2026), scrapa bara turneringar för det året.
                        Default: scrapa bara turneringar vars year == innevarande år
                        (förhindrar att ALLA historiska matcher laddas om vid varje körning).

    Tabeller utan Wisehockey-data returneras som tomma DataFrames:
      shifts, momentum, match_period_stats, match_powerplay_stats
    """
    from datetime import date

    if tournament_year is None:
        # Standardbeteende: aktuell säsong (september–april → år = nästa kalenderår)
        today = date.today()
        tournament_year = today.year + 1 if today.month >= 9 else today.year

    api = NorAPI()

    all_matches: list[pd.DataFrame] = []
    all_goals: list[pd.DataFrame] = []
    all_penalties: list[pd.DataFrame] = []
    all_lineup: list[pd.DataFrame] = []
    processed: set[int] = set()

    print("[nor-scraper] Hämtar turneringslista...", flush=True)
    all_tournaments = api.get_tournaments()
    # Filtrera på år
    tournaments = [
        t for t in all_tournaments
        if str(t.get("year", "")) == str(tournament_year)
    ]
    print(f"[nor-scraper] {len(all_tournaments)} turneringar totalt, "
          f"{len(tournaments)} för år {tournament_year}")

    for t in tournaments:
        tid = t["id"]
        origin_id = int(t.get("originId", 0))
        if not origin_id:
            continue

        print(f"[nor-scraper] Turnering {tid} ({t['name']}) – hämtar matcher...", flush=True)
        nif_matches = api.get_tournament_matches(origin_id)
        if not nif_matches:
            print(f"[nor-scraper]   inga matcher")
            continue

        # Filtrera ny, spelad data
        new_nif_matches = [
            m for m in nif_matches
            if m["matchId"] not in known_match_ids
            and m["matchId"] not in processed
            and m.get("matchResult") is not None
            and m["matchResult"].get("matchEndResult") not in (None, "")
        ]

        if not new_nif_matches:
            print(f"[nor-scraper]   inga nya matcher")
            continue

        print(f"[nor-scraper]   {len(new_nif_matches)} nya matcher")

        match_df = parse_matches(new_nif_matches, t)
        if not match_df.empty:
            all_matches.append(match_df)

        for m in new_nif_matches:
            mid = m["matchId"]
            print(f"[nor-scraper]   match {mid}...", flush=True)
            try:
                goals = api.get_goals(mid)
                penalties = api.get_penalties(mid)
                players = api.get_players(mid)

                if goals:
                    all_goals.append(parse_goal_events(goals, mid))
                if penalties:
                    all_penalties.append(parse_penalty_events(penalties, mid))
                if players:
                    all_lineup.append(parse_match_lineup(players, mid))

                processed.add(mid)
                time.sleep(0.1)          # skonsam mot API

            except Exception as exc:
                print(f"[nor-scraper]   FEL match {mid}: {exc}")

    def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    return {
        "matches": _concat(all_matches),
        "goal_events": _concat(all_goals),
        "penalty_events": _concat(all_penalties),
        "match_lineup": _concat(all_lineup),
        # Wisehockey tracking – kräver direkt API-åtkomst (api.wisehockey.com)
        "match_period_stats": pd.DataFrame(),
        "match_powerplay_stats": pd.DataFrame(),
        "shifts": pd.DataFrame(),
        "momentum": pd.DataFrame(),
    }


def scrape_season_summaries(tournament_ids: list[int]) -> dict[str, pd.DataFrame]:
    """
    Skater/goalie summaries via wise/tournaments/{id}/players|goalies/statistics.
    Returnerar tomma DataFrames om Wisehockey-integrationen i proxy:n ej fungerar.
    """
    api = NorAPI()
    all_summaries: list[pd.DataFrame] = []

    for tid in tournament_ids:
        try:
            data = api._get(f"wise/tournaments/{tid}/players/statistics")
            if data and not isinstance(data, dict) or (isinstance(data, dict) and "message" not in data):
                # Parsa om data finns
                pass
        except Exception:
            pass

    frames = [f for f in all_summaries if not f.empty]
    return {"skater_summaries": pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()}


def scrape_players() -> dict[str, pd.DataFrame]:
    """Spelarlista – NIF har ingen dedikerad endpoint; returnerar tom DataFrame."""
    return {"players": pd.DataFrame()}
