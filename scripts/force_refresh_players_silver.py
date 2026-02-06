#!/usr/bin/env python3
"""
Kör load_dimensions → transform_dimensions och skriver bara silver/players
(plattad spelardata). Kringår Mage block-cache så att vyn "players" får rätt schema.

Kör från projektroten, t.ex. i container:
  docker exec tur-mage-ai-mage-1 bash -c "cd /home/src && python scripts/force_refresh_players_silver.py"
"""
import os
import sys
from datetime import datetime

# Sätt så att mage_project finns på path och cwd
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_mage = os.path.join(_root, "mage_project")
sys.path.insert(0, _mage)
os.chdir(_mage)

# Ladda .env från projektrot
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except Exception:
    pass

# DATA_LAKE_PATH måste vara satt (t.ex. /home/src/mage_project/data_lake i container)
data_lake = os.getenv("DATA_LAKE_PATH", os.path.join(_mage, "data_lake"))
silver_players = os.path.join(data_lake, "silver", "players")


def _clean_parquet_dir(base_path: str):
    if not os.path.isdir(base_path):
        return
    for name in os.listdir(base_path):
        path = os.path.join(base_path, name)
        if os.path.isfile(path) and name.endswith(".parquet"):
            try:
                os.remove(path)
            except OSError:
                pass
        elif os.path.isdir(path):
            _clean_parquet_dir(path)


def main():
    print("Loading dimensions from S3...")
    from data_loaders.load_dimensions import load_dimensions
    payload = load_dimensions()

    print("Transforming (flatten players)...")
    from transformers.transform_dimensions import transform_dimensions
    data = transform_dimensions(payload)

    players_df = data.get("players")
    if players_df is None or players_df.empty:
        print("ERROR: No players DataFrame from transform.")
        sys.exit(1)

    cols = list(players_df.columns)
    print(f"Players columns: {cols[:10]}{'...' if len(cols) > 10 else ''}")
    if "forwards" in cols:
        print("ERROR: Transform returned forwards/defensemen structure (cache?). Clear Mage block output and run pipeline instead.")
        sys.exit(1)

    print("Cleaning silver/players and writing Parquet...")
    _clean_parquet_dir(silver_players)
    os.makedirs(silver_players, exist_ok=True)
    import pandas as pd
    out_path = os.path.join(silver_players, f"part-{datetime.utcnow().timestamp()}.parquet")
    players_df.to_parquet(out_path, index=False)
    print(f"Wrote {out_path}")

    # S3-upload om DATA_LAKE_SINK=s3
    if os.getenv("DATA_LAKE_SINK", "").strip().lower() == "s3":
        s3_prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
        s3_bucket = os.getenv("S3_DATA_LAKE_BUCKET") or os.getenv("HETZNER_BUCKET")
        if s3_bucket:
            from utils.s3_utils import get_s3_client, upload_file
            client = get_s3_client()
            rel = os.path.relpath(out_path, data_lake)
            key = f"{s3_prefix}/{rel}"
            upload_file(client, s3_bucket, key, out_path)
            print(f"Uploaded to s3://{s3_bucket}/{key}")

    print("Done. Run refresh_duckdb_views (e.g. ./scripts/run_refresh_duckdb.sh) to update Gold.")


if __name__ == "__main__":
    main()
