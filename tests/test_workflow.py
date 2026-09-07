from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from weather_sim.config import load_config
from weather_sim.errors import ExternalCommandError
from weather_sim.simulation.workflow import _validate_metgrid_inputs


def test_run_case_refuses_to_overwrite_previous_run(tmp_path: Path) -> None:
    from weather_sim.simulation.workflow import run_case
    case = tmp_path / "output/existing"
    (case / "wrf_run").mkdir(parents=True)
    manifest = case / "case.json"
    manifest.write_text('{"original": true}')
    with pytest.raises(ExternalCommandError, match="new --case-name"):
        run_case(load_config("config/case_20260904.yaml"), tmp_path, case_name="existing")
    assert manifest.read_text() == '{"original": true}'


def _write_met_em(directory: Path, soil_temperature_k: float) -> None:
    config = load_config("config/case_20260901.yaml")
    dataset = xr.Dataset(
        {
            "ST": (("Time", "num_st_layers", "y", "x"), np.full((1, 4, 2, 2), soil_temperature_k)),
            "LANDSEA": (("Time", "y", "x"), np.ones((1, 2, 2))),
            "TT": (("Time", "num_metgrid_levels", "y", "x"), np.full((1, 2, 2, 2), 298.0)),
            "RH": (("Time", "num_metgrid_levels", "y", "x"), np.full((1, 2, 2, 2), 60.0)),
        }
    )
    for timestamp in pd.date_range(config.simulation_start_utc, config.simulation_end_utc,
                                   freq=pd.Timedelta(seconds=config.wrf.input_interval_seconds)):
        for domain in range(1, len(config.domains) + 1):
            dataset.to_netcdf(directory / f"met_em.d{domain:02d}.{timestamp:%Y-%m-%d_%H:%M:%S}.nc")


def test_metgrid_soil_temperature_validation_accepts_physical_values(tmp_path: Path) -> None:
    config = load_config("config/case_20260901.yaml")
    _write_met_em(tmp_path, 300.0)

    _validate_metgrid_inputs(tmp_path, config)


def test_metgrid_soil_temperature_validation_rejects_zero_kelvin(tmp_path: Path) -> None:
    config = load_config("config/case_20260901.yaml")
    _write_met_em(tmp_path, 0.0)

    with pytest.raises(ExternalCommandError, match="invalid metgrid land soil temperature"):
        _validate_metgrid_inputs(tmp_path, config)


def test_metgrid_validation_checks_late_parent_file_and_partial_nan(tmp_path: Path) -> None:
    config = load_config("config/case_20260901.yaml")
    _write_met_em(tmp_path, 300.)
    last = sorted(tmp_path.glob("met_em.d01.*"))[-1]
    with xr.open_dataset(last) as source:
        corrupt = source.load()
    corrupt["ST"][0, 0, 0, 0] = np.nan
    corrupt.to_netcdf(last)
    with pytest.raises(ExternalCommandError, match="non-finite"):
        _validate_metgrid_inputs(tmp_path, config)
    last.unlink()
    with pytest.raises(ExternalCommandError, match="expected input"):
        _validate_metgrid_inputs(tmp_path, config)


def test_metgrid_ocean_soil_mask_and_small_supersaturation(tmp_path: Path) -> None:
    from weather_sim.simulation.input_validation import validate_metgrid_file
    _write_met_em(tmp_path, 300.)
    path = next(tmp_path.glob("met_em*"))
    with xr.open_dataset(path) as source:
        dataset = source.load()
    dataset["LANDSEA"][:] = 0.
    dataset["ST"][:] = np.nan
    dataset["RH"][:] = 100.1
    dataset.to_netcdf(path)
    validate_metgrid_file(path)
    dataset["TT"][0, 0, 0, 0] = np.nan
    dataset.to_netcdf(path)
    with pytest.raises(ExternalCommandError, match="non-finite"):
        validate_metgrid_file(path)


@pytest.mark.parametrize("returncode", [0, 1])
def test_command_timing_preserves_failure_diagnostics(tmp_path: Path, monkeypatch, returncode: int) -> None:
    import json
    import subprocess
    from datetime import datetime
    from weather_sim.simulation import workflow

    # Mock the subprocess: this test must never launch WRF or WPS.
    monkeypatch.setattr(workflow.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], returncode))
    ticks = iter([10.0, 12.5])
    monkeypatch.setattr(workflow, "perf_counter", lambda: next(ticks))
    (tmp_path / "rsl.error.0000").write_text("fatal diagnostic")
    if returncode:
        with pytest.raises(ExternalCommandError, match="rsl-error.txt"):
            workflow._run(["mock-model"], tmp_path, "stage.log")
        assert (tmp_path / "stage.log.rsl-error.txt").read_text() == "fatal diagnostic"
    else:
        workflow._run(["mock-model"], tmp_path, "stage.log")
    timing = json.loads((tmp_path / "stage.log.timing.json").read_text())
    assert timing["elapsed_seconds"] == 2.5
    assert timing["returncode"] == returncode
    assert datetime.fromisoformat(timing["started_at_utc"]).utcoffset().total_seconds() == 0
