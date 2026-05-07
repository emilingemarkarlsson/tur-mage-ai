import os
import sys

import duckdb
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "transformer" not in globals():
    from mage_ai.data_preparation.decorators import transformer

DB = "shl_analytics"


def _connect() -> duckdb.DuckDBPyConnection:
    token = os.environ.get("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        raise ValueError("[shl] MOTHERDUCK_TOKEN saknas")
    os.environ["motherduck_token"] = token
    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL motherduck")
    conn.execute("LOAD motherduck")
    conn.execute(f"ATTACH 'md:{DB}'")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS \"{DB}\".analytics")
    return conn


@transformer
def shl_fact_goalie_game(data, *args, **kwargs):
    """
    Steg 2/4 – Läser raw.goalies_per_game och skriver analytics.fact_goalie_game.
    Lägger till: save_pct (0-1), goals_against_avg.
    """
    conn = _connect()
    try:
        conn.execute(f"""
            CREATE OR REPLACE TABLE "{DB}".analytics.fact_goalie_game AS
            SELECT
                datum,
                game_uuid,
                season_name,
                game_type_name,
                round_number,
                spelare,
                lag,
                team_side,
                vann,
                inslappta_mal,
                skott_mot,
                raddningar,
                raddningsprocent,
                CAST(raddningsprocent AS DOUBLE) / 100.0 AS save_pct,
                CAST(inslappta_mal AS DOUBLE) AS goals_against_avg
            FROM "{DB}".raw.goalies_per_game
        """)
        count = conn.execute(
            f'SELECT COUNT(*) FROM "{DB}".analytics.fact_goalie_game'
        ).fetchone()[0]
        print(f"[shl] fact_goalie_game: {count} rader skrivna")
        return {"fact_goalie_game": count}
    except Exception as exc:
        print(f"[shl] ERROR fact_goalie_game: {exc}")
        raise
    finally:
        conn.close()
