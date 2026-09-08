import importlib.util
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from weather_sim.config import load_config
from weather_sim.simulation.namelists import render_namelist_input

spec = importlib.util.spec_from_file_location('benchmark_mpi', Path(__file__).parents[1] / 'scripts/benchmark_mpi.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_bounded_benchmark_crosses_day_without_changing_physics():
    original = render_namelist_input(load_config('config/msm_guided_solar.yaml'))
    original = original.replace('start_hour = 21, 21, 21,', 'start_hour = 23, 23, 23,')
    bounded = benchmark.bounded_namelist(original, 90, 3)
    assert 'end_hour = 0, 0, 0,' in bounded
    assert 'end_day = 4, 4, 4,' in bounded
    assert 'end_minute = 30, 30, 30,' in bounded
    assert 'run_minutes = 90,' in bounded
    assert original.split('&physics')[1] == bounded.split('&physics')[1]
    with pytest.raises(ValueError, match='15..180'):
        benchmark.bounded_namelist(original, 0, 3)


def test_mpi_comparison_detects_small_field_difference_and_missing_domain(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    data = xr.Dataset({'T2': (('Time', 'y', 'x'), np.ones((2, 2, 2)))})
    data.to_netcdf(a / 'wrfout_d01_test')
    data.to_netcdf(b / 'wrfout_d01_test')
    assert benchmark.compare_outputs(a, b)['all_saved_values_equal']
    data.T2[1, 0, 1] += 1e-9
    data.to_netcdf(b / 'wrfout_d01_test')
    assert not benchmark.compare_outputs(a, b)['all_saved_values_equal']
    data.to_netcdf(b / 'wrfout_d02_test')
    with pytest.raises(ValueError, match='mismatch'):
        benchmark.compare_outputs(a, b)
