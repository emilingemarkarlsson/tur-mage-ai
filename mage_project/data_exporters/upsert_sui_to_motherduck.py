import os
import sys

import duckdb
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter

# Naming follows the same convention as swe.*:
#   - own database "sui" (not prefixed inside nhl)
#   - game_* prefix for per-game tables
#
# CSV key → MotherDuck table name in sui database
TABLE_NAMES = {
    "games":        "games",
    "player_stats": "game_player_stats",
    "goalie_stats": "game_goalie_stats",
    "team_stats":   "game_team_stats",
    "goals":        "game_goals",
    "penalties":    "game_penalties",
}

# Composite primary keys per table
PRIMARY_KEYS = {
    "games":            ["game_id"],
    "game_player_stats": ["game_id", "player_id", "team_id"],
    "game_goalie_stats": ["game_id", "player_id", "team_id"],
    "game_team_stats":   ["game_id", "team_id"],
    "game_goals":        ["game_id", "time_sec", "team_id", "scorer_id"],
    # minutes included because fight penalties yield two simultaneous rows (5 min + 20 min)
    # for the same player at the same second — both rows are valid
    "game_penalties":    ["game_id", "start_sec", "player_id", "minutes"],
}

MD_CATALOG = "sui"


def _ensure_database(token: str):
    """Create the sui database in MotherDuck if it does not exist yet."""
    try:
        ws = duckdb.connect(f"md:?motherduck_token={token}")
        ws.execute(f"CREATE DATABASE IF NOT EXISTS {MD_CATALOG}")
        ws.close()
    except Exception as exc:
        raise RuntimeError(f"[sui motherduck] Kunde inte skapa databasen '{MD_CATALOG}': {exc}") from exc


def _md_table_exists(conn, table: str) -> bool:
    """Check existence via direct SELECT – same pattern as sync_swe_to_motherduck."""
    try:
        conn.execute(f'SELECT 1 FROM "{MD_CATALOG}".main."{table}" LIMIT 0')
        return True
    except Exception as e:
        err = str(e).lower()
        if any(s in err for s in ("does not exist", "not found", "no table", "catalog error")):
            return False
        # Unknown error (network timeout etc.) – assume exists to avoid accidental double-create
        print(f"[sui motherduck] Kan inte avgöra om {table} finns, antar att den gör det: {e}")
        return True


def _get_existing_columns(conn, table: str) -> list[str] | None:
    """Return column list from MotherDuck table, or None on failure."""
    try:
        rows = conn.execute(
            f"SELECT column_name FROM \"{MD_CATALOG}\".information_schema.columns "
            f"WHERE table_schema = 'main' AND table_name = '{table}' "
            f"ORDER BY ordinal_position"
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return None


def _upsert_table(conn, table: str, df, keys: list[str]) -> int:
    """
    Upsert DataFrame into sui.main.<table> using DELETE + INSERT keyed on `keys`.
    Creates the table on first run. Uses explicit catalog.main.table notation throughout
    so registered in-memory DataFrames and MotherDuck tables never clash.
    Returns number of rows upserted.
    """
    if df is None or df.empty:
        print(f"[sui motherduck] {table}: tom DataFrame, hoppar över")
        return 0

    qualified = f'"{MD_CATALOG}".main."{table}"'

    missing_keys = [k for k in keys if k not in df.columns]
    if missing_keys:
        print(
            f"[sui motherduck] ERROR: {table} saknar primary key-kolumner {missing_keys} "
            f"i CSV (tillgängliga: {list(df.columns)}) – hoppar över"
        )
        return 0

    conn.register("_sui_staging", df)

    try:
        if not _md_table_exists(conn, table):
            conn.execute(f"CREATE TABLE {qualified} AS SELECT * FROM _sui_staging")
            count = len(df)
            print(f"[sui motherduck] {table}: initial load {count} rader")
            return count

        # Reconcile columns: only INSERT columns that exist in the target table
        existing_cols = _get_existing_columns(conn, table)
        if existing_cols:
            cols = [c for c in df.columns if c in existing_cols]
            new_cols = [c for c in df.columns if c not in existing_cols]
            if new_cols:
                print(
                    f"[sui motherduck] WARNING: {table} saknar kolumner {new_cols} – "
                    "ignoreras. ALTER TABLE manuellt vid schemabyte."
                )
        else:
            cols = list(df.columns)

        # DELETE existing rows whose primary key matches any row in the incoming batch
        key_join = " AND ".join(
            f'{qualified}."{k}" = _sui_staging."{k}"' for k in keys
        )
        conn.execute(f"""
            DELETE FROM {qualified}
            WHERE EXISTS (
                SELECT 1 FROM _sui_staging
                WHERE {key_join}
            )
        """)

        col_list = ", ".join(f'"{c}"' for c in cols)
        conn.execute(f"""
            INSERT INTO {qualified} ({col_list})
            SELECT {col_list} FROM _sui_staging
        """)

        count = len(df)
        print(f"[sui motherduck] {table}: upsert {count} rader OK")
        return count

    finally:
        try:
            conn.unregister("_sui_staging")
        except Exception:
            pass


@data_exporter
def upsert_sui_to_motherduck(data: dict, *args, **kwargs):
    """
    Upserts Swiss hockey DataFrames into MotherDuck sui database.

    Naming follows the swe.* convention: own database "sui", game_* prefix for per-game tables.
    DELETE + INSERT pattern keyed on composite primary keys → idempotent on re-runs.
    Uses explicit sui.main.<table> notation (same as sync_swe_to_motherduck).

    Input key → sui table:
      games        → sui.games
      player_stats → sui.game_player_stats
      goalie_stats → sui.game_goalie_stats
      team_stats   → sui.game_team_stats
      goals        → sui.game_goals
      penalties    → sui.game_penalties
    """
    token = os.getenv("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        raise ValueError("[sui motherduck] MOTHERDUCK_TOKEN saknas – pipeline kan inte köras")

    if not data:
        print("[sui motherduck] Inga DataFrames att ladda – avslutar")
        return

    _ensure_database(token)

    conn = duckdb.connect(":memory:")
    try:
        conn.execute("INSTALL motherduck")
        conn.execute("LOAD motherduck")
        conn.execute(f"ATTACH 'md:{MD_CATALOG}'")
        print(f"[sui motherduck] Ansluten till MotherDuck ({MD_CATALOG})")
    except Exception as exc:
        conn.close()
        raise RuntimeError(f"[sui motherduck] Kunde inte ansluta: {exc}") from exc

    total_rows = 0
    ok_tables = []
    failed_tables = []

    try:
        for csv_name, df in data.items():
            table = TABLE_NAMES.get(csv_name)
            if table is None:
                print(f"[sui motherduck] Okänd CSV '{csv_name}' – hoppar över")
                continue
            keys = PRIMARY_KEYS[table]
            try:
                rows = _upsert_table(conn, table, df, keys)
                total_rows += rows
                ok_tables.append(table)
            except Exception as exc:
                print(f"[sui motherduck] ERROR {table}: {exc}")
                failed_tables.append(table)
    finally:
        conn.close()

    print(
        f"[sui motherduck] Klar. {total_rows} rader upsertade i {len(ok_tables)} tabeller. "
        f"Lyckade: {ok_tables}. Misslyckade: {failed_tables or 'ingen'}."
    )
