#!/usr/bin/env bash
# Deploy lokala mage_project-ändringar till Coolify-containern.
#
# Användning:
#   ./scripts/deploy_to_coolify.sh               # kopiera all kod, rör inte state/data_lake
#   ./scripts/deploy_to_coolify.sh --with-state  # kopiera även state/
#   ./scripts/deploy_to_coolify.sh --scripts-only
#   ./scripts/deploy_to_coolify.sh --restart     # restart efter sync (default: bara sync)
#
# Kräver: ssh tha fungerar, mage_project/ ligger i cwd.

set -euo pipefail

SSH_HOST="${COOLIFY_SSH_HOST:-tha}"
CONTAINER="${COOLIFY_MAGE_CONTAINER:-mage-k0oooc8ok4848880sk0g0kkc}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

WITH_STATE=0
SCRIPTS_ONLY=0
RESTART=0

for arg in "$@"; do
  case "$arg" in
    --with-state) WITH_STATE=1 ;;
    --scripts-only) SCRIPTS_ONLY=1 ;;
    --restart) RESTART=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

TS="$(date +%s)"
TARBALL="/tmp/mage_deploy_${TS}.tar.gz"

cd "$ROOT"

echo "==> Creating tarball at $TARBALL"
if [[ $SCRIPTS_ONLY -eq 1 ]]; then
  tar czf "$TARBALL" \
    --exclude='__pycache__' --exclude='.DS_Store' --exclude='*.pyc' \
    scripts/
else
  EXCLUDES=(
    --exclude='mage_project/data_lake'
    --exclude='mage_project/.ssh_tunnel'
    --exclude='__pycache__'
    --exclude='.DS_Store'
    --exclude='*.pyc'
  )
  if [[ $WITH_STATE -eq 0 ]]; then
    EXCLUDES+=(--exclude='mage_project/state')
  fi
  tar czf "$TARBALL" "${EXCLUDES[@]}" \
    mage_project/ \
    scripts/
fi

SIZE=$(ls -lh "$TARBALL" | awk '{print $5}')
echo "    size: $SIZE"

echo "==> Uploading to $SSH_HOST"
scp -q "$TARBALL" "$SSH_HOST:$TARBALL"

echo "==> Extracting into container $CONTAINER"
ssh "$SSH_HOST" "docker cp $TARBALL $CONTAINER:$TARBALL"
ssh "$SSH_HOST" "docker exec $CONTAINER sh -c '
  cd /home/src && \
  tar xzf $TARBALL && \
  find /home/src/mage_project -name \"._*\" -delete 2>/dev/null || true; \
  find /home/src/scripts -name \"._*\" -delete 2>/dev/null || true; \
  chown -R root:root /home/src/mage_project /home/src/scripts && \
  rm $TARBALL
'"

echo "==> Cleaning up local tarball on server"
ssh "$SSH_HOST" "rm -f $TARBALL"
rm -f "$TARBALL"

if [[ $RESTART -eq 1 ]]; then
  echo "==> Restarting container $CONTAINER"
  ssh "$SSH_HOST" "docker restart $CONTAINER"
  echo "    waiting for Mage to be ready..."
  for i in $(seq 1 30); do
    if curl -sf -o /dev/null https://mage.theunnamedroads.com/; then
      echo "    Mage is up (after ${i}s)."
      break
    fi
    sleep 1
  done
fi

echo ""
echo "Done. Mage UI: https://mage.theunnamedroads.com/"
if [[ $RESTART -eq 0 ]]; then
  echo "Tip: pipeline changes require 'docker restart $CONTAINER' to be seen by Mage."
  echo "     Run this script with --restart next time, or run:"
  echo "       ssh $SSH_HOST \"docker restart $CONTAINER\""
fi
