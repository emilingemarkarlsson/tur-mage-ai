"""
Load anomaly candidates from MotherDuck feature store.

Queries player_rolling_stats, goalie_rolling_stats, and team_rolling_stats
for rows where |z-score| >= Z_THRESHOLD (last 5 games vs 20-game baseline).
Only current season, only players/teams with sufficient game history (>= 20 games).
"""
import os
import sys

import duckdb
import pandas as pd
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader

# Minimum absolute z-score to be considered an anomaly candidate
Z_THRESHOLD = 1.0
# Minimum games played in current season to have a meaningful baseline
MIN_GAMES = 20
# Current season – derived from most recent regular-season game in MotherDuck
CURRENT_SEASON_SQL = "(SELECT MAX(season) FROM games WHERE game_type = '2')"


def _md_conn() -> duckdb.DuckDBPyConnection:
    token = os.getenv("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        raise RuntimeError("MOTHERDUCK_TOKEN not set")
    db = os.getenv("MOTHERDUCK_DATABASE_NAME", "nhl").strip() or "nhl"
    # Direct MotherDuck connection – works with the motherduck pip package
    # without needing INSTALL/LOAD extension (avoids HTTP 404 on new DuckDB versions)
    conn = duckdb.connect(f"md:{db}?motherduck_token={token}")
    return conn


@data_loader
def load_data(*args, **kwargs) -> dict:
    conn = _md_conn()
    results = {}

    # ── Player anomalies (skaters) ──────────────────────────────────────────
    try:
        results["player_anomalies"] = conn.execute(f"""
            SELECT
                player_id,
                player_first_name,
                player_last_name,
                team_abbr,
                position,
                game_date,
                season,
                pts_avg_5g,
                pts_avg_20g,
                pts_zscore_5v20,
                goals_zscore_5v20,
                pts_season,
                goals_season,
                gp_season,
                game_recency_rank
            FROM player_rolling_stats
            WHERE season = {CURRENT_SEASON_SQL}
              AND gp_season >= {MIN_GAMES}
              AND game_recency_rank = 1
              AND ABS(pts_zscore_5v20) >= {Z_THRESHOLD}
              AND player_first_name IS NOT NULL
              AND player_last_name IS NOT NULL
            ORDER BY ABS(pts_zscore_5v20) DESC
            LIMIT 20
        """).df()
        print(f"[load_analytics] player anomalies: {len(results['player_anomalies'])} rows")
    except Exception as e:
        print(f"[load_analytics] player_anomalies failed: {e}")
        results["player_anomalies"] = pd.DataFrame()

    # ── Goalie anomalies ─────────────────────────────────────────────────────
    try:
        results["goalie_anomalies"] = conn.execute(f"""
            SELECT
                player_id,
                player_first_name,
                player_last_name,
                team_abbr,
                game_date,
                season,
                sv_pct_avg_5g,
                sv_pct_avg_20g,
                sv_pct_zscore_5v20,
                gp_season,
                game_recency_rank
            FROM goalie_rolling_stats
            WHERE season = {CURRENT_SEASON_SQL}
              AND gp_season >= 10
              AND game_recency_rank = 1
              AND ABS(sv_pct_zscore_5v20) >= {Z_THRESHOLD}
              AND player_first_name IS NOT NULL
              AND player_last_name IS NOT NULL
            ORDER BY ABS(sv_pct_zscore_5v20) DESC
            LIMIT 10
        """).df()
        print(f"[load_analytics] goalie anomalies: {len(results['goalie_anomalies'])} rows")
    except Exception as e:
        print(f"[load_analytics] goalie_anomalies failed: {e}")
        results["goalie_anomalies"] = pd.DataFrame()

    # ── Team anomalies ───────────────────────────────────────────────────────
    try:
        results["team_anomalies"] = conn.execute(f"""
            SELECT
                team_abbr,
                game_date,
                season,
                pts_avg_5g,
                pts_avg_20g,
                pts_zscore_5v20,
                wins_last_5,
                losses_last_5,
                pts_cumulative,
                gp_season,
                gf_avg_10g,
                ga_avg_10g,
                game_recency_rank
            FROM team_rolling_stats
            WHERE season = {CURRENT_SEASON_SQL}
              AND gp_season >= {MIN_GAMES}
              AND game_recency_rank = 1
              AND ABS(pts_zscore_5v20) >= {Z_THRESHOLD}
            ORDER BY ABS(pts_zscore_5v20) DESC
            LIMIT 10
        """).df()
        print(f"[load_analytics] team anomalies: {len(results['team_anomalies'])} rows")
    except Exception as e:
        print(f"[load_analytics] team_anomalies failed: {e}")
        results["team_anomalies"] = pd.DataFrame()

    # ── Recent Corsi outliers (teams with corsi_pct < 0.42 or > 0.58) ───────
    try:
        results["corsi_outliers"] = conn.execute(f"""
            WITH recent AS (
                SELECT team_abbr, game_date, corsi_for, corsi_against, corsi_pct,
                    ROW_NUMBER() OVER (PARTITION BY team_abbr ORDER BY game_date DESC) AS rn
                FROM team_corsi
                WHERE TRY_CAST(game_type AS INTEGER) = 2
                  AND corsi_pct IS NOT NULL
            ),
            avg_last10 AS (
                SELECT tc.team_abbr,
                    AVG(tc.corsi_pct) AS corsi_pct_avg_10g,
                    COUNT(*)          AS n
                FROM team_corsi tc
                JOIN (SELECT DISTINCT team_abbr, game_date AS latest
                      FROM recent WHERE rn = 1) r ON r.team_abbr = tc.team_abbr
                WHERE tc.game_type = '2'
                  AND tc.game_date >= r.latest - INTERVAL 20 DAY
                  AND tc.corsi_pct IS NOT NULL
                GROUP BY tc.team_abbr
                HAVING COUNT(*) >= 5
            )
            SELECT * FROM avg_last10
            WHERE corsi_pct_avg_10g < 0.42 OR corsi_pct_avg_10g > 0.58
            ORDER BY corsi_pct_avg_10g DESC
        """).df()
        print(f"[load_analytics] corsi outliers: {len(results['corsi_outliers'])} rows")
    except Exception as e:
        print(f"[load_analytics] corsi_outliers failed: {e}")
        results["corsi_outliers"] = pd.DataFrame()

    conn.close()
    return results
