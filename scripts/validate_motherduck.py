#!/usr/bin/env python3
"""
Kör valideringsfrågor mot MotherDuck NHL-databasen.
Kräver: MOTHERDUCK_TOKEN i .env eller miljö.

  python scripts/validate_motherduck.py

Eller med token:
  MOTHERDUCK_TOKEN=xxx python scripts/validate_motherduck.py
"""
import os
import sys

try:
    import duckdb
except ImportError:
    print("Kräver: pip install duckdb>=1.4.4")
    sys.exit(1)

# Ladda .env om den finns
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MD_DB = os.getenv("MOTHERDUCK_DATABASE_NAME", "nhl").strip() or "nhl"


def run(conn, name: str, sql: str) -> None:
    """Kör en fråga och skriver resultat."""
    print(f"\n{'='*60}\n{name}\n{'='*60}")
    try:
        result = conn.execute(sql).fetchdf()
        print(result.to_string(index=False))
    except Exception as e:
        print(f"Fel: {e}")


def main():
    if not os.getenv("MOTHERDUCK_TOKEN", "").strip():
        print("Sätt MOTHERDUCK_TOKEN i .env eller miljö.")
        sys.exit(1)

    # Token läs från env av MotherDuck-extension
    conn = duckdb.connect(f"md:{MD_DB}")

    run(
        conn,
        "1. Antal rader per tabell",
        """
        SELECT 'teams' AS tabell, count(*) AS rader FROM main.teams
        UNION ALL SELECT 'players', count(*) FROM main.players
        UNION ALL SELECT 'countries', count(*) FROM main.countries
        UNION ALL SELECT 'games', count(*) FROM main.games
        UNION ALL SELECT 'game_players', count(*) FROM main.game_players
        UNION ALL SELECT 'player_game_stats', count(*) FROM main.player_game_stats
        UNION ALL SELECT 'team_game_stats', count(*) FROM main.team_game_stats
        UNION ALL SELECT 'standings', count(*) FROM main.standings
        UNION ALL SELECT 'skater_stats', count(*) FROM main.skater_stats
        UNION ALL SELECT 'goalie_stats', count(*) FROM main.goalie_stats
        ORDER BY tabell
        """,
    )

    run(
        conn,
        "2. Datumspann för matcher",
        """
        SELECT min(game_date) AS forsta, max(game_date) AS senaste,
               count(DISTINCT game_id) AS antal_matcher
        FROM main.games
        """,
    )

    run(
        conn,
        "3. Inga dubletter på game_id?",
        """
        SELECT count(*) AS total, count(DISTINCT game_id) AS unika,
               CASE WHEN count(*) = count(DISTINCT game_id) THEN 'OK' ELSE 'FEL' END AS status
        FROM main.games
        """,
    )

    run(
        conn,
        "4. Senaste 5 matcher",
        """
        SELECT game_id, game_date, home_team_abbr, away_team_abbr, home_score, away_score
        FROM main.games ORDER BY game_date DESC LIMIT 5
        """,
    )

    run(
        conn,
        "5. Topp 5 spelare (antal matcher)",
        """
        SELECT player_first_name || ' ' || player_last_name AS namn, count(*) AS matcher
        FROM main.player_game_stats
        GROUP BY player_id, player_first_name, player_last_name
        ORDER BY matcher DESC LIMIT 5
        """,
    )

    conn.close()
    print("\n" + "=" * 60 + "\nValidering klar.\n")


if __name__ == "__main__":
    main()
