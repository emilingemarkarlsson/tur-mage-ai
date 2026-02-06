import sys

from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.s3_utils import get_s3_bucket, get_s3_client, list_keys, read_json

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader


@data_loader
def load_seasonal_stats(*args, **kwargs):
    client = get_s3_client()
    bucket = get_s3_bucket()
    if not bucket:
        raise ValueError("S3 bucket is not configured (HETZNER_BUCKET or S3_BUCKET).")

    standings_keys = [
        k for k in list_keys(client, bucket, "nhl-data/basic/standings/")
        if k.endswith(".json")
    ]
    skater_keys = [
        k for k in list_keys(client, bucket, "nhl-data/stats/skaters/")
        if k.endswith(".json")
    ]
    goalie_keys = [
        k for k in list_keys(client, bucket, "nhl-data/stats/goalies/")
        if k.endswith(".json")
    ]
    team_keys = [
        k for k in list_keys(client, bucket, "nhl-data/stats/teams/")
        if k.endswith(".json")
    ]
    edge_skater_keys = [
        k for k in list_keys(client, bucket, "nhl-data/edge/skaters/")
        if k.endswith(".json")
    ]
    edge_goalie_keys = [
        k for k in list_keys(client, bucket, "nhl-data/edge/goalies/")
        if k.endswith(".json")
    ]
    edge_team_keys = [
        k for k in list_keys(client, bucket, "nhl-data/edge/teams/")
        if k.endswith(".json")
    ]

    def load_many(keys):
        items = []
        for key in keys:
            season = key.split("_")[-1].replace(".json", "")
            items.append({"season": season, "key": key, "payload": read_json(client, bucket, key)})
        return items

    return {
        "standings": load_many(standings_keys),
        "skaters": load_many(skater_keys),
        "goalies": load_many(goalie_keys),
        "teams": load_many(team_keys),
        "edge_skaters": load_many(edge_skater_keys),
        "edge_goalies": load_many(edge_goalie_keys),
        "edge_teams": load_many(edge_team_keys),
    }
