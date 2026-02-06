#!/usr/bin/env python3
"""
Jämför Bronze (S3 raw JSON) med Silver (Parquet) så du ser att du får med all relevant data
trots att Silver är mycket mindre i GB än Bronze (~100 GB).

Kör från projektroten med .env laddad:
  docker exec tur-mage-ai-mage-1 bash -c "cd /home/src && python scripts/compare_bronze_silver_volume.py"
  eller lokalt: python scripts/compare_bronze_silver_volume.py

För att bara se Silver (snabbare, ingen S3-anrop):
  python scripts/compare_bronze_silver_volume.py --silver-only
"""
import os
import sys
from collections import defaultdict

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_mage = os.path.join(_root, "mage_project")
sys.path.insert(0, _mage)
os.chdir(_mage)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except Exception:
    pass

# --- S3 (Bronze) ---
def get_prefix_stats(client, bucket: str, prefix: str):
    """Räknar antal matchfiler (.json, exkl. games_summary) och total storlek (bytes) under prefix."""
    total_size = 0
    count = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key", "")
            total_size += obj.get("Size", 0)
            if not key.endswith(".json"):
                continue
            if "games_summary" in key:
                continue
            count += 1
    return count, total_size


def main():
    silver_only = "--silver-only" in sys.argv
    print("=== Bronze (S3) vs Silver (Parquet) – volym och täckning ===\n")

    bronze_by_date = None

    # Bronze: S3 (hoppa över om --silver-only – sparar tid vid stora bucketer)
    if not silver_only:
        try:
            from utils.s3_utils import get_s3_bucket, get_s3_client
        except ImportError:
            print("Kunde inte importera utils.s3_utils. Kör från projektroten med PYTHONPATH eller från Mage-containern.")
            sys.exit(1)

        client = get_s3_client()
        bucket = get_s3_bucket()
        if not bucket:
            print("S3 bucket inte konfigurerad (HETZNER_BUCKET / S3_BUCKET). Hoppar över Bronze-statistik.\n")
        else:
            base = "nhl-data-reorganized/games/"
            by_date_prefix = base + "by_date/"
            by_team_prefix = base + "by_team/"
            by_player_prefix = base + "by_player/"

            print("Bronze (raw JSON i S3):")
            n_date, sz_date = get_prefix_stats(client, bucket, by_date_prefix)
            bronze_by_date = (n_date, sz_date)
            print(f"  by_date/   (det pipelinen läser):  {n_date} matcher,  {sz_date / (1024**3):.2f} GB")
            n_team, sz_team = get_prefix_stats(client, bucket, by_team_prefix)
            print(f"  by_team/   (samma data, per lag):  {n_team} filer,    {sz_team / (1024**3):.2f} GB")
            n_player, sz_player = get_prefix_stats(client, bucket, by_player_prefix)
            print(f"  by_player/ (samma data, per spelare): {n_player} filer, {sz_player / (1024**3):.2f} GB")
            total_bronze = sz_date + sz_team + sz_player
            print(f"  Totalt games i S3:                   {total_bronze / (1024**3):.2f} GB")
            print("  → Pipelinen läser bara by_date/. by_team och by_player är kopior, därav stor Bronze-volym.\n")
    else:
        print("Bronze: hoppat över (--silver-only). Kör utan flaggan för full S3-listning.\n")

    # Silver: lokala Parquet
    data_lake = os.environ.get("DATA_LAKE_PATH", os.path.join(_root, "mage_project", "data_lake"))
    silver = os.path.join(data_lake, "silver")
    games_silver = os.path.join(silver, "games")
    game_players_silver = os.path.join(silver, "game_players")

    print("Silver (Parquet efter pipeline):")
    if not os.path.isdir(silver):
        print(f"  Silver-mappen finns inte: {silver}")
        print("  Kör games_pipeline (och övriga pipelines) så skapas Silver.")
        sys.exit(0)

    try:
        import duckdb
    except ImportError:
        print("  Installera duckdb för att räkna Silver: pip install duckdb")
        sys.exit(1)

    conn = duckdb.connect(":memory:")
    silver_games_count = silver_players_count = 0
    silver_games_size = 0

    if os.path.exists(games_silver):
        games_glob = os.path.join(games_silver, "**", "*.parquet")
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM parquet_scan('{games_glob}')"
            ).fetchone()
            silver_games_count = row[0] if row else 0
        except Exception as e:
            print(f"  games: kunde inte läsa: {e}")
        for dirpath, _dirnames, filenames in os.walk(games_silver):
            for f in filenames:
                if f.endswith(".parquet"):
                    silver_games_size += os.path.getsize(os.path.join(dirpath, f))

    if os.path.exists(game_players_silver):
        gp_glob = os.path.join(game_players_silver, "**", "*.parquet")
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM parquet_scan('{gp_glob}')"
            ).fetchone()
            silver_players_count = row[0] if row else 0
        except Exception as e:
            print(f"  game_players: kunde inte läsa: {e}")

    print(f"  games:         {silver_games_count} matcher,  {silver_games_size / (1024**2):.2f} MB")
    print(f"  game_players:  {silver_players_count} rader (spelare × matcher)")
    print()

    # Täckning
    if bronze_by_date and bronze_by_date[0] and silver_games_count is not None:
        n_bronze = bronze_by_date[0]
        pct = 100.0 * silver_games_count / n_bronze if n_bronze else 0
        print("Täckning:")
        print(f"  Matcher i by_date (S3):  {n_bronze}")
        print(f"  Matcher i Silver:        {silver_games_count}")
        if silver_games_count >= n_bronze:
            print("  → Alla matcher från by_date är laddade i Silver.")
        else:
            print(f"  → Ca {pct:.0f}% laddat. Kontrollera GAMES_START_DATE och att games_pipeline körts till slut (inga fler datum kvar).")
    print()
    print("Varför Silver är mycket mindre än Bronze:")
    print("  • Pipelinen läser bara by_date/ (en kopia per match), inte by_team/ eller by_player/.")
    print("  • Vi sparar bara utplockade fält (resultat, lag, spelarstatistik), inte hela JSON")
    print("    (t.ex. ingen full play-by-play, rosterSpots eller gameStory).")
    print("  • Parquet är kolumnformat och komprimerar bra; JSON är repetitiv och stor.")
    print()


if __name__ == "__main__":
    main()
