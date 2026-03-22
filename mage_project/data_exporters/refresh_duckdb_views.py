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
            rows = conn.execute(
                f"SELECT 1 FROM \"{catalog}\".information_schema.tables "
                f"WHERE table_schema = 'main' AND table_name = '{name}' LIMIT 1"
            ).fetchall()
            return len(rows) > 0
        except Exception:
            return False

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
    try:
        conn.execute("""
            CREATE OR REPLACE VIEW player_game_stats AS
            SELECT gp.*,
                   p.firstName AS player_first_name,
                   p.lastName AS player_last_name
            FROM game_players gp
            LEFT JOIN players p ON p.id = gp.player_id
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

    # Synka till MotherDuck (måste ske efter conn.close så filen inte är låst)
    conn.close()
    _sync_to_motherduck(db_path)

    # Vid local: behåll filen (för Streamlit/validate). Vid s3: ladda upp och ta bort lokal kopia.
    sink = os.getenv("DATA_LAKE_SINK", "local").strip().lower()
    if sink != "s3":
        print(f"[refresh_duckdb_views] DATA_LAKE_SINK=local – Gold sparad lokalt: {db_path}")
        return

    if not os.path.isfile(db_path):
        return
    s3_prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
    s3_bucket = os.getenv("S3_DATA_LAKE_BUCKET") or get_s3_bucket()
    if not s3_bucket:
        return
    client = get_s3_client()
    key = f"{s3_prefix}/gold/nhl.duckdb"
    upload_file(client, s3_bucket, key, db_path)
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("[refresh_duckdb_views] Gold uppladdad till S3, lokal fil borttagen.")
