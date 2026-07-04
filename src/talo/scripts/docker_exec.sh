#!/usr/bin/env bash
set -euo pipefail

: "${HOST:?HOST is required}"
: "${CONTAINER:?CONTAINER is required}"
: "${REMOTE_WORKSPACE:?REMOTE_WORKSPACE is required}"
: "${ENV_SHELL:=bash}"
: "${DOCKER_CMD:?DOCKER_CMD is required}"

remote_cmd=$(printf 'docker exec -w %q -i %q %q -lc %q' \
  "$REMOTE_WORKSPACE" "$CONTAINER" "$ENV_SHELL" "$DOCKER_CMD")

exec ssh "$HOST" "$remote_cmd"
