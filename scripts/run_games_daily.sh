#!/usr/bin/env bash
# Tar bort GAMES_YEAR från .env så games_pipeline kör inkrementellt (endast nya datum efter senaste körning).
# Använd efter att all historik är inladdad (år för år eller en full körning).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
if [ -f "$ENV_FILE" ]; then
  if grep -q '^GAMES_YEAR=' "$ENV_FILE" 2>/dev/null; then
    sed -i.bak '/^GAMES_YEAR=/d' "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
    echo "GAMES_YEAR borttagen från .env – nästa games_pipeline blir inkrementell (dagliga uppdateringar)."
  else
    echo ".env innehåller redan inte GAMES_YEAR – du är i dagligt läge."
  fi
  echo ""
  echo "Starta om Mage om du ändrade .env: docker compose restart mage"
else
  echo "Hittar inte .env i $ROOT"
  exit 1
fi
