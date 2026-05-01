import os
import sys

import duckdb
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter

from utils.s3_utils import get_s3_bucket, get_s3_client, get_duckdb_s3_secret_sql, upload_file

DATASETS = [
    "teams",
    "players",
    "countries",
    "roster",
    "schedule",
    "game_ids",
    "glossary",
    "draft",
    "playoff_brackets",
    "standings",
    "skater_stats",
    "goalie_stats",
    "team_stats",
    "edge_skaters",
    "edge_goalies",
    "edge_teams",
    "games",
    "game_players",
    "game_events",   # playByPlay – om filer har full data
    "game_stories", # gameStory – om filer har full data
]


def _sync_to_motherduck(db_path: str) -> None:
    """Synkar lokal DuckDB till MotherDuck. Anropa efter conn.close() så filen inte är låst."""
    token = os.getenv("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        return
    md_db = os.getenv("MOTHERDUCK_DATABASE_NAME", "nhl").strip() or "nhl"
    abs_path = os.path.abspath(db_path)
    if not os.path.isfile(abs_path):
        return
    sync_conn = duckdb.connect(":memory:")
    try:
        sync_conn.execute("INSTALL motherduck")
        sync_conn.execute("LOAD motherduck")
        sync_conn.execute(f"ATTACH '{abs_path}' AS local (READ_ONLY)")
        sync_conn.execute(f"ATTACH 'md:{md_db}'")
    except Exception as e:
        err = str(e).lower()
        if "does not exist" in err or "not found" in err or "unknown database" in err:
            try:
                sync_conn.execute("ATTACH 'md:'")
                sync_conn.execute(f"CREATE DATABASE IF NOT EXISTS {md_db}")
                sync_conn.execute(f"ATTACH 'md:{md_db}'")
            except Exception as e2:
                print(f"[sync_to_motherduck] Kunde inte skapa databas i MotherDuck. Skapa '{md_db}' i MotherDuck UI först: {e2}")
                sync_conn.close()
                return
        else:
            print(f"[sync_to_motherduck] Kunde inte ansluta till MotherDuck: {e}")
            sync_conn.close()
            return
    try:
        rows = sync_conn.execute(
            "SELECT table_name FROM local.information_schema.tables WHERE table_schema = 'main' AND table_type IN ('BASE TABLE', 'VIEW') ORDER BY table_name"
        ).fetchall()
        tables = [r[0] for r in rows]
    except Exception:
        tables = DATASETS + ["player_game_stats", "team_game_stats"]
    # Game tables are upserted (INSERT new rows only) so that historical data in
    # MotherDuck is preserved when the pipeline runs incrementally (e.g. GitHub Actions
    # where only the latest Silver is local). Dimension/stats tables are always replaced
    # since they are small and always rebuilt from all S3 source files.
    UPSERT_KEYS: dict = {
        "games":                   ("game_id",),
        "game_players":            ("game_id", "player_id"),
        "game_events":             ("game_id", "event_id"),
        "game_stories":            ("game_id",),
        "player_game_stats":       ("game_id", "player_id"),
        "team_game_stats":         ("game_id", "team_abbr"),
        "team_game_stats_extended": ("game_id", "team_abbr"),
    }

    def _md_table_exists(conn, catalog: str, name: str) -> bool:
        try:
            conn.execute(f'SELECT 1 FROM "{catalog}".main."{name}" LIMIT 0')
            return True
        except Exception as e:
            err = str(e).lower()
            if any(s in err for s in ("does not exist", "not found", "no table", "catalog error")):
                return False
            # Annat fel (nätverk, timeout etc.) – anta att tabellen FINNS
            print(f"[_md_table_exists] Kan inte avgöra om {name} finns, antar att den gör det: {e}")
            return True

    catalog = md_db
    ok, fail = 0, 0
    try:
        for name in tables:
            try:
                if name in UPSERT_KEYS:
                    keys = UPSERT_KEYS[name]
                    if not _md_table_exists(sync_conn, catalog, name):
                        # First time: create table from local data
                        sync_conn.execute(
                            f'CREATE OR REPLACE TABLE "{catalog}".main."{name}" '
                            f'AS SELECT * FROM local.main."{name}"'
                        )
                    else:
                        # Subsequent runs: insert only rows not already in MotherDuck
                        join_cond = " AND ".join(
                            f'md."{k}" = src."{k}"' for k in keys
                        )
                        sync_conn.execute(f"""
                            INSERT INTO "{catalog}".main."{name}"
                            SELECT src.* FROM local.main."{name}" src
                            WHERE NOT EXISTS (
                                SELECT 1 FROM "{catalog}".main."{name}" md
                                WHERE {join_cond}
                            )
                        """)
                else:
                    sync_conn.execute(
                        f'CREATE OR REPLACE TABLE "{catalog}".main."{name}" '
                        f'AS SELECT * FROM local.main."{name}"'
                    )
                ok += 1
            except Exception as e:
                print(f"[sync_to_motherduck] {name}: {e}")
                fail += 1
    finally:
        sync_conn.close()
    print(f"[sync_to_motherduck] Klar: {ok} tabeller uppdaterade i MotherDuck ({fail} misslyckade)")


@data_exporter
def refresh_duckdb_views(*args, **kwargs):
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    silver = os.path.join(data_lake, "silver")
    gold = os.path.join(data_lake, "gold")
    os.makedirs(gold, exist_ok=True)

    db_path = os.path.join(gold, "nhl.duckdb")
    conn = duckdb.connect(db_path)

    # Relativ path från projektrot (tur-mage-ai / /home/src) så att vyerna fungerar när DB öppnas på Mac eller i container.
    workspace_root = os.path.dirname(os.path.dirname(data_lake))
    for dataset in DATASETS:
        dataset_dir = os.path.join(silver, dataset)
        dataset_path = os.path.join(silver, dataset, "**", "*.parquet")
        exists = os.path.exists(dataset_dir)
        if not exists:
            continue
        rel_parquet = os.path.relpath(dataset_path, workspace_root).replace("\\", "/")
        view_sql = f"CREATE OR REPLACE VIEW {dataset} AS SELECT * FROM parquet_scan('{rel_parquet}', union_by_name=True);"
        conn.execute(view_sql)

    # Player stats per game (one row per player per game) with player names. English view name.
    # Falls back to skater_stats/goalie_stats for historical players missing from the current
    # roster snapshot in the players table.
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW player_game_stats AS
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
            )
            SELECT gp.*,
                   COALESCE(p.firstName, nl.first_name) AS player_first_name,
                   COALESCE(p.lastName,  nl.last_name)  AS player_last_name
            FROM game_players gp
            LEFT JOIN players p ON p.id = gp.player_id
            LEFT JOIN name_lookup nl ON nl.player_id = gp.player_id
        """)
    except Exception:
        pass  # game_players or players missing on first run

    # Team stats per game (one row per team per game; unpivot of games: home + away).
    # Försök full schema först; vid äldre Silver (saknar game_state, ot_periods, home_team_id) använd minimal vy.
    _team_game_stats_sql_full = """
        CREATE OR REPLACE VIEW team_game_stats AS
        SELECT g.game_id, g.game_date, g.season, g.status,
          g.game_state, g.ot_periods, g.last_period_type, g.period_number, g.period_type,
          TRUE AS is_home, g.home_team_id AS team_id, g.home_team_abbr AS team_abbr,
          g.away_team_abbr AS opponent_abbr, g.home_score AS goals_for, g.away_score AS goals_against,
          g.home_points AS team_points, g.home_sog AS sog, g.home_pp_goals AS pp_goals,
          g.home_pp_opportunities AS pp_opportunities, g.home_hits AS hits,
          g.home_blocked AS blocked_shots, g.home_pim AS pim, g.home_giveaways AS giveaways,
          g.home_takeaways AS takeaways, g.home_faceoff_pct AS faceoff_win_pct,
          g.venue, g.venue_location, g.start_time_utc, g.reg_periods, g.game_type, g.limited_scoring
        FROM games g
        UNION ALL
        SELECT g.game_id, g.game_date, g.season, g.status,
          g.game_state, g.ot_periods, g.last_period_type, g.period_number, g.period_type,
          FALSE AS is_home, g.away_team_id AS team_id, g.away_team_abbr AS team_abbr,
          g.home_team_abbr AS opponent_abbr, g.away_score AS goals_for, g.home_score AS goals_against,
          g.away_points AS team_points, g.away_sog AS sog, g.away_pp_goals AS pp_goals,
          g.away_pp_opportunities AS pp_opportunities, g.away_hits AS hits,
          g.away_blocked AS blocked_shots, g.away_pim AS pim, g.away_giveaways AS giveaways,
          g.away_takeaways AS takeaways, g.away_faceoff_pct AS faceoff_win_pct,
          g.venue, g.venue_location, g.start_time_utc, g.reg_periods, g.game_type, g.limited_scoring
        FROM games g
    """
    _team_game_stats_sql_minimal = """
        CREATE OR REPLACE VIEW team_game_stats AS
        SELECT g.game_id, g.game_date, g.season, g.status,
          TRUE AS is_home, g.home_team_abbr AS team_abbr,
          g.away_team_abbr AS opponent_abbr, g.home_score AS goals_for, g.away_score AS goals_against,
          g.home_points AS team_points, g.home_sog AS sog, g.home_pp_goals AS pp_goals,
          g.home_pp_opportunities AS pp_opportunities, g.home_hits AS hits,
          g.home_blocked AS blocked_shots, g.home_pim AS pim, g.home_giveaways AS giveaways,
          g.home_takeaways AS takeaways, g.home_faceoff_pct AS faceoff_win_pct,
          g.venue, g.venue_location, g.start_time_utc, g.reg_periods, g.game_type, g.limited_scoring
        FROM games g
        UNION ALL
        SELECT g.game_id, g.game_date, g.season, g.status,
          FALSE AS is_home, g.away_team_abbr AS team_abbr,
          g.home_team_abbr AS opponent_abbr, g.away_score AS goals_for, g.home_score AS goals_against,
          g.away_points AS team_points, g.away_sog AS sog, g.away_pp_goals AS pp_goals,
          g.away_pp_opportunities AS pp_opportunities, g.away_hits AS hits,
          g.away_blocked AS blocked_shots, g.away_pim AS pim, g.away_giveaways AS giveaways,
          g.away_takeaways AS takeaways, g.away_faceoff_pct AS faceoff_win_pct,
          g.venue, g.venue_location, g.start_time_utc, g.reg_periods, g.game_type, g.limited_scoring
        FROM games g
    """
    try:
        conn.execute(_team_game_stats_sql_full)
    except Exception:
        try:
            conn.execute(_team_game_stats_sql_minimal)
        except Exception:
            pass  # games missing or schema too old

    # Team stats per game with conference and division (join team_game_stats + teams).
    # teams.abbr is the column from source (all_teams.json uses "abbr", not "abbrev").
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW team_game_stats_extended AS
            SELECT tgs.*,
                   t.conference_abbr,
                   t.conference_name,
                   t.division_abbr,
                   t.division_name
            FROM team_game_stats tgs
            LEFT JOIN teams t ON t.abbr = tgs.team_abbr
        """)
    except Exception:
        pass  # team_game_stats or teams missing

    # -------------------------------------------------------------------------
    # Feature store: rolling statistics + advanced metrics
    # Computed from base views above; materialized as tables in MotherDuck.
    # -------------------------------------------------------------------------

    # player_rolling_stats – rolling averages + z-scores for skaters (non-goalies)
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW player_rolling_stats AS
            WITH base AS (
                SELECT
                    player_id, player_first_name, player_last_name,
                    game_id, game_date, season, team_abbr, position, is_home,
                    COALESCE(goals, 0)       AS goals,
                    COALESCE(assists, 0)     AS assists,
                    COALESCE(points, 0)      AS points,
                    COALESCE(shots, 0)       AS shots,
                    COALESCE(toi_seconds, 0) AS toi_seconds,
                    COALESCE(hits, 0)        AS hits,
                    COALESCE(plus_minus, 0)  AS plus_minus
                FROM player_game_stats
                WHERE position NOT IN ('G') AND COALESCE(toi_seconds, 0) > 0
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
        """)
        print("[refresh_duckdb_views] player_rolling_stats: OK")
    except Exception as e:
        print(f"[refresh_duckdb_views] player_rolling_stats: {e}")

    # goalie_rolling_stats – rolling save% + z-scores for goalies
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW goalie_rolling_stats AS
            WITH base AS (
                SELECT
                    player_id, player_first_name, player_last_name,
                    game_id, game_date, season, team_abbr, is_home,
                    COALESCE(saves, 0)         AS saves,
                    COALESCE(shots_against, 0) AS shots_against,
                    COALESCE(save_pct, 0)      AS save_pct,
                    COALESCE(goals_against, 0) AS goals_against,
                    COALESCE(toi_seconds, 0)   AS toi_seconds
                FROM player_game_stats
                WHERE position = 'G' AND COALESCE(toi_seconds, 0) > 600
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
        """)
        print("[refresh_duckdb_views] goalie_rolling_stats: OK")
    except Exception as e:
        print(f"[refresh_duckdb_views] goalie_rolling_stats: {e}")

    # team_rolling_stats – rolling averages + z-scores + PDO for teams (regular season)
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW team_rolling_stats AS
            WITH base AS (
                SELECT
                    team_abbr, game_id, game_date, season, is_home, opponent_abbr,
                    COALESCE(team_points, 0)      AS team_points,
                    COALESCE(goals_for, 0)        AS goals_for,
                    COALESCE(goals_against, 0)    AS goals_against,
                    COALESCE(sog, 0)              AS sog,
                    COALESCE(pp_goals, 0)         AS pp_goals,
                    COALESCE(pp_opportunities, 0) AS pp_opportunities,
                    COALESCE(hits, 0)             AS hits,
                    COALESCE(blocked_shots, 0)    AS blocked_shots
                FROM team_game_stats
                WHERE game_type = '2'
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
                         THEN CAST(goals_for AS DOUBLE) / sog
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
        """)
        print("[refresh_duckdb_views] team_rolling_stats: OK")
    except Exception as e:
        print(f"[refresh_duckdb_views] team_rolling_stats: {e}")

    # team_corsi – shot attempt share (Corsi%) per team per game from play-by-play
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW team_corsi AS
            WITH shot_attempts AS (
                SELECT game_id, game_date, team_abbr,
                    COUNT(*) AS attempts
                FROM game_events
                WHERE event_type IN ('GOAL', 'SHOT', 'MISSED_SHOT', 'BLOCKED_SHOT')
                GROUP BY game_id, game_date, team_abbr
            ),
            game_sides AS (
                SELECT game_id, game_date, game_type,
                    home_team_abbr AS team_abbr, away_team_abbr AS opponent_abbr
                FROM games
                UNION ALL
                SELECT game_id, game_date, game_type,
                    away_team_abbr AS team_abbr, home_team_abbr AS opponent_abbr
                FROM games
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
        """)
        print("[refresh_duckdb_views] team_corsi: OK")
    except Exception as e:
        print(f"[refresh_duckdb_views] team_corsi: {e}")

    # -------------------------------------------------------------------------
    # Timeline views: kumulativa stats per spelare/lag per datum inom säsongen.
    # Används för att följa prestation över tid – inte bara snapshot-statistik.
    # -------------------------------------------------------------------------

    # player_season_timeline – kumulativa + rolling stats per skater per match-datum.
    # JOIN med games för att få season (saknas i game_players-parquet).
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW player_season_timeline AS
            WITH base AS (
                SELECT
                    pg.player_id,
                    pg.player_first_name,
                    pg.player_last_name,
                    pg.game_id,
                    pg.game_date,
                    g.season,
                    pg.team_abbr,
                    pg.position,
                    pg.is_home,
                    COALESCE(pg.goals, 0)            AS goals,
                    COALESCE(pg.assists, 0)          AS assists,
                    COALESCE(pg.points, 0)           AS points,
                    COALESCE(pg.shots, 0)            AS shots,
                    COALESCE(pg.hits, 0)             AS hits,
                    COALESCE(pg.plus_minus, 0)       AS plus_minus,
                    COALESCE(pg.pim, 0)              AS pim,
                    COALESCE(pg.toi_seconds, 0)      AS toi_seconds,
                    COALESCE(pg.power_play_goals, 0) AS pp_goals,
                    COALESCE(pg.blocked_shots, 0)    AS blocked_shots
                FROM player_game_stats pg
                JOIN games g ON g.game_id = pg.game_id
                WHERE pg.position NOT IN ('G')
                  AND COALESCE(pg.toi_seconds, 0) > 0
            ),
            cumulative AS (
                SELECT *,
                    -- Kumulativa summor inom säsongen
                    SUM(goals)         OVER wseason AS goals_cum,
                    SUM(assists)       OVER wseason AS assists_cum,
                    SUM(points)        OVER wseason AS points_cum,
                    SUM(shots)         OVER wseason AS shots_cum,
                    SUM(hits)          OVER wseason AS hits_cum,
                    SUM(plus_minus)    OVER wseason AS plus_minus_cum,
                    SUM(pim)           OVER wseason AS pim_cum,
                    SUM(toi_seconds)   OVER wseason AS toi_seconds_cum,
                    SUM(pp_goals)      OVER wseason AS pp_goals_cum,
                    SUM(blocked_shots) OVER wseason AS blocked_shots_cum,
                    COUNT(*)           OVER wseason AS gp_cum,
                    -- Rolling 5-matchersnitt
                    ROUND(AVG(points) OVER w5,  3) AS pts_avg_5g,
                    ROUND(AVG(goals)  OVER w5,  3) AS goals_avg_5g,
                    ROUND(AVG(shots)  OVER w5,  3) AS shots_avg_5g,
                    -- Rolling 10-matchersnitt
                    ROUND(AVG(points) OVER w10, 3) AS pts_avg_10g,
                    ROUND(AVG(goals)  OVER w10, 3) AS goals_avg_10g,
                    ROUND(AVG(shots)  OVER w10, 3) AS shots_avg_10g
                FROM base
                WINDOW
                    wseason AS (PARTITION BY player_id, season
                                ORDER BY game_date
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
                    w5      AS (PARTITION BY player_id
                                ORDER BY game_date
                                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
                    w10     AS (PARTITION BY player_id
                                ORDER BY game_date
                                ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)
            )
            SELECT
                *,
                -- Points per game (kumulativt)
                ROUND(CAST(points_cum AS DOUBLE) / NULLIF(gp_cum, 0), 3) AS points_per_game_cum,
                -- Poängranking bland alla skaters på detta datum i denna säsong
                RANK() OVER (
                    PARTITION BY season, game_date
                    ORDER BY points_cum DESC
                ) AS season_points_rank
            FROM cumulative
        """)
        print("[refresh_duckdb_views] player_season_timeline: OK")
    except Exception as e:
        print(f"[refresh_duckdb_views] player_season_timeline: {e}")

    # goalie_season_timeline – kumulativa + rolling stats per målvakt per datum.
    # JOIN med games för att få season (saknas i game_players-parquet).
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW goalie_season_timeline AS
            WITH base AS (
                SELECT
                    pg.player_id,
                    pg.player_first_name,
                    pg.player_last_name,
                    pg.game_id,
                    pg.game_date,
                    g.season,
                    pg.team_abbr,
                    pg.is_home,
                    COALESCE(pg.saves, 0)         AS saves,
                    COALESCE(pg.shots_against, 0) AS shots_against,
                    COALESCE(pg.goals_against, 0) AS goals_against,
                    COALESCE(pg.save_pct, 0)      AS save_pct,
                    COALESCE(pg.toi_seconds, 0)   AS toi_seconds
                FROM player_game_stats pg
                JOIN games g ON g.game_id = pg.game_id
                WHERE pg.position = 'G'
                  AND COALESCE(pg.toi_seconds, 0) > 600
            ),
            cumulative AS (
                SELECT *,
                    SUM(saves)         OVER wseason AS saves_cum,
                    SUM(shots_against) OVER wseason AS shots_against_cum,
                    SUM(goals_against) OVER wseason AS goals_against_cum,
                    SUM(toi_seconds)   OVER wseason AS toi_seconds_cum,
                    COUNT(*)           OVER wseason AS gp_cum,
                    -- Kumulativ SV% (räknat från raw-siffror, inte snitt av snitt)
                    ROUND(
                        CAST(SUM(saves) OVER wseason AS DOUBLE)
                        / NULLIF(SUM(shots_against) OVER wseason, 0),
                    4) AS save_pct_cum,
                    ROUND(AVG(save_pct) OVER w5,  4) AS sv_pct_avg_5g,
                    ROUND(AVG(save_pct) OVER w10, 4) AS sv_pct_avg_10g
                FROM base
                WINDOW
                    wseason AS (PARTITION BY player_id, season
                                ORDER BY game_date
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
                    w5      AS (PARTITION BY player_id
                                ORDER BY game_date
                                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
                    w10     AS (PARTITION BY player_id
                                ORDER BY game_date
                                ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)
            )
            SELECT
                *,
                -- GAA kumulativt (mål insläppta per 60 min)
                ROUND(
                    CAST(goals_against_cum AS DOUBLE) * 3600.0
                    / NULLIF(toi_seconds_cum, 0),
                4) AS gaa_cum,
                RANK() OVER (
                    PARTITION BY season, game_date
                    ORDER BY save_pct_cum DESC
                ) AS season_sv_pct_rank
            FROM cumulative
        """)
        print("[refresh_duckdb_views] goalie_season_timeline: OK")
    except Exception as e:
        print(f"[refresh_duckdb_views] goalie_season_timeline: {e}")

    # team_season_timeline – kumulativa tabellpoäng + statistik per lag per datum.
    # team_game_stats-kolumner är VARCHAR i MotherDuck → TRY_CAST defensivt.
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW team_season_timeline AS
            WITH base AS (
                SELECT
                    team_abbr,
                    game_id,
                    game_date,
                    CAST(season AS VARCHAR)                            AS season,
                    is_home,
                    opponent_abbr,
                    COALESCE(TRY_CAST(team_points   AS INTEGER), 0)   AS team_points,
                    COALESCE(TRY_CAST(goals_for     AS INTEGER), 0)   AS goals_for,
                    COALESCE(TRY_CAST(goals_against AS INTEGER), 0)   AS goals_against,
                    COALESCE(TRY_CAST(sog           AS INTEGER), 0)   AS shots,
                    COALESCE(TRY_CAST(pp_goals      AS INTEGER), 0)   AS pp_goals,
                    COALESCE(TRY_CAST(pp_opportunities AS INTEGER), 0) AS pp_opps,
                    CASE WHEN COALESCE(TRY_CAST(team_points AS INTEGER), 0) = 2 THEN 1 ELSE 0 END AS win,
                    CASE WHEN COALESCE(TRY_CAST(team_points AS INTEGER), 0) = 1 THEN 1 ELSE 0 END AS otl,
                    CASE WHEN COALESCE(TRY_CAST(team_points AS INTEGER), 0) = 0 THEN 1 ELSE 0 END AS loss
                FROM team_game_stats
                WHERE TRY_CAST(game_type AS INTEGER) = 2
            ),
            cumulative AS (
                SELECT *,
                    SUM(team_points)   OVER wseason AS points_cum,
                    SUM(goals_for)     OVER wseason AS gf_cum,
                    SUM(goals_against) OVER wseason AS ga_cum,
                    SUM(shots)         OVER wseason AS shots_cum,
                    SUM(pp_goals)      OVER wseason AS pp_goals_cum,
                    SUM(pp_opps)       OVER wseason AS pp_opps_cum,
                    SUM(win)           OVER wseason AS wins_cum,
                    SUM(otl)           OVER wseason AS otl_cum,
                    SUM(loss)          OVER wseason AS losses_cum,
                    COUNT(*)           OVER wseason AS gp_cum,
                    ROUND(AVG(team_points)   OVER w5,  3) AS pts_avg_5g,
                    ROUND(AVG(goals_for)     OVER w5,  3) AS gf_avg_5g,
                    ROUND(AVG(goals_against) OVER w5,  3) AS ga_avg_5g,
                    ROUND(AVG(team_points)   OVER w10, 3) AS pts_avg_10g,
                    ROUND(AVG(goals_for)     OVER w10, 3) AS gf_avg_10g,
                    ROUND(AVG(goals_against) OVER w10, 3) AS ga_avg_10g,
                    SUM(win) OVER w5                      AS wins_last_5
                FROM base
                WINDOW
                    wseason AS (PARTITION BY team_abbr, season
                                ORDER BY game_date
                                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
                    w5      AS (PARTITION BY team_abbr
                                ORDER BY game_date
                                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
                    w10     AS (PARTITION BY team_abbr
                                ORDER BY game_date
                                ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)
            )
            SELECT
                *,
                gf_cum - ga_cum AS goal_diff_cum,
                ROUND(
                    CAST(pp_goals_cum AS DOUBLE) / NULLIF(pp_opps_cum, 0),
                4) AS pp_pct_cum,
                RANK() OVER (
                    PARTITION BY season, game_date
                    ORDER BY points_cum DESC, (gf_cum - ga_cum) DESC
                ) AS season_rank
            FROM cumulative
        """)
        print("[refresh_duckdb_views] team_season_timeline: OK")
    except Exception as e:
        print(f"[refresh_duckdb_views] team_season_timeline: {e}")

    # Synka till MotherDuck (måste ske efter conn.close så filen inte är låst)
    conn.close()
    _sync_to_motherduck(db_path)

    # Vid local: behåll filen (för Streamlit/validate). Vid s3: ladda upp och ta bort lokal kopia.
    sink = os.getenv("DATA_LAKE_SINK", "local").strip().lower()
    if sink == "s3":
        if not os.path.isfile(db_path):
            return
        s3_prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
        s3_bucket = os.getenv("S3_DATA_LAKE_BUCKET") or get_s3_bucket()
        if s3_bucket:
            client = get_s3_client()
            key = f"{s3_prefix}/gold/nhl.duckdb"
            upload_file(client, s3_bucket, key, db_path)
            print("[refresh_duckdb_views] Gold uppladdad till Hetzner S3.")
    else:
        print(f"[refresh_duckdb_views] DATA_LAKE_SINK=local – Gold sparad lokalt: {db_path}")

    # Ladda alltid upp Gold till Minio nhl-gold (för Paperclip-access), om konfigurerat.
    minio_gold_bucket = os.getenv("MINIO_GOLD_BUCKET", "").strip()
    minio_endpoint = os.getenv("MINIO_ENDPOINT", "").strip()
    minio_access_key = os.getenv("MINIO_ACCESS_KEY", "").strip()
    minio_secret_key = os.getenv("MINIO_SECRET_KEY", "").strip()
    if minio_gold_bucket and minio_endpoint and minio_access_key and os.path.isfile(db_path):
        try:
            import boto3
            endpoint_url = minio_endpoint if minio_endpoint.startswith("http") else f"https://{minio_endpoint}"
            minio_client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=minio_access_key,
                aws_secret_access_key=minio_secret_key,
                region_name="us-east-1",
            )
            upload_file(minio_client, minio_gold_bucket, "nhl.duckdb", db_path)
            print(f"[refresh_duckdb_views] Gold uppladdad till Minio: {minio_gold_bucket}/nhl.duckdb")
        except Exception as e:
            print(f"[refresh_duckdb_views] Minio Gold upload misslyckades (ignorerar): {e}")
