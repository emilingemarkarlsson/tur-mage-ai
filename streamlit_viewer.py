import json
import os

import duckdb
import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
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


st.set_page_config(page_title="DuckDB Viewer", layout="wide")
st.title("DuckDB Viewer")

db_path = st.sidebar.text_input(
    "DuckDB path",
    value=os.getenv("DUCKDB_VIEWER_PATH", "mage_project/data_lake/gold/nhl.duckdb"),
    help="Lokal fil eller s3://bucket/prefix/gold/nhl.duckdb för att läsa direkt från S3.",
)

# Default för S3 om användaren vill använda samma bucket/prefix som i .env
if st.sidebar.checkbox("Använd S3 (Hetzner) från .env", value=False):
    bucket = os.getenv("S3_DATA_LAKE_BUCKET") or os.getenv("HETZNER_BUCKET") or ""
    prefix = os.getenv("S3_DATA_LAKE_PREFIX", "nhl-analytics")
    if bucket:
        db_path = f"s3://{bucket}/{prefix}/gold/nhl.duckdb"

limit = st.sidebar.number_input("Rows per page", min_value=10, max_value=1000, value=100, step=10)
page = st.sidebar.number_input("Page", min_value=0, value=0, step=1)
offset = page * limit

con = None
try:
    con, tables = connect_duckdb(db_path)
    table = st.sidebar.selectbox("Table/View", tables, key="table_select")

    if table:
        total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        st.caption(f"Total rows: {total}")
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
