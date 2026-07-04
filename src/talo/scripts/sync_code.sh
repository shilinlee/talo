#!/usr/bin/env bash
set -euo pipefail

: "${HOST:?HOST is required}"
: "${LOCAL_ROOT:?LOCAL_ROOT is required}"
: "${REMOTE_WORKSPACE:?REMOTE_WORKSPACE is required}"

if [[ ! -d "$LOCAL_ROOT" ]]; then
  echo "sync_code: local root not found: $LOCAL_ROOT" >&2
  exit 1
fi

printf 'sync_code: local_root=%s\n' "$LOCAL_ROOT"
printf 'sync_code: remote_workspace=%s:%s\n' "$HOST" "$REMOTE_WORKSPACE"

# First sync creates the remote workspace. Later syncs let rsync update/add/delete files.
remote_mkdir=$(printf 'mkdir -p %q' "$REMOTE_WORKSPACE")
ssh "$HOST" "$remote_mkdir"

rsync -az --delete \
  --exclude='.git/' \
  --exclude='.talo/' \
  --exclude='.envhub/' \
  --exclude='.talo-runs/' \
  --exclude='.envhub-runs/' \
  --exclude='node_modules/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --filter=':- .gitignore' \
  "$LOCAL_ROOT/" \
  "$HOST:$REMOTE_WORKSPACE/"

printf 'sync_code: done\n'
