"""
sync_data_dictionary.py – Synkar DATA_DICTIONARY.yaml till MotherDuck via COMMENT ON TABLE/COLUMN.

Kör:
    MOTHERDUCK_TOKEN=<token> python scripts/sync_data_dictionary.py [--dry-run] [--db nhl]

Kräver: duckdb, pyyaml
"""

import argparse
import os
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("Saknar duckdb – kör: pip install duckdb")

try:
    import yaml
except ImportError:
    sys.exit("Saknar pyyaml – kör: pip install pyyaml")


REPO_ROOT = Path(__file__).resolve().parent.parent
DICT_PATH = REPO_ROOT / "documentation" / "DATA_DICTIONARY.yaml"


def _escape(s: str) -> str:
    """Escape single quotes for SQL string literals."""
    return s.replace("'", "''")


def main():
    parser = argparse.ArgumentParser(description="Synka DATA_DICTIONARY.yaml till MotherDuck")
    parser.add_argument("--dry-run", action="store_true", help="Skriv ut SQL utan att köra")
    parser.add_argument("--db", default=None, help="MotherDuck-databas (default: MOTHERDUCK_DATABASE_NAME eller 'nhl')")
    args = parser.parse_args()

    token = os.getenv("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        sys.exit("MOTHERDUCK_TOKEN saknas – sätt variabeln och försök igen.")

    md_db = args.db or os.getenv("MOTHERDUCK_DATABASE_NAME", "nhl").strip() or "nhl"

    if not DICT_PATH.exists():
        sys.exit(f"Hittade inte {DICT_PATH}")

    with open(DICT_PATH, encoding="utf-8") as f:
        dd = yaml.safe_load(f)

    tables = dd.get("tables", {})
    if not tables:
        sys.exit("Inga tabeller hittades i YAML.")

    # Bygg SQL-kommandon
    statements: list[tuple[str, str]] = []  # (label, sql)
    for table_name, table_def in tables.items():
        if not isinstance(table_def, dict):
            continue

        table_desc = table_def.get("description", "").strip()
        if table_desc:
            sql = f"COMMENT ON TABLE \"{md_db}\".main.\"{table_name}\" IS '{_escape(table_desc)}'"
            statements.append((f"TABLE {table_name}", sql))

        columns = table_def.get("columns", {}) or {}
        for col_name, col_def in columns.items():
            if not isinstance(col_def, dict):
                continue
            col_desc = col_def.get("description", "").strip()
            if col_desc:
                sql = (
                    f"COMMENT ON COLUMN \"{md_db}\".main.\"{table_name}\".\"{col_name}\" "
                    f"IS '{_escape(col_desc)}'"
                )
                statements.append((f"COLUMN {table_name}.{col_name}", sql))

    print(f"Hittade {len(statements)} kommentarer att synka till MotherDuck ({md_db}).")

    if args.dry_run:
        for label, sql in statements:
            print(f"\n-- {label}\n{sql};")
        print("\n[dry-run] Inga ändringar gjorda.")
        return

    # Anslut till MotherDuck
    print("Ansluter till MotherDuck...")
    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL motherduck")
    conn.execute("LOAD motherduck")
    conn.execute(f"ATTACH 'md:{md_db}'")

    ok = 0
    fail = 0
    for label, sql in statements:
        try:
            conn.execute(sql)
            ok += 1
        except Exception as e:
            print(f"  [FEL] {label}: {e}")
            fail += 1

    conn.close()
    print(f"\nKlar: {ok} kommentarer satta, {fail} misslyckade.")


if __name__ == "__main__":
    main()
