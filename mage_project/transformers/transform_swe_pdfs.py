"""
Transformera Swehockey PDF-data till DataFrames.

Input: {"games": [{game_id, game_date, league, pdfs: {pdf_type: bytes}}]}
Output: {
  "game_referees": DataFrame,
  "game_period_stats": DataFrame,
  "game_roster": DataFrame,
  "game_player_stats": DataFrame,
  "game_goalie_stats": DataFrame,
  "game_on_ice": DataFrame,
  "game_goals": DataFrame,
  "game_penalties": DataFrame,
  "game_gk_changes": DataFrame,
  "game_starting_lineup": DataFrame,
  "game_spectators": DataFrame,
}
"""
import sys
from typing import Any, Dict, List

import pandas as pd
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.swe_pdf_parser import parse_pdf

if "transformer" not in globals():
    from mage_ai.data_preparation.decorators import transformer


# ---------------------------------------------------------------------------
# Kolumnschema – säkerställer konsistent Parquet-schema
# ---------------------------------------------------------------------------

REFEREES_COLUMNS = [
    "game_id", "game_date", "season", "league", "name", "role",
]

PERIOD_STATS_COLUMNS = [
    "game_id", "game_date", "season", "league", "team", "period",
    "goals", "shots", "saves", "svs_pct", "pim",
    "tpp_sec", "adv", "pp_pct", "tsh_sec", "dvg", "sh_pct",
]

ROSTER_COLUMNS = [
    "game_id", "game_date", "season", "league", "team", "position", "number", "name",
    "birthdate", "captain_role", "line_label", "is_coach", "coach_role",
]

PLAYER_STATS_COLUMNS = [
    "game_id", "game_date", "season", "league", "team", "number", "name", "position",
    "goals", "assists", "points", "plus_minus", "pim", "sog",
    "fo_won", "fo_lost", "fo_pct", "hits", "blocks", "shifts", "toi",
    "source",
]

GOALIE_STATS_COLUMNS = [
    "game_id", "game_date", "season", "league", "team", "number", "name",
    "sog", "ga", "saves", "svs_pct", "toi", "gaa",
    "pp_svs", "pp_shots_against",
    "source",
]

GOALS_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "period", "event_time", "team_abbr", "score", "goal_type",
    "scorer_number", "scorer_name",
    "assist1_number", "assist1_name",
    "assist2_number", "assist2_name",
]

PENALTIES_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "period", "event_time", "team_abbr",
    "minutes", "player_number", "player_name", "infraction",
]

GK_CHANGES_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "period", "event_time", "team_abbr",
    "direction", "player_number", "player_name",
]

STARTING_LINEUP_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "team", "line_number", "number", "name", "position",
]

ON_ICE_COLUMNS = [
    "game_id", "game_date", "season", "league",
    "period", "event_time", "score",
    "event_type", "team_abbr", "side", "player_number",
]

SPECTATORS_COLUMNS = [
    "game_id", "game_date", "season", "league", "spectators",
]


def _df(rows: List[Dict], columns: List[str]) -> pd.DataFrame:
    """Bygg DataFrame med fast schema; lägg till saknade kolumner som None."""
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns] if not df.empty else pd.DataFrame(columns=columns)


def _tag(rows: List[Dict], season: str, league: str) -> List[Dict]:
    """Sätt season och league på alla rader (in-place, returnerar rows)."""
    for r in rows:
        r["season"] = season
        r["league"] = league
    return rows


def _merge_player_stats(from_official: List[Dict], from_media: List[Dict]) -> List[Dict]:
    """
    Slå ihop Player_Summary och Media_Game_Summary.
    Media_Game_Summary föredras (fler fält), men Player_Summary kan fylla luckor.
    """
    if not from_official and not from_media:
        return []
    if not from_official:
        return from_media
    if not from_media:
        return from_official

    media_has_teams = any(r.get("team") for r in from_media)
    official_has_teams = any(r.get("team") for r in from_official)
    if not media_has_teams and official_has_teams:
        return from_official
    return from_media


@transformer
def transform_swe_pdfs(payload: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
    if isinstance(payload, dict) and payload.get("batched"):
        return payload

    all_referees: List[Dict] = []
    all_period_stats: List[Dict] = []
    all_roster: List[Dict] = []
    all_player_stats: List[Dict] = []
    all_goalie_stats: List[Dict] = []
    all_on_ice: List[Dict] = []
    all_goals: List[Dict] = []
    all_penalties: List[Dict] = []
    all_gk_changes: List[Dict] = []
    all_starting_lineup: List[Dict] = []
    all_spectators: List[Dict] = []

    seen_referees: set = set()

    for item in payload.get("games") or []:
        game_id = str(item.get("game_id", ""))
        game_date = str(item.get("game_date", ""))
        league = str(item.get("league") or "")
        season = game_date[:4] if len(game_date) >= 4 else ""
        pdfs = item.get("pdfs") or {}

        if not game_id:
            continue

        # --- Official_Game_Report ---
        if "Official_Game_Report" in pdfs:
            result = parse_pdf("Official_Game_Report", pdfs["Official_Game_Report"], game_id, game_date)

            # Referees (deduplicera per match)
            for ref in _tag(result.get("referees", []), season, league):
                key = (game_id, ref.get("name", ""))
                if key not in seen_referees:
                    seen_referees.add(key)
                    all_referees.append(ref)

            all_period_stats.extend(_tag(result.get("period_stats", []), season, league))
            all_on_ice.extend(_tag(result.get("on_ice_events", []), season, league))
            all_goals.extend(_tag(result.get("goals", []), season, league))
            all_penalties.extend(_tag(result.get("penalties", []), season, league))
            all_gk_changes.extend(_tag(result.get("gk_changes", []), season, league))

            # Åskådarantal
            spectators = result.get("spectators")
            if spectators is not None:
                all_spectators.append({
                    "game_id": game_id,
                    "game_date": game_date,
                    "season": season,
                    "league": league,
                    "spectators": spectators,
                })

        # --- Official_Team_Roster ---
        if "Official_Team_Roster" in pdfs:
            result = parse_pdf("Official_Team_Roster", pdfs["Official_Team_Roster"], game_id, game_date)
            all_roster.extend(_tag(result.get("roster", []), season, league))

        # --- Player stats: föredra Media_Game_Summary, fallback Player_Summary ---
        player_rows_official: List[Dict] = []
        goalie_rows_official: List[Dict] = []
        player_rows_media: List[Dict] = []
        goalie_rows_media: List[Dict] = []

        if "Player_Summary" in pdfs:
            result = parse_pdf("Player_Summary", pdfs["Player_Summary"], game_id, game_date)
            player_rows_official = _tag(result.get("player_stats", []), season, league)
            goalie_rows_official = _tag(result.get("goalie_stats", []), season, league)

        if "Media_Game_Summary" in pdfs:
            result = parse_pdf("Media_Game_Summary", pdfs["Media_Game_Summary"], game_id, game_date)
            player_rows_media = _tag(result.get("player_stats", []), season, league)
            goalie_rows_media = _tag(result.get("goalie_stats", []), season, league)

        # Official_Line_Up: referees backup + starting lineup
        if "Official_Line_Up" in pdfs:
            result = parse_pdf("Official_Line_Up", pdfs["Official_Line_Up"], game_id, game_date)
            if not any(r["game_id"] == game_id for r in all_referees):
                for ref in _tag(result.get("referees", []), season, league):
                    key = (game_id, ref.get("name", ""))
                    if key not in seen_referees:
                        seen_referees.add(key)
                        all_referees.append(ref)
            all_starting_lineup.extend(_tag(result.get("starting_lineup", []), season, league))

        merged_players = _merge_player_stats(player_rows_official, player_rows_media)
        all_player_stats.extend(merged_players)

        merged_goalies = goalie_rows_media if goalie_rows_media else goalie_rows_official
        all_goalie_stats.extend(merged_goalies)

    # Bygg DataFrames
    referees_df = _df(all_referees, REFEREES_COLUMNS)
    period_stats_df = _df(all_period_stats, PERIOD_STATS_COLUMNS)
    roster_df = _df(all_roster, ROSTER_COLUMNS)
    player_stats_df = _df(all_player_stats, PLAYER_STATS_COLUMNS)
    goalie_stats_df = _df(all_goalie_stats, GOALIE_STATS_COLUMNS)
    on_ice_df = _df(all_on_ice, ON_ICE_COLUMNS)
    goals_df = _df(all_goals, GOALS_COLUMNS)
    penalties_df = _df(all_penalties, PENALTIES_COLUMNS)
    gk_changes_df = _df(all_gk_changes, GK_CHANGES_COLUMNS)
    starting_lineup_df = _df(all_starting_lineup, STARTING_LINEUP_COLUMNS)
    spectators_df = _df(all_spectators, SPECTATORS_COLUMNS)

    # Normalisera kolumntyper (period = str, blandat int/str: 1,2,3,"OT","SO","total")
    for df in (period_stats_df, on_ice_df, goals_df, penalties_df, gk_changes_df):
        if not df.empty and "period" in df.columns:
            df["period"] = df["period"].astype(str)

    # Deduplicera
    if not referees_df.empty:
        referees_df = referees_df.drop_duplicates(subset=["game_id", "name"], keep="first")
    if not period_stats_df.empty:
        period_stats_df = period_stats_df.drop_duplicates(
            subset=["game_id", "team", "period"], keep="first"
        )
    if not roster_df.empty:
        roster_df = roster_df.drop_duplicates(
            subset=["game_id", "team", "number", "name"], keep="first"
        )
    if not player_stats_df.empty:
        player_stats_df = player_stats_df.drop_duplicates(
            subset=["game_id", "team", "number", "name"], keep="first"
        )
    if not goalie_stats_df.empty:
        goalie_stats_df = goalie_stats_df.drop_duplicates(
            subset=["game_id", "team", "number"], keep="first"
        )
    if not on_ice_df.empty:
        on_ice_df = on_ice_df.drop_duplicates(
            subset=["game_id", "period", "event_time", "team_abbr", "player_number"],
            keep="first",
        )
    if not goals_df.empty:
        goals_df = goals_df.drop_duplicates(
            subset=["game_id", "period", "event_time", "team_abbr", "scorer_number"],
            keep="first",
        )
    if not penalties_df.empty:
        penalties_df = penalties_df.drop_duplicates(
            subset=["game_id", "period", "event_time", "team_abbr", "player_number"],
            keep="first",
        )
    if not gk_changes_df.empty:
        gk_changes_df = gk_changes_df.drop_duplicates(
            subset=["game_id", "period", "event_time", "team_abbr", "direction", "player_number"],
            keep="first",
        )
    if not starting_lineup_df.empty:
        starting_lineup_df = starting_lineup_df.drop_duplicates(
            subset=["game_id", "team", "number"],
            keep="first",
        )
    if not spectators_df.empty:
        spectators_df = spectators_df.drop_duplicates(subset=["game_id"], keep="first")

    print(
        f"[swe pdf transform] referees={len(referees_df)}, "
        f"period_stats={len(period_stats_df)}, roster={len(roster_df)}, "
        f"player_stats={len(player_stats_df)}, goalie_stats={len(goalie_stats_df)}, "
        f"on_ice={len(on_ice_df)}, goals={len(goals_df)}, "
        f"penalties={len(penalties_df)}, gk_changes={len(gk_changes_df)}, "
        f"starting_lineup={len(starting_lineup_df)}, spectators={len(spectators_df)}"
    )

    return {
        "game_referees": referees_df,
        "game_period_stats": period_stats_df,
        "game_roster": roster_df,
        "game_player_stats": player_stats_df,
        "game_goalie_stats": goalie_stats_df,
        "game_on_ice": on_ice_df,
        "game_goals": goals_df,
        "game_penalties": penalties_df,
        "game_gk_changes": gk_changes_df,
        "game_starting_lineup": starting_lineup_df,
        "game_spectators": spectators_df,
    }
