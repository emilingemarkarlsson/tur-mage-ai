#!/usr/bin/env bash
# Pull new GHCR image into Coolify Mage-container and restart.
#
# Kräver att GitHub Actions har byggt och pushat ny image till GHCR
# (via .github/workflows/docker-build.yml).
#
# Användning:
#   ./scripts/deploy_image_to_coolify.sh                # latest
#   ./scripts/deploy_image_to_coolify.sh --tag sha-abc  # specifik build

set -euo pipefail

SSH_HOST="${COOLIFY_SSH_HOST:-tha}"
CONTAINER="${COOLIFY_MAGE_CONTAINER:-mage-k0oooc8ok4848880sk0g0kkc}"
IMAGE="ghcr.io/emilingemarkarlsson/tur-mage-ai"
TAG="latest"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="$2"; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
  shift
done

FULL_IMAGE="${IMAGE}:${TAG}"
echo "==> Pulling $FULL_IMAGE on $SSH_HOST"
ssh "$SSH_HOST" "docker pull $FULL_IMAGE"

echo "==> Restarting $CONTAINER"
# Get current image hash (so we know if anything actually changed)
BEFORE=$(ssh "$SSH_HOST" "docker inspect --format '{{.Image}}' $CONTAINER" | cut -c1-16)
echo "    before: $BEFORE"

# Restart makes Coolify's compose re-evaluate image
ssh "$SSH_HOST" "docker restart $CONTAINER" >/dev/null

# Note: docker restart does NOT pull new image tag automatically.
# To force the container to use the new image, we need to recreate it.
# Coolify's redeploy flow handles this. For manual use:
echo ""
echo "OBS: 'docker restart' använder SAMMA image som containern kör nu."
echo "För att containern ska plocka upp nya GHCR-image:n behöver du antingen:"
echo ""
echo "  1. Trigga Coolify redeploy via API:"
echo "     ssh $SSH_HOST \"curl -H 'Authorization: Bearer \\\$(cat ~/.coolify-token)' \\\\"
echo "       http://localhost:8000/api/v1/services/k0oooc8ok4848880sk0g0kkc/restart\""
echo ""
echo "  2. Eller manuellt via Coolify UI:"
echo "     https://<coolify-ui>/projects/theunnamedroads/service/k0oooc8ok4848880sk0g0kkc"
echo "     → klick 'Redeploy'"
echo ""
echo "  3. Eller recreate via docker (behåller volymer):"
echo "     ssh $SSH_HOST 'docker compose -f /data/coolify/services/<uuid>/docker-compose.yml up -d --force-recreate mage'"

for i in $(seq 1 30); do
  if curl -sf -o /dev/null https://mage.theunnamedroads.com/; then
    echo ""
    echo "Mage is up (restart done after ${i}s)."
    break
  fi
  sleep 1
done
