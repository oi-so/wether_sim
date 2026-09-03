"""Geographic selection and WRF-grid point extraction."""

from __future__ import annotations

import numpy as np
import xarray as xr

EARTH_RADIUS_KM = 6371.0088


def haversine_km(latitude: object, longitude: object, center_lat: float, center_lon: float) -> np.ndarray:
    lat = np.deg2rad(np.asarray(latitude, dtype=float))
    lon = np.deg2rad(np.asarray(longitude, dtype=float))
    center_lat_rad = np.deg2rad(center_lat)
    center_lon_rad = np.deg2rad(center_lon)
    delta_lat = lat - center_lat_rad
    delta_lon = lon - center_lon_rad
    a = np.sin(delta_lat / 2) ** 2 + np.cos(center_lat_rad) * np.cos(lat) * np.sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def radius_mask(latitude: object, longitude: object, center_lat: float, center_lon: float, radius_km: float) -> np.ndarray:
    if radius_km <= 0:
        raise ValueError("radius_km must be positive")
    return haversine_km(latitude, longitude, center_lat, center_lon) <= radius_km


def nearest_grid_index(latitude: object, longitude: object, point_lat: float, point_lon: float) -> tuple[int, int]:
    distances = haversine_km(latitude, longitude, point_lat, point_lon)
    if distances.ndim != 2 or not np.isfinite(distances).any():
        raise ValueError("latitude and longitude must define a finite two-dimensional grid")
    return tuple(int(value) for value in np.unravel_index(np.nanargmin(distances), distances.shape))


def extract_nearest_series(
    variable: xr.DataArray,
    latitude: xr.DataArray,
    longitude: xr.DataArray,
    point_lat: float,
    point_lon: float,
) -> xr.DataArray:
    """Extract a time series at the nearest curvilinear WRF grid point."""
    lat2d = latitude.isel(Time=0) if "Time" in latitude.dims else latitude
    lon2d = longitude.isel(Time=0) if "Time" in longitude.dims else longitude
    y, x = nearest_grid_index(lat2d.values, lon2d.values, point_lat, point_lon)
    spatial_dims = lat2d.dims
    if len(spatial_dims) != 2:
        raise ValueError("WRF latitude/longitude must have two spatial dimensions")
    result = variable.isel({spatial_dims[0]: y, spatial_dims[1]: x})
    result.attrs["grid_y"] = y
    result.attrs["grid_x"] = x
    result.attrs["grid_distance_km"] = float(haversine_km(lat2d.values[y, x], lon2d.values[y, x], point_lat, point_lon))
    return result
