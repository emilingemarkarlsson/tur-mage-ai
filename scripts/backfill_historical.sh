#!/usr/bin/env bash
# Kör historisk laddning av games_pipeline år för år (2010–2024).
# Minnesbesparande: liten batch-storlek + container-restart mellan år.
# Silver skrivs till S3 (Hetzner) som säkerhetskopia utöver lokalt.
#
# Förutsättningar i .env:
#   GAMES_START_DATE=2010-01-01
#   GAMES_BATCH_SIZE=10
#   DATA_LAKE_SINK=s3
#   S3_DATA_LAKE_BUCKET=nhlhockey-data
#   S3_DATA_LAKE_PREFIX=nhl-analytics
#   HETZNER_* (eller MINIO_*) med giltiga nycklar
#
# Användning:
#   ./scripts/backfill_historical.sh              # 2010–2024
#   ./scripts/backfill_historical.sh 2015         # 2015–2024
#   ./scripts/backfill_historical.sh 2015 2018    # 2015–2018
#
# Avbryt när som helst med Ctrl+C. Kör om scriptet för att fortsätta
# från senaste avslutade år (redan klarade år skippas).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
STATE_DIR="${ROOT}/mage_project/state"
PROGRESS_FILE="${STATE_DIR}/backfill_progress.txt"
LOG_FILE="${STATE_DIR}/backfill.log"
CONTAINER="tur-mage-ai-mage-1"

START_YEAR="${1:-2010}"
END_YEAR="${2:-2024}"

# -----------------------------------------------------------------------
# Färger
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[backfill]${NC} $*" | tee -a "$LOG_FILE"; }
warn() { echo -e "${YELLOW}[backfill]${NC} $*" | tee -a "$LOG_FILE"; }
err()  { echo -e "${RED}[backfill]${NC} $*" | tee -a "$LOG_FILE"; }

# -----------------------------------------------------------------------
# Kontrollera förutsättningar
mkdir -p "$STATE_DIR"
echo "" >> "$LOG_FILE"
log "=== Backfill startad $(date '+%Y-%m-%d %H:%M:%S') | år ${START_YEAR}–${END_YEAR} ==="

if [ ! -f "$ENV_FILE" ]; then
  err ".env saknas i $ROOT – kör: cp .env.example .env och fyll i credentials."
  exit 1
fi

# Läs .env (exportera variabler för kontroll, inga secrets i logg)
set -a; source "$ENV_FILE"; set +a

check_var() {
  local var="$1"
  if [ -z "${!var:-}" ]; then
    err "Saknar $var i .env. Lägg till och kör om."
    exit 1
  fi
}
check_var "GAMES_START_DATE"
check_var "GAMES_BATCH_SIZE"
check_var "DATA_LAKE_SINK"
check_var "S3_DATA_LAKE_BUCKET"
check_var "S3_DATA_LAKE_PREFIX"

if [ "${DATA_LAKE_SINK}" != "s3" ]; then
  err "DATA_LAKE_SINK=${DATA_LAKE_SINK} – måste vara 's3' för att skydda Silver i Hetzner."
  exit 1
fi

if [ "${GAMES_BATCH_SIZE:-99}" -gt 15 ]; then
  warn "GAMES_BATCH_SIZE=${GAMES_BATCH_SIZE} är högt (rekommenderat ≤10 för historisk laddning)."
  warn "Sätt GAMES_BATCH_SIZE=10 i .env och kör om för att minska minnesanvändning."
fi

START_YEAR_ENV="${GAMES_START_DATE:0:4}"
if [ "$START_YEAR_ENV" -gt "$START_YEAR" ]; then
  err "GAMES_START_DATE=$GAMES_START_DATE filtrerar bort år $START_YEAR."
  err "Sätt GAMES_START_DATE=2010-01-01 i .env."
  exit 1
fi

# -----------------------------------------------------------------------
# Hjälpfunktioner
container_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER}$"
}

wait_for_mage() {
  local max=60
  local i=0
  log "Väntar på att Mage startar (max ${max}s)..."
  while [ $i -lt $max ]; do
    if docker exec "$CONTAINER" bash -c "test -f /home/src/mage_project/metadata.yaml" 2>/dev/null; then
      log "Mage redo."
      return 0
    fi
    sleep 2
    i=$((i+2))
  done
  err "Mage startade inte inom ${max}s."
  return 1
}

year_done() {
  local year="$1"
  grep -q "^DONE:${year}$" "$PROGRESS_FILE" 2>/dev/null
}

mark_done() {
  local year="$1"
  echo "DONE:${year}" >> "$PROGRESS_FILE"
  log "År $year markerat som klart i $PROGRESS_FILE"
}

# -----------------------------------------------------------------------
log "Startar Docker-tjänsterna om de inte körs..."
if ! container_running; then
  (cd "$ROOT" && docker compose up -d --build)
  wait_for_mage
fi

# -----------------------------------------------------------------------
# Huvud-loop: år för år
for YEAR in $(seq "$START_YEAR" "$END_YEAR"); do
  if year_done "$YEAR"; then
    log "År $YEAR redan klart (progress-fil) – hoppar över."
    continue
  fi

  log "─────────────────────────────────────────"
  log "Laddar år $YEAR..."

  # Sätt games_year.txt (har företräde över .env i loadern)
  echo "$YEAR" > "${STATE_DIR}/games_year.txt"
  log "games_year.txt = $YEAR"

  # Starta om containern för att frigöra minne från föregående år
  log "Startar om Mage-containern (frigör minne)..."
  (cd "$ROOT" && docker compose restart mage)
  sleep 5
  wait_for_mage

  # Kör games_pipeline
  log "Kör games_pipeline för $YEAR..."
  if docker exec "$CONTAINER" bash -c \
      "cd /home/src && mage run mage_project games_pipeline" \
      2>&1 | tee -a "$LOG_FILE"; then
    mark_done "$YEAR"
    log "År $YEAR klart. Nästa år: $((YEAR+1))"
  else
    err "games_pipeline misslyckades för år $YEAR (exit $?)."
    err "Kontrollera loggen: $LOG_FILE"
    err "Åtgärd: rätta felet och kör om scriptet – redan klarade år skippas."
    # Rensa games_year.txt så inte nästa manuell körning fastnar på detta år
    rm -f "${STATE_DIR}/games_year.txt"
    exit 1
  fi

  # Ge containern lite andrum mellan år
  sleep 3
done

# -----------------------------------------------------------------------
# Rensa games_year.txt → dagligt inkrementellt läge
rm -f "${STATE_DIR}/games_year.txt"
log "games_year.txt borttagen – nu i inkrementellt dagligt läge."

log "═══════════════════════════════════════════"
log "Historisk laddning klar: ${START_YEAR}–${END_YEAR}"
log "Validera med:"
log "  docker exec $CONTAINER bash -c 'cd /home/src && python scripts/compare_bronze_silver_volume.py'"
log "  python scripts/validate_motherduck.py"
log "═══════════════════════════════════════════"
