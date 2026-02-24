import json
import os
from typing import Iterable, List, Optional

import boto3


def _normalize_endpoint(endpoint: Optional[str]) -> Optional[str]:
    if not endpoint:
        return None
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    return f"https://{endpoint}"


def _get_source() -> str:
    return (os.getenv("S3_SOURCE") or "hetzner").strip().lower()


def get_s3_bucket() -> str:
    source = _get_source()
    if source == "minio":
        return os.getenv("MINIO_BUCKET") or os.getenv("S3_BUCKET") or ""
    if source == "hetzner":
        return os.getenv("HETZNER_BUCKET") or os.getenv("S3_BUCKET") or ""
    return os.getenv("S3_BUCKET") or os.getenv("AWS_BUCKET") or ""


def get_s3_client():
    source = _get_source()
    if source == "minio":
        endpoint = os.getenv("MINIO_ENDPOINT") or os.getenv("S3_ENDPOINT") or os.getenv("AWS_ENDPOINT")
        access_key = os.getenv("MINIO_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("MINIO_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
        region = os.getenv("MINIO_REGION") or os.getenv("AWS_REGION", "eu-central")
    elif source == "hetzner":
        endpoint = os.getenv("HETZNER_ENDPOINT") or os.getenv("S3_ENDPOINT") or os.getenv("AWS_ENDPOINT")
        access_key = os.getenv("HETZNER_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("HETZNER_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
        region = os.getenv("HETZNER_REGION") or os.getenv("AWS_REGION", "eu-central")
    else:
        endpoint = os.getenv("S3_ENDPOINT") or os.getenv("AWS_ENDPOINT")
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        region = os.getenv("AWS_REGION", "eu-central")
    endpoint_url = _normalize_endpoint(endpoint)
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )


def list_keys(client, bucket: str, prefix: str) -> Iterable[str]:
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if key:
                yield key


def read_json(client, bucket: str, key: str):
    response = client.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read())


def upload_file(client, bucket: str, key: str, local_path: str):
    client.upload_file(local_path, bucket, key)


def list_unique_dates_from_keys(keys: Iterable[str], prefix: str) -> List[str]:
    dates = set()
    for key in keys:
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix):]
        parts = rest.split("/", 1)
        if parts and len(parts[0]) == 10:
            dates.add(parts[0])
    return sorted(dates)


def get_duckdb_s3_secret_sql(scope_bucket: str = "") -> str:
    """Return CREATE SECRET SQL for DuckDB httpfs (Hetzner/MinIO). Used by refresh_duckdb_views and Streamlit."""
    source = _get_source()
    if source == "minio":
        endpoint = os.getenv("MINIO_ENDPOINT") or ""
        access = os.getenv("MINIO_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or ""
        secret = os.getenv("MINIO_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or ""
        region = os.getenv("MINIO_REGION") or os.getenv("AWS_REGION", "us-east-1")
    else:
        endpoint = os.getenv("HETZNER_ENDPOINT") or os.getenv("S3_ENDPOINT") or ""
        access = os.getenv("HETZNER_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or ""
        secret = os.getenv("HETZNER_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or ""
        region = os.getenv("HETZNER_REGION") or os.getenv("AWS_REGION", "eu-central")
    endpoint_host = (endpoint or "").strip().replace("https://", "").replace("http://", "").rstrip("/")
    def esc(s):
        return (s or "").replace("'", "''")
    parts = [
        "CREATE OR REPLACE SECRET s3_nhl (TYPE S3, PROVIDER config, ",
        f"KEY_ID '{esc(access)}', SECRET '{esc(secret)}', REGION '{esc(region)}', ",
        f"ENDPOINT '{esc(endpoint_host)}', URL_STYLE 'path'",
    ]
    if scope_bucket:
        scope_val = f"s3://{scope_bucket.rstrip('/')}/"
        parts.append(f", SCOPE '{esc(scope_val)}'")
    parts.append(");")
    return "".join(parts)
