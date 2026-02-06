#!/usr/bin/env python3
"""
Listar innehållet i Hetzner S3-bucketen (samma credentials som Mage).
Kör från projektroten med .env laddad, t.ex.:
  docker exec tur-mage-ai-mage-1 bash -c "cd /home/src && python scripts/list_s3_bucket.py"
  eller lokalt: python scripts/list_s3_bucket.py (kräver boto3 + .env)
Utdata: alla "mappar" (prefix) och antal filer under nhl-data/ och nhl-data-reorganized/.
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

from utils.s3_utils import get_s3_bucket, get_s3_client, list_keys


def get_top_level_prefixes(client, bucket: str, prefix: str) -> dict:
    """Returnerar dict: 'prefix/subprefix' -> antal nycklar (filer)."""
    counts = defaultdict(int)
    for key in list_keys(client, bucket, prefix):
        rest = key[len(prefix):].lstrip("/")
        if not rest:
            continue
        parts = rest.split("/")
        if len(parts) >= 1:
            sub = parts[0]
            counts[f"{prefix.rstrip('/')}/{sub}"] += 1
    return dict(counts)


def get_subtree(client, bucket: str, prefix: str, max_depth: int = 3) -> dict:
    """Rekursivt antal filer per prefix, max_depth nivåer."""
    out = {}
    for key in list_keys(client, bucket, prefix):
        rest = key[len(prefix):].lstrip("/")
        if not rest:
            continue
        parts = rest.split("/")
        for d in range(1, min(max_depth + 1, len(parts) + 1)):
            sub_prefix = prefix + "/".join(parts[:d]) + "/"
            out[sub_prefix] = out.get(sub_prefix, 0) + 1
    return out


def main():
    client = get_s3_client()
    bucket = get_s3_bucket()
    if not bucket:
        print("ERROR: S3 bucket not configured (HETZNER_BUCKET or S3_BUCKET in .env)")
        sys.exit(1)
    print(f"Bucket: {bucket}\n")
    print("=== nhl-data/ (grunddata, statistik, edge) ===")
    try:
        top = get_top_level_prefixes(client, bucket, "nhl-data/")
        for p in sorted(top.keys()):
            print(f"  {p}  ->  {top[p]} filer")
        # Fördjupning för vanliga mappar
        for folder in ["basic", "stats", "edge", "misc"]:
            prefix = f"nhl-data/{folder}/"
            sub = get_top_level_prefixes(client, bucket, prefix)
            if sub:
                for s in sorted(sub.keys()):
                    print(f"    {s}  ->  {sub[s]} filer")
    except Exception as e:
        print(f"  ERROR: {e}")
    print("\n=== nhl-data-reorganized/ (matchdata) ===")
    try:
        top = get_top_level_prefixes(client, bucket, "nhl-data-reorganized/")
        for p in sorted(top.keys()):
            print(f"  {p}  ->  {top[p]} filer")
        sub = get_top_level_prefixes(client, bucket, "nhl-data-reorganized/games/")
        if sub:
            for s in sorted(sub.keys()):
                print(f"    {s}  ->  {sub[s]} filer")
    except Exception as e:
        print(f"  ERROR: {e}")
    print("\nKlar. Jämför med documentation/DATA_SOURCES_S3.md för vad pipelinen läser.")


if __name__ == "__main__":
    main()
