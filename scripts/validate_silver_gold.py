#!/usr/bin/env python3
"""
Validerar att dimensions (och övriga) pipelines skrivit till Silver och att Gold-vyerna finns.
Kör från projektroten, t.ex.:
  python scripts/validate_silver_gold.py
  docker exec tur-mage-ai-mage-1 python /home/src/scripts/validate_silver_gold.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_LAKE = os.environ.get("DATA_LAKE_PATH", os.path.join(ROOT, "mage_project", "data_lake"))
SILVER = os.path.join(DATA_LAKE, "silver")
GOLD_DB = os.path.join(DATA_LAKE, "gold", "nhl.duckdb")

EXPECTED_DATASETS = [
    "teams", "players", "countries", "roster",
    "schedule", "game_ids", "glossary", "draft",
    "standings", "skater_stats", "goalie_stats", "team_stats",
    "edge_skaters", "edge_goalies", "edge_teams",
    "games", "game_players",
]


def count_parquets(path: str) -> int:
    n = 0
    if not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            if f.endswith(".parquet"):
                n += 1
    return n


def main():
    print("=== Silver (Parquet) ===\n")
    if not os.path.isdir(SILVER):
        print(f"  Saknas: {SILVER}")
        sys.exit(1)
    ok = 0
    missing = []
    for name in EXPECTED_DATASETS:
        folder = os.path.join(SILVER, name)
        n = count_parquets(folder)
        if n > 0:
            print(f"  OK   {name}: {n} fil(er)")
            ok += 1
        else:
            print(f"  --   {name}: (inga filer)")
            missing.append(name)
    print(f"\n  Sammanfattning: {ok}/{len(EXPECTED_DATASETS)} datamängder har data.\n")

    print("=== Gold (DuckDB) ===\n")
    if not os.path.isfile(GOLD_DB):
        print(f"  DuckDB finns inte (lokalt): {GOLD_DB}")
        print("  Om du använder S3: kör refresh_duckdb_views och öppna Streamlit med S3-koppling.\n")
        return
    try:
        import duckdb
        conn = duckdb.connect(GOLD_DB, read_only=True)
        for name in EXPECTED_DATASETS:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
                cnt = row[0] if row else 0
                print(f"  OK   {name}: {cnt} rader")
            except Exception as e:
                print(f"  --   {name}: (saknas eller fel: {e})")
        conn.close()
        print("\n  Validering klar. Öppna Streamlit och välj en tabell för att dubbelkolla innehåll.\n")
    except Exception as e:
        print(f"  Kunde inte öppna DuckDB: {e}\n")


if __name__ == "__main__":
    main()
