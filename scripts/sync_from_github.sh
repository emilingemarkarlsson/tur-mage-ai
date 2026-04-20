#!/usr/bin/env bash
# Synka Coolify-containerns kod från GitHub via `git pull`.
#
# Förutsätter:
# - Du har pushat lokala ändringar till GitHub först (git push origin main)
# - Git-repot är initialiserat i /home/src inuti containern (gjort vid migreringen)
# - Repot är publikt (ingen auth behövs för pull). För privat repo: sätt GIT_ACCESS_TOKEN i Coolify.
#
# Användning:
#   ./scripts/sync_from_github.sh              # pull senaste main, ingen restart
#   ./scripts/sync_from_github.sh --restart    # pull + restart container (för nya pipelines)
#   ./scripts/sync_from_github.sh --branch dev # pull annan branch
#
# Exempel-flöde vid utveckling:
#   1. Redigera i mage_project/ lokalt
#   2. git add . && git commit -m "..." && git push
#   3. ./scripts/sync_from_github.sh --restart
#   4. Se ändringarna på https://mage.theunnamedroads.com/

set -euo pipefail

SSH_HOST="${COOLIFY_SSH_HOST:-tha}"
CONTAINER="${COOLIFY_MAGE_CONTAINER:-mage-k0oooc8ok4848880sk0g0kkc}"
BRANCH="main"
RESTART=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) RESTART=1 ;;
    --branch) BRANCH="$2"; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
  shift
done

echo "==> Pulling branch '$BRANCH' inside $CONTAINER"
ssh "$SSH_HOST" "docker exec $CONTAINER bash -c '
  set -e
  cd /home/src
  git fetch origin $BRANCH --depth=1
  LOCAL=\$(git rev-parse HEAD)
  REMOTE=\$(git rev-parse origin/$BRANCH)
  if [ \"\$LOCAL\" = \"\$REMOTE\" ]; then
    echo \"    Already up to date (\$LOCAL)\"
  else
    # Stash eventuella oommitted ändringar som gjorts i UI
    HAS_CHANGES=\$(git status --porcelain | wc -l)
    if [ \"\$HAS_CHANGES\" -gt 0 ]; then
      echo \"    Stashing \$HAS_CHANGES uncommitted change(s) from container\"
      git stash push -u -m \"auto-stash before pull \$(date -Iseconds)\"
    fi
    git reset --hard origin/$BRANCH
    echo \"    Pulled: \$LOCAL → \$REMOTE\"
    if [ \"\$HAS_CHANGES\" -gt 0 ]; then
      echo \"    Note: uncommitted ändringar finns i git stash (inte borta)\"
      echo \"          kör: docker exec $CONTAINER git -C /home/src stash list\"
    fi
  fi
'"

if [[ $RESTART -eq 1 ]]; then
  echo "==> Restarting container $CONTAINER"
  ssh "$SSH_HOST" "docker restart $CONTAINER" >/dev/null
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
  echo "Tip: nya pipelines kräver restart för att synas – kör med --restart."
fi
