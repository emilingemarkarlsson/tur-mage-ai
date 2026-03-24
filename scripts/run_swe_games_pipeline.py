"""
Standalone JSON games pipeline för Swehockey.
Kör utanför Mage runtime – ingen Docker krävs.

Krav:
  pip install boto3 polars pandas python-dotenv

Användning:
  python3 scripts/run_swe_games_pipeline.py --year 2026
  python3 scripts/run_swe_games_pipeline.py --year 2025
  python3 scripts/run_swe_games_pipeline.py --year 2025 --batch-size 14
  python3 scripts/run_swe_games_pipeline.py --sync-only
  python3 scripts/run_swe_games_pipeline.py --reset --year 2026
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import types
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Mage-mock (måste ligga före imports från mage_project)
# ---------------------------------------------------------------------------
_mage = types.ModuleType("mage_ai")
_mage.settings = types.ModuleType("mage_ai.settings")
_mage.settings.repo = types.ModuleType("mage_ai.settings.repo")
_mage.settings.repo.get_repo_path = lambda: str(
    Path(__file__).resolve().parent.parent / "mage_project"
)
_mage.data_preparation = types.ModuleType("mage_ai.data_preparation")
_mage.data_preparation.decorators = types.ModuleType("mage_ai.data_preparation.decorators")
_mage.data_preparation.decorators.transformer = lambda f: f
_mage.data_preparation.decorators.data_loader = lambda f: f
_mage.data_preparation.decorators.data_exporter = lambda f: f
for _k, _v in {
    "mage_ai": _mage,
    "mage_ai.settings": _mage.settings,
    "mage_ai.settings.repo": _mage.settings.repo,
    "mage_ai.data_preparation": _mage.data_preparation,
    "mage_ai.data_preparation.decorators": _mage.data_preparation.decorators,
}.items():
    sys.modules.setdefault(_k, _v)

_repo = Path(__file__).resolve().parent.parent / "mage_project"
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------
from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Pipeline-imports
# ---------------------------------------------------------------------------
import boto3

from utils.s3_utils import list_keys, read_json
from transformers.transform_swe_games import transform_swe_games
from data_exporters.export_swe_games_parquet import export_swe_games_parquet
from data_exporters.sync_swe_to_motherduck import _build_local_duckdb, _sync_to_motherduck

# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------

GAMES_PREFIX   = "raw/games/"
DETAILS_PREFIX = "raw/game_details/"


def _get_client():
    def _env(*keys):
        for k in keys:
            v = os.getenv(k, "").strip()
            if v:
                return v
        return ""
    endpoint   = _env("SWE_ENDPOINT", "MINIO_ENDPOINT")
    access_key = _env("SWE_ACCESS_KEY", "MINIO_ACCESS_KEY")
    secret_key = _env("SWE_SECRET_KEY", "MINIO_SECRET_KEY")
    region     = _env("SWE_REGION", "MINIO_REGION") or "eu-central"
    if endpoint and not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )


def _get_bucket() -> str:
    for k in ("SWE_BUCKET", "MINIO_BUCKET"):
        v = os.getenv(k, "").strip()
        if v:
            return v
    raise ValueError("SWE_BUCKET ej konfigurerad")


def _list_dates(client, bucket: str, year: Optional[str] = None) -> List[str]:
    dates = set()
    for key in list_keys(client, bucket, GAMES_PREFIX):
        name = key[len(GAMES_PREFIX):]
        if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", name):
            dates.add(name[:10])
    dates = sorted(dates)
    if year:
        dates = [d for d in dates if d.startswith(year)]
    return dates


def _load_metas_for_date(client, bucket: str, date: str) -> List[Dict]:
    key = f"{GAMES_PREFIX}{date}.json"
    try:
        payload = read_json(client, bucket, key)
        return [
            {"game_id": str(g["game_id"]), "league_id": str(g.get("league_id") or "")}
            for g in (payload.get("games") or []) if g.get("game_id")
        ]
    except Exception as exc:
        print(f"  [warn] {key}: {exc}")
        return []


def _load_detail(client, bucket: str, game_id: str) -> Optional[Dict]:
    key = f"{DETAILS_PREFIX}{game_id}.json"
    try:
        return read_json(client, bucket, key)
    except Exception as exc:
        print(f"  [warn] {key}: {exc}")
        return None


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _state_dir() -> Path:
    configured = os.getenv("DATA_LAKE_PATH", "")
    if configured and os.path.isdir(os.path.dirname(configured)):
        return Path(configured).parent / "state"
    return Path(__file__).resolve().parent.parent / "mage_project" / "state"


def _read_last_date(year: Optional[str]) -> Optional[str]:
    key = f"last_swe_date_{year}.txt" if year else "last_swe_date.txt"
    path = _state_dir() / key
    if path.exists():
        v = path.read_text(encoding="utf-8").strip()
        return v or None
    return None


def _write_last_date(date: str, year: Optional[str]):
    key = f"last_swe_date_{year}.txt" if year else "last_swe_date.txt"
    d = _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / key).write_text(date, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Swehockey JSON games pipeline")
    parser.add_argument("--year", type=str, default=None, help="Filtrera på år, t.ex. 2026")
    parser.add_argument("--batch-size", type=int, default=7, help="Antal datum per batch (default 7)")
    parser.add_argument("--reset", action="store_true", help="Ignorera state, ladda hela året om")
    parser.add_argument("--sync-only", action="store_true", help="Hoppa extraction, synka bara till MotherDuck")
    args = parser.parse_args()

    # Data lake-sökväg
    configured = os.getenv("DATA_LAKE_PATH", "")
    if configured and os.path.isdir(os.path.dirname(configured)):
        data_lake = configured
    else:
        data_lake = str(Path(__file__).resolve().parent.parent / "mage_project" / "data_lake")
        print(f"[run] DATA_LAKE_PATH ej satt – använder: {data_lake}")
    os.environ["DATA_LAKE_PATH"] = data_lake

    silver_swe = os.path.join(data_lake, "silver", "swe")
    gold_dir   = os.path.join(data_lake, "gold")
    os.makedirs(gold_dir, exist_ok=True)
    db_path    = os.path.join(gold_dir, "swe.duckdb")

    if args.sync_only:
        print("[run] STEP: Bygg lokal DuckDB + synka till MotherDuck")
        _build_local_duckdb(db_path, silver_swe)
        _sync_to_motherduck(db_path)
        return

    # --- Steg 1: Lista datum ---
    print(f"[run] STEP 1: Hämtar datum{' för ' + args.year if args.year else ''}...")
    client = _get_client()
    bucket = _get_bucket()

    all_dates = _list_dates(client, bucket, args.year)
    if not all_dates:
        print(f"[run] Inga datum hittades{' för ' + args.year if args.year else ''}.")
        return

    last_date = None if args.reset else _read_last_date(args.year)
    if last_date:
        pending = [d for d in all_dates if d > last_date]
        print(f"[run] State: senaste datum={last_date}. {len(pending)}/{len(all_dates)} datum kvar.")
    else:
        pending = all_dates
        print(f"[run] {len(pending)} datum att ladda ({all_dates[0]} → {all_dates[-1]}).")

    if not pending:
        print("[run] Inget nytt. Synkar till MotherDuck...")
        _build_local_duckdb(db_path, silver_swe)
        _sync_to_motherduck(db_path)
        return

    # --- Steg 2: Ladda + transformera batch-vis ---
    batch_size  = args.batch_size
    num_batches = (len(pending) + batch_size - 1) // batch_size
    processed   = 0
    t0          = time.time()

    for start in range(0, len(pending), batch_size):
        batch_dates = pending[start: start + batch_size]
        batch_num   = start // batch_size + 1

        games_batch = []
        for date in batch_dates:
            metas = _load_metas_for_date(client, bucket, date)
            for meta in metas:
                gid    = meta["game_id"]
                detail = _load_detail(client, bucket, gid)
                if not detail:
                    continue
                if not detail.get("league_id"):
                    detail["league_id"] = meta.get("league_id", "")
                games_batch.append({"game_date": date, "game_id": gid, "payload": detail})

        if games_batch:
            transformed = transform_swe_games({
                "games": games_batch,
                "last_date": max(batch_dates),
            })
            export_swe_games_parquet(transformed)

        processed += len(batch_dates)
        _write_last_date(max(batch_dates), args.year)

        elapsed  = time.time() - t0
        rate     = processed / elapsed if elapsed > 0 else 0
        remaining = len(pending) - processed
        eta_min  = (remaining / rate / 60) if rate > 0 else 0
        print(
            f"[run] Batch {batch_num}/{num_batches} klar "
            f"({batch_dates[0]}–{batch_dates[-1]}, {len(games_batch)} matcher). "
            f"{processed}/{len(pending)} datum, ETA ~{eta_min:.0f} min"
        )

    # --- Steg 3: Synka ---
    print("\n[run] STEP 3: Bygg lokal DuckDB + synka till MotherDuck")
    _build_local_duckdb(db_path, silver_swe)
    _sync_to_motherduck(db_path)
    print(f"[run] Klar! {processed} datum processade.")


if __name__ == "__main__":
    main()
