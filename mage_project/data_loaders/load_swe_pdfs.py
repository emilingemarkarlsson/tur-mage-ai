"""
Ladda PDF-rapporter för Swehockey-matcher från S3 (raw/reports/{game_id}/).
Stöder:
  - Official_Game_Report  → referees, period_stats, goals, on_ice
  - Official_Team_Roster  → player birthdates, captains, coaches
  - Player_Summary        → player + goalie stats (kompakt format)
  - Media_Game_Summary    → player + goalie stats (utökat format)
  - Official_Line_Up      → referees (backup)

State: raw/reports/ processar game_ids som INTE finns i Silver.
"""
import os
import re
import sys
from typing import Any, Dict, List, Optional

import boto3

from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.s3_utils import list_keys

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader


# --- S3-klient ---

def _get_swe_s3_client():
    def _env(*keys):
        for k in keys:
            v = os.getenv(k, "").strip()
            if v:
                return v
        return ""

    endpoint = _env("SWE_ENDPOINT", "MINIO_ENDPOINT")
    access_key = _env("SWE_ACCESS_KEY", "MINIO_ACCESS_KEY", "AWS_ACCESS_KEY_ID")
    secret_key = _env("SWE_SECRET_KEY", "MINIO_SECRET_KEY", "AWS_SECRET_ACCESS_KEY")
    region = _env("SWE_REGION", "MINIO_REGION", "AWS_REGION") or "eu-central"

    if endpoint and not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"

    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )


def _get_swe_bucket() -> str:
    for k in ("SWE_BUCKET", "MINIO_BUCKET"):
        v = os.getenv(k, "").strip()
        if v:
            return v
    raise ValueError("SWE_BUCKET ej konfigurerad.")


REPORTS_PREFIX = "raw/reports/"
PDF_TYPES = [
    "Official_Game_Report",
    "Official_Team_Roster",
    "Player_Summary",
    "Media_Game_Summary",
    "Official_Line_Up",
]


# --- State ---

def _state_dir() -> str:
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    return os.path.join(os.path.dirname(data_lake), "state")


def _read_processed_ids() -> set:
    path = os.path.join(_state_dir(), "swe_pdf_processed.txt")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _write_processed_ids(ids: set):
    d = _state_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "swe_pdf_processed.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(ids)))


# --- S3 helpers ---

def _list_game_ids_with_pdfs(client, bucket: str) -> List[str]:
    """Hämtar alla game_ids som har minst en PDF under raw/reports/."""
    paginator = client.get_paginator("list_objects_v2")
    game_ids = []
    for page in paginator.paginate(Bucket=bucket, Prefix=REPORTS_PREFIX, Delimiter="/"):
        for prefix in page.get("CommonPrefixes", []):
            gid = prefix["Prefix"].rstrip("/").split("/")[-1]
            if gid:
                game_ids.append(gid)
    return game_ids


def _get_game_date_from_details(client, bucket: str, game_id: str) -> str:
    """Försök hitta game_date från raw/game_details/{game_id}.json."""
    key = f"raw/game_details/{game_id}.json"
    try:
        import json
        data = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        payload = json.loads(data)
        return payload.get("game_date") or payload.get("date") or ""
    except Exception:
        return ""


def _list_pdfs_for_game(client, bucket: str, game_id: str) -> Dict[str, str]:
    """
    Returnerar {pdf_type: s3_key} för alla kända PDF-typer för game_id.
    """
    resp = client.list_objects_v2(Bucket=bucket, Prefix=f"{REPORTS_PREFIX}{game_id}/")
    result = {}
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        name = key.split("/")[-1]
        for pdf_type in PDF_TYPES:
            if pdf_type in name:
                result[pdf_type] = key
    return result


def _download_pdf(client, bucket: str, key: str) -> Optional[bytes]:
    try:
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as exc:
        print(f"[swe pdf loader] Kunde inte ladda {key}: {exc}")
        return None


def _get_runtime_year(kwargs: dict) -> Optional[str]:
    for key in ("swe_games_year", "games_year", "swe_pdf_year"):
        val = kwargs.get(key)
        if val and re.match(r"^(19|20)\d{2}$", str(val).strip()):
            return str(val).strip()
    return _valid_env_year()


def _valid_env_year() -> Optional[str]:
    v = os.getenv("SWE_GAMES_YEAR", "").strip()
    return v if re.match(r"^(19|20)\d{2}$", v) else None


def _process_batch(batch: List[Dict], *args, **kwargs):
    """Ladda, parsa och exportera en batch game_ids."""
    try:
        from transformers.transform_swe_pdfs import transform_swe_pdfs
        from data_exporters.export_swe_pdf_parquet import export_swe_pdf_parquet
    except ImportError:
        from mage_project.transformers.transform_swe_pdfs import transform_swe_pdfs
        from mage_project.data_exporters.export_swe_pdf_parquet import export_swe_pdf_parquet

    transformed = transform_swe_pdfs({"games": batch}, *args, **kwargs)
    export_swe_pdf_parquet(transformed, *args, **kwargs)


@data_loader
def load_swe_pdfs(*args, **kwargs):
    client = _get_swe_s3_client()
    bucket = _get_swe_bucket()

    # Alla game_ids med PDFs
    all_game_ids = _list_game_ids_with_pdfs(client, bucket)
    print(f"[swe pdf loader] {len(all_game_ids)} game_ids med PDFs i S3.")

    # Filtrera på år (om satt)
    runtime_year = _get_runtime_year(kwargs)
    if runtime_year:
        # Vi har inte direkt game_date för game_ids i raw/reports/ – hoppa over filtrering per år
        # om ej önskat, kör utan år-filter (laddar allt)
        print(f"[swe pdf loader] Notera: år-filtrering ({runtime_year}) stöds ej för PDF-pipeline.")

    # State: hoppa över redan processade
    processed = _read_processed_ids()
    new_ids = [gid for gid in all_game_ids if gid not in processed]
    print(f"[swe pdf loader] {len(new_ids)} game_ids att processa ({len(processed)} redan klara).")

    if not new_ids:
        print("[swe pdf loader] Inget nytt att processa.")
        return {"games": [], "batched": True}

    # Batch-storlek
    batch_size = 50
    try:
        batch_size = max(1, int(kwargs.get("swe_pdf_batch_size", 50)))
    except (TypeError, ValueError):
        pass

    num_batches = (len(new_ids) + batch_size - 1) // batch_size
    newly_processed = set()

    for start in range(0, len(new_ids), batch_size):
        batch_ids = new_ids[start: start + batch_size]
        batch_num = start // batch_size + 1

        games_batch = []
        for game_id in batch_ids:
            pdfs = _list_pdfs_for_game(client, bucket, game_id)
            if not pdfs:
                continue

            # Hämta game_date från game_details om möjligt
            game_date = _get_game_date_from_details(client, bucket, game_id)

            pdf_data = {}
            for pdf_type, key in pdfs.items():
                raw = _download_pdf(client, bucket, key)
                if raw:
                    pdf_data[pdf_type] = raw

            if pdf_data:
                games_batch.append({
                    "game_id": game_id,
                    "game_date": game_date,
                    "pdfs": pdf_data,
                })

        if games_batch:
            _process_batch(games_batch, *args, **kwargs)

        for gid in batch_ids:
            newly_processed.add(gid)

        all_processed = processed | newly_processed
        _write_processed_ids(all_processed)
        print(f"[swe pdf loader] Batch {batch_num}/{num_batches} klar: {len(batch_ids)} game_ids.")

    print(f"[swe pdf loader] Klar. {len(newly_processed)} game_ids processade.")
    return {"games": [], "batched": True}
