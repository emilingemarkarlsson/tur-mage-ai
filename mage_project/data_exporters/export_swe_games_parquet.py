import os
import sys
from datetime import datetime

import pandas as pd
import polars as pl
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter


def _state_dir() -> str:
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    return os.path.join(os.path.dirname(data_lake), "state")


def _write_last_date(value: str):
    if not value:
        return
    d = _state_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "last_swe_date.txt"), "w", encoding="utf-8") as f:
        f.write(value)


def _clean_partition_dir(part_dir: str):
    """Ta bort gamla parquet-filer i partition-mappen (undviker dubletter vid omkörning)."""
    if not os.path.isdir(part_dir):
        return
    for name in os.listdir(part_dir):
        if name.endswith(".parquet"):
            try:
                os.remove(os.path.join(part_dir, name))
            except OSError:
                pass


def _write_df(df: pd.DataFrame, base_path: str, partition_col: str = "game_date"):
    if df is None or df.empty:
        return

    os.makedirs(base_path, exist_ok=True)
    pl_df = pl.from_pandas(df)

    if partition_col and partition_col in pl_df.columns:
        for value in pl_df[partition_col].unique().to_list():
            part_dir = os.path.join(base_path, f"{partition_col}={value}")
            os.makedirs(part_dir, exist_ok=True)
            _clean_partition_dir(part_dir)
            file_path = os.path.join(part_dir, f"part-{datetime.utcnow().timestamp()}.parquet")
            pl_df.filter(pl.col(partition_col) == value).write_parquet(file_path)
    else:
        file_path = os.path.join(base_path, f"part-{datetime.utcnow().timestamp()}.parquet")
        pl_df.write_parquet(file_path)


@data_exporter
def export_swe_games_parquet(data, *args, **kwargs):
    if data and data.get("batched"):
        return

    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    silver_swe = os.path.join(data_lake, "silver", "swe")

    tables = {
        "games":                 (data or {}).get("games"),
        "game_events":           (data or {}).get("game_events"),
        "game_goalkeepers":      (data or {}).get("game_goalkeepers"),
        "game_lineups":          (data or {}).get("game_lineups"),
        "game_period_scores":    (data or {}).get("game_period_scores"),
        "game_referees_json":    (data or {}).get("game_referees_json"),
        "game_on_ice_json":      (data or {}).get("game_on_ice_json"),
        "game_player_stats_json": (data or {}).get("game_player_stats_json"),
    }

    for table_name, df in tables.items():
        _write_df(df, os.path.join(silver_swe, table_name))

    games_df = tables["games"]
    games_count = len(games_df) if games_df is not None and not games_df.empty else 0
    print(f"[swe export] Silver skrivet: {games_count} matcher → {silver_swe}")

    newest_date = (data or {}).get("newest_date")
    if newest_date:
        _write_last_date(str(newest_date).strip())
