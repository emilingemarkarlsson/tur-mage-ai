#!/usr/bin/env python3
"""
Kollar om games/game_players finns i Silver i S3 (då har games_pipeline skrivit dit).
Kör: python scripts/check_silver_games_in_s3.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
except Exception:
    pass

sys.path.insert(0, os.path.join(ROOT, "mage_project"))
from utils.s3_utils import get_s3_bucket, get_s3_client, list_keys

def main():
    bucket = get_s3_bucket()
    prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
    if not bucket:
        print("S3 bucket inte satt.")
        sys.exit(1)
    client = get_s3_client()
    games_count = 0
    players_count = 0
    for name, key_prefix in [
        ("games", f"{prefix}/silver/games/"),
        ("game_players", f"{prefix}/silver/game_players/"),
    ]:
        keys = list(list_keys(client, bucket, key_prefix))
        parquet = [k for k in keys if k.endswith(".parquet")]
        n = len(parquet)
        print(f"Silver {name} i S3: {n} parquet-filer (prefix: {key_prefix})")
        if name == "games":
            games_count = n
        else:
            players_count = n
    if games_count > 0 or players_count > 0:
        print("\n→ Data finns i S3 Silver. Gold kan byggas om utan att köra games load igen:")
        print("  Sätt REFRESH_USE_S3_FALLBACK_FOR_GAMES=1 i .env, starta om Mage, kör dimensions_pipeline.")
        print("  Refresh läser då games/game_players från S3 och bygger full Gold.")

if __name__ == "__main__":
    main()
