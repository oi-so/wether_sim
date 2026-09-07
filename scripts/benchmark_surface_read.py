"""Benchmark station surface caching and assert exact numerical equivalence.

Run with: uv run python scripts/benchmark_surface_read.py CASE --output JSON
No WRF/WPS process is launched. Both paths use the same corrected diagnostics.
"""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import numpy as np

from weather_sim.analysis.wrf import open_wrfout
from weather_sim.case_operations import load_case, find_inner_wrfout
from weather_sim.observations.csv_reader import read_observations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    case = load_case(args.case)
    observations = read_observations(case.directory / "observations/observations.csv")
    stations = observations.loc[observations.is_valid, ["latitude", "longitude"]].drop_duplicates()
    points = list(stations.itertuples(index=False, name=None))
    if not points:
        raise ValueError("no valid stations for station-read benchmark")
    path = find_inner_wrfout(case)

    def read(cached):
        context = nullcontext() if cached else patch("weather_sim.analysis.wrf._load_station_surface")
        with context:
            started = perf_counter()
            with open_wrfout(path, points=points) as ds:
                names = [name for name in ds.data_vars if name.endswith(
                    ("_c", "_ms", "_deg", "_hpa", "_percent", "_mm", "_hours"))]
                values = {name: ds[name].values.copy() for name in names}
            return perf_counter() - started, values

    read(False)
    read(True)
    timings = {"before": [], "after": []}
    for i in range(7):
        outputs = {}
        for cached in ([False, True] if i % 2 == 0 else [True, False]):
            elapsed, values = read(cached)
            timings["after" if cached else "before"].append(elapsed)
            outputs[cached] = values
        assert outputs[False].keys() == outputs[True].keys()
        for name in outputs[False]:
            np.testing.assert_array_equal(outputs[False][name], outputs[True][name], err_msg=name)
    result = {"seconds": timings, "median_seconds": {k: float(np.median(v)) for k, v in timings.items()},
              "exactly_equal_fields": sorted(outputs[True]), "samples": 7,
              "scope": "station rectangle read and derived fields, not WRF integration"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
