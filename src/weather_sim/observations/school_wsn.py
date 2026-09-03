"""Reader for the CP932 WSN logger files supplied by the school station."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from weather_sim.errors import ObservationDataError

WSN_COLUMNS = (
    "timestamp", "temperature", "relative_humidity", "wind_direction",
    "wind_direction_max", "wind_direction_min", "wind_speed",
    "wind_speed_max", "wind_speed_min", "pressure", "precipitation_rate",
    "precipitation_accumulated", "hail_rate", "hail_accumulated",
)

VARIABLE_UNITS = {
    "temperature": "degC",
    "relative_humidity": "%",
    "wind_direction": "degree",
    "wind_speed": "m/s",
    "pressure": "hPa",
    "precipitation_rate": "mm/h",
    "precipitation_accumulated": "mm",
}


def read_school_wsn(
    paths: list[str | Path], *, latitude: float, longitude: float,
    elevation_m: float | None = None, station_id: str = "school",
    timezone_name: str = "Asia/Tokyo",
) -> pd.DataFrame:
    """Convert one or more WSN daily logs to the canonical observation table."""
    daily: list[pd.DataFrame] = []
    for item in paths:
        path = Path(item)
        if not path.is_file():
            raise ObservationDataError(f"school observation file does not exist: {path}")
        try:
            frame = pd.read_csv(path, encoding="cp932")
        except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
            raise ObservationDataError(f"could not read school WSN file {path}: {exc}") from exc
        if len(frame.columns) != len(WSN_COLUMNS):
            raise ObservationDataError(
                f"expected {len(WSN_COLUMNS)} WSN columns in {path}, found {len(frame.columns)}"
            )
        frame.columns = WSN_COLUMNS
        daily.append(frame)
    if not daily:
        raise ObservationDataError("at least one school WSN file is required")

    wide = pd.concat(daily, ignore_index=True)
    timestamps = pd.to_datetime(wide["timestamp"], format="%Y/%m/%d %H:%M:%S", errors="coerce")
    if timestamps.isna().any():
        raise ObservationDataError("school WSN data contains invalid timestamps")
    wide["timestamp"] = timestamps.dt.tz_localize(timezone_name).dt.tz_convert("UTC")
    selected = wide[["timestamp", *VARIABLE_UNITS]].melt(
        id_vars="timestamp", var_name="variable", value_name="value"
    )
    selected["value"] = pd.to_numeric(selected["value"], errors="coerce")
    selected["station_id"] = station_id
    selected["latitude"] = latitude
    selected["longitude"] = longitude
    selected["elevation_m"] = elevation_m
    selected["unit"] = selected["variable"].map(VARIABLE_UNITS)
    selected["quality"] = selected["value"].notna().map({True: "valid", False: "missing"})
    selected["source"] = "school_wsn"
    return selected[
        ["timestamp", "station_id", "latitude", "longitude", "elevation_m", "variable", "value", "unit", "quality", "source"]
    ].sort_values(["timestamp", "variable"]).reset_index(drop=True)
