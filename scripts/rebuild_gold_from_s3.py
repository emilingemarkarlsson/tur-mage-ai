#!/usr/bin/env python3
"""
Bygger om Gold (nhl.duckdb) enbart från Silver i S3.

Standard: laddar upp Gold till S3 (samma som Mage refresh).
Lokalt (Streamlit / MotherDuck): bygg bara lokalt, ladda inte upp.

  python scripts/rebuild_gold_from_s3.py              # bygg + ladda upp till S3
  BUILD_GOLD_LOCAL_ONLY=1 python scripts/rebuild_gold_from_s3.py   # bygg lokalt (mage_project/data_lake/gold/nhl.duckdb)

Vid lokalt bygg: sätt DUCKDB_VIEWER_PATH till den lokala filen i .env, kör Streamlit.
Sen kan du migrera till MotherDuck (EXPORT eller attach denna fil).

Kräver: duckdb, boto3, python-dotenv
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "mage_project"))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
except Exception:
    pass

DATASETS = [
    "teams", "players", "countries", "roster", "schedule", "game_ids",
    "glossary", "draft", "standings", "skater_stats", "goalie_stats", "team_stats",
    "edge_skaters", "edge_goalies", "edge_teams", "games", "game_players",
    "game_events", "game_stories",
]


def main():
    import duckdb
    from utils.s3_utils import get_s3_bucket, get_s3_client, get_duckdb_s3_secret_sql, list_keys, upload_file

    bucket = get_s3_bucket()
    prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
    if not bucket:
        print("S3 bucket inte satt (HETZNER_BUCKET).")
        sys.exit(1)

    client = get_s3_client()
    # Vilka datasets har parquet i S3?
    has_in_s3 = {}
    for name in DATASETS:
        key_prefix = f"{prefix}/silver/{name}/"
        keys = list(list_keys(client, bucket, key_prefix))
        parquet = [k for k in keys if k.endswith(".parquet")]
        has_in_s3[name] = len(parquet) > 0
        if parquet:
            print(f"  S3 Silver {name}: {len(parquet)} filer")

    if not any(has_in_s3.values()):
        print("Ingen Silver-data i S3.")
        sys.exit(1)

    print("\nBygger Gold från S3 Silver...")
    db_path = os.path.join(ROOT, "gold_rebuild.duckdb")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn2 = duckdb.connect(db_path)
    conn2.execute("INSTALL httpfs; LOAD httpfs;")
    conn2.execute(get_duckdb_s3_secret_sql(scope_bucket=bucket))
    for name in DATASETS:
        if not has_in_s3[name]:
            continue
        s3_path = f"s3://{bucket}/{prefix}/silver/{name}/**/*.parquet"
        try:
            # games/game_players: export skriver ny part-<timestamp>.parquet per körning (överskriver inte).
            # Vid flera körningar samma datum blir samma match flera gånger – deduplicera på game_id resp (game_id, player_id).
            if name == "games":
                conn2.execute(f"""
                    CREATE VIEW games AS
                    SELECT * EXCLUDE (_rn) FROM (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY game_date) AS _rn
                        FROM read_parquet('{s3_path}', union_by_name=true)
                    ) _ WHERE _rn = 1
                """)
            elif name == "game_players":
                conn2.execute(f"""
                    CREATE VIEW game_players AS
                    SELECT * EXCLUDE (_rn) FROM (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY game_id, player_id ORDER BY game_date) AS _rn
                        FROM read_parquet('{s3_path}', union_by_name=true)
                    ) _ WHERE _rn = 1
                """)
            else:
                conn2.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{s3_path}', union_by_name=true);")
            print(f"  OK: {name}")
        except Exception as e:
            print(f"  Fel {name}: {e}")
    if has_in_s3.get("game_players") and has_in_s3.get("players"):
        try:
            conn2.execute("""
                CREATE VIEW player_game_stats AS
                SELECT gp.*, p.firstName AS player_first_name, p.lastName AS player_last_name
                FROM game_players gp LEFT JOIN players p ON p.id = gp.player_id
            """)
            print("  OK: player_game_stats")
        except Exception as e:
            print(f"  Fel player_game_stats: {e}")
    if has_in_s3.get("games"):
        try:
            # Silver i S3 kan ha äldre schema – bygg team_game_stats från kolumner som faktiskt finns.
            desc = conn2.execute("DESCRIBE games").fetchall()
            games_cols = set((row[0] for row in desc)) if desc else set()
            parts = [
                ("game_id", "g.game_id", "g.game_id"),
                ("game_date", "g.game_date", "g.game_date"),
                ("season", "g.season", "g.season"),
                ("status", "g.status", "g.status"),
                ("is_home", "TRUE", "FALSE"),
                ("team_id", "g.home_team_id", "g.away_team_id"),
                ("team_abbr", "g.home_team_abbr", "g.away_team_abbr"),
                ("opponent_abbr", "g.away_team_abbr", "g.home_team_abbr"),
                ("goals_for", "g.home_score", "g.away_score"),
                ("goals_against", "g.away_score", "g.home_score"),
                ("team_points", "g.home_points", "g.away_points"),
                ("sog", "g.home_sog", "g.away_sog"),
                ("pp_goals", "g.home_pp_goals", "g.away_pp_goals"),
                ("pp_opportunities", "g.home_pp_opportunities", "g.away_pp_opportunities"),
                ("hits", "g.home_hits", "g.away_hits"),
                ("blocked_shots", "g.home_blocked", "g.away_blocked"),
                ("pim", "g.home_pim", "g.away_pim"),
                ("giveaways", "g.home_giveaways", "g.away_giveaways"),
                ("takeaways", "g.home_takeaways", "g.away_takeaways"),
                ("faceoff_win_pct", "g.home_faceoff_pct", "g.away_faceoff_pct"),
                ("venue", "g.venue", "g.venue"),
                ("venue_location", "g.venue_location", "g.venue_location"),
                ("start_time_utc", "g.start_time_utc", "g.start_time_utc"),
                ("reg_periods", "g.reg_periods", "g.reg_periods"),
                ("game_type", "g.game_type", "g.game_type"),
                ("limited_scoring", "g.limited_scoring", "g.limited_scoring"),
            ]
            home_select = []
            away_select = []
            for alias, home_expr, away_expr in parts:
                if not home_expr.startswith("g."):  # literal (TRUE/FALSE)
                    home_select.append(f"{home_expr} AS {alias}")
                    away_select.append(f"{away_expr} AS {alias}")
                    continue
                home_col = home_expr.replace("g.", "", 1).strip()
                away_col = away_expr.replace("g.", "", 1).strip()
                home_select.append(f"{home_expr} AS {alias}" if home_col in games_cols else f"NULL AS {alias}")
                away_select.append(f"{away_expr} AS {alias}" if away_col in games_cols else f"NULL AS {alias}")
            home_s = ", ".join(home_select)
            away_s = ", ".join(away_select)
            sql = f"CREATE VIEW team_game_stats AS SELECT {home_s} FROM games g UNION ALL SELECT {away_s} FROM games g"
            conn2.execute(sql)
            print("  OK: team_game_stats")
        except Exception as e:
            print(f"  Fel team_game_stats: {e}")
    conn2.close()

    local_only = os.getenv("BUILD_GOLD_LOCAL_ONLY", "").strip().lower() in ("1", "true", "yes")
    if local_only:
        out_path = os.path.join(ROOT, "mage_project", "data_lake", "gold", "nhl.duckdb")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        if os.path.abspath(db_path) != os.path.abspath(out_path):
            import shutil
            shutil.move(db_path, out_path)
            db_path = out_path
        print(f"\nGold sparad lokalt: {db_path}")
        print("  Sätt i .env: DUCKDB_VIEWER_PATH=" + os.path.abspath(db_path))
        print("  Kör: streamlit run streamlit_viewer.py  och  python scripts/validate_duckdb_viewer.py")
        print("  För MotherDuck: använd denna fil eller EXPORT DATABASE.")
        return

    key = f"{prefix}/gold/nhl.duckdb"
    print(f"\nLaddar upp till s3://{bucket}/{key} ...")
    upload_file(client, bucket, key, db_path)
    try:
        os.remove(db_path)
    except OSError:
        pass
    print("Klart. Kör python scripts/validate_duckdb_viewer.py för att verifiera.")


if __name__ == "__main__":
    main()
