"""
Bootstrap feature store tables directly in MotherDuck.
Run this once (or whenever refresh_duckdb_views hasn't been run with the new views yet).
Reads from existing base tables in MotherDuck and creates materialized feature store tables.
"""
import os, sys, time
import duckdb
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

token = os.getenv("MOTHERDUCK_TOKEN", "").strip()
db    = os.getenv("MOTHERDUCK_DATABASE_NAME", "nhl").strip() or "nhl"

if not token:
    print("ERROR: MOTHERDUCK_TOKEN not set"); sys.exit(1)

print(f"Connecting to MotherDuck ({db})...")
conn = duckdb.connect(":memory:")
conn.execute("INSTALL motherduck; LOAD motherduck;")
conn.execute(f"ATTACH 'md:{db}' AS nhl;")
print("Connected.")

TABLES = {
    "player_rolling_stats": """
        WITH base AS (
            SELECT
                pgs.player_id, pgs.player_first_name, pgs.player_last_name,
                pgs.game_id, pgs.game_date, g.season, pgs.team_abbr, pgs.position, pgs.is_home,
                COALESCE(pgs.goals, 0)       AS goals,
                COALESCE(pgs.assists, 0)     AS assists,
                COALESCE(pgs.points, 0)      AS points,
                COALESCE(pgs.shots, 0)       AS shots,
                COALESCE(pgs.toi_seconds, 0) AS toi_seconds,
                COALESCE(pgs.hits, 0)        AS hits,
                COALESCE(pgs.plus_minus, 0)  AS plus_minus
            FROM nhl.main.player_game_stats pgs
            JOIN nhl.main.games g ON g.game_id = pgs.game_id
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
                 THEN (pts_avg_5g - pts_avg_20g) / pts_stddev_20g ELSE 0 END, 3) AS pts_zscore_5v20,
            ROUND(CASE WHEN goals_stddev_20g > 0
                 THEN (goals_avg_5g - goals_avg_20g) / goals_stddev_20g ELSE 0 END, 3) AS goals_zscore_5v20
        FROM rolling
    """,
    "goalie_rolling_stats": """
        WITH base AS (
            SELECT
                pgs.player_id, pgs.player_first_name, pgs.player_last_name,
                pgs.game_id, pgs.game_date, g.season, pgs.team_abbr, pgs.is_home,
                COALESCE(pgs.saves, 0)         AS saves,
                COALESCE(pgs.shots_against, 0) AS shots_against,
                COALESCE(pgs.save_pct, 0)      AS save_pct,
                COALESCE(pgs.goals_against, 0) AS goals_against,
                COALESCE(pgs.toi_seconds, 0)   AS toi_seconds
            FROM nhl.main.player_game_stats pgs
            JOIN nhl.main.games g ON g.game_id = pgs.game_id
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
                 THEN (sv_pct_avg_5g - sv_pct_avg_20g) / sv_pct_stddev_20g ELSE 0 END, 3) AS sv_pct_zscore_5v20
        FROM rolling
    """,
    "team_rolling_stats": """
        WITH base AS (
            SELECT
                team_abbr, game_id, game_date, season, is_home, opponent_abbr,
                COALESCE(TRY_CAST(team_points AS DOUBLE), 0)      AS team_points,
                COALESCE(TRY_CAST(goals_for AS DOUBLE), 0)        AS goals_for,
                COALESCE(TRY_CAST(goals_against AS DOUBLE), 0)    AS goals_against,
                COALESCE(TRY_CAST(sog AS DOUBLE), 0)              AS sog,
                COALESCE(TRY_CAST(pp_goals AS DOUBLE), 0)         AS pp_goals,
                COALESCE(TRY_CAST(pp_opportunities AS DOUBLE), 0) AS pp_opportunities,
                COALESCE(TRY_CAST(hits AS DOUBLE), 0)             AS hits,
                COALESCE(TRY_CAST(blocked_shots AS DOUBLE), 0)    AS blocked_shots
            FROM nhl.main.team_game_stats
            WHERE game_type = 2
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
                CASE WHEN sog > 0 THEN CAST(goals_for AS DOUBLE) / sog ELSE NULL END AS shooting_pct_game,
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
                 THEN (pts_avg_5g - pts_avg_20g) / pts_stddev_20g ELSE 0 END, 3) AS pts_zscore_5v20
        FROM rolling
    """,
    "team_corsi": """
        WITH shot_attempts AS (
            SELECT game_id, game_date, team_abbr, COUNT(*) AS attempts
            FROM nhl.main.game_events
            WHERE event_type IN ('GOAL', 'SHOT', 'MISSED_SHOT', 'BLOCKED_SHOT')
            GROUP BY game_id, game_date, team_abbr
        ),
        game_sides AS (
            SELECT game_id, game_date, game_type,
                home_team_abbr AS team_abbr, away_team_abbr AS opponent_abbr
            FROM nhl.main.games
            UNION ALL
            SELECT game_id, game_date, game_type,
                away_team_abbr AS team_abbr, home_team_abbr AS opponent_abbr
            FROM nhl.main.games
        )
        SELECT
            gs.game_id, gs.game_date, gs.game_type, gs.team_abbr, gs.opponent_abbr,
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
    """,
}

for name, sql in TABLES.items():
    print(f"\nBuilding {name}...", end=" ", flush=True)
    t0 = time.time()
    try:
        conn.execute(f'DROP TABLE IF EXISTS nhl.main."{name}"')
        conn.execute(f'CREATE TABLE nhl.main."{name}" AS {sql}')
        rows = conn.execute(f'SELECT COUNT(*) FROM nhl.main."{name}"').fetchone()[0]
        print(f"OK – {rows:,} rows ({time.time()-t0:.1f}s)")
    except Exception as e:
        print(f"FAILED: {e}")

conn.close()
print("\nFeature store bootstrap complete.")
