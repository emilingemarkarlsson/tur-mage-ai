"""
Laddar upp nor-parquet-filer (EHL norsk hockey) till Hetzner S3.
Engångsscript för initial data-migrering.

Kör:
  python3 scripts/upload_nor_to_s3.py
  python3 scripts/upload_nor_to_s3.py --source-dir /custom/path/to/parquet
  python3 scripts/upload_nor_to_s3.py --dry-run

Kräver: HETZNER_ACCESS_KEY, HETZNER_SECRET_KEY, HETZNER_ENDPOINT i .env
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_env():
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

BUCKET = os.environ.get("HETZNER_BUCKET", "nhlhockey-data")
S3_PREFIX = "nor-data/parquet"
DEFAULT_SOURCE = Path.home() / "Desktop/tur-scrape-no/parquet"


def _s3_client():
    import boto3

    endpoint = os.environ.get("HETZNER_ENDPOINT", "").strip()
    if endpoint and not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=os.environ.get("HETZNER_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("HETZNER_SECRET_KEY", ""),
        region_name=os.environ.get("HETZNER_REGION", "eu-central"),
    )


def upload(source_dir: str, dry_run: bool = False):
    source = Path(source_dir)
    if not source.exists():
        print(f"[nor-upload] FEL: Katalog saknas: {source}")
        sys.exit(1)

    parquet_files = sorted(source.glob("*.parquet"))
    if not parquet_files:
        print(f"[nor-upload] Inga parquet-filer i {source}")
        sys.exit(1)

    total_mb = sum(f.stat().st_size for f in parquet_files) / 1024 / 1024
    print(f"[nor-upload] {len(parquet_files)} filer ({total_mb:.1f} MB) → s3://{BUCKET}/{S3_PREFIX}/")

    if dry_run:
        for f in parquet_files:
            print(f"  [dry-run] {f.name} ({f.stat().st_size/1024/1024:.1f} MB)")
        return

    s3 = _s3_client()
    t0 = time.time()

    for f in parquet_files:
        key = f"{S3_PREFIX}/{f.name}"
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"[nor-upload] Laddar upp {f.name} ({size_mb:.1f} MB)...", end=" ", flush=True)
        t1 = time.time()
        s3.upload_file(str(f), BUCKET, key)
        print(f"✓ ({time.time()-t1:.1f}s)")

    print(f"\n[nor-upload] Klar! {len(parquet_files)} filer på {time.time()-t0:.1f}s")
    print(f"[nor-upload] S3-sökväg: s3://{BUCKET}/{S3_PREFIX}/")


def main():
    parser = argparse.ArgumentParser(description="Ladda upp NOR-parquet till Hetzner S3")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE))
    parser.add_argument("--dry-run", action="store_true", help="Visa filer utan att ladda upp")
    args = parser.parse_args()
    upload(args.source_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
