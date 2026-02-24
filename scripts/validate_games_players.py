#!/usr/bin/env python3
"""
Validerar games, game_players och players: radantal och att det inte finns dubletter.
Kör från projektroten:
  python scripts/validate_games_players.py
  docker exec tur-mage-ai-mage-1 python /home/src/scripts/validate_games_players.py
Om Gold ligger i S3: använd Streamlit med S3-koppling och kör dublettkontroll manuellt (se README).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_LAKE = os.environ.get("DATA_LAKE_PATH", os.path.join(ROOT, "mage_project", "data_lake"))
GOLD_DB = os.path.join(DATA_LAKE, "gold", "nhl.duckdb")


def main():
    if not os.path.isfile(GOLD_DB):
        print(f"DuckDB finns inte lokalt: {GOLD_DB}")
        print("Om du skriver till S3: Gold ligger i S3. Validera via Streamlit (välj games / game_players / players) eller kör detta skript i containern där DB skapas.\n")
        sys.exit(0)

    try:
        import duckdb
    except ImportError:
        print("duckdb saknas. Installera med: pip install duckdb")
        sys.exit(1)

    conn = duckdb.connect(GOLD_DB, read_only=True)
    ok = True

    # --- games ---
    print("=== games ===\n")
    try:
        (total,) = conn.execute("SELECT COUNT(*) FROM games").fetchone()
        print(f"  Rader: {total}")
        (dupes,) = conn.execute(
            "SELECT COUNT(*) FROM (SELECT game_id FROM games GROUP BY game_id HAVING COUNT(*) > 1) t"
        ).fetchone()
        if dupes > 0:
            print(f"  VARNING: {dupes} game_id har dubletter.")
            ok = False
        else:
            print("  Dubletter (game_id): inga")
        # exempelkolumner
        row = conn.execute(
            "SELECT game_id, game_date, home_team_abbr, away_team_abbr, home_score, away_score FROM games LIMIT 1"
        ).fetchone()
        if row:
            print(f"  Exempelrad: game_id={row[0]}, date={row[1]}, {row[2]}–{row[3]} {row[4]}–{row[5]}")
    except Exception as e:
        print(f"  Fel: {e}")
        ok = False

    # --- game_players ---
    print("\n=== game_players ===\n")
    try:
        (total,) = conn.execute("SELECT COUNT(*) FROM game_players").fetchone()
        print(f"  Rader: {total}")
        (dupes,) = conn.execute(
            "SELECT COUNT(*) FROM (SELECT game_id, player_id FROM game_players GROUP BY game_id, player_id HAVING COUNT(*) > 1) t"
        ).fetchone()
        if dupes > 0:
            print(f"  VARNING: {dupes} (game_id, player_id)-par har dubletter.")
            ok = False
        else:
            print("  Dubletter (game_id, player_id): inga")
        row = conn.execute(
            "SELECT game_id, game_date, player_id, team_abbr, position, goals, assists FROM game_players LIMIT 1"
        ).fetchone()
        if row:
            print(f"  Exempelrad: game_id={row[0]}, date={row[1]}, player_id={row[2]}, {row[3]} {row[4]}, G–A {row[5]}–{row[6]}")
    except Exception as e:
        print(f"  Fel: {e}")
        ok = False

    # --- players (dimension) ---
    print("\n=== players ===\n")
    try:
        (total,) = conn.execute("SELECT COUNT(*) FROM players").fetchone()
        print(f"  Rader: {total}")
        row = conn.execute("SELECT id, firstName, lastName FROM players LIMIT 1").fetchone()
        if row:
            print(f"  Exempelrad: id={row[0]}, name={row[1]} {row[2]}")
        else:
            print("  (Inga rader)")
    except Exception as e:
        # Kolumnnamn kan vara annorlunda (firstName/lastName)
        try:
            (total,) = conn.execute("SELECT COUNT(*) FROM players").fetchone()
            print(f"  Rader: {total}")
        except Exception as e2:
            print(f"  Fel: {e2}")
            ok = False

    conn.close()

    print("\n" + ("Validering OK." if ok else "Det fanns varningar – se ovan.") + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
