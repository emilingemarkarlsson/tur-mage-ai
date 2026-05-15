"""
Norwegian EHL hockey pipeline.

Steg:
  0. (initialt) Ladda upp befintlig parquet-data till Hetzner S3
  1. Skrapa nya matcher från API → lokala parquet-filer
  2. Ladda upp nya parquet-filer till S3
  3. Upserta S3-parquet → MotherDuck `nor`-databas

Kräver:
  MOTHERDUCK_TOKEN
  HETZNER_ACCESS_KEY, HETZNER_SECRET_KEY, HETZNER_ENDPOINT
  NOR_API_BASE_URL  (för skrapning, krävs ej med --load-only)
  NOR_API_KEY       (valfritt)

Kör:
  python3 scripts/run_nor_pipeline.py                # full pipeline (scrape + load)
  python3 scripts/run_nor_pipeline.py --load-only    # bara S3 → MotherDuck
  python3 scripts/run_nor_pipeline.py --scrape-only  # bara skrapning (utan MD-load)
  python3 scripts/run_nor_pipeline.py --force        # kör även om inga nya matcher
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

BUCKET = "nhlhockey-data"
S3_PREFIX = "nor-data/parquet"
NOR_DB = "nor"

# Parquet-tabeller och deras primärnycklar för upsert (DELETE+INSERT per match_id)
MATCH_TABLES = [
    "matches",
    "goal_events",
    "penalty_events",
    "match_lineup",
    "match_period_stats",
    "match_powerplay_stats",
    "shifts",
    "momentum",
]
# Dessa byts ut helt vid varje körning (liten storlek)
REPLACE_TABLES = ["players", "skater_summaries", "tournaments"]


def _load_env():
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env()


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------

def _s3_client():
    import boto3

    endpoint = os.environ.get("HETZNER_ENDPOINT", "").strip()
    if endpoint and not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=os.environ.get("HETZNER_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("HETZNER_SECRET_KEY", ""),
        region_name=os.environ.get("HETZNER_REGION", "eu-central"),
    )


def _upload_df(s3, df, table_name: str):
    import pandas as pd

    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    key = f"{S3_PREFIX}/{table_name}.parquet"
    s3.upload_fileobj(buf, BUCKET, key)
    print(f"[nor] S3: {table_name}.parquet ({len(df)} rader)")


def _list_s3_tables(s3) -> list[str]:
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=S3_PREFIX + "/")
    tables = []
    for obj in resp.get("Contents", []):
        name = obj["Key"].split("/")[-1]
        if name.endswith(".parquet"):
            tables.append(name[:-8])
    return tables


# ---------------------------------------------------------------------------
# MotherDuck
# ---------------------------------------------------------------------------

def _md_connect():
    import duckdb

    token = os.environ.get("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        raise SystemExit("[nor] MOTHERDUCK_TOKEN saknas")

    # Anslut mot default-databasen och skapa nor om den saknas
    conn = duckdb.connect(f"md:?motherduck_token={token}")
    conn.execute(f"CREATE DATABASE IF NOT EXISTS {NOR_DB}")
    conn.close()

    conn = duckdb.connect(f"md:{NOR_DB}?motherduck_token={token}")
    conn.execute("INSTALL httpfs; LOAD httpfs;")
    return conn


def _s3_secret(conn):
    endpoint = os.environ.get("HETZNER_ENDPOINT", "").strip().replace("https://", "").replace("http://", "").rstrip("/")
    conn.execute(f"""
    CREATE OR REPLACE SECRET hetzner_s3 (
        TYPE S3,
        KEY_ID     '{os.environ.get("HETZNER_ACCESS_KEY", "")}',
        SECRET     '{os.environ.get("HETZNER_SECRET_KEY", "")}',
        ENDPOINT   '{endpoint}',
        URL_STYLE  'path',
        REGION     '{os.environ.get("HETZNER_REGION", "eu-central")}'
    )
    """)


def _s3_url(table_name: str) -> str:
    return f"s3://{BUCKET}/{S3_PREFIX}/{table_name}.parquet"


def _ensure_database(conn):
    conn.execute(f"CREATE DATABASE IF NOT EXISTS {NOR_DB}")


def _load_table_from_s3(conn, table_name: str):
    url = _s3_url(table_name)
    conn.execute(f"""
    CREATE OR REPLACE TABLE {NOR_DB}.{table_name} AS
    SELECT * FROM read_parquet('{url}')
    """)
    count = conn.execute(f"SELECT COUNT(*) FROM {NOR_DB}.{table_name}").fetchone()[0]
    print(f"[nor] MotherDuck: {table_name} ({count} rader)")


def _upsert_table_from_s3(conn, table_name: str, new_match_ids: list[int]):
    """Tar bort befintliga rader för new_match_ids och infogar från S3."""
    url = _s3_url(table_name)

    table_exists = conn.execute(f"""
    SELECT COUNT(*) FROM information_schema.tables
    WHERE table_schema = '{NOR_DB}' AND table_name = '{table_name}'
    """).fetchone()[0]

    if not table_exists:
        conn.execute(f"""
        CREATE TABLE {NOR_DB}.{table_name} AS
        SELECT * FROM read_parquet('{url}')
        """)
        count = conn.execute(f"SELECT COUNT(*) FROM {NOR_DB}.{table_name}").fetchone()[0]
        print(f"[nor] MotherDuck: {table_name} skapad ({count} rader)")
        return

    if new_match_ids:
        ids_str = ",".join(str(i) for i in new_match_ids)
        conn.execute(f"DELETE FROM {NOR_DB}.{table_name} WHERE match_id IN ({ids_str})")

    conn.execute(f"""
    INSERT INTO {NOR_DB}.{table_name}
    SELECT * FROM read_parquet('{url}')
    WHERE match_id IN ({",".join(str(i) for i in new_match_ids) if new_match_ids else "NULL"})
    """)

    count = conn.execute(f"SELECT COUNT(*) FROM {NOR_DB}.{table_name}").fetchone()[0]
    print(f"[nor] MotherDuck: {table_name} uppdaterad (+{len(new_match_ids)} matcher, {count} totalt)")


def load_all_from_s3(conn):
    """Full inläsning från S3 (används vid --load-only utan befintlig data)."""
    _ensure_database(conn)
    _s3_secret(conn)

    s3 = _s3_client()
    available = _list_s3_tables(s3)
    print(f"[nor] Hittade {len(available)} tabeller i S3: {available}")

    for table in available:
        _load_table_from_s3(conn, table)


def get_known_match_ids(conn) -> set[int]:
    """Hämtar match_ids som redan finns i MotherDuck."""
    try:
        rows = conn.execute(f"SELECT DISTINCT match_id FROM {NOR_DB}.matches").fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Pipeline steg
# ---------------------------------------------------------------------------

def step_scrape(known_ids: set[int], tournament_year: int | None = None) -> dict:
    """Kör skraparen och returnerar nya DataFrames."""
    from nor_scraper import scrape_new_matches  # type: ignore

    print(f"[nor] Skrapar nya matcher (redan kända: {len(known_ids)}, "
          f"år={tournament_year or 'auto'})...")
    return scrape_new_matches(known_ids, tournament_year=tournament_year)


def step_upload(data: dict, s3) -> list[int]:
    """Laddar upp nya DataFrames till S3 och returnerar nya match_ids."""
    new_match_ids: list[int] = []

    # Ladda ner befintliga S3-tabeller, slå ihop med nya data, ladda upp
    for table_name, new_df in data.items():
        if new_df.empty:
            print(f"[nor] {table_name}: inga nya rader")
            continue

        # Ladda ned befintlig fil om den finns
        try:
            import io as _io
            import pandas as pd

            buf = _io.BytesIO()
            s3.download_fileobj(BUCKET, f"{S3_PREFIX}/{table_name}.parquet", buf)
            buf.seek(0)
            existing = pd.read_parquet(buf)

            if table_name == "matches":
                existing = existing[~existing["match_id"].isin(new_df["match_id"])]
            elif "match_id" in existing.columns:
                existing = existing[~existing["match_id"].isin(new_df["match_id"])]

            combined = pd.concat([existing, new_df], ignore_index=True)
        except Exception:
            combined = new_df

        _upload_df(s3, combined, table_name)

        if table_name == "matches" and not new_df.empty:
            new_match_ids = new_df["match_id"].unique().tolist()

    return new_match_ids


def step_load_to_motherduck(conn, new_match_ids: list[int]):
    """Uppdaterar MotherDuck med nya match_ids."""
    _ensure_database(conn)
    _s3_secret(conn)

    s3 = _s3_client()
    available = _list_s3_tables(s3)

    for table in available:
        if table in MATCH_TABLES:
            _upsert_table_from_s3(conn, table, new_match_ids)
        else:
            _load_table_from_s3(conn, table)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Norwegian EHL hockey pipeline")
    parser.add_argument("--load-only", action="store_true", help="Bara S3 → MotherDuck")
    parser.add_argument("--scrape-only", action="store_true", help="Bara skrapa (ingen MD-load)")
    parser.add_argument("--force", action="store_true", help="Kör även utan nya matcher")
    parser.add_argument("--year", type=int, default=None,
                        help="Säsong att skrapa (t.ex. 2026). Default: innevarande säsong.")
    args = parser.parse_args()

    t0 = time.time()

    if args.load_only:
        print("[nor] Läser in alla tabeller från S3 till MotherDuck...")
        conn = _md_connect()
        load_all_from_s3(conn)
        conn.close()
        print(f"[nor] Klar på {time.time()-t0:.1f}s")
        return

    # Hämta kända match_ids
    conn = _md_connect()
    known_ids = get_known_match_ids(conn)
    print(f"[nor] {len(known_ids)} matcher redan i MotherDuck")

    try:
        data = step_scrape(known_ids, tournament_year=args.year)
    except SystemExit as e:
        print(e)
        conn.close()
        sys.exit(1)

    new_match_count = len(data.get("matches", []))
    if new_match_count == 0 and not args.force:
        print("[nor] Inga nya matcher hittades – avslutar")
        conn.close()
        return

    print(f"[nor] {new_match_count} nya matcher att ladda")

    # Ladda upp till S3
    s3 = _s3_client()
    new_match_ids = step_upload(data, s3)

    if args.scrape_only:
        print("[nor] --scrape-only: hoppar över MotherDuck-inläsning")
        conn.close()
        print(f"[nor] Klar på {time.time()-t0:.1f}s")
        return

    # Ladda till MotherDuck
    step_load_to_motherduck(conn, new_match_ids)
    conn.close()

    print(f"\n[nor] Pipeline klar! {new_match_count} nya matcher, {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
