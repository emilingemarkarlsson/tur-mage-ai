"""
Skriv Swehockey PDF-tabeller till Silver parquet.

Tabeller:
  silver/swe/game_referees/       (partitioneras på game_date)
  silver/swe/game_period_stats/
  silver/swe/game_roster/
  silver/swe/game_player_stats/
  silver/swe/game_goalie_stats/
  silver/swe/game_on_ice/
"""
import os
from datetime import datetime

import pandas as pd
import polars as pl

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter


def _clean_partition_dir(part_dir: str):
    """Ta bort gamla parquet-filer i partition-mappen."""
    if not os.path.isdir(part_dir):
        return
    for name in os.listdir(part_dir):
        if name.endswith(".parquet"):
            try:
                os.remove(os.path.join(part_dir, name))
            except OSError:
                pass


def _write_df(df: pd.DataFrame, base_path: str, partition_col: str = "game_date"):
    """Skriv DataFrame till partitionerat parquet."""
    if df is None or df.empty:
        return

    os.makedirs(base_path, exist_ok=True)

    # Konvertera period till str för parquet-kompatibilitet
    pl_df = pl.from_pandas(df)

    if partition_col and partition_col in pl_df.columns:
        for value in pl_df[partition_col].unique().to_list():
            if value is None:
                part_dir = os.path.join(base_path, f"{partition_col}=unknown")
            else:
                part_dir = os.path.join(base_path, f"{partition_col}={value}")
            os.makedirs(part_dir, exist_ok=True)
            _clean_partition_dir(part_dir)
            ts = datetime.utcnow().timestamp()
            file_path = os.path.join(part_dir, f"part-{ts}.parquet")
            pl_df.filter(pl.col(partition_col) == value).write_parquet(file_path)
    else:
        ts = datetime.utcnow().timestamp()
        file_path = os.path.join(base_path, f"part-{ts}.parquet")
        pl_df.write_parquet(file_path)


@data_exporter
def export_swe_pdf_parquet(data: dict, *args, **kwargs):
    if data and data.get("batched"):
        return

    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    silver_swe = os.path.join(data_lake, "silver", "swe")

    tables = {
        "game_referees":        data.get("game_referees"),
        "game_period_stats":    data.get("game_period_stats"),
        "game_roster":          data.get("game_roster"),
        "game_player_stats":    data.get("game_player_stats"),
        "game_goalie_stats":    data.get("game_goalie_stats"),
        "game_on_ice":          data.get("game_on_ice"),
        "game_goals":           data.get("game_goals"),
        "game_penalties":       data.get("game_penalties"),
        "game_gk_changes":      data.get("game_gk_changes"),
        "game_starting_lineup": data.get("game_starting_lineup"),
    }

    total_rows = 0
    for table_name, df in tables.items():
        if df is not None and not df.empty:
            _write_df(df, os.path.join(silver_swe, table_name))
            total_rows += len(df)

    print(f"[swe pdf export] {total_rows} rader skrivna till {silver_swe}")
