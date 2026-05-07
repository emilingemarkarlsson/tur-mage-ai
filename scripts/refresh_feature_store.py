"""
Refresh feature store tables in MotherDuck.

Runs directly against MotherDuck's base game tables (which are kept up to
date by daily UPSERT sync). Safe to call after games_pipeline has finished.

Can be run standalone:
    python3 scripts/refresh_feature_store.py
Or imported and called from run_analytics_pipeline.py.
"""
import os
import sys

import duckdb

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
_env_file = os.path.join(_project_root, ".env")
if os.path.isfile(_env_file):
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        pass


# ── SQL definitions ────────────────────────────────────────────────────────────
# Adapted from refresh_duckdb_views.py to run directly on MotherDuck tables.
# TRY_CAST used for game_type (stored as VARCHAR or DOUBLE depending on season).

_PLAYER_ROLLING_SQL = """
WITH name_lookup AS (
    SELECT DISTINCT playerId AS player_id,
           SPLIT_PART(skaterFullName, ' ', 1) AS first_name,
           REGEXP_REPLACE(skaterFullName, CONCAT(SPLIT_PART(skaterFullName, ' ', 1), ' '), '') AS last_name
    FROM skater_stats WHERE skaterFullName IS NOT NULL
    UNION
    SELECT DISTINCT playerId,
           SPLIT_PART(goalieFullName, ' ', 1),
           REGEXP_REPLACE(goalieFullName, CONCAT(SPLIT_PART(goalieFullName, ' ', 1), ' '), '')
    FROM goalie_stats WHERE goalieFullName IS NOT NULL
),
base AS (
    SELECT
        pgs.player_id,
        COALESCE(pgs.player_first_name, nl.first_name) AS player_first_name,
        COALESCE(pgs.player_last_name,  nl.last_name)  AS player_last_name,
        pgs.game_id, pgs.game_date,
        -- Derive season from game_id (format SSSSTTNNNN): 2009020611 → 20092010
        (pgs.game_id / 1000000)::BIGINT * 10000 + ((pgs.game_id / 1000000)::BIGINT + 1) AS season,
        pgs.team_abbr, pgs.position, pgs.is_home,
        COALESCE(pgs.goals, 0)       AS goals,
        COALESCE(pgs.assists, 0)     AS assists,
        COALESCE(pgs.points, 0)      AS points,
        COALESCE(pgs.shots, 0)       AS shots,
        COALESCE(pgs.toi_seconds, 0) AS toi_seconds,
        COALESCE(pgs.hits, 0)        AS hits,
        COALESCE(pgs.plus_minus, 0)  AS plus_minus
    FROM player_game_stats pgs
    LEFT JOIN name_lookup nl ON nl.player_id = pgs.player_id
    WHERE pgs.position NOT IN ('G') AND COALESCE(pgs.toi_seconds, 0) > 0
),
rolling AS (
    SELECT *,
        AVG(points)      OVER w5  AS pts_avg_5g,
        AVG(points)      OVER w10 AS pts_avg_10g,
        AVG(points)      OVER w20 AS pts_avg_20g,
        AVG(goals)       OVER w5  AS goals_avg_5g,
        AVG(goals)       OVER w10 AS goals_avg_10g,
        AVG(goals)       OVER w20 AS goals_avg_20g,
        AVG(shots)       OVER w10 AS shots_avg_10g,
        AVG(toi_seconds) OVER w10 AS toi_avg_10g,
        SUM(points)      OVER wseason AS pts_season,
        SUM(goals)       OVER wseason AS goals_season,
        SUM(assists)     OVER wseason AS assists_season,
        COUNT(*)         OVER wseason AS gp_season,
        STDDEV(points)   OVER w20 AS pts_stddev_20g,
        STDDEV(goals)    OVER w20 AS goals_stddev_20g,
        ROW_NUMBER()     OVER (PARTITION BY player_id ORDER BY game_date DESC) AS game_recency_rank
    FROM base
    WINDOW
        w5      AS (PARTITION BY player_id ORDER BY game_date ROWS BETWEEN 4  PRECEDING AND CURRENT ROW),
        w10     AS (PARTITION BY player_id ORDER BY game_date ROWS BETWEEN 9  PRECEDING AND CURRENT ROW),
        w20     AS (PARTITION BY player_id ORDER BY game_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        wseason AS (PARTITION BY player_id, season ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT *,
    ROUND(CASE WHEN pts_stddev_20g > 0
         THEN (pts_avg_5g - pts_avg_20g) / pts_stddev_20g
         ELSE 0 END, 3) AS pts_zscore_5v20,
    ROUND(CASE WHEN goals_stddev_20g > 0
         THEN (goals_avg_5g - goals_avg_20g) / goals_stddev_20g
         ELSE 0 END, 3) AS goals_zscore_5v20
FROM rolling
"""

_GOALIE_ROLLING_SQL = """
WITH name_lookup AS (
    SELECT DISTINCT playerId AS player_id,
           SPLIT_PART(skaterFullName, ' ', 1) AS first_name,
           REGEXP_REPLACE(skaterFullName, CONCAT(SPLIT_PART(skaterFullName, ' ', 1), ' '), '') AS last_name
    FROM skater_stats WHERE skaterFullName IS NOT NULL
    UNION
    SELECT DISTINCT playerId,
           SPLIT_PART(goalieFullName, ' ', 1),
           REGEXP_REPLACE(goalieFullName, CONCAT(SPLIT_PART(goalieFullName, ' ', 1), ' '), '')
    FROM goalie_stats WHERE goalieFullName IS NOT NULL
),
base AS (
    SELECT
        pgs.player_id,
        COALESCE(pgs.player_first_name, nl.first_name) AS player_first_name,
        COALESCE(pgs.player_last_name,  nl.last_name)  AS player_last_name,
        pgs.game_id, pgs.game_date,
        -- Derive season from game_id (format SSSSTTNNNN): 2009020611 → 20092010
        (pgs.game_id / 1000000)::BIGINT * 10000 + ((pgs.game_id / 1000000)::BIGINT + 1) AS season,
        pgs.team_abbr, pgs.is_home,
        COALESCE(pgs.saves, 0)         AS saves,
        COALESCE(pgs.shots_against, 0) AS shots_against,
        COALESCE(pgs.save_pct, 0)      AS save_pct,
        COALESCE(pgs.goals_against, 0) AS goals_against,
        COALESCE(pgs.toi_seconds, 0)   AS toi_seconds
    FROM player_game_stats pgs
    LEFT JOIN name_lookup nl ON nl.player_id = pgs.player_id
    WHERE pgs.position = 'G' AND COALESCE(pgs.toi_seconds, 0) > 600
),
rolling AS (
    SELECT *,
        AVG(save_pct)      OVER w5  AS sv_pct_avg_5g,
        AVG(save_pct)      OVER w10 AS sv_pct_avg_10g,
        AVG(save_pct)      OVER w20 AS sv_pct_avg_20g,
        AVG(goals_against) OVER w5  AS ga_avg_5g,
        AVG(goals_against) OVER w10 AS ga_avg_10g,
        SUM(saves)         OVER wseason AS saves_season,
        SUM(shots_against) OVER wseason AS shots_against_season,
        COUNT(*)           OVER wseason AS gp_season,
        STDDEV(save_pct)   OVER w20 AS sv_pct_stddev_20g,
        ROW_NUMBER()       OVER (PARTITION BY player_id ORDER BY game_date DESC) AS game_recency_rank
    FROM base
    WINDOW
        w5      AS (PARTITION BY player_id ORDER BY game_date ROWS BETWEEN 4  PRECEDING AND CURRENT ROW),
        w10     AS (PARTITION BY player_id ORDER BY game_date ROWS BETWEEN 9  PRECEDING AND CURRENT ROW),
        w20     AS (PARTITION BY player_id ORDER BY game_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        wseason AS (PARTITION BY player_id, season ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT *,
    ROUND(CASE WHEN sv_pct_stddev_20g > 0
         THEN (sv_pct_avg_5g - sv_pct_avg_20g) / sv_pct_stddev_20g
         ELSE 0 END, 3) AS sv_pct_zscore_5v20
FROM rolling
"""

_TEAM_ROLLING_SQL = """
WITH base AS (
    -- Unpivot games (home/away columns) into one row per team per game.
    -- team_game_stats only contains FUT placeholder rows so we derive from games instead.
    SELECT
        game_id, game_date, season, game_type,
        home_team_abbr            AS team_abbr,
        away_team_abbr            AS opponent_abbr,
        TRUE                      AS is_home,
        COALESCE(TRY_CAST(home_points          AS INTEGER), 0) AS team_points,
        COALESCE(TRY_CAST(home_score           AS INTEGER), 0) AS goals_for,
        COALESCE(TRY_CAST(away_score           AS INTEGER), 0) AS goals_against,
        COALESCE(TRY_CAST(home_sog             AS INTEGER), 0) AS sog,
        COALESCE(TRY_CAST(home_pp_goals        AS INTEGER), 0) AS pp_goals,
        COALESCE(TRY_CAST(home_pp_opportunities AS INTEGER), 0) AS pp_opportunities,
        COALESCE(TRY_CAST(home_hits            AS INTEGER), 0) AS hits,
        COALESCE(TRY_CAST(home_blocked         AS INTEGER), 0) AS blocked_shots
    FROM games
    WHERE status NOT IN ('FUT', 'PRE')
      AND TRY_CAST(game_type AS INTEGER) = 2

    UNION ALL

    SELECT
        game_id, game_date, season, game_type,
        away_team_abbr            AS team_abbr,
        home_team_abbr            AS opponent_abbr,
        FALSE                     AS is_home,
        COALESCE(TRY_CAST(away_points          AS INTEGER), 0) AS team_points,
        COALESCE(TRY_CAST(away_score           AS INTEGER), 0) AS goals_for,
        COALESCE(TRY_CAST(home_score           AS INTEGER), 0) AS goals_against,
        COALESCE(TRY_CAST(away_sog             AS INTEGER), 0) AS sog,
        COALESCE(TRY_CAST(away_pp_goals        AS INTEGER), 0) AS pp_goals,
        COALESCE(TRY_CAST(away_pp_opportunities AS INTEGER), 0) AS pp_opportunities,
        COALESCE(TRY_CAST(away_hits            AS INTEGER), 0) AS hits,
        COALESCE(TRY_CAST(away_blocked         AS INTEGER), 0) AS blocked_shots
    FROM games
    WHERE status NOT IN ('FUT', 'PRE')
      AND TRY_CAST(game_type AS INTEGER) = 2
),
rolling AS (
    SELECT *,
        AVG(team_points)   OVER w5  AS pts_avg_5g,
        AVG(team_points)   OVER w10 AS pts_avg_10g,
        AVG(team_points)   OVER w20 AS pts_avg_20g,
        AVG(goals_for)     OVER w10 AS gf_avg_10g,
        AVG(goals_against) OVER w10 AS ga_avg_10g,
        AVG(sog)           OVER w10 AS sog_avg_10g,
        SUM(CASE WHEN team_points = 2 THEN 1 ELSE 0 END) OVER w5 AS wins_last_5,
        SUM(CASE WHEN team_points = 0 THEN 1 ELSE 0 END) OVER w5 AS losses_last_5,
        SUM(team_points)   OVER wseason AS pts_cumulative,
        SUM(goals_for)     OVER wseason AS gf_cumulative,
        SUM(goals_against) OVER wseason AS ga_cumulative,
        COUNT(*)           OVER wseason AS gp_season,
        STDDEV(team_points) OVER w20   AS pts_stddev_20g,
        CASE WHEN sog > 0
             THEN goals_for / sog
             ELSE NULL END AS shooting_pct_game,
        ROW_NUMBER() OVER (PARTITION BY team_abbr ORDER BY game_date DESC) AS game_recency_rank
    FROM base
    WINDOW
        w5      AS (PARTITION BY team_abbr ORDER BY game_date ROWS BETWEEN 4  PRECEDING AND CURRENT ROW),
        w10     AS (PARTITION BY team_abbr ORDER BY game_date ROWS BETWEEN 9  PRECEDING AND CURRENT ROW),
        w20     AS (PARTITION BY team_abbr ORDER BY game_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        wseason AS (PARTITION BY team_abbr, season ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT *,
    ROUND(CASE WHEN pts_stddev_20g > 0
         THEN (pts_avg_5g - pts_avg_20g) / pts_stddev_20g
         ELSE 0 END, 3) AS pts_zscore_5v20
FROM rolling
"""

_TEAM_CORSI_SQL = """
WITH shot_attempts AS (
    SELECT game_id, game_date, team_abbr,
        COUNT(*) AS attempts
    FROM game_events
    WHERE event_type IN ('GOAL', 'SHOT', 'MISSED_SHOT', 'BLOCKED_SHOT')
    GROUP BY game_id, game_date, team_abbr
),
game_sides AS (
    SELECT game_id, game_date, game_type, home_team_abbr AS team_abbr, away_team_abbr AS opponent_abbr
    FROM games WHERE status NOT IN ('FUT', 'PRE')
    UNION ALL
    SELECT game_id, game_date, game_type, away_team_abbr, home_team_abbr
    FROM games WHERE status NOT IN ('FUT', 'PRE')
)
SELECT
    gs.game_id,
    gs.game_date,
    gs.game_type,
    gs.team_abbr,
    gs.opponent_abbr,
    COALESCE(sa_for.attempts, 0)     AS corsi_for,
    COALESCE(sa_against.attempts, 0) AS corsi_against,
    ROUND(CASE
        WHEN COALESCE(sa_for.attempts, 0) + COALESCE(sa_against.attempts, 0) > 0
        THEN CAST(COALESCE(sa_for.attempts, 0) AS DOUBLE)
             / (COALESCE(sa_for.attempts, 0) + COALESCE(sa_against.attempts, 0))
        ELSE NULL END, 4) AS corsi_pct
FROM game_sides gs
LEFT JOIN shot_attempts sa_for
    ON sa_for.game_id = gs.game_id AND sa_for.team_abbr = gs.team_abbr
LEFT JOIN shot_attempts sa_against
    ON sa_against.game_id = gs.game_id AND sa_against.team_abbr = gs.opponent_abbr
"""

_TABLES = {
    "player_rolling_stats": _PLAYER_ROLLING_SQL,
    "goalie_rolling_stats": _GOALIE_ROLLING_SQL,
    "team_rolling_stats":   _TEAM_ROLLING_SQL,
    "team_corsi":           _TEAM_CORSI_SQL,
}


# ── Public function ────────────────────────────────────────────────────────────

def refresh_feature_store() -> None:
    """Recompute all four feature store tables in MotherDuck."""
    token = os.getenv("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        print("[feature_store] MOTHERDUCK_TOKEN not set – skipping refresh")
        return
    db = os.getenv("MOTHERDUCK_DATABASE_NAME", "nhl").strip() or "nhl"
    conn = duckdb.connect(f"md:{db}?motherduck_token={token}")
    try:
        for name, sql in _TABLES.items():
            try:
                conn.execute(f"CREATE OR REPLACE TABLE {name} AS ({sql})")
                count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                print(f"[feature_store] {name}: {count:,} rows")
            except Exception as e:
                print(f"[feature_store] {name} failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    refresh_feature_store()
    print("Done.")
