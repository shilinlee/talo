#!/usr/bin/env bash
set -euo pipefail

: "${HOST:?HOST is required}"
: "${REMOTE_CMD:?REMOTE_CMD is required}"

exec ssh "$HOST" "$REMOTE_CMD"
