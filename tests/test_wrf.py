import numpy as np
import pytest
import xarray as xr

from weather_sim.analysis.wrf import open_wrfout


def test_open_wrfout_derives_temperature_wind_and_precipitation(tmp_path) -> None:
    path = tmp_path / "wrfout_d03_test"
    dims = ("Time", "south_north", "west_east")
    times = np.array([list("2024-01-01_00:00:00"), list("2024-01-01_00:10:00")], dtype="S1")
    dataset = xr.Dataset(
        {
            "Times": (("Time", "DateStrLen"), times),
            "XLAT": (dims, np.array([[[35, 35], [36, 36]]] * 2)),
            "XLONG": (dims, np.array([[[139, 140], [139, 140]]] * 2)),
            "T2": (dims, np.full((2, 2, 2), 293.15)),
            "U10": (dims, np.full((2, 2, 2), 3.0)),
            "V10": (dims, np.full((2, 2, 2), 4.0)),
            "PSFC": (dims, np.full((2, 2, 2), 100000.0)),
            "Q2": (dims, np.full((2, 2, 2), 0.01)),
            "TSK": (dims, np.full((2, 2, 2), 295.15)),
            "RAINC": (dims, np.array([np.zeros((2, 2)), np.ones((2, 2))])),
            "RAINNC": (dims, np.array([np.zeros((2, 2)), np.ones((2, 2))])),
        }
    )
    dataset.to_netcdf(path)
    opened = open_wrfout(path)
    try:
        assert opened["temperature_2m_c"].isel(Time=0, south_north=0, west_east=0).item() == 20.0
        assert opened["wind_speed_10m_ms"].isel(Time=0, south_north=0, west_east=0).item() == 5.0
        assert opened["wind_direction_10m_deg"].isel(Time=0, south_north=0, west_east=0).item() == pytest.approx(216.87, abs=0.01)
        assert opened["surface_pressure_hpa"].isel(Time=0, south_north=0, west_east=0).item() == 1000
        assert opened["skin_temperature_c"].isel(Time=0, south_north=0, west_east=0).item() == 22
        assert 60 < opened["relative_humidity_2m_percent"].isel(Time=0, south_north=0, west_east=0).item() < 100
        assert opened["precipitation_interval_mm"].isel(Time=1, south_north=0, west_east=0).item() == 2.0
    finally:
        opened.close()
