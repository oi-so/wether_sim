"""Read the surface variables required by Version 1 from wrfout files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from weather_sim.errors import WRFOutputError


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


def open_wrfout(path: str | Path) -> xr.Dataset:
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
    times = _decode_times(source)
    if len(times) != source.sizes.get("Time", len(times)):
        source.close()
        raise WRFOutputError("WRF time coordinate length does not match Time dimension")
    dataset = source.assign_coords(Time=times)
    dataset["temperature_2m_c"] = dataset["T2"] - 273.15
    dataset["temperature_2m_c"].attrs.update(units="degC", long_name="2 m air temperature")
    dataset["wind_speed_10m_ms"] = np.hypot(dataset["U10"], dataset["V10"])
    dataset["wind_speed_10m_ms"].attrs.update(units="m s-1", long_name="10 m wind speed")
    dataset["wind_direction_10m_deg"] = (270 - np.degrees(np.arctan2(dataset["V10"], dataset["U10"]))) % 360
    dataset["wind_direction_10m_deg"].attrs.update(
        units="degree", long_name="10 m meteorological wind direction (from)"
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
        first = accumulated.isel(Time=0).expand_dims(Time=[times[0]])
        dataset["precipitation_interval_mm"] = xr.concat([first, interval], dim="Time").clip(min=0)
        dataset["precipitation_interval_mm"].attrs.update(units="mm", long_name="interval precipitation")
    return dataset
