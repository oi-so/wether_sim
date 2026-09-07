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
        vapor_pressure = 0.01 * 100000 / (0.622 + 0.01)
        saturation = 611.2 * np.exp(17.67 * 20 / (293.15 - 29.65))
        assert opened["relative_humidity_2m_percent"].isel(Time=0, south_north=0, west_east=0).item() == pytest.approx(100 * vapor_pressure / saturation)
        assert opened["precipitation_interval_mm"].isel(Time=1, south_north=0, west_east=0).item() == 2.0
    finally:
        opened.close()
    with open_wrfout(path, points=[(36.0, 140.0)]) as cropped:
        assert cropped.sizes["south_north"] == cropped.sizes["west_east"] == 1
        assert cropped.attrs["grid_y_offset"] == cropped.attrs["grid_x_offset"] == 1
        assert np.isnan(cropped["precipitation_interval_mm"].isel(Time=0)).all()
        assert cropped["precipitation_interval_hours"].isel(Time=1).item() == pytest.approx(1 / 6)
        assert cropped["temperature_2m_c"].isel(Time=1).item() == 20

    dataset["RAINNC"][1] = -2.0
    dataset.to_netcdf(path)
    with open_wrfout(path) as reset:
        assert np.isnan(reset["precipitation_interval_mm"].isel(Time=1)).all()

    dataset["Times"][1] = dataset["Times"][0]
    dataset.to_netcdf(path)
    from weather_sim.errors import WRFOutputError
    with pytest.raises(WRFOutputError, match="unique"):
        open_wrfout(path)


def test_surface_wind_rotation_preserves_speed_and_raw_components(tmp_path) -> None:
    from weather_sim.errors import WRFOutputError
    dims = ("Time", "south_north", "west_east")
    array = np.ones((1, 2, 2), dtype=np.float32)
    ds = xr.Dataset({name: (dims, array * value) for name, value in
                     {"T2": 293.15, "U10": 3., "V10": 4., "XLAT": 35., "XLONG": 139.,
                      "COSALPHA": 0., "SINALPHA": 1.}.items()},
                    attrs={"MAP_PROJ": 1, "SIMULATION_START_DATE": "2026-09-04_03:00:00"})
    ds["XTIME"] = ("Time", [0.])
    path = tmp_path / "wrfout"
    ds.to_netcdf(path)
    with open_wrfout(path) as full, open_wrfout(path, points=[(35., 139.)]) as point:
        assert point.eastward_wind_10m_ms.item() == -4.
        assert point.northward_wind_10m_ms.item() == 3.
        assert point.wind_speed_10m_ms.item() == 5.
        assert point.U10.item() == 3.
        assert point.V10.item() == 4.
        assert point.wind_direction_10m_deg.item() == pytest.approx(126.87, abs=.01)
        for name in ("temperature_2m_c", "eastward_wind_10m_ms", "northward_wind_10m_ms", "wind_speed_10m_ms"):
            np.testing.assert_array_equal(point[name].values.ravel(), full[name].isel(south_north=0, west_east=0).values)
    ds["U10"][:] = 0.
    ds["V10"][:] = 0.
    ds.to_netcdf(path)
    with open_wrfout(path) as calm:
        assert np.isnan(calm.wind_direction_10m_deg).all()
    ds.drop_vars("COSALPHA").to_netcdf(path)
    with pytest.raises(WRFOutputError, match="COSALPHA"):
        open_wrfout(path)
