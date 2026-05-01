import os
import sys

import duckdb
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter


# Tabeller som skrivs via UPSERT (inkrementell – bevara historik i MotherDuck).
# Alla andra tabeller skrivs med CREATE OR REPLACE (full replace).
UPSERT_KEYS = {
    # Matchdata från JSON
    "games":              ("game_id",),
    "game_events":        ("game_id", "period", "event_time", "event_type", "player_name"),
    "game_goalkeepers":   ("game_id", "team", "name"),
    "game_lineups":       ("game_id", "team", "position", "player_number"),
    "game_period_scores":     ("game_id", "period"),
    "game_referees_json":     ("game_id", "name"),
    "game_on_ice_json":       ("game_id", "period", "event_time", "event_type", "team_side", "player_number"),
    # PDF-extrakt
    "game_referees":        ("game_id", "name"),
    "game_period_stats":    ("game_id", "team", "period"),
    "game_roster":          ("game_id", "team", "number", "name"),
    "game_player_stats":    ("game_id", "team", "number", "name"),
    "game_goalie_stats":    ("game_id", "team", "number"),
    "game_on_ice":          ("game_id", "period", "event_time", "team_abbr", "player_number"),
    "game_goals":           ("game_id", "period", "event_time", "team_abbr", "scorer_number"),
    "game_penalties":       ("game_id", "period", "event_time", "team_abbr", "player_number"),
    "game_gk_changes":      ("game_id", "period", "event_time", "team_abbr", "direction", "player_number"),
    "game_starting_lineup": ("game_id", "team", "number"),
    "game_spectators":      ("game_id",),
}

SWE_DATASETS = [
    # JSON-pipeline
    "games", "game_events", "game_goalkeepers", "game_lineups",
    "game_period_scores", "game_referees_json", "game_on_ice_json",
    # PDF-pipeline
    "game_referees", "game_period_stats", "game_roster",
    "game_player_stats", "game_goalie_stats", "game_on_ice",
    "game_goals", "game_penalties", "game_gk_changes", "game_starting_lineup",
    "game_spectators",
]


def _build_local_duckdb(db_path: str, silver_swe: str):
    """Bygger lokal DuckDB från Silver-parquet. Skapar en vy per tabell."""
    conn = duckdb.connect(db_path)
    for dataset in SWE_DATASETS:
        dataset_dir = os.path.join(silver_swe, dataset)
        if not os.path.isdir(dataset_dir):
            print(f"[swe duckdb] Silver-mapp saknas, hoppar over: {dataset_dir}")
            continue
        parquet_glob = os.path.join(dataset_dir, "**", "*.parquet")
        try:
            conn.execute(
                f"CREATE OR REPLACE VIEW {dataset} AS "
                f"SELECT * FROM parquet_scan('{parquet_glob}', union_by_name=True)"
            )
            count = conn.execute(f"SELECT COUNT(*) FROM {dataset}").fetchone()[0]
            print(f"[swe duckdb] {dataset}: {count} rader")
        except Exception as exc:
            print(f"[swe duckdb] Kunde inte skapa vy {dataset}: {exc}")
    conn.close()


def _md_table_exists(conn, catalog: str, table: str) -> bool:
    try:
        conn.execute(f'SELECT 1 FROM "{catalog}".main."{table}" LIMIT 0')
        return True
    except Exception as e:
        err = str(e).lower()
        if any(s in err for s in ("does not exist", "not found", "no table", "catalog error")):
            return False
        # Annat fel (nätverk, timeout etc.) – anta att tabellen FINNS
        print(f"[swe motherduck] Kan inte avgöra om {table} finns, antar att den gör det: {e}")
        return True


def _sync_to_motherduck(db_path: str):
    """Synkar lokal swe.duckdb till MotherDuck (swe-databasen)."""
    token = os.getenv("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        print("[swe motherduck] MOTHERDUCK_TOKEN saknas – hoppar over sync.")
        return

    abs_path = os.path.abspath(db_path)
    if not os.path.isfile(abs_path):
        print(f"[swe motherduck] Lokal DuckDB saknas: {abs_path}")
        return

    md_db = os.getenv("MOTHERDUCK_SWE_DATABASE", "swe").strip() or "swe"
    conn = duckdb.connect(":memory:")

    try:
        conn.execute("INSTALL motherduck")
        conn.execute("LOAD motherduck")
        conn.execute(f"ATTACH '{abs_path}' AS local (READ_ONLY)")
        try:
            conn.execute(f"ATTACH 'md:{md_db}'")
        except Exception as e:
            err = str(e).lower()
            if any(s in err for s in ("does not exist", "not found", "no database", "unknown database", "catalog error", "named")):
                print(f"[swe motherduck] Databasen '{md_db}' finns inte – skapar den via workspace-anslutning.")
                try:
                    import duckdb as _ddb
                    workspace = _ddb.connect(f"md:?motherduck_token={token}")
                    workspace.execute(f"CREATE DATABASE IF NOT EXISTS {md_db}")
                    workspace.close()
                    print(f"[swe motherduck] Databasen '{md_db}' skapad.")
                    conn.execute(f"ATTACH 'md:{md_db}'")
                except Exception as create_err:
                    print(f"[swe motherduck] Kunde inte skapa databasen: {create_err}")
                    print(f"[swe motherduck] Skapa databasen '{md_db}' manuellt i MotherDuck UI.")
                    conn.close()
                    return
            else:
                print(f"[swe motherduck] Anslutningsfel: {e}")
                conn.close()
                return
    except Exception as exc:
        print(f"[swe motherduck] Kunde inte initiera MotherDuck: {exc}")
        conn.close()
        return

    # Hämta vilka tabeller/vyer som finns lokalt (verifiera existens)
    try:
        rows = conn.execute(
            "SELECT table_name FROM local.information_schema.tables "
            "WHERE table_schema = 'main' AND table_type IN ('BASE TABLE', 'VIEW') "
            "ORDER BY table_name"
        ).fetchall()
        candidate_tables = [r[0] for r in rows]
    except Exception:
        candidate_tables = SWE_DATASETS

    # Filtrera bort tabeller som saknar data lokalt
    tables = []
    for t in candidate_tables:
        try:
            conn.execute(f'SELECT 1 FROM local.main."{t}" LIMIT 0')
            tables.append(t)
        except Exception:
            print(f"[swe motherduck] {t}: lokal vy saknas, hoppar över")

    ok, fail = 0, 0
    try:
        for name in tables:
            try:
                if name in UPSERT_KEYS:
                    keys = UPSERT_KEYS[name]
                    if not _md_table_exists(conn, md_db, name):
                        # Första gången: skapa tabellen direkt
                        conn.execute(
                            f'CREATE OR REPLACE TABLE "{md_db}".main."{name}" '
                            f'AS SELECT * FROM local.main."{name}"'
                        )
                        print(f"[swe motherduck] {name}: initial load klar")
                    else:
                        # Efterföljande körningar: UPSERT (insert nya rader)
                        join_cond = " AND ".join(
                            f'md."{k}" = src."{k}"' for k in keys
                        )
                        conn.execute(f"""
                            INSERT INTO "{md_db}".main."{name}"
                            SELECT src.* FROM local.main."{name}" src
                            WHERE NOT EXISTS (
                                SELECT 1 FROM "{md_db}".main."{name}" md
                                WHERE {join_cond}
                            )
                        """)
                        print(f"[swe motherduck] {name}: UPSERT klar")
                else:
                    conn.execute(
                        f'CREATE OR REPLACE TABLE "{md_db}".main."{name}" '
                        f'AS SELECT * FROM local.main."{name}"'
                    )
                    print(f"[swe motherduck] {name}: ersatt (full replace)")
                ok += 1
            except Exception as exc:
                print(f"[swe motherduck] {name}: {exc}")
                fail += 1
    finally:
        conn.close()

    print(f"[swe motherduck] Klar: {ok} tabeller uppdaterade ({fail} misslyckade).")


@data_exporter
def sync_swe_to_motherduck(data, *args, **kwargs):
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    silver_swe = os.path.join(data_lake, "silver", "swe")
    gold = os.path.join(data_lake, "gold")
    os.makedirs(gold, exist_ok=True)

    db_path = os.path.join(gold, "swe.duckdb")

    _build_local_duckdb(db_path, silver_swe)
    _sync_to_motherduck(db_path)

    print(f"[swe motherduck] Lokal Gold-fil: {db_path}")
