import os
import sys

import duckdb
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter

from utils.s3_utils import get_s3_bucket, get_s3_client, upload_file


DATASETS = [
    "teams",
    "players",
    "countries",
    "roster",
    "schedule",
    "game_ids",
    "glossary",
    "draft",
    "standings",
    "skater_stats",
    "goalie_stats",
    "team_stats",
    "edge_skaters",
    "edge_goalies",
    "edge_teams",
    "games",
    "game_players",
]


@data_exporter
def refresh_duckdb_views(*args, **kwargs):
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    silver = os.path.join(data_lake, "silver")
    gold = os.path.join(data_lake, "gold")
    os.makedirs(gold, exist_ok=True)

    db_path = os.path.join(gold, "nhl.duckdb")
    conn = duckdb.connect(db_path)

    for dataset in DATASETS:
        dataset_path = os.path.join(silver, dataset, "**", "*.parquet")
        if not os.path.exists(os.path.join(silver, dataset)):
            continue
        view_sql = f"CREATE OR REPLACE VIEW {dataset} AS SELECT * FROM parquet_scan('{dataset_path}');"
        conn.execute(view_sql)

    conn.close()

    # Upload DuckDB to S3 when DATA_LAKE_SINK=s3 (t.ex. Hetzner). S3 blir enda kopian.
    sink = os.getenv("DATA_LAKE_SINK", "local").strip().lower()
    if sink == "s3" and os.path.isfile(db_path):
        s3_prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
        s3_bucket = os.getenv("S3_DATA_LAKE_BUCKET") or get_s3_bucket()
        if s3_bucket:
            client = get_s3_client()
            key = f"{s3_prefix}/gold/nhl.duckdb"
            upload_file(client, s3_bucket, key, db_path)
            # Ta bort lokal fil så den inte fyller disken; databasen finns bara i S3.
            try:
                os.remove(db_path)
            except OSError:
                pass
