import os
import sys

from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.s3_utils import get_s3_bucket, get_s3_client, list_keys, read_json

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader


@data_loader
def load_dimensions(*args, **kwargs):
    client = get_s3_client()
    bucket = get_s3_bucket()
    if not bucket:
        raise ValueError("S3 bucket is not configured (HETZNER_BUCKET or S3_BUCKET).")

    teams = read_json(client, bucket, "nhl-data/basic/teams/all_teams.json")
    players = read_json(client, bucket, "nhl-data/basic/players/all_players.json")
    players_by_team = read_json(client, bucket, "nhl-data/basic/players/players_by_team.json")

    countries_key = "nhl-data/misc/countries.json"
    try:
        countries = read_json(client, bucket, countries_key)
    except Exception:
        countries = {}

    roster_prefix = "nhl-data/basic/teams/rosters/"
    roster_keys = [k for k in list_keys(client, bucket, roster_prefix) if k.endswith(".json")]
    if not roster_keys:
        roster_keys = [
            k for k in list_keys(client, bucket, "nhl-data/basic/teams/")
            if "roster" in k.lower() and k.endswith(".json")
        ]
    rosters = []
    for key in roster_keys:
        parts = key.rstrip("/").split("/")
        season = parts[-2] if len(parts) >= 2 else "unknown"
        payload = read_json(client, bucket, key)
        rosters.append({"season": season, "payload": payload})

    # Schedule (daily_YYYY-MM-DD.json, weekly.json, etc.)
    schedule_keys = [k for k in list_keys(client, bucket, "nhl-data/basic/schedule/") if k.endswith(".json")]
    schedule_payloads = []
    for key in schedule_keys:
        try:
            schedule_payloads.append({"key": key, "payload": read_json(client, bucket, key)})
        except Exception:
            pass

    # Helpers (t.ex. game_ids_{season}.json)
    helpers_keys = [k for k in list_keys(client, bucket, "nhl-data/helpers/") if k.endswith(".json")]
    helpers_payloads = []
    for key in helpers_keys:
        try:
            helpers_payloads.append({"key": key, "payload": read_json(client, bucket, key)})
        except Exception:
            pass

    # Misc: glossary, draft
    glossary = None
    try:
        glossary = read_json(client, bucket, "nhl-data/misc/glossary.json")
    except Exception:
        pass
    draft = None
    try:
        draft = read_json(client, bucket, "nhl-data/misc/draft_year_and_rounds.json")
    except Exception:
        pass

    return {
        "teams": teams,
        "players": players,
        "players_by_team": players_by_team,
        "countries": countries,
        "rosters": rosters,
        "roster_keys": roster_keys,
        "bucket": bucket,
        "schedule_payloads": schedule_payloads,
        "helpers_payloads": helpers_payloads,
        "glossary": glossary,
        "draft": draft,
    }
