#!/usr/bin/env python3
"""
Visar vilket datumspann som finns i din inhämtade data (games, standings, etc.).
Kör från projektroten:
  python scripts/show_data_date_range.py
  docker exec tur-mage-ai-mage-1 python /home/src/scripts/show_data_date_range.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_LAKE = os.environ.get("DATA_LAKE_PATH", os.path.join(ROOT, "mage_project", "data_lake"))
SILVER = os.path.join(DATA_LAKE, "silver")


def main():
    if not os.path.isdir(SILVER):
        print(f"Silver-mappen finns inte: {SILVER}")
        sys.exit(1)
    try:
        import duckdb
    except ImportError:
        print("Installera duckdb: pip install duckdb")
        sys.exit(1)

    conn = duckdb.connect(":memory:")
    print("=== Datumspann i din data ===\n")

    # Games (matchdata) – det som styrs av GAMES_START_DATE och vad som finns i S3
    games_glob = os.path.join(SILVER, "games", "**", "*.parquet")
    if os.path.exists(os.path.join(SILVER, "games")):
        try:
            row = conn.execute(
                f"SELECT MIN(game_date) AS första, MAX(game_date) AS sista, COUNT(*) AS antal_matcher FROM parquet_scan('{games_glob}')"
            ).fetchone()
            if row and row[2] and row[2] > 0:
                print(f"  Matcher (games):     {row[0]} → {row[1]}  ({row[2]} matcher)")
            else:
                print("  Matcher (games):     (inga rader)")
        except Exception as e:
            print(f"  Matcher (games):     kunde inte läsa: {e}")
    else:
        print("  Matcher (games):     (mappen saknas)")

    # Standings – ofta per säsong
    stand_glob = os.path.join(SILVER, "standings", "**", "*.parquet")
    if os.path.exists(os.path.join(SILVER, "standings")):
        try:
            # standings kan ha season eller liknande
            r = conn.execute(f"SELECT * FROM parquet_scan('{stand_glob}') LIMIT 1").fetchdf()
            cols = list(r.columns)
            season_col = "season" if "season" in cols else (cols[0] if cols else None)
            if season_col:
                row = conn.execute(
                    f"SELECT MIN({season_col}) AS första_säsong, MAX({season_col}) AS sista_säsong, COUNT(*) AS antal FROM parquet_scan('{stand_glob}')"
                ).fetchone()
                if row and row[2] and row[2] > 0:
                    print(f"  Ställningar:         säsong {row[0]} → {row[1]}  ({row[2]} rader)")
            else:
                n = conn.execute(f"SELECT COUNT(*) FROM parquet_scan('{stand_glob}')").fetchone()[0]
                print(f"  Ställningar:         {n} rader")
        except Exception as e:
            print(f"  Ställningar:         kunde inte läsa: {e}")
    else:
        print("  Ställningar:         (mappen saknas)")

    # Schedule
    sched_glob = os.path.join(SILVER, "schedule", "**", "*.parquet")
    if os.path.exists(os.path.join(SILVER, "schedule")):
        try:
            row = conn.execute(
                f"SELECT MIN(schedule_date) AS första, MAX(schedule_date) AS sista, COUNT(*) FROM parquet_scan('{sched_glob}')"
            ).fetchone()
            if row and row[2] and row[2] > 0:
                print(f"  Schema (schedule):   {row[0]} → {row[1]}  ({row[2]} rader)")
            else:
                print("  Schema (schedule):   (inga rader)")
        except Exception as e:
            print(f"  Schema (schedule):   kunde inte läsa: {e}")
    else:
        print("  Schema (schedule):   (mappen saknas)")

    print("\n  Konfiguration: GAMES_START_DATE i .env styr från vilket datum games_pipeline laddar matcher.")
    print("  Övre gräns: vad som faktiskt finns i S3 under nhl-data-reorganized/games/by_date/.\n")


if __name__ == "__main__":
    main()
