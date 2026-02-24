#!/bin/bash
# Startar Streamlit DuckDB Viewer från projektrot så att .env laddas.
# Använder DUCKDB_VIEWER_PATH eller DATA_LAKE_SINK från .env.
cd "$(dirname "$0")/.."
export DUCKDB_VIEWER_PATH="${DUCKDB_VIEWER_PATH:-}"
# Ladda .env om det finns
if [ -f .env ]; then set -a; source .env; set +a; fi
echo "DuckDB-sökväg: ${DUCKDB_VIEWER_PATH:-s3://$S3_DATA_LAKE_BUCKET/$S3_DATA_LAKE_PREFIX/gold/nhl.duckdb (från DATA_LAKE_SINK=s3)}"
# Om 8501 är upptagen används nästa lediga port (8502, 8503, ...)
exec python -m streamlit run streamlit_viewer.py --server.headless true --server.port 8502 --server.address 0.0.0.0
