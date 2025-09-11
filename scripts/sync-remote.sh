#!/usr/bin/env bash
set -euo pipefail

# Usage: scripts/sync-remote.sh [user@host] [remote_path]
# Defaults: root@dev-wlanpi3 /tmp/pycharm_project_880

REMOTE_HOST="${1:-root@dev-wlanpi3}"
REMOTE_PATH="${2:-/tmp/pycharm_project_880}"

EXCLUDES=(
  ".git"
  "__pycache__"
  ".pytest_cache"
  "*.pyc"
  "dist"
  "build"
  ".mypy_cache"
  ".idea"
)

echo "Ensuring remote directory: ${REMOTE_HOST}:${REMOTE_PATH}"
ssh "${REMOTE_HOST}" "mkdir -p '${REMOTE_PATH}'"

if command -v rsync >/dev/null 2>&1; then
  echo "Syncing via rsync..."
  RSYNC_EXCLUDES=()
  for p in "${EXCLUDES[@]}"; do
    RSYNC_EXCLUDES+=("--exclude" "$p")
  done
  rsync -az ${RSYNC_EXCLUDES[@]} ./ "${REMOTE_HOST}:${REMOTE_PATH}/"
else
  echo "rsync not found; falling back to tar over ssh..."
  TAR_EXCLUDES=()
  for p in "${EXCLUDES[@]}"; do
    TAR_EXCLUDES+=("--exclude=$p")
  done
  tar cz ${TAR_EXCLUDES[@]} -C . . | ssh "${REMOTE_HOST}" "tar xz -C '${REMOTE_PATH}'"
fi

echo "Sync complete."

