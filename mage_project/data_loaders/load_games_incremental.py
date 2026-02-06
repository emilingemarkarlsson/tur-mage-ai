import json
import os
import sys
from datetime import datetime

from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.s3_utils import (
    get_s3_bucket,
    get_s3_client,
    list_keys,
    list_unique_dates_from_keys,
    read_json,
)

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader


STATE_PATH = "/home/src/mage_project/state/last_games_date.txt"
PREFIX = "nhl-data-reorganized/games/by_date/"


def _read_last_date():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
            return value or None
    return None


def _write_last_date(value: str):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        handle.write(value)


@data_loader
def load_games_incremental(*args, **kwargs):
    client = get_s3_client()
    bucket = get_s3_bucket()
    if not bucket:
        raise ValueError("S3 bucket is not configured (HETZNER_BUCKET or S3_BUCKET).")

    keys = list(list_keys(client, bucket, PREFIX))
    available_dates = list_unique_dates_from_keys(keys, PREFIX)

    last_date = _read_last_date()
    start_date = os.getenv("GAMES_START_DATE")
    if start_date:
        available_dates = [d for d in available_dates if d >= start_date]
    if last_date:
        available_dates = [d for d in available_dates if d > last_date]

    if not available_dates:
        return {"games": [], "game_players": [], "last_date": last_date}

    games = []
    errors = []
    for game_date in available_dates:
        date_prefix = f"{PREFIX}{game_date}/"
        for key in keys:
            if not key.startswith(date_prefix):
                continue
            if not key.endswith(".json") or key.endswith("games_summary.json"):
                continue
            try:
                payload = read_json(client, bucket, key)
            except json.JSONDecodeError as exc:
                errors.append({"key": key, "error": str(exc)})
                continue
            games.append({"game_date": game_date, "key": key, "payload": payload})

    newest_date = max(available_dates)
    _write_last_date(newest_date)

    if errors:
        print(f"Invalid JSON files skipped ({len(errors)}):")
        for item in errors:
            print(f"- {item['key']}: {item['error']}")

    return {
        "games": games,
        "last_date": newest_date,
        "last_date_previous": last_date,
        "count": len(games),
        "errors": errors,
    }
