"""
Standalone PDF extraction pipeline för Swehockey.
Kör utanför Mage runtime – ingen Docker krävs.

Krav:
  pip install boto3 pdfplumber polars pandas

Användning:
  python3 scripts/run_swe_pdf_pipeline.py
  python3 scripts/run_swe_pdf_pipeline.py --batch-size 100
  python3 scripts/run_swe_pdf_pipeline.py --reset    # rensa state, börja om
  python3 scripts/run_swe_pdf_pipeline.py --sync-only # hoppa PDF-extraction, synka bara till MotherDuck
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Minimal mock av Mage-dekoratorer
# ---------------------------------------------------------------------------
import types

_mage_mocks = types.ModuleType("mage_ai")
_mage_mocks.settings = types.ModuleType("mage_ai.settings")
_mage_mocks.settings.repo = types.ModuleType("mage_ai.settings.repo")
_mage_mocks.settings.repo.get_repo_path = lambda: str(
    Path(__file__).resolve().parent.parent / "mage_project"
)
_mage_mocks.data_preparation = types.ModuleType("mage_ai.data_preparation")
_mage_mocks.data_preparation.decorators = types.ModuleType("mage_ai.data_preparation.decorators")
_mage_mocks.data_preparation.decorators.transformer = lambda f: f
_mage_mocks.data_preparation.decorators.data_loader = lambda f: f
_mage_mocks.data_preparation.decorators.data_exporter = lambda f: f
sys.modules.setdefault("mage_ai", _mage_mocks)
sys.modules.setdefault("mage_ai.settings", _mage_mocks.settings)
sys.modules.setdefault("mage_ai.settings.repo", _mage_mocks.settings.repo)
sys.modules.setdefault("mage_ai.data_preparation", _mage_mocks.data_preparation)
sys.modules.setdefault("mage_ai.data_preparation.decorators", _mage_mocks.data_preparation.decorators)

# Lägg till mage_project i sys.path
_repo = Path(__file__).resolve().parent.parent / "mage_project"
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

# ---------------------------------------------------------------------------
# Miljövariabler
# ---------------------------------------------------------------------------
from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import boto3

try:
    import pdfplumber
except ImportError:
    print("pdfplumber saknas. Installera: pip install pdfplumber")
    sys.exit(1)

try:
    import polars as pl
    import pandas as pd
except ImportError:
    print("polars/pandas saknas. Installera: pip install polars pandas")
    sys.exit(1)

from utils.swe_pdf_parser import parse_pdf
from transformers.transform_swe_pdfs import transform_swe_pdfs
from data_exporters.export_swe_pdf_parquet import export_swe_pdf_parquet
from data_exporters.sync_swe_to_motherduck import _build_local_duckdb, _sync_to_motherduck

# ---------------------------------------------------------------------------
# Konstanter
# ---------------------------------------------------------------------------

REPORTS_PREFIX = "raw/reports/"
PDF_TYPES = [
    "Official_Game_Report",
    "Official_Team_Roster",
    "Player_Summary",
    "Media_Game_Summary",
    "Official_Line_Up",
]


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------

def _get_swe_client():
    def _env(*keys):
        for k in keys:
            v = os.getenv(k, "").strip()
            if v:
                return v
        return ""

    endpoint = _env("SWE_ENDPOINT", "MINIO_ENDPOINT")
    access_key = _env("SWE_ACCESS_KEY", "MINIO_ACCESS_KEY")
    secret_key = _env("SWE_SECRET_KEY", "MINIO_SECRET_KEY")
    region = _env("SWE_REGION", "MINIO_REGION") or "eu-central"
    if endpoint and not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )


def _get_bucket():
    for k in ("SWE_BUCKET", "MINIO_BUCKET"):
        v = os.getenv(k, "").strip()
        if v:
            return v
    raise ValueError("SWE_BUCKET ej konfigurerad")


def _list_game_ids(client, bucket: str) -> List[str]:
    paginator = client.get_paginator("list_objects_v2")
    game_ids = []
    for page in paginator.paginate(Bucket=bucket, Prefix=REPORTS_PREFIX, Delimiter="/"):
        for prefix in page.get("CommonPrefixes", []):
            gid = prefix["Prefix"].rstrip("/").split("/")[-1]
            if gid:
                game_ids.append(gid)
    return game_ids


def _list_pdfs(client, bucket: str, game_id: str) -> Dict[str, str]:
    resp = client.list_objects_v2(Bucket=bucket, Prefix=f"{REPORTS_PREFIX}{game_id}/")
    result = {}
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        name = key.split("/")[-1]
        for pdf_type in PDF_TYPES:
            if pdf_type in name:
                result[pdf_type] = key
    return result


def _get_game_date(client, bucket: str, game_id: str) -> str:
    key = f"raw/game_details/{game_id}.json"
    try:
        data = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        payload = json.loads(data)
        return payload.get("game_date") or payload.get("date") or ""
    except Exception:
        return ""


def _download(client, bucket: str, key: str) -> Optional[bytes]:
    try:
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as exc:
        print(f"  [warn] Kunde inte ladda {key}: {exc}")
        return None


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _state_dir() -> Path:
    configured = os.getenv("DATA_LAKE_PATH", "")
    if configured and os.path.isdir(os.path.dirname(configured)):
        return Path(configured).parent / "state"
    return Path(__file__).resolve().parent.parent / "mage_project" / "state"


def _read_processed() -> set:
    path = _state_dir() / "swe_pdf_processed.txt"
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _write_processed(ids: set):
    d = _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "swe_pdf_processed.txt").write_text("\n".join(sorted(ids)), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Swehockey PDF extraction pipeline")
    parser.add_argument("--batch-size", type=int, default=50, help="Game-IDs per batch")
    parser.add_argument("--reset", action="store_true", help="Rensa state, börja om")
    parser.add_argument("--sync-only", action="store_true", help="Hoppa PDF-extraction, synka bara")
    parser.add_argument("--limit", type=int, default=None, help="Max antal game_ids att processa")
    args = parser.parse_args()

    # Lokalt fallback: använd sökväg relativt skriptet om Docker-path ej nåbar
    _configured_path = os.getenv("DATA_LAKE_PATH", "")
    if _configured_path and os.path.isdir(os.path.dirname(_configured_path)):
        data_lake = _configured_path
    else:
        # Lokal körning utanför Docker
        data_lake = str(Path(__file__).resolve().parent.parent / "mage_project" / "data_lake")
        print(f"[run] DATA_LAKE_PATH ej tillgänglig, använder lokal sökväg: {data_lake}")
    # Exporters/loaders läser DATA_LAKE_PATH från env – sätt det nu
    os.environ["DATA_LAKE_PATH"] = data_lake

    silver_swe = os.path.join(data_lake, "silver", "swe")
    gold_dir = os.path.join(data_lake, "gold")
    os.makedirs(gold_dir, exist_ok=True)
    db_path = os.path.join(gold_dir, "swe.duckdb")

    if args.reset:
        state_path = _state_dir() / "swe_pdf_processed.txt"
        if state_path.exists():
            state_path.unlink()
        print("[run] State rensad.")

    if args.sync_only:
        print("[run] STEP: Bygg lokal DuckDB + synka till MotherDuck")
        _build_local_duckdb(db_path, silver_swe)
        _sync_to_motherduck(db_path)
        return

    # --- STEP 1: Lista game_ids med PDFs ---
    print("[run] STEP 1: Ansluter till S3 och listar game_ids...")
    client = _get_swe_client()
    bucket = _get_bucket()
    all_game_ids = _list_game_ids(client, bucket)
    print(f"[run] {len(all_game_ids)} game_ids med PDFs i S3.")

    processed = _read_processed()
    new_ids = [gid for gid in all_game_ids if gid not in processed]
    if args.limit:
        new_ids = new_ids[:args.limit]
    print(f"[run] {len(new_ids)} game_ids att processa ({len(processed)} redan klara).")

    if not new_ids:
        print("[run] Inget nytt att processa. Synkar till MotherDuck...")
        _build_local_duckdb(db_path, silver_swe)
        _sync_to_motherduck(db_path)
        return

    # --- STEP 2: Hämta + parsa PDFs batch-vis ---
    batch_size = args.batch_size
    num_batches = (len(new_ids) + batch_size - 1) // batch_size
    newly_processed = set()
    t0 = time.time()

    for batch_start in range(0, len(new_ids), batch_size):
        batch_ids = new_ids[batch_start: batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        print(f"\n[run] STEP 2 – Batch {batch_num}/{num_batches} ({len(batch_ids)} game_ids)")

        games_batch = []
        for game_id in batch_ids:
            pdfs_map = _list_pdfs(client, bucket, game_id)
            if not pdfs_map:
                continue
            game_date = _get_game_date(client, bucket, game_id)
            pdf_data = {}
            for pdf_type, key in pdfs_map.items():
                raw = _download(client, bucket, key)
                if raw:
                    pdf_data[pdf_type] = raw

            if pdf_data:
                games_batch.append({
                    "game_id": game_id,
                    "game_date": game_date,
                    "pdfs": pdf_data,
                })

        if games_batch:
            transformed = transform_swe_pdfs({"games": games_batch})
            export_swe_pdf_parquet(transformed)

        for gid in batch_ids:
            newly_processed.add(gid)
        _write_processed(processed | newly_processed)

        elapsed = time.time() - t0
        rate = len(newly_processed) / elapsed if elapsed > 0 else 0
        remaining = len(new_ids) - len(newly_processed)
        eta_s = remaining / rate if rate > 0 else 0
        print(f"[run] Batch {batch_num} klar. {len(newly_processed)}/{len(new_ids)} "
              f"processade ({rate:.1f}/s, ETA ~{eta_s/60:.1f} min)")

    # --- STEP 3: Bygg lokal DuckDB + synka ---
    print("\n[run] STEP 3: Bygg lokal DuckDB + synka till MotherDuck")
    _build_local_duckdb(db_path, silver_swe)
    _sync_to_motherduck(db_path)
    print(f"\n[run] Klar! {len(newly_processed)} game_ids processade.")


if __name__ == "__main__":
    main()
