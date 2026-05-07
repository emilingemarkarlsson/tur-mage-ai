import io
import os
import sys

import boto3
import botocore.exceptions
import pandas as pd
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader

BUCKET = "sui-scrape"
PREFIX = "parsed/"
CSV_FILES = ["games", "player_stats", "goalie_stats", "team_stats", "goals", "penalties"]


def _get_minio_client():
    endpoint = os.getenv("MINIO_ENDPOINT", "").strip()
    if endpoint and not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", ""),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", ""),
        region_name="us-east-1",  # required by boto3 even for non-AWS endpoints
    )


def _clean_player_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Remove aggregate rows (player_id=0 / player_name='Total') leaked by the scraper."""
    before = len(df)
    df = df[~df["player_id"].isin(["0", "", "None", None])]
    df = df[df["player_name"].str.lower() != "total"]
    removed = before - len(df)
    if removed:
        print(f"[sui loader] player_stats: filtrerade bort {removed} aggregatrader (player_id=0/Total)")
    return df


@data_loader
def load_csvs_from_minio(*args, **kwargs):
    """
    Downloads parsed SUI hockey CSVs from Minio (sui-scrape/parsed/) into DataFrames.
    Skips and warns on missing files; all columns read as str to preserve IDs.
    Returns dict keyed by csv name (without .csv extension).
    """
    client = _get_minio_client()
    result = {}

    for name in CSV_FILES:
        key = f"{PREFIX}{name}.csv"
        try:
            resp = client.get_object(Bucket=BUCKET, Key=key)
            body = resp["Body"].read()
            df = pd.read_csv(io.BytesIO(body), dtype=str)
            df = df.where(pd.notnull(df), None)  # NaN → None for proper DuckDB NULLs

            if name == "player_stats":
                df = _clean_player_stats(df)

            result[name] = df
            print(f"[sui loader] {name}.csv: {len(df)} rader, kolumner={list(df.columns)}")
        except botocore.exceptions.ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "AccessDenied"):
                print(f"[sui loader] WARNING: {key} saknas eller åtkomst nekad ({code}) – hoppar över")
            else:
                print(f"[sui loader] WARNING: S3-fel för {key} ({code}): {e}")
        except Exception as exc:
            print(f"[sui loader] WARNING: Kunde inte läsa {key}: {exc}")

    loaded = list(result.keys())
    skipped = [n for n in CSV_FILES if n not in result]
    print(f"[sui loader] Klart. Laddade: {loaded}. Hoppade över: {skipped or 'ingen'}.")
    return result
