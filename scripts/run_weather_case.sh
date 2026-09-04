#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
  echo "usage: $0 START END [run-case options]" >&2
  echo "example: $0 '2026-09-01 15:00' '2026-09-01 21:00'" >&2
  exit 2
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
START=$1
END=$2
shift 2

cd "$ROOT"
UV_CACHE_DIR="$ROOT/.uv-cache" exec uv run weather-sim run-case \
  --start "$START" \
  --end "$END" \
  "$@"
