#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUN_DIR="$ROOT/output/case_20260901/wrf_run"
RESULT_DIR="$ROOT/output/case_20260901/analysis"
WRF_PROCESSES=${WRF_PROCESSES:-4}

if [ ! -x "$RUN_DIR/real.exe" ] || [ ! -x "$RUN_DIR/wrf.exe" ]; then
  echo "WRF executables are missing from $RUN_DIR" >&2
  exit 1
fi

cd "$RUN_DIR"
env OMPI_MCA_btl=self,vader ./real.exe
env OMPI_MCA_btl=self,vader mpirun -np "$WRF_PROCESSES" ./wrf.exe

cd "$ROOT"
UV_CACHE_DIR="$ROOT/.uv-cache" uv run weather-sim analyze \
  config/case_20260901.yaml \
  --wrfout "$RUN_DIR/wrfout_d03_2026-09-01_00:00:00" \
  --observations data/observations/case_20260901.csv \
  --station-id school \
  --reference-station-id amedas_fuchu \
  --output-dir "$RESULT_DIR" \
  --animation

echo "Completed. Results: $RESULT_DIR"
