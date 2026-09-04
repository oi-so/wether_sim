from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from weather_sim.config import load_config
from weather_sim.errors import ExternalCommandError
from weather_sim.simulation.workflow import _validate_metgrid_inputs


def _write_met_em(directory: Path, soil_temperature_k: float) -> None:
    config = load_config("config/case_20260901.yaml")
    timestamp = config.simulation_start_utc.replace(tzinfo=None)
    path = directory / f"met_em.d03.{timestamp:%Y-%m-%d_%H:%M:%S}.nc"
    xr.Dataset(
        {
            "ST": (("Time", "num_st_layers", "y", "x"), np.full((1, 4, 2, 2), soil_temperature_k)),
            "LANDSEA": (("Time", "y", "x"), np.ones((1, 2, 2))),
            "TT": (("Time", "num_metgrid_levels", "y", "x"), np.full((1, 2, 2, 2), 298.0)),
            "RH": (("Time", "num_metgrid_levels", "y", "x"), np.full((1, 2, 2, 2), 60.0)),
        }
    ).to_netcdf(path)


def test_metgrid_soil_temperature_validation_accepts_physical_values(tmp_path: Path) -> None:
    config = load_config("config/case_20260901.yaml")
    _write_met_em(tmp_path, 300.0)

    _validate_metgrid_inputs(tmp_path, config)


def test_metgrid_soil_temperature_validation_rejects_zero_kelvin(tmp_path: Path) -> None:
    config = load_config("config/case_20260901.yaml")
    _write_met_em(tmp_path, 0.0)

    with pytest.raises(ExternalCommandError, match="invalid metgrid land soil temperature"):
        _validate_metgrid_inputs(tmp_path, config)
