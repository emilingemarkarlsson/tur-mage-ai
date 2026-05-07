import os
import sys

import duckdb
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "transformer" not in globals():
    from mage_ai.data_preparation.decorators import transformer

DB = "ha_analytics"


def _connect() -> duckdb.DuckDBPyConnection:
    token = os.environ.get("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        raise ValueError("[ha] MOTHERDUCK_TOKEN saknas")
    os.environ["motherduck_token"] = token
    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL motherduck")
    conn.execute("LOAD motherduck")
    conn.execute(f"ATTACH 'md:{DB}'")
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{DB}".analytics')
    return conn


@transformer
def ha_fact_player_game(data, *args, **kwargs):
    """
    Steg 1/4 – Läser raw.players_per_game och skriver analytics.fact_player_game.
    Lägger till: toi_min, points_per_60, shots_per_60.
    """
    conn = _connect()
    try:
        conn.execute(f"""
            CREATE OR REPLACE TABLE "{DB}".analytics.fact_player_game AS
            SELECT
                datum,
                game_uuid,
                ssgt_uuid,
                season_name,
                game_type_name,
                round_number,
                spelare,
                first_name,
                last_name,
                lag,
                pos,
                vann,
                mal,
                assist,
                poang,
                pp_mal,
                pim,
                sog,
                plus_minus,
                toi_seconds,
                hits,
                fo_vinster,
                fo_forluster,
                fo_procent,
                CAST(toi_seconds AS DOUBLE) / 60.0 AS toi_min,
                CASE
                    WHEN CAST(toi_seconds AS DOUBLE) > 0
                    THEN (CAST(poang AS DOUBLE) / CAST(toi_seconds AS DOUBLE)) * 3600.0
                END AS points_per_60,
                CASE
                    WHEN CAST(toi_seconds AS DOUBLE) > 0
                    THEN (CAST(sog AS DOUBLE) / CAST(toi_seconds AS DOUBLE)) * 3600.0
                END AS shots_per_60
            FROM "{DB}".raw.players_per_game
        """)
        count = conn.execute(
            f'SELECT COUNT(*) FROM "{DB}".analytics.fact_player_game'
        ).fetchone()[0]
        print(f"[ha] fact_player_game: {count} rader skrivna")
        return {"fact_player_game": count}
    except Exception as exc:
        print(f"[ha] ERROR fact_player_game: {exc}")
        raise
    finally:
        conn.close()
