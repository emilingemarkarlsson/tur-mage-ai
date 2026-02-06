#!/usr/bin/env bash
# Kör bara blocket refresh_duckdb_views i dimensions_pipeline.
# Kräver att Docker Compose är igång (docker compose up -d).
set -e
CONTAINER="${1:-tur-mage-ai-mage-1}"
PROJECT_PATH="/home/src/mage_project"
echo "Running refresh_duckdb_views in container: $CONTAINER"
# Utan -it så att scriptet fungerar även när det körs icke-interaktivt (t.ex. från CI)
docker exec "$CONTAINER" mage run "$PROJECT_PATH" dimensions_pipeline --block-uuid refresh_duckdb_views
