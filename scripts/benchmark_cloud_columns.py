"""Compare cloud-column runtime and exact values against a saved Python source."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import xarray as xr

from weather_sim.analysis.atmosphere import cloud_columns


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wrfout', type=Path)
    parser.add_argument('--reference-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start-index', type=int, default=36)
    parser.add_argument('--frames', type=int, default=49)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1 or args.frames < 1 or args.start_index < 0:
        parser.error('invalid repeats/frame selection')
    spec = importlib.util.spec_from_file_location('reference_atmosphere', args.reference_source)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    timings = {'reference': [], 'optimized': []}
    results = {}
    for repeat in range(args.repeats):
        order = [('reference', reference.cloud_columns), ('optimized', cloud_columns)]
        if repeat % 2:
            order.reverse()
        for label, function in order:
            with xr.open_dataset(args.wrfout, decode_times=False) as raw:
                data = raw.isel(Time=slice(args.start_index, args.start_index + args.frames))
                if data.sizes['Time'] != args.frames:
                    raise ValueError('requested frames not present')
                start = perf_counter()
                result = function(data)
                timings[label].append(perf_counter() - start)
                results[label] = result
        for field in results['reference']:
            a, b = results['reference'][field].values, results['optimized'][field].values
            if a.dtype != b.dtype or not np.array_equal(a, b, equal_nan=True):
                raise AssertionError(f'cloud-column values changed: {field}')
    medians = {key: float(np.median(values)) for key, values in timings.items()}
    report = {'frames': args.frames, 'repeats': args.repeats, 'all_six_products_exactly_equal': True,
              'times_seconds': timings, 'medians_seconds': medians,
              'reduction_percent': 100 * (1 - medians['optimized'] / medians['reference'])}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
