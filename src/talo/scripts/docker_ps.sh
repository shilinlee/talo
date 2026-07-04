#!/usr/bin/env bash
set -euo pipefail

: "${HOST:?HOST is required}"

remote_cmd="docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'"
exec ssh "$HOST" "$remote_cmd"
