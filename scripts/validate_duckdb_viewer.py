#!/usr/bin/env python3
"""
Validerar anslutning till Gold DuckDB (lokal eller S3) och listar tabeller.
Kör från projektroten med .env laddad:
  python scripts/validate_duckdb_viewer.py
Använder samma sökväg som Streamlit (DUCKDB_VIEWER_PATH eller DATA_LAKE_SINK + bucket/prefix).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass


def _default_db_path():
    explicit = os.getenv("DUCKDB_VIEWER_PATH", "").strip()
    if explicit:
        return explicit
    sink = (os.getenv("DATA_LAKE_SINK") or "local").strip().lower()
    if sink == "s3":
        bucket = os.getenv("S3_DATA_LAKE_BUCKET") or os.getenv("HETZNER_BUCKET") or ""
        prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
        if bucket:
            return f"s3://{bucket}/{prefix}/gold/nhl.duckdb"
    return os.path.join(ROOT, "mage_project", "data_lake", "gold", "nhl.duckdb")


def _s3_secret_sql(scope_bucket: str = ""):
    source = (os.getenv("S3_SOURCE") or "hetzner").strip().lower()
    if source == "minio":
        endpoint = os.getenv("MINIO_ENDPOINT") or ""
        access = os.getenv("MINIO_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or ""
        secret = os.getenv("MINIO_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or ""
        region = os.getenv("MINIO_REGION") or os.getenv("AWS_REGION", "us-east-1")
    else:
        endpoint = os.getenv("HETZNER_ENDPOINT") or os.getenv("S3_ENDPOINT") or ""
        access = os.getenv("HETZNER_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or ""
        secret = os.getenv("HETZNER_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or ""
        region = os.getenv("HETZNER_REGION") or os.getenv("AWS_REGION", "eu-central")
    endpoint_host = (endpoint or "").strip().replace("https://", "").replace("http://", "").rstrip("/")
    def esc(s):
        return (s or "").replace("'", "''")
    parts = [
        "CREATE OR REPLACE SECRET s3_nhl (TYPE S3, PROVIDER config, ",
        f"KEY_ID '{esc(access)}', SECRET '{esc(secret)}', REGION '{esc(region)}', ",
        f"ENDPOINT '{esc(endpoint_host)}', URL_STYLE 'path'",
    ]
    if scope_bucket:
        scope_val = f"s3://{scope_bucket.rstrip('/')}/"
        parts.append(f", SCOPE '{esc(scope_val)}'")
    parts.append(");")
    return "".join(parts)


def connect_duckdb(db_path: str):
    import duckdb
    db_path = (db_path or "").strip()
    if db_path.startswith("s3://"):
        bucket = db_path.replace("s3://", "").strip().split("/")[0] or ""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute(_s3_secret_sql(scope_bucket=bucket))
        conn.execute(f"ATTACH '{db_path}' AS nhl (READ_ONLY);")
        rows = conn.execute(
            "SELECT table_catalog || '.' || table_schema || '.' || table_name FROM information_schema.tables WHERE table_catalog = 'nhl' ORDER BY 1"
        ).fetchall()
        tables = [r[0] for r in rows]
        return conn, tables
    conn = duckdb.connect(db_path, read_only=True)
    tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
    return conn, tables


def main():
    db_path = _default_db_path()
    print(f"DuckDB-sökväg: {db_path}\n")

    if not db_path.startswith("s3://") and not os.path.isfile(db_path):
        print("Lokal fil finns inte. Vid S3: sätt DUCKDB_VIEWER_PATH eller DATA_LAKE_SINK=s3 i .env.")
        sys.exit(1)

    try:
        conn, tables = connect_duckdb(db_path)
    except Exception as e:
        print(f"Anslutningsfel: {e}")
        sys.exit(1)

    short_names = {t.split(".")[-1] if "." in t else t for t in tables}
    expected = {"games", "game_players", "player_game_stats", "team_game_stats"}
    missing = expected - short_names

    print("Tabeller/vyer:", len(tables))
    for t in tables:
        short = t.split(".")[-1] if "." in t else t
        mark = " ✓" if short in expected else ""
        print(f"  - {short}{mark}")
    if missing:
        print(f"\nSaknade (games-pipeline): {missing}")
        print("  Kör games_pipeline i Mage och refresh_duckdb_views, sedan validera igen.")
    else:
        print("\n--- Validering games / game_players ---")
        games_table = next((t for t in tables if t.endswith(".games") or t == "games"), None)
        players_table = next((t for t in tables if t.endswith(".game_players") or t == "game_players"), None)
        ok = True
        if games_table:
            try:
                (n,) = conn.execute(f"SELECT COUNT(*) FROM {games_table}").fetchone()
                print(f"  games: {n} rader")
                (dupes,) = conn.execute(f"SELECT COUNT(*) FROM (SELECT game_id FROM {games_table} GROUP BY game_id HAVING COUNT(*) > 1) t").fetchone()
                if dupes and dupes > 0:
                    print(f"  VARNING: {dupes} game_id har dubletter.")
                    print("    Orsak: Silver skrivs med part-<timestamp>.parquet per körning (lägger till filer). Vid omkörning samma datum läses alla filer → dubletter. Kör scripts/rebuild_gold_from_s3.py för att bygga Gold med deduplicering.")
                    ok = False
                else:
                    print("  Dubletter (game_id): inga")
                row = conn.execute(f"SELECT game_id, game_date, home_team_abbr, away_team_abbr, home_score, away_score FROM {games_table} ORDER BY game_date ASC LIMIT 1").fetchone()
                if row:
                    print(f"  Första match: game_id={row[0]}, date={row[1]}, {row[2]}–{row[3]} {row[4]}–{row[5]}")
                row2 = conn.execute(f"SELECT game_id, game_date, home_team_abbr, away_team_abbr FROM {games_table} ORDER BY game_date DESC LIMIT 1").fetchone()
                if row2:
                    print(f"  Senaste match: game_id={row2[0]}, date={row2[1]}, {row2[2]}–{row2[3]}")
                print("  Datumspann: beroende på källan (nhl-data-reorganized/games/by_date/) och GAMES_START_DATE + state (last_games_date.txt). För data från 2010: GAMES_START_DATE=2010-01-01, ta bort state, kör games_pipeline fullt.")
            except Exception as e:
                print(f"  games-fel: {e}")
                ok = False
        if players_table:
            try:
                (n,) = conn.execute(f"SELECT COUNT(*) FROM {players_table}").fetchone()
                print(f"  game_players: {n} rader")
                (dupes,) = conn.execute(f"SELECT COUNT(*) FROM (SELECT game_id, player_id FROM {players_table} GROUP BY game_id, player_id HAVING COUNT(*) > 1) t").fetchone()
                if dupes and dupes > 0:
                    print(f"  VARNING: {dupes} (game_id, player_id)-par har dubletter.")
                    print("    Orsak: samma som games – flera Parquet-filer per datum vid omkörningar. Rebuild Gold med scripts/rebuild_gold_from_s3.py för deduplicering.")
                    ok = False
                else:
                    print("  Dubletter (game_id, player_id): inga")
            except Exception as e:
                print(f"  game_players-fel: {e}")
                ok = False
        if ok and games_table:
            print("\nValidering OK. Öppna Streamlit och välj games / player_game_stats / team_game_stats för att bläddra.")
    conn.close()
    sys.exit(0 if not missing else 1)


if __name__ == "__main__":
    main()
