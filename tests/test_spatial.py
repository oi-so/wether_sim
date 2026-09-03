import numpy as np
import xarray as xr

from weather_sim.analysis.spatial import extract_nearest_series, haversine_km, nearest_grid_index, radius_mask


def test_haversine_and_radius_mask() -> None:
    distance = haversine_km([35.0], [139.0], 35.0, 139.0)
    assert distance[0] == 0
    mask = radius_mask([[35.0, 36.0]], [[139.0, 139.0]], 35.0, 139.0, 20)
    assert mask.tolist() == [[True, False]]


def test_nearest_grid_series() -> None:
    lat = xr.DataArray([[35.0, 35.0], [36.0, 36.0]], dims=("south_north", "west_east"))
    lon = xr.DataArray([[139.0, 140.0], [139.0, 140.0]], dims=("south_north", "west_east"))
    values = xr.DataArray(np.arange(8).reshape(2, 2, 2), dims=("Time", "south_north", "west_east"))
    assert nearest_grid_index(lat, lon, 35.1, 139.1) == (0, 0)
    result = extract_nearest_series(values, lat, lon, 35.1, 139.1)
    assert result.values.tolist() == [0, 4]
