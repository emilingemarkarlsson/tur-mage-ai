import os
import sys
from datetime import datetime

import polars as pl
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.s3_utils import get_s3_bucket, get_s3_client, upload_file

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter


def _clean_parquet_dir(base_path: str):
    """Ta bort gamla Parquet-filer så att vyn bara ser senaste exporten."""
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


def _write_df(df, base_path: str, partition_col: str = None, s3_prefix: str = None, s3_bucket: str = None):
    if df is None or df.empty:
        return
    _clean_parquet_dir(base_path)
    os.makedirs(base_path, exist_ok=True)
    # Parquet klarar inte dict/list i celler – konvertera objektkolumner till str
    if hasattr(df, "dtypes"):
        import json
        obj_cols = [c for c in df.columns if hasattr(df.dtypes[c], "kind") and df.dtypes[c].kind == "O"]
        if not obj_cols and hasattr(df, "select_dtypes"):
            obj_cols = list(df.select_dtypes(include=["object"]).columns) if hasattr(df, "columns") else []
        if obj_cols:
            df = df.copy()
            for c in obj_cols:
                def _to_serializable(x):
                    if isinstance(x, (dict, list)):
                        try:
                            return json.dumps(x)
                        except (TypeError, ValueError):
                            return str(x)
                    if x is None:
                        return x
                    if isinstance(x, (str, int, float, bool)):
                        return x
                    return str(x)
                df[c] = df[c].apply(_to_serializable)
    pl_df = pl.from_pandas(df)
    s3_client = get_s3_client() if s3_prefix and s3_bucket else None
    if partition_col and partition_col in pl_df.columns:
        for value in pl_df[partition_col].unique().to_list():
            part_df = pl_df.filter(pl.col(partition_col) == value)
            part_dir = os.path.join(base_path, f"{partition_col}={value}")
            os.makedirs(part_dir, exist_ok=True)
            file_path = os.path.join(part_dir, f"part-{datetime.utcnow().timestamp()}.parquet")
            part_df.write_parquet(file_path)
            if s3_client:
                rel_path = os.path.relpath(file_path, "/home/src/mage_project/data_lake")
                key = f"{s3_prefix}/{rel_path}"
                upload_file(s3_client, s3_bucket, key, file_path)
    else:
        file_path = os.path.join(base_path, f"part-{datetime.utcnow().timestamp()}.parquet")
        pl_df.write_parquet(file_path)
        if s3_client:
            rel_path = os.path.relpath(file_path, "/home/src/mage_project/data_lake")
            key = f"{s3_prefix}/{rel_path}"
            upload_file(s3_client, s3_bucket, key, file_path)


@data_exporter
def export_dimensions_parquet(data, *args, **kwargs):
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    silver = os.path.join(data_lake, "silver")
    sink = os.getenv("DATA_LAKE_SINK", "local").lower()
    s3_prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics") if sink == "s3" else None
    s3_bucket = os.getenv("S3_DATA_LAKE_BUCKET") or get_s3_bucket() if sink == "s3" else None

    _write_df(data.get("teams"), os.path.join(silver, "teams"), s3_prefix=s3_prefix, s3_bucket=s3_bucket)
    _write_df(data.get("players"), os.path.join(silver, "players"), s3_prefix=s3_prefix, s3_bucket=s3_bucket)
    _write_df(data.get("countries"), os.path.join(silver, "countries"), s3_prefix=s3_prefix, s3_bucket=s3_bucket)
    _write_df(
        data.get("roster"),
        os.path.join(silver, "roster"),
        partition_col="season",
        s3_prefix=s3_prefix,
        s3_bucket=s3_bucket,
    )
    _write_df(data.get("schedule"), os.path.join(silver, "schedule"), s3_prefix=s3_prefix, s3_bucket=s3_bucket)
    _write_df(data.get("game_ids"), os.path.join(silver, "game_ids"), s3_prefix=s3_prefix, s3_bucket=s3_bucket)
    _write_df(data.get("glossary"), os.path.join(silver, "glossary"), s3_prefix=s3_prefix, s3_bucket=s3_bucket)
    _write_df(data.get("draft"), os.path.join(silver, "draft"), s3_prefix=s3_prefix, s3_bucket=s3_bucket)
