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
    "game_id", "game_date", "season", "league", "league_id",
    "home_team", "away_team", "home_score", "away_score",
    "home_points", "away_points", "venue", "time",
    "home_shots", "away_shots", "home_saves", "away_saves",
    "home_save_pct", "away_save_pct", "home_pim", "away_pim",
    "periods", "scraped_at",
]

EVENTS_COLUMNS = [
    "game_id", "game_date", "period", "event_time", "event_type",
    "team", "player_name", "player_number", "goal_type",
    "penalty_minutes", "penalty_start", "penalty_end",
    "score_home", "score_away", "assists",
]

GOALKEEPERS_COLUMNS = [
    "game_id", "game_date", "team", "name", "number",
    "saves", "shots_against", "save_pct",
]

LINEUPS_COLUMNS = [
    "game_id", "game_date", "team", "is_home",
    "head_coach", "assistant_coach",
    "line_number", "position", "player_name", "player_number",
    "is_starting",
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
    # home_save_pct = home_saves / away_shots  (INTE home_saves / home_shots)
    home_save_pct = round(home_saves / away_shots * 100, 2) if away_shots else None
    away_save_pct = round(away_saves / home_shots * 100, 2) if home_shots else None

    scraped_at = (payload.get("metadata") or {}).get("scraped_at") or ""

    return {
        "game_id": game_id,
        "game_date": parse_date(game_date),
        "season": _derive_season(game_date),
        "league": _clean_str(payload.get("league")),
        "league_id": str(payload.get("league_id") or ""),
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
        "scraped_at": scraped_at[:26] if scraped_at else "",
    }


def _extract_events(payload: Dict[str, Any], game_id: str, game_date: str) -> List[Dict[str, Any]]:
    rows = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue

        assists_raw = event.get("assists") or []
        assists_json = json.dumps(assists_raw) if assists_raw else None

        rows.append({
            "game_id": game_id,
            "game_date": parse_date(game_date),
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
            "score_home": to_int(event.get("score_home")),
            "score_away": to_int(event.get("score_away")),
            "assists": assists_json,
        })
    return rows


def _extract_goalkeepers(payload: Dict[str, Any], game_id: str, game_date: str) -> List[Dict[str, Any]]:
    rows = []
    for gk in payload.get("goalkeepers") or []:
        if not isinstance(gk, dict):
            continue
        rows.append({
            "game_id": game_id,
            "game_date": parse_date(game_date),
            "team": gk.get("team") or "",
            "name": gk.get("name") or "",
            "number": str(gk.get("number") or ""),
            "saves": to_int(gk.get("saves")),
            "shots_against": to_int(gk.get("shots_against")),
            "save_pct": to_float(gk.get("save_percentage")),
        })
    return rows


def _lineup_player_row(game_id, game_date, team, is_home, head_coach, assistant_coach,
                        line_num, position, player: Dict) -> Dict:
    """Bygg en spelrad från ett player-objekt oavsett format."""
    # Standardisera MV → G (svensk position-förkortning)
    pos = (player.get("position") or position or "").upper()
    if pos == "MV":
        pos = "G"
    return {
        "game_id": game_id,
        "game_date": parse_date(game_date),
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


def _extract_lineups(payload: Dict[str, Any], game_id: str, game_date: str) -> List[Dict[str, Any]]:
    """Plattar laguppställning till en rad per spelare.

    Hanterar det faktiska formatet (bekräftat via S3-sampling):
      lines[i].forwards = [{number, name, position, starting}, ...]
      lines[i].defense  = [{number, name, position, starting}, ...]
      lines[i].line     = linje-nummer (int)

    Hanterar också gammalt format som fallback:
      lines[i].left_wing / center / right_wing / left_defense / right_defense
    """
    rows = []

    # Gammalt format: position som nyckel direkt på line-objektet
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

        base = dict(
            game_id=game_id, game_date=parse_date(game_date),
            team=team, is_home=is_home,
            head_coach=head_coach, assistant_coach=assistant_coach,
        )

        # Målvakter (finns i båda formaten under "goalies")
        for gk in lineup.get("goalies") or []:
            if isinstance(gk, dict):
                rows.append(_lineup_player_row(
                    game_id, game_date, team, is_home,
                    head_coach, assistant_coach,
                    line_num=None, position="G", player=gk,
                ))

        # Fältspelare
        for line in lineup.get("lines") or []:
            if not isinstance(line, dict):
                continue

            # Nytt format använder "line" (int), gammalt använder "line_number"
            line_num = to_int(line.get("line") or line.get("line_number"))

            # FIX: Nytt format – forwards[] + defense[]
            if "forwards" in line or "defense" in line:
                for player in (line.get("forwards") or []) + (line.get("defense") or []):
                    if isinstance(player, dict):
                        rows.append(_lineup_player_row(
                            game_id, game_date, team, is_home,
                            head_coach, assistant_coach,
                            line_num=line_num, position="", player=player,
                        ))
            else:
                # Gammalt format – left_wing, center, right_wing, left_defense, right_defense
                for pos_key, pos_abbr in _old_position_map.items():
                    player = line.get(pos_key)
                    if isinstance(player, dict):
                        rows.append(_lineup_player_row(
                            game_id, game_date, team, is_home,
                            head_coach, assistant_coach,
                            line_num=line_num, position=pos_abbr, player=player,
                        ))

        # Extra spelare
        for player in lineup.get("extra_players") or []:
            if isinstance(player, dict):
                rows.append(_lineup_player_row(
                    game_id, game_date, team, is_home,
                    head_coach, assistant_coach,
                    line_num=None, position="EXTRA", player=player,
                ))

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

    for item in payload.get("games") or []:
        game_date = item.get("game_date", "")
        game_id = str(item.get("game_id", ""))
        data = item.get("payload") or {}

        game_rows.append(_extract_game_row(data, game_date))
        event_rows.extend(_extract_events(data, game_id, game_date))
        goalkeeper_rows.extend(_extract_goalkeepers(data, game_id, game_date))
        lineup_rows.extend(_extract_lineups(data, game_id, game_date))

    games_df = _df(game_rows, GAMES_COLUMNS)
    events_df = _df(event_rows, EVENTS_COLUMNS)
    goalkeepers_df = _df(goalkeeper_rows, GOALKEEPERS_COLUMNS)
    lineups_df = _df(lineup_rows, LINEUPS_COLUMNS)

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

    print(
        f"[swe transform] games={len(games_df)}, events={len(events_df)}, "
        f"goalkeepers={len(goalkeepers_df)}, lineups={len(lineups_df)}"
    )

    return {
        "games": games_df,
        "game_events": events_df,
        "game_goalkeepers": goalkeepers_df,
        "game_lineups": lineups_df,
        "newest_date": payload.get("last_date"),
    }
