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
def ha_fact_team_game(data, *args, **kwargs):
    """
    Steg 3/4 – Läser raw.teams_per_game och skriver analytics.fact_team_game.
    Lägger till: points (3/2/1/0 beroende på vinst + övertid/straffar).
    """
    conn = _connect()
    try:
        conn.execute(f"""
            CREATE OR REPLACE TABLE "{DB}".analytics.fact_team_game AS
            SELECT
                datum,
                game_uuid,
                season_name,
                game_type_name,
                round_number,
                lag,
                hemma_borta,
                motstandare,
                egna_mal,
                inslappta_mal,
                vann,
                overtime,
                shootout,
                skott,
                pp_mal,
                pim,
                hits,
                fo_procent,
                CASE
                    WHEN CAST(vann      AS INTEGER) = 1
                     AND CAST(overtime  AS INTEGER) = 0
                     AND CAST(shootout  AS INTEGER) = 0 THEN 3
                    WHEN CAST(vann      AS INTEGER) = 1 THEN 2
                    WHEN CAST(vann      AS INTEGER) = 0
                     AND (CAST(overtime AS INTEGER) = 1
                          OR CAST(shootout AS INTEGER) = 1) THEN 1
                    ELSE 0
                END AS points
            FROM "{DB}".raw.teams_per_game
        """)
        count = conn.execute(
            f'SELECT COUNT(*) FROM "{DB}".analytics.fact_team_game'
        ).fetchone()[0]
        print(f"[ha] fact_team_game: {count} rader skrivna")
        return {"fact_team_game": count}
    except Exception as exc:
        print(f"[ha] ERROR fact_team_game: {exc}")
        raise
    finally:
        conn.close()
