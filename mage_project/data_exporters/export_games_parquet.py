import os
import sys
from datetime import datetime

import pandas as pd
import polars as pl
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.s3_utils import get_s3_bucket, get_s3_client, list_keys, upload_file

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter

# Fast schema för game_players så att alla Parquet-filer får samma kolumner (undviker schema mismatch i DuckDB).
GAME_PLAYERS_COLUMNS = [
    "game_id", "game_date", "player_id", "team_abbr", "is_home", "position", "sweater_number",
    "goals", "assists", "points", "plus_minus", "shots", "pim", "toi_seconds", "hits",
    "power_play_goals", "short_handed_goals", "blocked_shots", "shifts", "giveaways", "takeaways",
    "faceoff_win_pct",
    "saves", "shots_against", "save_pct", "goals_against", "even_strength_goals_against",
    "power_play_goals_against", "shorthanded_goals_against",
    "even_strength_shots_against", "power_play_shots_against", "shorthanded_shots_against",
    "gaa",
]


def _clean_partition_dir(part_dir: str):
    """Ta bort befintliga parquet-filer i partition-mappen så att omkörning inte ger dubletter."""
    if not os.path.isdir(part_dir):
        return
    for name in os.listdir(part_dir):
        if name.endswith(".parquet"):
            try:
                os.remove(os.path.join(part_dir, name))
            except OSError:
                pass


def _delete_s3_prefix(client, bucket: str, key_prefix: str):
    """Ta bort alla objekt under prefix (så att ny export inte ackumulerar gamla filer)."""
    for key in list_keys(client, bucket, key_prefix):
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            pass


def _write_df(df, base_path: str, partition_col: str = None, s3_prefix: str = None, s3_bucket: str = None, columns: list = None):
    if df is None or df.empty:
        return
    if columns is not None and hasattr(df, "columns"):
        df = pd.DataFrame(df).reindex(columns=columns)
    os.makedirs(base_path, exist_ok=True)
    pl_df = pl.from_pandas(df)
    s3_client = get_s3_client() if s3_prefix and s3_bucket else None
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    if partition_col and partition_col in pl_df.columns:
        for value in pl_df[partition_col].unique().to_list():
            part_dir = os.path.join(base_path, f"{partition_col}={value}")
            os.makedirs(part_dir, exist_ok=True)
            _clean_partition_dir(part_dir)
            if s3_client:
                rel_prefix = os.path.relpath(part_dir, data_lake).replace("\\", "/")
                key_prefix = f"{s3_prefix}/{rel_prefix}/"
                _delete_s3_prefix(s3_client, s3_bucket, key_prefix)
            file_path = os.path.join(part_dir, f"part-{datetime.utcnow().timestamp()}.parquet")
            part_df = pl_df.filter(pl.col(partition_col) == value)
            part_df.write_parquet(file_path)
            if s3_client:
                rel_path = os.path.relpath(file_path, data_lake)
                key = f"{s3_prefix}/{rel_path}".replace("\\", "/")
                upload_file(s3_client, s3_bucket, key, file_path)
    else:
        file_path = os.path.join(base_path, f"part-{datetime.utcnow().timestamp()}.parquet")
        pl_df.write_parquet(file_path)
        if s3_client:
            rel_path = os.path.relpath(file_path, data_lake).replace("\\", "/")
            key = f"{s3_prefix}/{rel_path}"
            upload_file(s3_client, s3_bucket, key, file_path)


# #region agent log
def _debug_log(msg: str, data: dict, hypothesis_id: str = "C"):
    try:
        import json
        from mage_ai.settings.repo import get_repo_path
        rp = get_repo_path()
        p = os.getenv("DEBUG_LOG_PATH") or os.path.normpath(os.path.join(rp, "..", ".cursor", "debug.log"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"hypothesisId": hypothesis_id, "location": "export_games_parquet", "message": msg, "data": data, "timestamp": __import__("time").time() * 1000}) + "\n")
    except Exception:
        pass
# #endregion

# State för games incremental – samma sökväg som i load_games_incremental (skrivs här efter lyckad export så Mage-retry inte ger tom data).
_data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
GAMES_STATE_PATH = os.path.join(os.path.dirname(_data_lake), "state", "last_games_date.txt")
def _write_games_state(newest_date: str):
    if not newest_date:
        return
    state_dir = os.path.dirname(GAMES_STATE_PATH)
    os.makedirs(state_dir, exist_ok=True)
    with open(GAMES_STATE_PATH, "w", encoding="utf-8") as f:
        f.write(newest_date)


@data_exporter
def export_games_parquet(data, *args, **kwargs):
    # Automatisk batch-körning: loadern har redan skrivit alla batchar; skippa så vi inte skriver tom data.
    if data and data.get("batched"):
        return
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    silver = os.path.join(data_lake, "silver")
    sink = os.getenv("DATA_LAKE_SINK", "local").lower()
    s3_prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics") if sink == "s3" else None
    s3_bucket = os.getenv("S3_DATA_LAKE_BUCKET") or get_s3_bucket() if sink == "s3" else None

    games_df = data.get("games") if data else None
    players_df = data.get("game_players") if data else None
    game_events_df = data.get("game_events") if data else None
    game_stories_df = data.get("game_stories") if data else None
    games_empty = games_df is None or (hasattr(games_df, "empty") and games_df.empty)
    players_empty = players_df is None or (hasattr(players_df, "empty") and players_df.empty)
    _debug_log("Export entry", {
        "silver_base": silver, "games_empty": games_empty, "players_empty": players_empty,
        "events_empty": game_events_df is None or (hasattr(game_events_df, "empty") and game_events_df.empty),
        "stories_empty": game_stories_df is None or (hasattr(game_stories_df, "empty") and game_stories_df.empty),
    }, "C")

    _write_df(
        games_df,
        os.path.join(silver, "games"),
        partition_col="game_date",
        s3_prefix=s3_prefix,
        s3_bucket=s3_bucket,
    )
    _write_df(
        players_df,
        os.path.join(silver, "game_players"),
        partition_col="game_date",
        s3_prefix=s3_prefix,
        s3_bucket=s3_bucket,
        columns=GAME_PLAYERS_COLUMNS,
    )
    # playByPlay → game_events, gameStory → game_stories (valfritt, filer utan dessa ger tom export)
    _write_df(
        game_events_df,
        os.path.join(silver, "game_events"),
        partition_col="game_date",
        s3_prefix=s3_prefix,
        s3_bucket=s3_bucket,
    )
    _write_df(
        game_stories_df,
        os.path.join(silver, "game_stories"),
        partition_col="game_date",
        s3_prefix=s3_prefix,
        s3_bucket=s3_bucket,
    )
    # Uppdatera state först när export lyckats – så vid Mage-retry (t.ex. loader timeout) används inte redan sparad state och nästa körning får inte tom data.
    newest_date = (data or {}).get("newest_date")
    if newest_date:
        _write_games_state(str(newest_date).strip())
    _debug_log("Export after write", {"silver_games_exists": os.path.exists(os.path.join(silver, "games")), "silver_game_players_exists": os.path.exists(os.path.join(silver, "game_players"))}, "C")