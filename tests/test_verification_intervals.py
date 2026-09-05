import numpy as np
import pandas as pd
import pytest
import xarray as xr

from weather_sim.analysis.observation_verification import VARIABLES, _model_series


def test_rain_rate_retains_interval_when_analysis_is_sliced() -> None:
    times = pd.date_range("2026-09-04T03:00Z", periods=2, freq="10min")
    dataset = xr.Dataset({
        "precipitation_interval_mm": (("Time", "south_north", "west_east"), np.array([[[1.0]], [[2.0]]])),
        "precipitation_interval_hours": ("Time", [1/6, 1/6]),
        "XLAT": (("south_north", "west_east"), [[35.0]]),
        "XLONG": (("south_north", "west_east"), [[139.0]]),
    }, coords={"Time": times})
    series, _ = _model_series(dataset.isel(Time=slice(1, None)), VARIABLES[-1], 35.0, 139.0)
    assert series.iloc[0] == pytest.approx(12.0)
