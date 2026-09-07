"""Station metadata kept separately from immutable measurement values."""
from pathlib import Path
import math

import yaml

from weather_sim.errors import ObservationDataError


def read_station_metadata(path: Path) -> dict[str, dict]:
    try:
        metadata = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ObservationDataError(f"could not read station metadata {path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ObservationDataError("station metadata must be a station-id mapping")
    for station, info in metadata.items():
        if not isinstance(info, dict):
            raise ObservationDataError(f"invalid station metadata: {station}")
        required = ("latitude", "longitude", "ground_elevation_m", "pressure_sensor_height_m")
        for name in required:
            try:
                value = float(info[name])
            except (KeyError, ValueError, TypeError) as exc:
                raise ObservationDataError(f"{station}.{name} must be numeric") from exc
            if not math.isfinite(value):
                raise ObservationDataError(f"{station}.{name} must be finite")
            info[name] = value
        if info.get("pressure_type") not in {"station", "sea_level"}:
            raise ObservationDataError(f"{station}.pressure_type must be station or sea_level")
    return metadata
