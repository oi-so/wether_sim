"""Read observations into the project's canonical long-table schema."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from weather_sim.errors import ObservationDataError

REQUIRED_COLUMNS = {
    "timestamp",
    "station_id",
    "latitude",
    "longitude",
    "elevation_m",
    "variable",
    "value",
    "unit",
}
OPTIONAL_DEFAULTS = {"quality": "valid", "source": "unknown"}


def read_observations(path: str | Path, *, timezone_name: str = "Asia/Tokyo") -> pd.DataFrame:
    """Load a canonical observation CSV and normalize timestamps to UTC.

    NaN values and rows whose quality is ``missing`` or ``invalid`` remain in the
    returned table, with an ``is_valid`` flag so raw information is not destroyed.
    """
    csv_path = Path(path)
    if not csv_path.is_file():
        raise ObservationDataError(f"observation file does not exist: {csv_path}")
    try:
        frame = pd.read_csv(csv_path)
    except (OSError, pd.errors.ParserError) as exc:
        raise ObservationDataError(f"could not read observation CSV {csv_path}: {exc}") from exc
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ObservationDataError(f"missing required columns: {', '.join(sorted(missing))}")
    for column, default in OPTIONAL_DEFAULTS.items():
        if column not in frame:
            frame[column] = default

    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ObservationDataError(f"unknown timezone: {timezone_name}") from exc

    parsed = pd.to_datetime(frame["timestamp"], errors="coerce")
    if parsed.isna().any():
        rows = (parsed.index[parsed.isna()] + 2).tolist()
        raise ObservationDataError(f"invalid timestamps at CSV rows: {rows}")
    if parsed.dt.tz is None:
        try:
            parsed = parsed.dt.tz_localize(timezone_name, ambiguous="raise", nonexistent="raise")
        except ValueError as exc:
            raise ObservationDataError(f"ambiguous or nonexistent local timestamp: {exc}") from exc
    frame["timestamp"] = parsed.dt.tz_convert("UTC")

    for column in ("latitude", "longitude", "elevation_m", "value"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[["latitude", "longitude"]].isna().any(axis=None):
        raise ObservationDataError("station coordinates must be numeric")
    if not frame["latitude"].between(-90, 90).all() or not frame["longitude"].between(-180, 180).all():
        raise ObservationDataError("station coordinates are outside valid latitude/longitude ranges")

    quality = frame["quality"].astype(str).str.lower()
    frame["is_valid"] = frame["value"].notna() & ~quality.isin({"missing", "invalid", "bad"})
    return frame.sort_values(["station_id", "variable", "timestamp"]).reset_index(drop=True)


def convert_temperature_to_celsius(values: pd.Series, units: pd.Series) -> pd.Series:
    """Convert temperature values with C/degC/K units to degrees Celsius."""
    normalized = units.astype(str).str.strip().str.lower()
    result = pd.to_numeric(values, errors="coerce").astype(float)
    kelvin = normalized.isin({"k", "kelvin"})
    celsius = normalized.isin({"c", "°c", "degc", "celsius"})
    unsupported = ~(kelvin | celsius) & result.notna()
    if unsupported.any():
        bad = sorted(set(units[unsupported].astype(str)))
        raise ObservationDataError(f"unsupported temperature units: {bad}")
    result.loc[kelvin] -= 273.15
    return result
