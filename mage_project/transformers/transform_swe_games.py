import json
import sys
from typing import Any, Dict, List, Optional

import pandas as pd
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.transform_utils import parse_date, to_float, to_int

if "transformer" not in globals():
    from mage_ai.data_preparation.decorators import transformer


# Kolumner med fast schema (undviker Parquet-schema-mismatch vid union)
GAMES_COLUMNS = [
    "game_id", "game_date", "season", "league", "league_id", "game_type",
    "home_team", "away_team", "home_score", "away_score",
    "home_points", "away_points", "venue", "time",
    "home_shots", "away_shots", "home_saves", "away_saves",
    "home_save_pct", "away_save_pct", "home_pim", "away_pim",
    "periods", "went_ot", "went_so",
    "home_coach", "away_coach",
    "scraped_at",
]

EVENTS_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "period", "event_time", "event_type",
    "team", "player_name", "player_number", "goal_type",
    "penalty_minutes", "penalty_start", "penalty_end",
    "penalty_type", "goalkeeper_action", "powerplay_number",
    "score_home", "score_away", "assists",
]

GOALKEEPERS_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "team", "name", "number",
    "saves", "shots_against", "save_pct",
]

LINEUPS_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "team", "is_home",
    "head_coach", "assistant_coach",
    "line_number", "position", "player_name", "player_number",
    "is_starting",
]

PERIOD_SCORES_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "period", "home_score", "away_score",
]

REFEREES_JSON_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "name", "role",
]

ON_ICE_JSON_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "period", "event_time", "event_type",
    "event_team",   # laget som äger händelsen (positiv sida = scoringlag)
    "team_side",    # "positive" = event_team, "negative" = motståndet
    "player_number",
]

PLAYER_STATS_JSON_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "team", "player_id", "player_name",
    "goals", "assists", "pim", "shots", "plus_minus",
]


def _clean_str(value) -> str:
    """Rensa NBSP, tab och dubbla mellanslag från strängar."""
    if not value:
        return ""
    import re
    s = str(value).replace("\xa0", " ").replace("\t", " ")
    return re.sub(r" {2,}", " ", s).strip()


def _derive_season(date_str: str) -> str:
    """Kalenderår som säsong: matchen 2024-11-15 → '2024'."""
    return date_str[:4] if date_str and len(date_str) >= 4 else ""


def _derive_game_type(league: str) -> str:
    """Härledd matchtyp från liga-strängen.
    'SM-slutspel SHL' → 'playoff', 'Play Out SHL' → 'play_out', etc.
    """
    ll = league.lower()
    if "slutspel" in ll:
        return "playoff"
    if "play out" in ll or "play-out" in ll:
        return "play_out"
    if "kval" in ll:
        return "qualification"
    if "chl" in ll or "champions" in ll:
        return "champions_league"
    return "regular"


def _parse_result(result_str: str | None) -> tuple:
    """'2 - 3' → (2, 3). Returnerar (None, None) om ogiltigt format."""
    if not result_str:
        return None, None
    parts = str(result_str).replace(" ", "").split("-")
    if len(parts) == 2:
        return to_int(parts[0]), to_int(parts[1])
    return None, None


def _extract_game_row(payload: Dict[str, Any], game_date: str) -> Dict[str, Any]:
    game_id = str(payload.get("game_id", ""))

    # Poäng direkt från fält eller från result-sträng som fallback
    home_score = to_int(payload.get("home_score"))
    away_score = to_int(payload.get("away_score"))
    if home_score is None and away_score is None:
        home_score, away_score = _parse_result(payload.get("result"))

    # Poängberäkning (SE-hockey: 2p vinst, 1p OT-förlust, 0p förlust)
    periods = payload.get("period_scores") or []
    regulation_periods = [p for p in periods if to_int(p.get("period")) in (1, 2, 3)]
    went_to_ot = len(periods) > len(regulation_periods)

    # OT och SO-flaggor
    period_labels = [str(p.get("period", "")).upper() for p in periods]
    went_so = any(lbl in ("SO", "SHOOTOUT") for lbl in period_labels)
    went_ot = went_to_ot and not went_so

    # Fallback: om period_scores saknar OT-info, detektera via events (period=4 eller "OT")
    if not went_to_ot:
        events = payload.get("events") or []
        event_periods = {str(e.get("period", "")).upper() for e in events if e.get("period")}
        so_labels = {"SO", "SHOOTOUT"}
        went_so = went_so or bool(event_periods & so_labels)
        has_ot_event = any(
            (p.isdigit() and int(p) > 3) or p in ("OT", "OVERTIME")
            for p in event_periods
        )
        went_ot = (has_ot_event and not went_so) or went_ot

    if home_score is not None and away_score is not None:
        if home_score > away_score:
            home_pts, away_pts = 2, (1 if went_to_ot else 0)
        elif away_score > home_score:
            home_pts, away_pts = (1 if went_to_ot else 0), 2
        else:
            home_pts, away_pts = None, None  # oavgjort / pågående
    else:
        home_pts, away_pts = None, None

    home_stats = payload.get("home_team_stats") or {}
    away_stats = payload.get("away_team_stats") or {}

    home_shots = to_int(home_stats.get("shots"))
    away_shots = to_int(away_stats.get("shots"))
    home_saves = to_int(home_stats.get("saves"))
    away_saves = to_int(away_stats.get("saves"))

    # FIX: save_pct är cross-referens – home målvakt räddade mot bortalagets skott.
    home_save_pct = round(home_saves / away_shots * 100, 2) if away_shots else None
    away_save_pct = round(away_saves / home_shots * 100, 2) if home_shots else None

    # Tränare från laguppställning
    home_lineup = payload.get("home_team_lineup") or {}
    away_lineup = payload.get("away_team_lineup") or {}
    home_coach = _clean_str(home_lineup.get("head_coach") or "")
    away_coach = _clean_str(away_lineup.get("head_coach") or "")

    scraped_at = (payload.get("metadata") or {}).get("scraped_at") or ""

    league_str = _clean_str(payload.get("league"))
    return {
        "game_id": game_id,
        "game_date": parse_date(game_date),
        "season": _derive_season(game_date),
        "league": league_str,
        "league_id": str(payload.get("league_id") or ""),
        "game_type": _derive_game_type(league_str),
        "home_team": _clean_str(payload.get("home_team")),
        "away_team": _clean_str(payload.get("away_team")),
        "home_score": home_score,
        "away_score": away_score,
        "home_points": home_pts,
        "away_points": away_pts,
        "venue": _clean_str(payload.get("venue")),
        "time": payload.get("time") or "",
        "home_shots": home_shots,
        "away_shots": away_shots,
        "home_saves": home_saves,
        "away_saves": away_saves,
        "home_save_pct": home_save_pct,
        "away_save_pct": away_save_pct,
        "home_pim": to_int(home_stats.get("penalty_minutes")),
        "away_pim": to_int(away_stats.get("penalty_minutes")),
        "periods": len(periods),
        "went_ot": went_ot,
        "went_so": went_so,
        "home_coach": home_coach,
        "away_coach": away_coach,
        "scraped_at": scraped_at[:26] if scraped_at else "",
    }


def _extract_events(payload: Dict[str, Any], game_id: str, game_date: str,
                    league: str, season: str) -> List[Dict[str, Any]]:
    rows = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue

        assists_raw = event.get("assists") or []
        assists_json = json.dumps(assists_raw) if assists_raw else None

        rows.append({
            "game_id": game_id,
            "game_date": parse_date(game_date),
            "season": season,
            "league": league,
            "period": to_int(event.get("period")),
            "event_time": event.get("time") or "",
            "event_type": event.get("event_type") or "",
            "team": event.get("team") or "",
            "player_name": event.get("player_name") or "",
            "player_number": str(event.get("player_number") or ""),
            "goal_type": event.get("goal_type") or "",
            "penalty_minutes": to_int(event.get("penalty_minutes")),
            "penalty_start": event.get("penalty_start") or "",
            "penalty_end": event.get("penalty_end") or "",
            "penalty_type": event.get("penalty_type") or "",
            "goalkeeper_action": event.get("goalkeeper_action") or "",
            "powerplay_number": to_int(event.get("powerplay_number")),
            "score_home": to_int(event.get("score_home")),
            "score_away": to_int(event.get("score_away")),
            "assists": assists_json,
        })
    return rows


def _extract_goalkeepers(payload: Dict[str, Any], game_id: str, game_date: str,
                          league: str, season: str) -> List[Dict[str, Any]]:
    rows = []
    for gk in payload.get("goalkeepers") or []:
        if not isinstance(gk, dict):
            continue
        rows.append({
            "game_id": game_id,
            "game_date": parse_date(game_date),
            "season": season,
            "league": league,
            "team": gk.get("team") or "",
            "name": gk.get("name") or "",
            "number": str(gk.get("number") or ""),
            "saves": to_int(gk.get("saves")),
            "shots_against": to_int(gk.get("shots_against")),
            "save_pct": to_float(gk.get("save_percentage")),
        })
    return rows


def _lineup_player_row(game_id, game_date, season, league, team, is_home,
                        head_coach, assistant_coach, line_num, position,
                        player: Dict) -> Dict:
    """Bygg en spelrad från ett player-objekt oavsett format."""
    pos = (player.get("position") or position or "").upper()
    if pos == "MV":
        pos = "G"
    return {
        "game_id": game_id,
        "game_date": parse_date(game_date),
        "season": season,
        "league": league,
        "team": team,
        "is_home": is_home,
        "head_coach": head_coach,
        "assistant_coach": assistant_coach,
        "line_number": line_num,
        "position": pos,
        "player_name": player.get("name") or "",
        "player_number": str(player.get("number") or ""),
        "is_starting": bool(player.get("starting")),
    }


def _extract_lineups(payload: Dict[str, Any], game_id: str, game_date: str,
                     league: str, season: str) -> List[Dict[str, Any]]:
    rows = []

    _old_position_map = {
        "left_wing": "LW",
        "center": "C",
        "right_wing": "RW",
        "left_defense": "LD",
        "right_defense": "RD",
    }

    for side_key, is_home in (("home_team_lineup", True), ("away_team_lineup", False)):
        lineup = payload.get(side_key)
        if not isinstance(lineup, dict):
            continue

        team = _clean_str(lineup.get("team"))
        head_coach = lineup.get("head_coach") or ""
        assistant_coach = lineup.get("assistant_coach") or ""

        for gk in lineup.get("goalies") or []:
            if isinstance(gk, dict):
                rows.append(_lineup_player_row(
                    game_id, game_date, season, league, team, is_home,
                    head_coach, assistant_coach,
                    line_num=None, position="G", player=gk,
                ))

        for line in lineup.get("lines") or []:
            if not isinstance(line, dict):
                continue
            line_num = to_int(line.get("line") or line.get("line_number"))

            if "forwards" in line or "defense" in line:
                for player in (line.get("forwards") or []) + (line.get("defense") or []):
                    if isinstance(player, dict):
                        rows.append(_lineup_player_row(
                            game_id, game_date, season, league, team, is_home,
                            head_coach, assistant_coach,
                            line_num=line_num, position="", player=player,
                        ))
            else:
                for pos_key, pos_abbr in _old_position_map.items():
                    player = line.get(pos_key)
                    if isinstance(player, dict):
                        rows.append(_lineup_player_row(
                            game_id, game_date, season, league, team, is_home,
                            head_coach, assistant_coach,
                            line_num=line_num, position=pos_abbr, player=player,
                        ))

        for player in lineup.get("extra_players") or []:
            if isinstance(player, dict):
                rows.append(_lineup_player_row(
                    game_id, game_date, season, league, team, is_home,
                    head_coach, assistant_coach,
                    line_num=None, position="EXTRA", player=player,
                ))

    return rows


def _extract_period_scores(payload: Dict[str, Any], game_id: str, game_date: str,
                            league: str, season: str) -> List[Dict[str, Any]]:
    rows = []
    for ps in payload.get("period_scores") or []:
        if not isinstance(ps, dict):
            continue
        rows.append({
            "game_id": game_id,
            "game_date": parse_date(game_date),
            "season": season,
            "league": league,
            "period": str(ps.get("period", "")),
            "home_score": to_int(ps.get("home")),
            "away_score": to_int(ps.get("away")),
        })
    return rows


def _extract_referees_json(payload: Dict[str, Any], game_id: str, game_date: str,
                            league: str, season: str) -> List[Dict[str, Any]]:
    """Hanterar både listformat (str) och dict-format för referees/linesmen."""
    rows = []
    for ref in payload.get("referees") or []:
        if isinstance(ref, str):
            name, role = ref, "Referee"
        elif isinstance(ref, dict):
            name, role = ref.get("name") or "", ref.get("role") or "Referee"
        else:
            continue
        rows.append({
            "game_id": game_id,
            "game_date": parse_date(game_date),
            "season": season,
            "league": league,
            "name": name,
            "role": role,
        })
    for linesman in payload.get("linesmen") or []:
        if isinstance(linesman, str):
            name = linesman
        elif isinstance(linesman, dict):
            name = linesman.get("name") or ""
        else:
            continue
        rows.append({
            "game_id": game_id,
            "game_date": parse_date(game_date),
            "season": season,
            "league": league,
            "name": name,
            "role": "Linesman",
        })
    return rows


def _extract_on_ice_json(payload: Dict[str, Any], game_id: str, game_date: str,
                          league: str, season: str) -> List[Dict[str, Any]]:
    """Extrahera on-ice spelare vid händelser.
    event_team = laget som äger händelsen (positiv sida).
    team_side = 'positive' (event_team) eller 'negative' (motståndet).
    """
    rows = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        pos_participants = event.get("positive_participants") or []
        neg_participants = event.get("negative_participants") or []
        if not pos_participants and not neg_participants:
            continue

        event_type = event.get("event_type") or ""
        period = to_int(event.get("period"))
        event_time = event.get("time") or ""
        event_team = event.get("team") or ""  # laget som äger händelsen

        for side, participants in (("positive", pos_participants), ("negative", neg_participants)):
            for player_number in participants:
                rows.append({
                    "game_id": game_id,
                    "game_date": parse_date(game_date),
                    "season": season,
                    "league": league,
                    "period": period,
                    "event_time": event_time,
                    "event_type": event_type,
                    "event_team": event_team,
                    "team_side": side,
                    "player_number": str(player_number),
                })
    return rows


def _extract_player_stats_json(payload: Dict[str, Any], game_id: str, game_date: str,
                                league: str, season: str) -> List[Dict[str, Any]]:
    rows = []
    for ps in payload.get("player_stats") or []:
        if not isinstance(ps, dict):
            continue
        rows.append({
            "game_id": game_id,
            "game_date": parse_date(game_date),
            "season": season,
            "league": league,
            "team": ps.get("team") or "",
            "player_id": str(ps.get("player_id") or ""),
            "player_name": ps.get("player_name") or "",
            "goals": to_int(ps.get("goals")),
            "assists": to_int(ps.get("assists")),
            "pim": to_int(ps.get("pim")),
            "shots": to_int(ps.get("shots")),
            "plus_minus": to_int(ps.get("plusMinus") or ps.get("plus_minus")),
        })
    return rows


def _df(rows: List[Dict], columns: List[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns] if not df.empty else pd.DataFrame(columns=columns)


@transformer
def transform_swe_games(payload: Dict[str, Any], *args, **kwargs):
    if isinstance(payload, dict) and payload.get("batched"):
        return payload

    game_rows: List[Dict] = []
    event_rows: List[Dict] = []
    goalkeeper_rows: List[Dict] = []
    lineup_rows: List[Dict] = []
    period_score_rows: List[Dict] = []
    referee_rows: List[Dict] = []
    on_ice_rows: List[Dict] = []
    player_stat_rows: List[Dict] = []

    for item in payload.get("games") or []:
        game_date = item.get("game_date", "")
        game_id = str(item.get("game_id", ""))
        data = item.get("payload") or {}

        league = _clean_str(data.get("league"))
        season = _derive_season(game_date)

        game_rows.append(_extract_game_row(data, game_date))
        event_rows.extend(_extract_events(data, game_id, game_date, league, season))
        goalkeeper_rows.extend(_extract_goalkeepers(data, game_id, game_date, league, season))
        lineup_rows.extend(_extract_lineups(data, game_id, game_date, league, season))
        period_score_rows.extend(_extract_period_scores(data, game_id, game_date, league, season))
        referee_rows.extend(_extract_referees_json(data, game_id, game_date, league, season))
        on_ice_rows.extend(_extract_on_ice_json(data, game_id, game_date, league, season))
        player_stat_rows.extend(_extract_player_stats_json(data, game_id, game_date, league, season))

    games_df = _df(game_rows, GAMES_COLUMNS)
    events_df = _df(event_rows, EVENTS_COLUMNS)
    goalkeepers_df = _df(goalkeeper_rows, GOALKEEPERS_COLUMNS)
    lineups_df = _df(lineup_rows, LINEUPS_COLUMNS)
    period_scores_df = _df(period_score_rows, PERIOD_SCORES_COLUMNS)
    referees_json_df = _df(referee_rows, REFEREES_JSON_COLUMNS)
    on_ice_json_df = _df(on_ice_rows, ON_ICE_JSON_COLUMNS)
    player_stats_json_df = _df(player_stat_rows, PLAYER_STATS_JSON_COLUMNS)

    # Ta bort dubletter
    if not games_df.empty:
        games_df = games_df.drop_duplicates(subset=["game_id"], keep="first")
    if not events_df.empty:
        events_df = events_df.drop_duplicates(
            subset=["game_id", "period", "event_time", "event_type", "player_name"],
            keep="first",
        )
    if not goalkeepers_df.empty:
        goalkeepers_df = goalkeepers_df.drop_duplicates(
            subset=["game_id", "team", "name"], keep="first"
        )
    if not lineups_df.empty:
        lineups_df = lineups_df.drop_duplicates(
            subset=["game_id", "team", "position", "player_number"], keep="first"
        )
    if not period_scores_df.empty:
        period_scores_df = period_scores_df.drop_duplicates(
            subset=["game_id", "period"], keep="first"
        )
    if not referees_json_df.empty:
        referees_json_df = referees_json_df.drop_duplicates(
            subset=["game_id", "name"], keep="first"
        )
    if not on_ice_json_df.empty:
        on_ice_json_df = on_ice_json_df.drop_duplicates(
            subset=["game_id", "period", "event_time", "event_type", "team_side", "player_number"],
            keep="first",
        )
    if not player_stats_json_df.empty:
        player_stats_json_df = player_stats_json_df.drop_duplicates(
            subset=["game_id", "team", "player_name"], keep="first"
        )

    print(
        f"[swe transform] games={len(games_df)}, events={len(events_df)}, "
        f"goalkeepers={len(goalkeepers_df)}, lineups={len(lineups_df)}, "
        f"period_scores={len(period_scores_df)}, referees_json={len(referees_json_df)}, "
        f"on_ice_json={len(on_ice_json_df)}, player_stats_json={len(player_stats_json_df)}"
    )

    return {
        "games": games_df,
        "game_events": events_df,
        "game_goalkeepers": goalkeepers_df,
        "game_lineups": lineups_df,
        "game_period_scores": period_scores_df,
        "game_referees_json": referees_json_df,
        "game_on_ice_json": on_ice_json_df,
        "game_player_stats_json": player_stats_json_df,
        "newest_date": payload.get("last_date"),
    }
