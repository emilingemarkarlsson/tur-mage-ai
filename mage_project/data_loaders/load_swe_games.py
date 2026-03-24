import json
import os
import re
import sys

import boto3

from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.s3_utils import list_keys, read_json

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader


# --- S3-klient för Swehockey (MinIO) ---
# Läser SWE_* i första hand, faller tillbaka på MINIO_* och S3_*.

def _get_swe_s3_client():
    def _env(*keys):
        for k in keys:
            v = os.getenv(k, "").strip()
            if v:
                return v
        return ""

    endpoint = _env("SWE_ENDPOINT", "MINIO_ENDPOINT", "S3_ENDPOINT")
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
    for k in ("SWE_BUCKET", "MINIO_BUCKET", "MINIO_BUCKET_NAME", "S3_BUCKET"):
        v = os.getenv(k, "").strip()
        if v:
            return v
    raise ValueError("Swehockey S3-bucket ej konfigurerad. Sätt SWE_BUCKET eller MINIO_BUCKET.")


# --- State ---

def _state_dir() -> str:
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    return os.path.join(os.path.dirname(data_lake), "state")


def _read_last_date() -> str | None:
    path = os.path.join(_state_dir(), "last_swe_date.txt")
    if os.path.exists(path):
        value = open(path, encoding="utf-8").read().strip()
        return value or None
    return None


def _write_last_date(value: str):
    d = _state_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "last_swe_date.txt"), "w", encoding="utf-8") as f:
        f.write(value)


# S3-prefix i Swehockey-bucketen
GAMES_PREFIX = "raw/games/"
DETAILS_PREFIX = "raw/game_details/"


def _valid_year(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s if re.match(r"^(19|20)\d{2}$", s) else None


def _get_runtime_year(kwargs: dict) -> str | None:
    for key in ("swe_games_year", "games_year"):
        val = kwargs.get(key)
        y = _valid_year(val)
        if y:
            return y
        for container in ("variables", "configuration"):
            c = kwargs.get(container)
            if isinstance(c, dict):
                y = _valid_year(c.get(key))
                if y:
                    return y
    return _valid_year(os.getenv("SWE_GAMES_YEAR"))


def _list_available_dates(client, bucket: str) -> list:
    """Hämtar alla datum (YYYY-MM-DD) från raw/games/YYYY-MM-DD.json."""
    dates = set()
    for key in list_keys(client, bucket, GAMES_PREFIX):
        name = key[len(GAMES_PREFIX):]
        if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", name):
            dates.add(name[:10])
    return sorted(dates)


def _load_game_ids_for_date(client, bucket: str, date: str) -> list:
    """Läser raw/games/YYYY-MM-DD.json och returnerar alla game_id:n."""
    key = f"{GAMES_PREFIX}{date}.json"
    try:
        payload = read_json(client, bucket, key)
        return [str(g["game_id"]) for g in (payload.get("games") or []) if g.get("game_id")]
    except Exception as exc:
        print(f"[swe loader] Kunde inte läsa datum-index {key}: {exc}")
        return []


def _load_game_detail(client, bucket: str, game_id: str) -> dict | None:
    """Läser raw/game_details/{game_id}.json."""
    key = f"{DETAILS_PREFIX}{game_id}.json"
    try:
        return read_json(client, bucket, key)
    except json.JSONDecodeError as exc:
        print(f"[swe loader] Ogiltig JSON: {key}: {exc}")
        return None
    except Exception as exc:
        print(f"[swe loader] Kunde inte läsa {key}: {exc}")
        return None


def _process_batch(batch_dates, client, bucket, kwargs, args):
    """Ladda, transformera och exportera en batch datum."""
    try:
        from transformers.transform_swe_games import transform_swe_games
        from data_exporters.export_swe_games_parquet import export_swe_games_parquet
    except ImportError:
        from mage_project.transformers.transform_swe_games import transform_swe_games
        from mage_project.data_exporters.export_swe_games_parquet import export_swe_games_parquet

    games_batch = []
    for date in batch_dates:
        game_ids = _load_game_ids_for_date(client, bucket, date)
        for gid in game_ids:
            detail = _load_game_detail(client, bucket, gid)
            if detail:
                games_batch.append({"game_date": date, "game_id": gid, "payload": detail})

    if not games_batch:
        print(f"[swe loader] Inga matchdetaljer hittades för {batch_dates[0]}–{batch_dates[-1]}.")
        return

    payload = {
        "games": games_batch,
        "last_date": max(batch_dates),
        "count": len(games_batch),
    }
    transformed = transform_swe_games(payload, *args, **kwargs)
    export_swe_games_parquet(transformed, *args, **kwargs)


@data_loader
def load_swe_games(*args, **kwargs):
    client = _get_swe_s3_client()
    bucket = _get_swe_bucket()

    available_dates = _list_available_dates(client, bucket)
    last_date = _read_last_date()
    games_year = _get_runtime_year(kwargs)

    trigger_name = kwargs.get("trigger_name")
    is_schedule_run = bool(trigger_name)

    if is_schedule_run and not games_year and not last_date:
        raise ValueError(
            "Schedule-run saknar swe_games_year och ingen state finns. "
            "Sätt runtime variable swe_games_year, eller kör manuellt."
        )

    # Filtrera på år
    if games_year:
        available_dates = [d for d in available_dates if d[:4] == games_year]
        if last_date and last_date[:4] == games_year:
            available_dates = [d for d in available_dates if d > last_date]
        elif last_date and last_date[:4] != games_year:
            print(f"[swe loader] State är från {last_date[:4]} – laddar hela år {games_year}.")
    else:
        if last_date:
            available_dates = [d for d in available_dates if d > last_date]

    if not available_dates:
        print(f"[swe loader] Inga nya datum att ladda (senaste state: {last_date or 'ingen'}).")
        return {"games": [], "last_date": last_date}

    # Batch-storlek (standard: 7 dagar – en vecka)
    _batch_raw = kwargs.get("swe_batch_size") or os.getenv("SWE_BATCH_SIZE")
    batch_size = 7
    if _batch_raw is not None:
        try:
            batch_size = max(1, int(_batch_raw))
        except (TypeError, ValueError):
            pass

    num_batches = (len(available_dates) + batch_size - 1) // batch_size
    print(
        f"[swe loader] {len(available_dates)} datum ({available_dates[0]}–{available_dates[-1]}), "
        f"{num_batches} batchar (max {batch_size} datum/batch)."
    )

    for start in range(0, len(available_dates), batch_size):
        batch_dates = available_dates[start: start + batch_size]
        batch_num = start // batch_size + 1
        _process_batch(batch_dates, client, bucket, kwargs, args)
        _write_last_date(max(batch_dates))
        print(f"[swe loader] Batch {batch_num}/{num_batches} klar: {batch_dates[0]}–{batch_dates[-1]}.")

    newest_date = max(available_dates)
    print(f"[swe loader] Klar. Nästa körning startar från > {newest_date}.")

    return {"games": [], "last_date": newest_date, "batched": True}
