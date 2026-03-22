#!/usr/bin/env bash
# Sätter GAMES_YEAR i .env för uppdelad historik (år för år). Ingen dubbletter: state + export rensar partition.
# Användning: ./scripts/run_games_year.sh 2010
# Därefter: docker compose restart mage && kör games_pipeline i Mage UI. När klar, kör t.ex. ./scripts/run_games_year.sh 2011
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
YEAR="$1"
if [ -z "$YEAR" ]; then
  echo "Användning: ./scripts/run_games_year.sh <år>"
  echo "  t.ex. ./scripts/run_games_year.sh 2010"
  echo "Efter körning: docker compose restart mage  (så Mage läser ny .env)"
  echo "Kör sedan games_pipeline i Mage UI. För nästa år: ./scripts/run_games_year.sh 2011"
  exit 1
fi
# games_year.txt har företräde över .env – uppdatera båda
STATE_FILE="${ROOT}/mage_project/state/games_year.txt"
mkdir -p "$(dirname "$STATE_FILE")"
echo "$YEAR" > "$STATE_FILE"
echo "games_year.txt: $YEAR"

if [ -f "$ENV_FILE" ]; then
  if grep -q '^GAMES_YEAR=' "$ENV_FILE" 2>/dev/null; then
    sed -i.bak "s/^GAMES_YEAR=.*/GAMES_YEAR=$YEAR/" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
  else
    echo "GAMES_YEAR=$YEAR" >> "$ENV_FILE"
  fi
  echo "GAMES_YEAR=$YEAR satt i .env"

  # Varna om GAMES_START_DATE skulle blockera detta år
  START_DATE=$(grep -E '^GAMES_START_DATE=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d ' ')
  START_YEAR="${START_DATE:0:4}"
  if [ -n "$START_YEAR" ] && [ "$START_YEAR" -gt "$YEAR" ] 2>/dev/null; then
    echo ""
    echo "VARNING: GAMES_START_DATE=$START_DATE – datum i $YEAR filtreras bort."
    echo "  Sätt GAMES_START_DATE=2010-01-01 (eller tidigare) i .env för att inkludera $YEAR."
  fi

  echo ""
  echo "Nästa steg:"
  echo "  1. docker compose restart mage"
  echo "  2. Kör games_pipeline i Mage UI (laddar endast år $YEAR)"
  echo "  3. När klar, för nästa år: ./scripts/run_games_year.sh $((YEAR+1))"
else
  echo "Hittar inte .env i $ROOT"
  exit 1
fi
