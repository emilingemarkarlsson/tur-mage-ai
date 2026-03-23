"""
Classify and rank anomaly candidates into actionable insight objects.

Each insight has:
  - insight_type: hot_streak | cold_spell | breakout | slump | goalie_hot | goalie_cold | team_surge | team_collapse | possession_edge
  - severity: 0.0–1.0 (normalized abs z-score, capped at z=3)
  - entity info + supporting numbers
  - prompt_context: ready-made string for LLM narrative generation
"""
import hashlib
from datetime import date, datetime
from typing import Any

import pandas as pd

if "transformer" not in globals():
    from mage_ai.data_preparation.decorators import transformer


def _severity(z: float) -> float:
    """Normalize |z-score| to 0–1, capped at z=3."""
    return round(min(abs(float(z)), 3.0) / 3.0, 4)


def _insight_id(entity_type: str, entity_id: str, insight_type: str, game_date: Any) -> str:
    raw = f"{entity_type}:{entity_id}:{insight_type}:{game_date}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _classify_player(z: float) -> str:
    if z >= 2.5:  return "breakout"
    if z >= 1.0:  return "hot_streak"
    if z <= -2.5: return "slump"
    return "cold_spell"


def _classify_team(z: float) -> str:
    if z >= 1.5:
        return "team_surge"
    return "team_collapse"


def _player_context(row: pd.Series) -> str:
    direction = "above" if row.pts_zscore_5v20 > 0 else "below"
    return (
        f"{row.player_first_name} {row.player_last_name} ({row.team_abbr}, {row.position}) "
        f"is averaging {row.pts_avg_5g:.2f} pts/game over the last 5 games, "
        f"vs their 20-game baseline of {row.pts_avg_20g:.2f} pts/game "
        f"(z-score: {row.pts_zscore_5v20:+.2f}, {direction} baseline). "
        f"Season totals: {int(row.pts_season)} pts in {int(row.gp_season)} games. "
        f"Most recent game: {row.game_date}."
    )


def _goalie_context(row: pd.Series) -> str:
    direction = "above" if row.sv_pct_zscore_5v20 > 0 else "below"
    return (
        f"Goalie {row.player_first_name} {row.player_last_name} ({row.team_abbr}) "
        f"has a 5-game save% of {row.sv_pct_avg_5g:.3f}, "
        f"vs 20-game baseline of {row.sv_pct_avg_20g:.3f} "
        f"(z-score: {row.sv_pct_zscore_5v20:+.2f}, {direction} baseline). "
        f"Games played this season: {int(row.gp_season)}. "
        f"Most recent game: {row.game_date}."
    )


def _team_context(row: pd.Series) -> str:
    direction = "above" if row.pts_zscore_5v20 > 0 else "below"
    record_5g = f"{int(row.wins_last_5)}W-{int(row.losses_last_5)}L"
    return (
        f"{row.team_abbr} is averaging {row.pts_avg_5g:.2f} pts/game over the last 5 games "
        f"({record_5g}), vs 20-game baseline of {row.pts_avg_20g:.2f} "
        f"(z-score: {row.pts_zscore_5v20:+.2f}, {direction} baseline). "
        f"Season: {int(row.pts_cumulative)} pts in {int(row.gp_season)} GP. "
        f"10-game avg GF/GA: {row.gf_avg_10g:.2f}/{row.ga_avg_10g:.2f}. "
        f"Last game: {row.game_date}."
    )


def _corsi_context(row: pd.Series) -> str:
    edge = "strong possession edge" if row.corsi_pct_avg_10g > 0.50 else "possession concerns"
    return (
        f"{row.team_abbr} has a 10-game Corsi% of {row.corsi_pct_avg_10g:.3f} "
        f"({int(row.n)} games analyzed) – {edge}. "
        f"Corsi% below 0.42 or above 0.58 is a statistically significant outlier."
    )


@transformer
def transform(data: dict, *args, **kwargs) -> list[dict]:
    insights = []
    today = date.today().isoformat()

    # ── Player insights ──────────────────────────────────────────────────────
    player_df = data.get("player_anomalies", pd.DataFrame())
    for _, row in player_df.iterrows():
        z = float(row.pts_zscore_5v20)
        itype = _classify_player(z)
        insights.append({
            "insight_id":    _insight_id("player", str(row.player_id), itype, row.game_date),
            "generated_at":  datetime.utcnow().isoformat(),
            "insight_type":  itype,
            "entity_type":   "player",
            "entity_id":     str(row.player_id),
            "entity_name":   f"{row.player_first_name} {row.player_last_name}",
            "team_abbr":     row.team_abbr,
            "severity":      _severity(z),
            "zscore":        round(z, 3),
            "season":        str(row.season),
            "game_date":     str(row.game_date),
            "prompt_context": _player_context(row),
            "headline":      None,
            "body":          None,
        })

    # ── Goalie insights ──────────────────────────────────────────────────────
    goalie_df = data.get("goalie_anomalies", pd.DataFrame())
    for _, row in goalie_df.iterrows():
        z = float(row.sv_pct_zscore_5v20)
        itype = "goalie_hot" if z > 0 else "goalie_cold"
        insights.append({
            "insight_id":    _insight_id("player", str(row.player_id), itype, row.game_date),
            "generated_at":  datetime.utcnow().isoformat(),
            "insight_type":  itype,
            "entity_type":   "player",
            "entity_id":     str(row.player_id),
            "entity_name":   f"{row.player_first_name} {row.player_last_name}",
            "team_abbr":     row.team_abbr,
            "severity":      _severity(z),
            "zscore":        round(z, 3),
            "season":        str(row.season),
            "game_date":     str(row.game_date),
            "prompt_context": _goalie_context(row),
            "headline":      None,
            "body":          None,
        })

    # ── Team insights ────────────────────────────────────────────────────────
    team_df = data.get("team_anomalies", pd.DataFrame())
    for _, row in team_df.iterrows():
        z = float(row.pts_zscore_5v20)
        itype = _classify_team(z)
        insights.append({
            "insight_id":    _insight_id("team", row.team_abbr, itype, row.game_date),
            "generated_at":  datetime.utcnow().isoformat(),
            "insight_type":  itype,
            "entity_type":   "team",
            "entity_id":     row.team_abbr,
            "entity_name":   row.team_abbr,
            "team_abbr":     row.team_abbr,
            "severity":      _severity(z),
            "zscore":        round(z, 3),
            "season":        str(row.season),
            "game_date":     str(row.game_date),
            "prompt_context": _team_context(row),
            "headline":      None,
            "body":          None,
        })

    # ── Corsi/possession insights ─────────────────────────────────────────────
    corsi_df = data.get("corsi_outliers", pd.DataFrame())
    for _, row in corsi_df.iterrows():
        z_proxy = (row.corsi_pct_avg_10g - 0.50) / 0.04  # rough z relative to league avg
        insights.append({
            "insight_id":    _insight_id("team", row.team_abbr, "possession_edge", today),
            "generated_at":  datetime.utcnow().isoformat(),
            "insight_type":  "possession_edge",
            "entity_type":   "team",
            "entity_id":     row.team_abbr,
            "entity_name":   row.team_abbr,
            "team_abbr":     row.team_abbr,
            "severity":      _severity(z_proxy),
            "zscore":        round(z_proxy, 3),
            "season":        today[:4],
            "game_date":     today,
            "prompt_context": _corsi_context(row),
            "headline":      None,
            "body":          None,
        })

    # Sort by severity desc; top insights get LLM narratives (cost-controlled in next block)
    insights.sort(key=lambda x: x["severity"], reverse=True)
    print(f"[detect_anomalies] {len(insights)} total candidates ranked by severity")
    return insights
