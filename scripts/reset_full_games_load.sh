#!/usr/bin/env bash
# Rensar incremental state för games så nästa körning av games_pipeline laddar all data från GAMES_START_DATE.
# Kör från projektroten: ./scripts/reset_full_games_load.sh
# Eller: docker exec -it tur-mage-ai-mage-1 rm -f /home/src/mage_project/state/last_games_date.txt

set -e
CONTAINER="${1:-tur-mage-ai-mage-1}"
STATE_FILE="/home/src/mage_project/state/last_games_date.txt"

echo "Rensar games-state i container: $CONTAINER"
docker exec -i "$CONTAINER" rm -f "$STATE_FILE" 2>/dev/null || true
echo "Klart. Nästa körning av games_pipeline i Mage laddar all data från GAMES_START_DATE."
