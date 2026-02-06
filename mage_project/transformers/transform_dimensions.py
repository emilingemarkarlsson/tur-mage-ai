from typing import Any, Dict, List
import sys

import pandas as pd
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.transform_utils import extract_list, flatten_dict_for_row, flatten_player, get_nested_list

if "transformer" not in globals():
    from mage_ai.data_preparation.decorators import transformer


def _roster_rows_from_franchise_keyed_payload(roster_payload: Any, season: str) -> List[Dict[str, Any]]:
    """Extrahera roster-rader när payload är dict med franchise_id som nyckel (t.ex. all_rosters.json).
    Värde per nyckel: lista av spelare (playerId/id) eller dict med forwards/defensemen/goalies.
    """
    rows: List[Dict[str, Any]] = []
    if not isinstance(roster_payload, dict):
        return rows
    for team_id_key, val in roster_payload.items():
        if not team_id_key or team_id_key.startswith("_"):
            continue
        team_id = str(team_id_key).strip()
        if isinstance(val, list):
            for p in val:
                if not isinstance(p, dict):
                    continue
                pid = p.get("playerId") or p.get("id")
                if pid is not None:
                    rows.append({"season": season, "team_id": team_id, "player_id": pid})
        elif isinstance(val, dict):
            for group in ("forwards", "defensemen", "goalies"):
                for p in (val.get(group) or []):
                    if isinstance(p, dict):
                        pid = p.get("playerId") or p.get("id")
                    elif isinstance(p, (int, float)):
                        pid = int(p)
                    else:
                        pid = None
                    if pid is not None:
                        rows.append({"season": season, "team_id": team_id, "player_id": pid})
    return rows


def _roster_from_players_by_team(players_by_team_raw: Any) -> List[Dict[str, Any]]:
    """Bygg platt roster (player_id, team_id) från players_by_team.json.
    Struktur: { "27": [ {"forwards": [...], "defensemen": [...], "goalies": [...]} ], "15": [...], ... }
    eller list/objekt med teams som har forwards/defensemen/goalies.
    """
    from utils.transform_utils import get_nested_list, extract_list

    rows: List[Dict[str, Any]] = []

    # Struktur: toppnivå = dict med team_id som nyckel -> list med en dict (forwards/defensemen/goalies)
    if isinstance(players_by_team_raw, dict) and players_by_team_raw:
        first_val = next(iter(players_by_team_raw.values()))
        if isinstance(first_val, list) and first_val and isinstance(first_val[0], dict):
            if "forwards" in first_val[0] or "defensemen" in first_val[0]:
                for team_id, payload_list in players_by_team_raw.items():
                    if not isinstance(payload_list, list) or not payload_list:
                        continue
                    team_dict = payload_list[0] if isinstance(payload_list[0], dict) else {}
                    for group in ("forwards", "defensemen", "goalies"):
                        for player in team_dict.get(group) or []:
                            if isinstance(player, dict):
                                pid = player.get("id") or player.get("playerId")
                            elif isinstance(player, (int, float)):
                                pid = int(player)
                            else:
                                pid = None
                            if pid is not None:
                                rows.append({"player_id": pid, "team_id": team_id, "team_abbr": None})
                if rows:
                    return rows
    # Fallback: nästlad struktur players.data.items etc.
    team_list = get_nested_list(players_by_team_raw, ["players", "data", "items"])
    if not team_list:
        team_list = get_nested_list(players_by_team_raw, ["teams", "data", "items"])
    if not team_list:
        team_list = extract_list(players_by_team_raw, ["teams", "data", "items", "players"])
    for team in team_list or []:
        team = dict(team)
        team_id = team.get("id") or team.get("franchiseId")
        team_abbr = team.get("abbrev") or team.get("abbreviation") or team.get("triCode")
        for group in ("forwards", "defensemen", "goalies"):
            for player in (team.get(group) or []):
                if isinstance(player, dict):
                    pid = player.get("id") or player.get("playerId")
                elif isinstance(player, (int, float)):
                    pid = int(player)
                else:
                    pid = None
                if pid is not None:
                    rows.append({"player_id": pid, "team_id": team_id, "team_abbr": team_abbr})
    return rows


def _schedule_to_rows(schedule_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Platta ut schedule-filer till en rad per match med schedule_date och source_key."""
    rows: List[Dict[str, Any]] = []
    for item in schedule_payloads or []:
        key = item.get("key") or ""
        data = item.get("payload") or {}
        # NHL API: dates[] -> date, games[] -> gamePk, etc.
        dates_list = get_nested_list(data, ["dates"])
        if not dates_list:
            gl = data.get("games") if isinstance(data.get("games"), list) else None
            if gl:
                dates_list = [{"date": None, "games": gl}]
            else:
                dates_list = extract_list(data, ["dates", "games"])
        if not dates_list and isinstance(data.get("games"), list):
            dates_list = [{"date": None, "games": data["games"]}]
        if not dates_list:
            games_list = extract_list(data, ["games", "data", "items"])
            if games_list:
                dates_list = [{"date": None, "games": games_list}]
        # Stöd även gameWeek[].games[] (t.ex. weekly/calendar-format)
        if not dates_list and isinstance(data.get("gameWeek"), list):
            dates_list = []
            for gw in data.get("gameWeek") or []:
                if isinstance(gw, dict):
                    date_block = {"date": gw.get("date"), "games": gw.get("games") or []}
                    dates_list.append(date_block)
        for date_block in dates_list or []:
            if not isinstance(date_block, dict):
                continue
            schedule_date = date_block.get("date")
            games_list = date_block.get("games") or []
            for g in games_list:
                if not isinstance(g, dict):
                    continue
                # NHL API: teams.home.id / teams.away.id; schedule-format: homeTeam.id / awayTeam.id
                home_id = None
                away_id = None
                if isinstance(g.get("teams"), dict):
                    home_id = (g["teams"].get("home") or {}).get("id")
                    away_id = (g["teams"].get("away") or {}).get("id")
                if home_id is None and isinstance(g.get("homeTeam"), dict):
                    home_id = g["homeTeam"].get("id")
                if away_id is None and isinstance(g.get("awayTeam"), dict):
                    away_id = g["awayTeam"].get("id")
                venue_obj = g.get("venue") or {}
                venue = venue_obj.get("default") if isinstance(venue_obj, dict) else None
                # Endast skalära fält så Parquet-export inte kraschar på nästlade objekt
                row = {
                    "schedule_date": schedule_date,
                    "schedule_source_key": key,
                    "gamePk": g.get("gamePk") or g.get("id"),
                    "gameDate": g.get("gameDate"),
                    "season": g.get("season"),
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "gameType": g.get("gameType"),
                    "status": (g.get("status") or {}).get("detailedState") if isinstance(g.get("status"), dict) else g.get("gameState") or g.get("status"),
                    "start_time_utc": g.get("startTimeUTC"),
                    "game_state": g.get("gameState"),
                    "venue": venue,
                }
                rows.append(row)
    return rows


def _helpers_to_rows(helpers_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Platta helpers (t.ex. game_ids_{season}.json) till season + game_id."""
    rows: List[Dict[str, Any]] = []
    for item in helpers_payloads or []:
        key = item.get("key") or ""
        data = item.get("payload")
        if data is None:
            data = {}
        # Filnamn game_ids_20252026.json -> season 20252026
        parts = key.replace("\\", "/").split("/")[-1].replace(".json", "").split("_")
        season = parts[-1] if len(parts) >= 2 else None
        if isinstance(data, list):
            game_ids = data
        else:
            if not season and isinstance(data.get("season"), str):
                season = data.get("season")
            game_ids = (
                data.get("gameIds") or data.get("game_ids") or data.get("games") or
                get_nested_list(data, ["data", "items"]) or
                []
            )
        if not isinstance(game_ids, list):
            game_ids = [game_ids] if game_ids is not None else []
        for gid in game_ids:
            # Säkerställ skalär (Parquet klarar inte dict i cell)
            game_id_val = gid.get("gamePk") or gid.get("id") if isinstance(gid, dict) else gid
            rows.append({"season": season, "game_id": game_id_val, "source_key": key})
    return rows


def _glossary_to_rows(glossary_raw: Any) -> List[Dict[str, Any]]:
    """Platta glossary till en rad per term."""
    if not glossary_raw:
        return []
    terms = (
        extract_list(glossary_raw, ["terms", "data", "items", "glossary"]) or
        get_nested_list(glossary_raw, ["terms"]) or
        (glossary_raw if isinstance(glossary_raw, list) else [])
    )
    rows: List[Dict[str, Any]] = []
    for t in terms or []:
        if isinstance(t, dict):
            rows.append(t)
        else:
            rows.append({"term": str(t), "definition": None})
    return rows


def _draft_to_rows(draft_raw: Any) -> List[Dict[str, Any]]:
    """Platta draft_year_and_rounds till rader."""
    if not draft_raw:
        return []
    items = (
        extract_list(draft_raw, ["rounds", "years", "data", "items"]) or
        get_nested_list(draft_raw, ["rounds"]) or
        get_nested_list(draft_raw, ["years"]) or
        (draft_raw if isinstance(draft_raw, list) else [])
    )
    rows: List[Dict[str, Any]] = []
    for x in items or []:
        if isinstance(x, dict):
            rows.append(x)
        else:
            rows.append({"value": x})
    return rows


@transformer
def transform_dimensions(payload: Dict[str, Any], *args, **kwargs):
    teams_raw = payload.get("teams")
    players_raw = payload.get("players")
    players_by_team_raw = payload.get("players_by_team")
    countries_raw = payload.get("countries")
    rosters_raw = payload.get("rosters", [])
    schedule_payloads = payload.get("schedule_payloads") or []
    helpers_payloads = payload.get("helpers_payloads") or []
    glossary_raw = payload.get("glossary")
    draft_raw = payload.get("draft")

    teams_list = extract_list(teams_raw, ["teams", "data", "items"])
    if not teams_list and isinstance(teams_raw, list):
        teams_list = teams_raw
    teams = [flatten_dict_for_row(t) for t in teams_list] if teams_list and isinstance(teams_list[0], dict) else (teams_list or [])
    # Platt ut conference/division till egna kolumner (så mycket som möjligt från inventering)
    for t in teams:
        if not isinstance(t, dict):
            continue
        conf = t.get("conference")
        if isinstance(conf, dict):
            t["conference_abbr"] = conf.get("abbr")
            t["conference_name"] = conf.get("name")
        div = t.get("division")
        if isinstance(div, dict):
            t["division_abbr"] = div.get("abbr")
            t["division_name"] = div.get("name")
    players_raw_list = extract_list(players_raw, ["players", "data", "items"])
    countries = extract_list(countries_raw, ["countries", "data", "items"])
    if not countries and isinstance(countries_raw, dict) and countries_raw:
        # vissa källor: { "SE": "Sverige", "US": "USA", ... }
        countries = [{"code": k, "name": v if not isinstance(v, dict) else v.get("default", v)} for k, v in countries_raw.items()]

    # Bygg platt spelarlista. Källan kan vara antingen:
    # A) Lista av spelarobjekt: [ {id, firstName, ...}, ... ]
    # B) Lista av lag-roster: [ {forwards: [...], defensemen: [...], goalies: [...]}, ... ] (samma som players_by_team)
    flat_players: List[Dict[str, Any]] = []
    if players_raw_list and isinstance(players_raw_list[0], dict):
        first = players_raw_list[0]
        if "forwards" in first or "defensemen" in first:
            # B: Roster-struktur – platta ut alla spelare från alla lag
            for team_row in players_raw_list:
                if not isinstance(team_row, dict):
                    continue
                for group in ("forwards", "defensemen", "goalies"):
                    for p in (team_row.get(group) or []):
                        if isinstance(p, dict):
                            flat_players.append(flatten_player(p))
        else:
            # A: Redan lista av spelare
            flat_players = [flatten_player(p) for p in players_raw_list if isinstance(p, dict)]
    # Om all_players gav tomt, försök platta från players_by_team
    if not flat_players and players_by_team_raw and isinstance(players_by_team_raw, dict):
        for _team_id, payload_list in players_by_team_raw.items():
            if not isinstance(payload_list, list) or not payload_list:
                continue
            team_dict = payload_list[0] if isinstance(payload_list[0], dict) else {}
            for group in ("forwards", "defensemen", "goalies"):
                for p in (team_dict.get(group) or []):
                    if isinstance(p, dict):
                        flat_players.append(flatten_player(p))

    teams_df = pd.DataFrame(teams)
    players_df = pd.DataFrame(flat_players)
    countries_df = pd.DataFrame(countries)

    roster_rows: List[Dict[str, Any]] = []
    for roster_item in rosters_raw:
        season = roster_item.get("season")
        roster_payload = roster_item.get("payload") or {}
        roster_list = get_nested_list(roster_payload, ["rosters", "teams", "data", "items"])
        if not roster_list:
            roster_list = get_nested_list(roster_payload, ["rosters", "data", "items"])
        if not roster_list:
            roster_list = extract_list(roster_payload, ["rosters", "teams", "data", "items"])
        if not roster_list:
            # Enligt HETZNER-dokumentation: all_rosters.json har root = dict med franchise_id som nyckel
            roster_list = _roster_rows_from_franchise_keyed_payload(roster_payload, season)
        for entry in roster_list:
            entry = dict(entry) if isinstance(entry, dict) else {}
            if "season" not in entry:
                entry["season"] = season
            roster_rows.append(entry)

    # Om inga roster-filer i S3: bygg roster från players_by_team.json
    if not roster_rows and players_by_team_raw:
        roster_rows = _roster_from_players_by_team(players_by_team_raw)

    # Fyll i team_abbr från teams (team_id i roster = id/franchiseId i teams)
    if roster_rows and not teams_df.empty:
        id_col = "id" if "id" in teams_df.columns else "franchise_id"
        abbr_col = "abbrev" if "abbrev" in teams_df.columns else "abbr"
        if id_col in teams_df.columns and abbr_col in teams_df.columns:
            team_to_abbr = dict(zip(teams_df[id_col].astype(str), teams_df[abbr_col]))
            for row in roster_rows:
                row["team_abbr"] = team_to_abbr.get(str(row.get("team_id")))

    roster_df = pd.DataFrame(roster_rows)

    # Schedule, helpers (game_ids), glossary, draft
    schedule_rows = _schedule_to_rows(schedule_payloads)
    schedule_df = pd.DataFrame(schedule_rows) if schedule_rows else pd.DataFrame()
    game_ids_rows = _helpers_to_rows(helpers_payloads)
    game_ids_df = pd.DataFrame(game_ids_rows) if game_ids_rows else pd.DataFrame()
    glossary_rows = _glossary_to_rows(glossary_raw)
    glossary_df = pd.DataFrame(glossary_rows) if glossary_rows else pd.DataFrame()
    draft_rows = _draft_to_rows(draft_raw)
    draft_df = pd.DataFrame(draft_rows) if draft_rows else pd.DataFrame()

    return {
        "teams": teams_df,
        "players": players_df,
        "countries": countries_df,
        "roster": roster_df,
        "schedule": schedule_df,
        "game_ids": game_ids_df,
        "glossary": glossary_df,
        "draft": draft_df,
    }
