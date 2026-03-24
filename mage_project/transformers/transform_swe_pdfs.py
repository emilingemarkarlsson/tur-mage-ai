"""
Transformera Swehockey PDF-data till DataFrames.

Input: {"games": [{game_id, game_date, pdfs: {pdf_type: bytes}}]}
Output: {
  "game_referees": DataFrame,
  "game_period_stats": DataFrame,
  "game_roster": DataFrame,
  "game_player_stats": DataFrame,
  "game_goalie_stats": DataFrame,
  "game_on_ice": DataFrame,
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
    "game_id", "game_date", "name", "role",
]

PERIOD_STATS_COLUMNS = [
    "game_id", "game_date", "team", "period",
    "goals", "shots", "saves", "svs_pct", "pim",
    "tpp_sec", "adv", "pp_pct", "tsh_sec", "dvg", "sh_pct",
]

ROSTER_COLUMNS = [
    "game_id", "game_date", "team", "position", "number", "name",
    "birthdate", "captain_role", "line_label", "is_coach", "coach_role",
]

PLAYER_STATS_COLUMNS = [
    "game_id", "game_date", "team", "number", "name", "position",
    "goals", "assists", "points", "plus_minus", "pim", "sog",
    "fo_won", "fo_lost", "fo_pct", "hits", "blocks", "shifts", "toi",
    "source",
]

GOALIE_STATS_COLUMNS = [
    "game_id", "game_date", "team", "number", "name",
    "sog", "ga", "saves", "svs_pct", "toi", "gaa",
    "source",
]

ON_ICE_COLUMNS = [
    "game_id", "game_date", "period", "event_time", "score",
    "event_type", "team_abbr", "side", "player_number",
]


def _df(rows: List[Dict], columns: List[str]) -> pd.DataFrame:
    """Bygg DataFrame med fast schema; lägg till saknade kolumner som None."""
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns] if not df.empty else pd.DataFrame(columns=columns)


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

    # Media har bättre data (fler kolumner) – returnera media
    # Men om media saknar team-info, fyll från official
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

    seen_referees: set = set()

    for item in payload.get("games") or []:
        game_id = str(item.get("game_id", ""))
        game_date = str(item.get("game_date", ""))
        pdfs = item.get("pdfs") or {}

        if not game_id:
            continue

        # --- Official_Game_Report ---
        if "Official_Game_Report" in pdfs:
            result = parse_pdf("Official_Game_Report", pdfs["Official_Game_Report"], game_id, game_date)

            # Referees (deduplicera per match)
            for ref in result.get("referees", []):
                key = (game_id, ref.get("name", ""))
                if key not in seen_referees:
                    seen_referees.add(key)
                    all_referees.append(ref)

            # Period stats
            all_period_stats.extend(result.get("period_stats", []))

            # On-ice events
            all_on_ice.extend(result.get("on_ice_events", []))

        # --- Official_Team_Roster ---
        if "Official_Team_Roster" in pdfs:
            result = parse_pdf("Official_Team_Roster", pdfs["Official_Team_Roster"], game_id, game_date)
            all_roster.extend(result.get("roster", []))

        # --- Player stats: föredra Media_Game_Summary, fallback Player_Summary ---
        player_rows_official: List[Dict] = []
        goalie_rows_official: List[Dict] = []
        player_rows_media: List[Dict] = []
        goalie_rows_media: List[Dict] = []

        if "Player_Summary" in pdfs:
            result = parse_pdf("Player_Summary", pdfs["Player_Summary"], game_id, game_date)
            player_rows_official = result.get("player_stats", [])
            goalie_rows_official = result.get("goalie_stats", [])

        if "Media_Game_Summary" in pdfs:
            result = parse_pdf("Media_Game_Summary", pdfs["Media_Game_Summary"], game_id, game_date)
            player_rows_media = result.get("player_stats", [])
            goalie_rows_media = result.get("goalie_stats", [])

        # Official_Line_Up: referees backup (om ej i Game_Report)
        if "Official_Line_Up" in pdfs and not any(r["game_id"] == game_id for r in all_referees):
            result = parse_pdf("Official_Line_Up", pdfs["Official_Line_Up"], game_id, game_date)
            for ref in result.get("referees", []):
                key = (game_id, ref.get("name", ""))
                if key not in seen_referees:
                    seen_referees.add(key)
                    all_referees.append(ref)

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

    # Normalisera kolumntyper
    if not period_stats_df.empty:
        period_stats_df["period"] = period_stats_df["period"].astype(str)
    if not on_ice_df.empty:
        on_ice_df["period"] = on_ice_df["period"].astype(str)

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

    print(
        f"[swe pdf transform] referees={len(referees_df)}, "
        f"period_stats={len(period_stats_df)}, roster={len(roster_df)}, "
        f"player_stats={len(player_stats_df)}, goalie_stats={len(goalie_stats_df)}, "
        f"on_ice={len(on_ice_df)}"
    )

    return {
        "game_referees": referees_df,
        "game_period_stats": period_stats_df,
        "game_roster": roster_df,
        "game_player_stats": player_stats_df,
        "game_goalie_stats": goalie_stats_df,
        "game_on_ice": on_ice_df,
    }
