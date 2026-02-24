import json
import os

import duckdb
import pandas as pd
import streamlit as st

# Ladda .env från projektrot så att DATA_LAKE_SINK / DUCKDB_VIEWER_PATH alltid gäller
def _project_root():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(3):
        if os.path.isfile(os.path.join(d, ".env")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_project_root(), ".env"))
except Exception:
    pass


def _s3_secret_sql(scope_bucket: str = ""):
    """Bygger CREATE SECRET för S3 (Hetzner eller MinIO) från miljövariabler."""
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
    # DuckDB custom endpoint: använd endast host (utan https://) så att httpfs bygger URL rätt
    endpoint_host = (endpoint or "").strip().replace("https://", "").replace("http://", "").rstrip("/")
    # Escape single quotes i strängar för SQL
    def esc(s):
        return (s or "").replace("'", "''")
    # S3-compatible (Hetzner, MinIO): path-style URL + explicit SCOPE så secret används vid ATTACH
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


def _item_to_json_serializable(x):
    """Struct/dict till dict så att json.dumps ger ren JSON istället för Python-repr."""
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    if isinstance(x, dict):
        return x
    if hasattr(x, "keys") and callable(getattr(x, "keys", None)):
        try:
            return dict(x)
        except Exception:
            return str(x)
    return x


def _cell_to_display_value(v):
    """En cell till läsbar sträng; dict/list/struct -> JSON, annars skalär oförändrad."""
    if v is None or (isinstance(v, (str, int, float, bool)) and not isinstance(v, (dict, list))):
        return v
    if isinstance(v, (pd.Timestamp,)):
        return str(v)
    if isinstance(v, dict):
        return json.dumps(v, default=str)
    # List eller DuckDB LIST (iterable, inte str/bytes)
    if isinstance(v, list) or (hasattr(v, "__iter__") and not isinstance(v, (str, bytes))):
        try:
            out_list = [_item_to_json_serializable(x) for x in v]
            return json.dumps(out_list, default=str)
        except Exception:
            return str(v)
    if hasattr(v, "keys") and callable(getattr(v, "keys", None)):
        try:
            return json.dumps(dict(v), default=str)
        except Exception:
            return str(v)
    return str(v)


def _dataframe_display_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Konverterar alla kolumner med nästlade objekt till läsbar sträng så de inte visas som [object Object]."""
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        try:
            # Konvertera alla objekt-kolumner: antingen första värdet är komplex, eller dtype är object
            sample = out[col].dropna()
            if len(sample) == 0:
                continue
            first = sample.iloc[0]
            is_complex = isinstance(first, (dict, list)) or (
                hasattr(first, "keys") and callable(getattr(first, "keys", None))
            )
            # Också konvertera om kolumnen har dtype object (kan innehålla structs/listor)
            if is_complex or out[col].dtype == object:
                out[col] = out[col].apply(_cell_to_display_value)
        except Exception:
            pass
    return out


def connect_duckdb(db_path: str):
    """
    Öppnar antingen lokal fil eller S3 (read-only).
    Returnerar (conn, table_list) där table_list är list[str] med fullständiga namn (t.ex. "nhl.games" vid S3).
    """
    db_path = (db_path or "").strip()
    if db_path.startswith("s3://"):
        # Bucket = första path-delen (s3://bucket/...) för SCOPE så secret används vid ATTACH
        bucket = db_path.replace("s3://", "").strip().split("/")[0] or ""
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute(_s3_secret_sql(scope_bucket=bucket))
        conn.execute(f"ATTACH '{db_path}' AS nhl (READ_ONLY);")
        # Bifogad DB har catalog='nhl', schema='main' – inte table_schema='nhl'
        rows = conn.execute(
            "SELECT table_catalog || '.' || table_schema || '.' || table_name FROM information_schema.tables WHERE table_catalog = 'nhl' ORDER BY 1"
        ).fetchall()
        tables = [r[0] for r in rows]
        return conn, tables
    # Lokal fil
    conn = duckdb.connect(db_path, read_only=True)
    tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
    return conn, tables


def _default_db_path():
    """Välj DuckDB-sökväg: DUCKDB_VIEWER_PATH, eller S3 om DATA_LAKE_SINK=s3, annars lokal."""
    explicit = os.getenv("DUCKDB_VIEWER_PATH", "").strip()
    if explicit:
        return explicit
    sink = (os.getenv("DATA_LAKE_SINK") or "local").strip().lower()
    if sink == "s3":
        bucket = os.getenv("S3_DATA_LAKE_BUCKET") or os.getenv("HETZNER_BUCKET") or ""
        prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
        if bucket:
            return f"s3://{bucket}/{prefix}/gold/nhl.duckdb"
    return "mage_project/data_lake/gold/nhl.duckdb"


st.set_page_config(page_title="DuckDB Viewer", layout="wide")
st.title("DuckDB Viewer")

default_path = _default_db_path()
# Sökväg i session_state så att "Återställ" kan sätta rätt standard (S3/lokal)
if "duckdb_path" not in st.session_state:
    st.session_state["duckdb_path"] = default_path
if st.sidebar.button("Återställ sökväg till standard"):
    st.session_state["duckdb_path"] = default_path
    st.rerun()

db_path = st.sidebar.text_input(
    "DuckDB path",
    value=st.session_state["duckdb_path"],
    key="duckdb_path",
    help="Lokal fil eller s3://bucket/prefix/gold/nhl.duckdb. Vid DATA_LAKE_SINK=s3 används S3 som standard.",
)
# Efter widget: använd det som står i rutan (session_state uppdateras av text_input)
db_path = st.session_state["duckdb_path"]

# Överskriv med S3 från .env om användaren kryssar i
if st.sidebar.checkbox("Använd S3 (Hetzner) från .env", value=(os.getenv("DATA_LAKE_SINK", "").strip().lower() == "s3")):
    bucket = os.getenv("S3_DATA_LAKE_BUCKET") or os.getenv("HETZNER_BUCKET") or ""
    prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
    if bucket:
        db_path = f"s3://{bucket}/{prefix}/gold/nhl.duckdb"

limit = st.sidebar.number_input("Rows per page", min_value=10, max_value=1000, value=100, step=10)
page = st.sidebar.number_input("Page", min_value=0, value=0, step=1)
offset = page * limit

def _table_display_name(full_name: str) -> str:
    """Visa kort namn i listan (t.ex. 'games' istället för 'nhl.main.games')."""
    if not full_name:
        return full_name
    return full_name.split(".")[-1] if "." in full_name else full_name

# Table/view descriptions (English; naming standard: snake_case)
TABLE_DESCRIPTIONS = {
    "game_players": "One row per player per game – goals, assists, shots, toi, etc. Raw stats; join to players for names.",
    "player_game_stats": "Same as game_players with player_first_name, player_last_name. Use for player trends by game.",
    "games": "One row per game – home/away teams, scores, SOG, hits, PP, venue. Use for game-level analysis.",
    "team_game_stats": "One row per team per game (unpivot of games). goals_for, goals_against, sog, etc. Use for team trends by game.",
}

def _table_description(table_full_name: str) -> str:
    short = _table_display_name(table_full_name)
    return TABLE_DESCRIPTIONS.get(short, "")

# Förväntade tabeller för match/spelarstatistik – visa varning om de saknas
EXPECTED_GAMES_TABLES = {"games", "game_players", "player_game_stats", "team_game_stats"}

def _short_names(tables_list):
    return {_table_display_name(t) for t in tables_list}

# #region agent log
def _debug_log(msg: str, data: dict, hypothesis_id: str = "E"):
    try:
        import json
        root = _project_root()
        p = os.path.join(root, ".cursor", "debug.log")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"hypothesisId": hypothesis_id, "location": "streamlit_viewer", "message": msg, "data": data, "timestamp": __import__("time").time() * 1000}) + "\n")
    except Exception:
        pass
# #endregion

con = None
try:
    con, tables = connect_duckdb(db_path)
    short_names = {t.split(".")[-1] if "." in t else t for t in (tables or [])}
    _debug_log("Connect result", {"db_path": db_path, "tables_count": len(tables or []), "table_names": list(short_names)[:30], "has_games": "games" in short_names, "has_game_players": "game_players" in short_names}, "E")
    if not tables:
        st.warning("Inga tabeller eller vyer hittades. Kontrollera att DuckDB-filen finns och att pipelines har körts (gold skapas i sista steget). Vid S3: kryssa i 'Använd S3 (Hetzner) från .env' om datan ligger i S3.")
    else:
        short = _short_names(tables)
        missing = EXPECTED_GAMES_TABLES - short
        if missing:
            st.sidebar.warning(
                "**games / game_players** saknas i denna databas. "
                "Kör **games_pipeline** i Mage (Loader → Transform → Export → refresh_duckdb_views). "
                "Om du använder S3: sätt DuckDB-sökvägen till s3://bucket/prefix/gold/nhl.duckdb (vid DATA_LAKE_SINK=s3 görs detta automatiskt)."
            )
    table = st.sidebar.selectbox("Table/View", tables, format_func=_table_display_name, key="table_select")

    if table:
        desc = _table_description(table)
        total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        st.caption(f"Total rows: {total}")
        if desc:
            st.info(desc)
        df = con.execute(f"SELECT * FROM {table} LIMIT {limit} OFFSET {offset}").df()
        df = _dataframe_display_safe(df)
        st.dataframe(df, use_container_width=True, height=600)
        # CSV-export från samma display-safe df så att nästlade kolumner blir JSON
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        table_name = table.split(".")[-1] if "." in table else table
        st.caption("Använd knappen nedan för CSV – inte tabellens egen export (då blir nästlade fält fel).")
        st.download_button(
            "Ladda ner som CSV",
            data=csv_bytes,
            file_name=f"{table_name}_export.csv",
            mime="text/csv",
            key="download_csv",
        )
except Exception as exc:
    st.error(str(exc))
finally:
    if con:
        try:
            con.close()
        except Exception:
            pass
