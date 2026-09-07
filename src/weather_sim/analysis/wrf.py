"""Read the surface variables required by Version 1 from wrfout files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from weather_sim.errors import WRFOutputError
from weather_sim.analysis.spatial import nearest_grid_index


def _load_station_surface(dataset: xr.Dataset) -> None:
    """Reuse selected surface reads without loading the atmospheric volume."""
    for name in ("T2", "U10", "V10", "PSFC", "TSK", "Q2", "RAINC", "RAINNC", "COSALPHA", "SINALPHA"):
        if name in dataset:
            dataset[name].load()


def _decode_times(dataset: xr.Dataset) -> pd.DatetimeIndex:
    if "Times" in dataset:
        raw = dataset["Times"].values
        if raw.ndim == 2:
            values = [b"".join(row).decode("ascii") if row.dtype.kind == "S" else "".join(row.astype(str)) for row in raw]
        else:
            values = [item.decode("ascii") if isinstance(item, bytes) else str(item) for item in raw]
        return pd.DatetimeIndex(pd.to_datetime(values, format="%Y-%m-%d_%H:%M:%S", utc=True))
    if "XTIME" in dataset and "SIMULATION_START_DATE" in dataset.attrs:
        start = pd.Timestamp(str(dataset.attrs["SIMULATION_START_DATE"]).replace("_", " "), tz="UTC")
        return pd.DatetimeIndex(start + pd.to_timedelta(dataset["XTIME"].values, unit="m"))
    raise WRFOutputError("wrfout has neither Times nor usable XTIME metadata")


def open_wrfout(path: str | Path, *, points: list[tuple[float, float]] | None = None) -> xr.Dataset:
    """Open one wrfout file and expose normalized SI/analysis variables."""
    wrf_path = Path(path)
    if not wrf_path.is_file():
        raise WRFOutputError(f"WRF output does not exist: {wrf_path}")
    try:
        source = xr.open_dataset(wrf_path, decode_times=False)
    except (OSError, ValueError) as exc:
        raise WRFOutputError(f"could not open WRF output {wrf_path}: {exc}") from exc
    required = {"XLAT", "XLONG", "T2", "U10", "V10"}
    missing = required - set(source.variables)
    if missing:
        source.close()
        raise WRFOutputError(f"WRF output is missing variables: {', '.join(sorted(missing))}")
    try:
        times = _decode_times(source)
        if not times.is_monotonic_increasing or times.has_duplicates:
            raise WRFOutputError("WRF timestamps must be strictly increasing and unique")
    except Exception:
        source.close()
        raise
    if len(times) != source.sizes.get("Time", len(times)):
        source.close()
        raise WRFOutputError("WRF time coordinate length does not match Time dimension")
    dataset = source.assign_coords(Time=times)
    if points:
        # Select on the raw, lazily indexed NetCDF before derived variables
        # materialize whole horizontal fields. The nearest cells are unchanged.
        lat = source["XLAT"].isel(Time=0) if "Time" in source["XLAT"].dims else source["XLAT"]
        lon = source["XLONG"].isel(Time=0) if "Time" in source["XLONG"].dims else source["XLONG"]
        indices = [nearest_grid_index(lat.values, lon.values, *point) for point in points]
        ys, xs = zip(*indices)
        dataset = dataset.isel(south_north=slice(min(ys), max(ys) + 1), west_east=slice(min(xs), max(xs) + 1))
        dataset.attrs.update(grid_y_offset=min(ys), grid_x_offset=min(xs))
        # These surface fields are reused by multiple diagnostics. Cache only
        # the selected station rectangle, preserving dtype and every time.
        _load_station_surface(dataset)
    dataset["temperature_2m_c"] = dataset["T2"] - 273.15
    dataset["temperature_2m_c"].attrs.update(units="degC", long_name="2 m air temperature")
    dataset["wind_speed_10m_ms"] = np.hypot(dataset["U10"], dataset["V10"])
    dataset["wind_speed_10m_ms"].attrs.update(units="m s-1", long_name="10 m wind speed")
    if {"COSALPHA", "SINALPHA"}.issubset(dataset.variables):
        east = dataset["U10"] * dataset["COSALPHA"] - dataset["V10"] * dataset["SINALPHA"]
        north = dataset["V10"] * dataset["COSALPHA"] + dataset["U10"] * dataset["SINALPHA"]
        reference = "earth"
    elif "MAP_PROJ" in dataset.attrs or {"COSALPHA", "SINALPHA"} & set(dataset.variables):
        source.close()
        raise WRFOutputError("projected WRF winds require COSALPHA and SINALPHA for earth rotation")
    else:
        # Unprojected, minimal input datasets (e.g. synthetic tests).
        east, north = dataset["U10"], dataset["V10"]
        reference = "assumed_earth_without_projection_metadata"
    dataset["eastward_wind_10m_ms"] = east
    dataset["northward_wind_10m_ms"] = north
    for name in ("eastward_wind_10m_ms", "northward_wind_10m_ms"):
        dataset[name].attrs.update(units="m s-1", reference=reference)
    direction = (270 - np.degrees(np.arctan2(north, east))) % 360
    dataset["wind_direction_10m_deg"] = direction.where(dataset["wind_speed_10m_ms"] > 0)
    dataset["wind_direction_10m_deg"].attrs.update(
        units="degree", long_name="10 m meteorological wind direction (from)", reference=reference
    )
    if "PSFC" in dataset:
        dataset["surface_pressure_hpa"] = dataset["PSFC"] / 100
        dataset["surface_pressure_hpa"].attrs.update(units="hPa", long_name="surface pressure")
    if "TSK" in dataset:
        dataset["skin_temperature_c"] = dataset["TSK"] - 273.15
        dataset["skin_temperature_c"].attrs.update(units="degC", long_name="surface skin temperature")
    if "Q2" in dataset and "PSFC" in dataset:
        # WRF Q2 is a mixing ratio (kg water / kg dry air), not specific humidity.
        vapor_pressure_pa = dataset["Q2"] * dataset["PSFC"] / (0.622 + dataset["Q2"])
        saturation_pressure_pa = 611.2 * np.exp(
            17.67 * (dataset["T2"] - 273.15) / (dataset["T2"] - 29.65)
        )
        dataset["relative_humidity_2m_percent"] = (100 * vapor_pressure_pa / saturation_pressure_pa).clip(0, 100)
        dataset["relative_humidity_2m_percent"].attrs.update(units="%", long_name="2 m relative humidity")
    if "RAINC" in dataset and "RAINNC" in dataset:
        accumulated = dataset["RAINC"] + dataset["RAINNC"]
        dataset["precipitation_accumulated_mm"] = accumulated
        interval = accumulated.diff("Time", label="upper")
        first = xr.full_like(accumulated.isel(Time=0), np.nan).expand_dims(Time=[times[0]])
        intervals = xr.concat([first, interval], dim="Time")
        # No previous record at file start; a cumulative reset is not zero rain.
        dataset["precipitation_interval_mm"] = intervals.where(intervals >= 0)
        dataset["precipitation_interval_mm"].attrs.update(units="mm", long_name="interval precipitation")
        dataset["precipitation_interval_hours"] = xr.DataArray(
            np.r_[np.nan, (times[1:] - times[:-1]).total_seconds() / 3600],
            dims="Time", coords={"Time": times}, attrs={"units": "h"}
        )
    dataset.set_close(source.close)
    return dataset
