"""Run bounded, naturally finishing WRF trials; compare every saved field.

This changes only MPI process count between trials. Never runs in, overwrites,
or stops the source case. Short-run equivalence is not a full forecast test.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from time import perf_counter

import numpy as np
import xarray as xr

from weather_sim.simulation.metgrid_cache import digest
from weather_sim.simulation.runtime_cache import TABLE_NAMES


def bounded_namelist(text: str, minutes: int, domains: int) -> str:
    if not 15 <= minutes <= 180:
        raise ValueError("benchmark duration must be 15..180 minutes")
    def value(key: str) -> int:
        return int(re.search(rf"^\s*{key}\s*=\s*(\d+)", text, re.M).group(1))
    start = datetime(*(value('start_' + key) for key in ('year', 'month', 'day', 'hour', 'minute', 'second')))
    end = start + timedelta(minutes=minutes)
    replacements = dict(run_days='0', run_hours='0', run_minutes=str(minutes), run_seconds='0',
                        history_interval=', '.join(['10'] * domains))
    for key in ('year', 'month', 'day', 'hour', 'minute', 'second'):
        replacements['end_' + key] = ', '.join([str(getattr(end, key))] * domains)
    for key, value_text in replacements.items():
        text, count = re.subn(rf"^\s*{key}\s*=.*$", f" {key} = {value_text},", text, flags=re.M)
        if count != 1:
            raise ValueError(f"expected one {key} in namelist")
    return text


def compare_outputs(reference: Path, candidate: Path) -> dict:
    differences = {}
    checked = 0
    names = sorted(p.name for p in reference.glob('wrfout_d0*'))
    if not names or names != sorted(p.name for p in candidate.glob('wrfout_d0*')):
        raise ValueError('output domain/file mismatch')
    for name in names:
        with xr.open_dataset(reference / name, decode_times=False) as a, xr.open_dataset(candidate / name, decode_times=False) as b:
            if dict(a.sizes) != dict(b.sizes) or set(a.variables) != set(b.variables):
                raise ValueError(f'output schema mismatch: {name}')
            for field in a.variables:
                for i in range(a.sizes['Time'] if 'Time' in a[field].dims else 1):
                    av = a[field].isel(Time=i).values if 'Time' in a[field].dims else a[field].values
                    bv = b[field].isel(Time=i).values if 'Time' in b[field].dims else b[field].values
                    checked += 1
                    if np.issubdtype(av.dtype, np.number):
                        if not np.array_equal(av, bv, equal_nan=True):
                            key = f'{name}/{field}'
                            delta = np.abs(av.astype(np.float64) - bv.astype(np.float64))
                            finite = np.isfinite(delta)
                            record = differences.setdefault(key, {'max_abs': 0., 'nonfinite_difference_cells': 0})
                            record['max_abs'] = max(record['max_abs'], float(delta[finite].max()) if finite.any() else 0.)
                            record['nonfinite_difference_cells'] += int((~finite).sum())
                    elif not np.array_equal(av, bv):
                        raise ValueError(f'non-numeric field differs: {name}/{field}')
    return {'checked_field_frames': checked, 'all_saved_values_equal': not differences, 'differences': differences}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--processes', type=int, nargs='+', default=[4, 6, 8])
    parser.add_argument('--minutes', type=int, default=30)
    args = parser.parse_args()
    if any(n < 1 for n in args.processes) or len(set(args.processes)) != len(args.processes):
        parser.error('processes must be positive and unique')
    source = args.case.resolve() / 'wrf_run'
    manifest = json.loads((args.case / 'case.json').read_text())
    namelist = bounded_namelist((source / 'namelist.input').read_text(), args.minutes, len(manifest['configuration']['domains']))
    runtime = source.joinpath('wrf.exe').resolve().parent.parent / 'run'
    if not runtime.is_dir():
        raise ValueError(f'WRF installed runtime is missing: {runtime}')
    # Read-only installed runtime inputs; actual forecast inputs are copied.
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'source': str(source), 'minutes': args.minutes, 'binary_sha256': digest(source / 'wrf.exe'), 'trials': []}
    reference = None
    for processes in args.processes:
        directory = (args.output / f'mpi_{processes}').resolve()
        directory.mkdir()
        for path in runtime.iterdir():
            if path.is_file() and path.name != 'namelist.input' and not path.name.startswith(('wrfout', 'rsl.', 'wrfinput', 'wrfbdy', 'wrffdda', 'wrfrst')):
                (directory / path.name).symlink_to(path.resolve())
        for pattern in ('wrfinput_d0*', 'wrfbdy_d01', 'wrffdda_d0*', *TABLE_NAMES):
            for path in source.glob(pattern):
                target = directory / path.name
                if target.is_symlink():
                    target.unlink()
                shutil.copyfile(path, target)
        (directory / 'namelist.input').write_text(namelist)
        env = os.environ.copy()
        env['OMPI_MCA_btl'] = 'self,vader'
        print(f'Running MPI={processes}, planned duration={args.minutes} model minutes', flush=True)
        with (directory / 'launch.log').open('w') as log:
            started = perf_counter()
            result = subprocess.run(['mpirun', '-np', str(processes), str(directory / 'wrf.exe')], cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT)
            elapsed = perf_counter() - started
        content = '\n'.join(p.read_text(errors='replace') for p in directory.glob('rsl.error.*'))
        if result.returncode or 'SUCCESS COMPLETE WRF' not in content or re.search(r'\b(CFL|FATAL|NaN)\b', content, re.I):
            raise RuntimeError(f'WRF trial failed; see {directory}')
        if reference is None:
            reference = directory
        comparison = compare_outputs(reference, directory)
        trial = {'processes': processes, 'elapsed_seconds': elapsed, **comparison}
        report['trials'].append(trial)
        (args.output / 'benchmark.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in trial.items() if key != 'differences'}), flush=True)


if __name__ == '__main__':
    main()
