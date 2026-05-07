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
def shl_dim_standings(data, *args, **kwargs):
    """
    Steg 4/4 – Aggregerar analytics.fact_team_game → analytics.dim_standings.
    Kräver att shl_fact_team_game körts först (upstream-block).
    """
    conn = _connect()
    try:
        conn.execute(f"""
            CREATE OR REPLACE TABLE "{DB}".analytics.dim_standings AS
            SELECT
                season_name,
                game_type_name,
                lag,
                COUNT(DISTINCT game_uuid)                                   AS matcher,
                SUM(CASE WHEN CAST(vann AS INTEGER) = 1 THEN 1 ELSE 0 END) AS vinster,
                SUM(points)                                                 AS poang,
                SUM(CAST(egna_mal      AS INTEGER))                         AS gjorda_mal,
                SUM(CAST(inslappta_mal AS INTEGER))                         AS inslappta_mal,
                SUM(CAST(egna_mal      AS INTEGER))
                    - SUM(CAST(inslappta_mal AS INTEGER))                   AS malminus
            FROM "{DB}".analytics.fact_team_game
            GROUP BY season_name, game_type_name, lag
            ORDER BY season_name DESC, poang DESC
        """)
        count = conn.execute(
            f'SELECT COUNT(*) FROM "{DB}".analytics.dim_standings'
        ).fetchone()[0]
        print(f"[shl] dim_standings: {count} rader skrivna")
        return {"dim_standings": count}
    except Exception as exc:
        print(f"[shl] ERROR dim_standings: {exc}")
        raise
    finally:
        conn.close()
