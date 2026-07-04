#!/usr/bin/env bash
set -euo pipefail

: "${HOST:?HOST is required}"
: "${LOCAL_PATH:?LOCAL_PATH is required}"
: "${REMOTE_PATH:?REMOTE_PATH is required}"

exec rsync -az "$LOCAL_PATH" "$HOST:$REMOTE_PATH"
