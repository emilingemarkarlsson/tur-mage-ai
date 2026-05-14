"""
Norwegian EHL hockey API scraper.

Hämtar nya matcher och tillhörande statistik från API:et och
konverterar till pandas DataFrames i samma schema som nor-parquet-filerna.

Miljövariabler:
  NOR_API_BASE_URL  – API:ets bas-URL, t.ex. https://api.example.no (krävs för skrapning)
  NOR_API_KEY       – API-nyckel som skickas som x-api-key header (om krävs)
  NOR_API_BEARER    – Bearer token för Authorization-header (om krävs)

Förväntade API-endpoints (baserat på befintlig datastruktur):
  GET /teams/{team_id}/matches                            → matchlista per lag
  GET /teams/{team_id}/seasons                           → turneringar per lag
  GET /matches/{match_id}                                → matchdetaljer
  GET /matches/{match_id}/events                         → mål, straff, GK-händelser
  GET /matches/{match_id}/stats                          → period-statistik (per strength)
  GET /matches/{match_id}/momentum                       → momentum-tidslinje (per sekund)
  GET /matches/{match_id}/shifts                         → skift-data per spelare
  GET /players                                           → alla spelare
  GET /teams/{team_id}/skater-summaries?tournamentId=X   → säsongsstatistik per skridskoåkare
  GET /teams/{team_id}/goalkeeper-summaries?tournamentId=X → säsongsstatistik per målvakt
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests

TEAMS: dict[str, int] = {
    "friskasker": 1,
    "gruner": 2,
    "lillehammer": 3,
    "manglerud": 4,
    "ringerike": 5,
    "sparta": 6,
    "stavanger": 7,
    "stjernen": 8,
    "storhamar": 9,
    "valerenga": 10,
    "comet": 17,
    "lorenskog": 18,
    "narvik": 21,
    "nidaros": 67,
}


class NorAPI:
    def __init__(self):
        self.base = os.environ.get("NOR_API_BASE_URL", "").rstrip("/")
        if not self.base:
            raise ValueError("NOR_API_BASE_URL saknas i miljövariabler")

        headers: dict[str, str] = {"Accept": "application/json"}
        key = os.environ.get("NOR_API_KEY", "").strip()
        bearer = os.environ.get("NOR_API_BEARER", "").strip()
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        elif key:
            headers["x-api-key"] = key

        self.session = requests.Session()
        self.session.headers.update(headers)

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.base}/{path.lstrip('/')}"
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_tournaments(self, team_id: int) -> list[dict]:
        return self._get(f"teams/{team_id}/seasons")

    def get_matches(self, team_id: int) -> list[dict]:
        return self._get(f"teams/{team_id}/matches")

    def get_match(self, match_id: int) -> dict:
        return self._get(f"matches/{match_id}")

    def get_events(self, match_id: int) -> dict:
        return self._get(f"matches/{match_id}/events")

    def get_stats(self, match_id: int) -> dict:
        return self._get(f"matches/{match_id}/stats")

    def get_momentum(self, match_id: int) -> list[dict]:
        return self._get(f"matches/{match_id}/momentum")

    def get_shifts(self, match_id: int) -> list[dict]:
        return self._get(f"matches/{match_id}/shifts")

    def get_players(self) -> list[dict]:
        return self._get("players")

    def get_skater_summaries(self, team_id: int, tournament_id: int) -> list[dict]:
        return self._get(f"teams/{team_id}/skater-summaries", {"tournamentId": tournament_id})

    def get_goalkeeper_summaries(self, team_id: int, tournament_id: int) -> list[dict]:
        return self._get(f"teams/{team_id}/goalkeeper-summaries", {"tournamentId": tournament_id})


# ---------------------------------------------------------------------------
# Parsers: JSON API-svar → DataFrames i rätt schema
# ---------------------------------------------------------------------------

def parse_matches(raw: list[dict], team_slug: str) -> pd.DataFrame:
    rows = []
    for m in raw:
        if m.get("status") not in ("Finished", "FinishedOvertime", "FinishedShootout"):
            continue
        rows.append({
            "match_id": m["id"],
            "team_slug": team_slug,
            "match_date": m.get("matchDate"),
            "end_time": m.get("endTime"),
            "home_team_id": m["homeTeam"]["id"],
            "home_team_name": m["homeTeam"]["fullName"],
            "away_team_id": m["awayTeam"]["id"],
            "away_team_name": m["awayTeam"]["fullName"],
            "home_goals": m.get("homeGoals", 0),
            "away_goals": m.get("awayGoals", 0),
            "status": m.get("status"),
            "game_time": m.get("gameTime", 0),
            "has_statistics": m.get("hasStatistics", False),
            "tournament_id": m["matchSeason"]["id"],
            "tournament_name": m["matchSeason"]["tournamentName"],
            "season_year": m["matchSeason"]["year"],
            "season_phase": m["matchSeason"]["phase"],
        })
    return pd.DataFrame(rows)


def parse_goal_events(events: dict, match_id: int, team_slug: str) -> pd.DataFrame:
    rows = []
    for e in events.get("goalEvents", []):
        rows.append({
            "event_id": e["id"],
            "match_id": match_id,
            "team_slug": team_slug,
            "timestamp": e.get("timestamp"),
            "match_time": e.get("matchTime"),
            "period": e.get("periodNumber"),
            "team_id": e["team"]["id"],
            "team_name": e["team"]["fullName"],
            "home_goals": e.get("homeGoals"),
            "away_goals": e.get("awayGoals"),
            "goal_type": e.get("type"),
            "scorer_id": e.get("scorer", {}).get("id") if e.get("scorer") else None,
            "scorer_name": (
                f"{e['scorer']['firstName']} {e['scorer']['lastName']}"
                if e.get("scorer") else None
            ),
            "assist1_id": e.get("assist1", {}).get("id") if e.get("assist1") else None,
            "assist1_name": (
                f"{e['assist1']['firstName']} {e['assist1']['lastName']}"
                if e.get("assist1") else None
            ),
            "assist2_id": e.get("assist2", {}).get("id") if e.get("assist2") else None,
            "assist2_name": (
                f"{e['assist2']['firstName']} {e['assist2']['lastName']}"
                if e.get("assist2") else None
            ),
        })
    return pd.DataFrame(rows)


def parse_penalty_events(events: dict, match_id: int, team_slug: str) -> pd.DataFrame:
    rows = []
    for e in events.get("penaltyEvents", []):
        rows.append({
            "event_id": e["id"],
            "match_id": match_id,
            "team_slug": team_slug,
            "timestamp": e.get("timestamp"),
            "match_time": e.get("matchTime"),
            "period": e.get("periodNumber"),
            "team_id": e["team"]["id"],
            "team_name": e["team"]["fullName"],
            "duration_minutes": e.get("durationMinutes", 0),
            "reason": e.get("reason"),
            "info": e.get("info"),
            "is_team_or_official": e.get("isTeamOrOfficial", False),
            "player_id": e.get("player", {}).get("id") if e.get("player") else None,
            "player_name": (
                f"{e['player']['firstName']} {e['player']['lastName']}"
                if e.get("player") else None
            ),
        })
    return pd.DataFrame(rows)


def parse_match_lineup(match: dict, match_id: int, team_slug: str) -> pd.DataFrame:
    rows = []
    for side, key in [("home", "homeTeamRoster"), ("away", "awayTeamRoster")]:
        for p in match.get(key, []):
            rows.append({
                "match_id": match_id,
                "team_slug": team_slug,
                "side": side,
                "player_id": p["id"],
                "first_name": p.get("firstName"),
                "last_name": p.get("lastName"),
                "jersey": p.get("jersey", 0),
                "role": p.get("role"),
                "line_number": p.get("lineNumber", 0),
                "height": p.get("height", 0),
                "weight": p.get("weight", 0),
                "date_of_birth": p.get("dateOfBirth"),
                "handedness": p.get("handedness"),
            })
    return pd.DataFrame(rows)


def parse_period_stats(stats: dict, match_id: int, team_slug: str) -> pd.DataFrame:
    rows = []
    for period in stats.get("periodStatistics", []):
        p_num = period.get("periodNumber")
        for ts in period.get("teamStrengthStatistics", [period]):
            strength = ts.get("teamStrength", {})
            home_s = None
            away_s = None
            for ts_entry in ts.get("teamStats", []):
                if ts_entry.get("team") == "Home":
                    home_s = ts_entry
                elif ts_entry.get("team") == "Away":
                    away_s = ts_entry
            rows.append({
                "match_id": match_id,
                "team_slug": team_slug,
                "period": p_num,
                "home_players": strength.get("homePlayers"),
                "away_players": strength.get("awayPlayers"),
                "home_goalie_on_ice": strength.get("homeGoalieOnIce"),
                "away_goalie_on_ice": strength.get("awayGoalieOnIce"),
                "home_shots": home_s.get("shots") if home_s else None,
                "away_shots": away_s.get("shots") if away_s else None,
                "home_goals": home_s.get("goals") if home_s else None,
                "away_goals": away_s.get("goals") if away_s else None,
                "home_blocked_shots": home_s.get("blockedShots") if home_s else None,
                "away_blocked_shots": away_s.get("blockedShots") if away_s else None,
            })
    return pd.DataFrame(rows)


def parse_powerplay_stats(stats: dict, match_id: int, team_slug: str) -> pd.DataFrame:
    rows = []
    for side, key in [("home", "homePowerplayStats"), ("away", "awayPowerplayStats")]:
        pp = stats.get(key, {})
        if pp:
            rows.append({
                "match_id": match_id,
                "team_slug": team_slug,
                "team_side": side,
                "powerplay_count": pp.get("powerplayCount", 0),
                "powerplay_goals": pp.get("powerplayGoals", 0),
                "powerplay_time": pp.get("powerplayTime"),
            })
    return pd.DataFrame(rows)


def parse_shifts(shifts_raw: list[dict], match_id: int, team_slug: str) -> pd.DataFrame:
    rows = []
    for player_data in shifts_raw:
        pid = player_data.get("playerId")
        for shift in player_data.get("shifts", []):
            stats = shift.get("stats", [{}])
            s = stats[0] if stats else {}
            rows.append({
                "match_id": match_id,
                "team_slug": team_slug,
                "player_id": pid,
                "shift_id": shift.get("id"),
                "period": shift.get("periodNumber"),
                "start_time_from_period": shift.get("startTimeFromPeriodStart"),
                "start_timestamp": shift.get("startTimestamp"),
                "end_timestamp": shift.get("endTimestamp"),
                "time_on_ice": s.get("timeOnIce"),
                "distance_travelled": s.get("distanceTravelled"),
                "distance_with_puck": s.get("distanceTravelledWithPuck"),
                "top_speed": s.get("topSpeed"),
                "puck_control_time": s.get("puckControlTime"),
                "shots": s.get("shots", 0),
                "goals": s.get("goals", 0),
                "fastest_shot": s.get("fastestShot"),
                "plus": s.get("corsiFor"),
                "minus": s.get("corsiAgainst"),
                "plus_minus": (
                    (s.get("corsiFor") or 0) - (s.get("corsiAgainst") or 0)
                    if s.get("corsiFor") is not None else None
                ),
                "blocked_shots": s.get("blockedShots", 0),
                "offensive_screens": s.get("offensiveScreens", 0),
            })
    return pd.DataFrame(rows)


def parse_momentum(momentum_raw: list[dict], match_id: int, team_slug: str) -> pd.DataFrame:
    rows = []
    for entry in momentum_raw:
        period = entry.get("periodNumber")
        for i, point in enumerate(entry.get("dataPoints", [])):
            rows.append({
                "match_id": match_id,
                "team_slug": team_slug,
                "period": period,
                "index": i,
                "timestamp": point.get("timestamp"),
                "value": point.get("value"),
            })
    return pd.DataFrame(rows)


def parse_players(players_raw: list[dict]) -> pd.DataFrame:
    rows = []
    for p in players_raw:
        rows.append({
            "player_id": p["id"],
            "first_name": p.get("firstName"),
            "last_name": p.get("lastName"),
            "jersey": p.get("jersey", 0),
            "role": p.get("role"),
            "handedness": p.get("handedness"),
            "height": p.get("height", 0),
            "weight": p.get("weight", 0),
            "date_of_birth": p.get("dateOfBirth"),
            "image_id": p.get("imageId"),
        })
    return pd.DataFrame(rows)


def parse_skater_summaries(raw: list[dict], team_slug: str, tournament_id: int) -> pd.DataFrame:
    rows = []
    for entry in raw:
        pid = entry.get("playerId")
        pt = entry.get("totalPointTable", {})
        for s in entry.get("totalStats", []):
            ts = s.get("teamStrength", {})
            if ts.get("type") != "FullStrength":
                continue
            rows.append({
                "team_slug": team_slug,
                "tournament_id": tournament_id,
                "player_id": pid,
                "games_played": pt.get("gamesPlayed", 0),
                "goals": pt.get("goals", 0),
                "assists": pt.get("assists", 0),
                "points": pt.get("points", 0),
                "penalty_count": pt.get("penaltyCount", 0),
                "penalty_minutes": pt.get("penaltyMinutes", 0),
                "time_on_ice": s.get("timeOnIce"),
                "distance_travelled": s.get("distanceTravelled"),
                "top_speed": s.get("topSpeed"),
                "shots": s.get("shots"),
                "goals_5v5": s.get("goals"),
                "plus": s.get("plus"),
                "minus": s.get("minus"),
                "plus_minus": s.get("plusMinus"),
                "puck_control_time": s.get("puckControlTime"),
                "blocked_shots": s.get("blockedShots"),
                "offensive_screens": s.get("offensiveScreens"),
                "fastest_shot": s.get("fastestShot"),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Public scrape interface
# ---------------------------------------------------------------------------

def scrape_new_matches(known_match_ids: set[int]) -> dict[str, pd.DataFrame]:
    """
    Hämtar alla nya avslutade matcher som inte finns i known_match_ids.
    Returnerar dict med DataFrames för varje tabell.
    """
    api = NorAPI()

    all_matches: list[pd.DataFrame] = []
    all_goals: list[pd.DataFrame] = []
    all_penalties: list[pd.DataFrame] = []
    all_lineup: list[pd.DataFrame] = []
    all_period_stats: list[pd.DataFrame] = []
    all_pp_stats: list[pd.DataFrame] = []
    all_shifts: list[pd.DataFrame] = []
    all_momentum: list[pd.DataFrame] = []

    processed_match_ids: set[int] = set()

    for slug, team_id in TEAMS.items():
        print(f"[nor-scraper] {slug} – hämtar matchlista...", flush=True)
        try:
            raw_matches = api.get_matches(team_id)
        except Exception as exc:
            print(f"[nor-scraper] VARNING: kunde inte hämta matcher för {slug}: {exc}")
            continue

        match_df = parse_matches(raw_matches, slug)
        all_matches.append(match_df)

        new_ids = [
            mid for mid in match_df["match_id"].tolist()
            if mid not in known_match_ids and mid not in processed_match_ids
            and match_df.loc[match_df["match_id"] == mid, "has_statistics"].any()
        ]

        if not new_ids:
            print(f"[nor-scraper] {slug} – inga nya matcher")
            continue

        print(f"[nor-scraper] {slug} – {len(new_ids)} nya matcher: {new_ids}")

        for mid in new_ids:
            print(f"[nor-scraper]   match {mid}...", flush=True)
            try:
                match_detail = api.get_match(mid)
                events = api.get_events(mid)
                stats = api.get_stats(mid)
                shifts_raw = api.get_shifts(mid)
                momentum_raw = api.get_momentum(mid)

                all_goals.append(parse_goal_events(events, mid, slug))
                all_penalties.append(parse_penalty_events(events, mid, slug))
                all_lineup.append(parse_match_lineup(match_detail, mid, slug))
                all_period_stats.append(parse_period_stats(stats, mid, slug))
                all_pp_stats.append(parse_powerplay_stats(stats, mid, slug))
                all_shifts.append(parse_shifts(shifts_raw, mid, slug))
                all_momentum.append(parse_momentum(momentum_raw, mid, slug))
                processed_match_ids.add(mid)

            except Exception as exc:
                print(f"[nor-scraper]   FEL för match {mid}: {exc}")

    def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
        frames = [f for f in frames if not f.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    return {
        "matches": _concat(all_matches),
        "goal_events": _concat(all_goals),
        "penalty_events": _concat(all_penalties),
        "match_lineup": _concat(all_lineup),
        "match_period_stats": _concat(all_period_stats),
        "match_powerplay_stats": _concat(all_pp_stats),
        "shifts": _concat(all_shifts),
        "momentum": _concat(all_momentum),
    }


def scrape_season_summaries(tournament_ids: list[int]) -> dict[str, pd.DataFrame]:
    """Hämtar säsongssammanfattning för alla lag och turneringar."""
    api = NorAPI()
    all_summaries: list[pd.DataFrame] = []

    for slug, team_id in TEAMS.items():
        for tid in tournament_ids:
            try:
                raw = api.get_skater_summaries(team_id, tid)
                all_summaries.append(parse_skater_summaries(raw, slug, tid))
            except Exception:
                pass

    frames = [f for f in all_summaries if not f.empty]
    return {"skater_summaries": pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()}


def scrape_players() -> dict[str, pd.DataFrame]:
    api = NorAPI()
    raw = api.get_players()
    return {"players": parse_players(raw)}
