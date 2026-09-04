#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 CASE_DIRECTORY [evaluate-case options]" >&2
  exit 2
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CASE_DIRECTORY=$1
shift

cd "$ROOT"
UV_CACHE_DIR="$ROOT/.uv-cache" exec uv run weather-sim evaluate-case "$CASE_DIRECTORY" "$@"
