import pandas as pd
import pytest

from weather_sim.errors import ObservationDataError
from weather_sim.observations.csv_reader import convert_temperature_to_celsius, read_observations


def test_read_observations_normalizes_timezone_and_quality(tmp_path) -> None:
    path = tmp_path / "observations.csv"
    pd.DataFrame(
        {
            "timestamp": ["2024-01-01 12:00", "2024-01-01 12:10"],
            "station_id": ["school", "school"],
            "latitude": [35.0, 35.0], "longitude": [139.0, 139.0], "elevation_m": [10, 10],
            "variable": ["temperature", "temperature"], "value": [20, None], "unit": ["degC", "degC"],
            "quality": ["valid", "missing"],
        }
    ).to_csv(path, index=False)
    result = read_observations(path)
    assert str(result.loc[0, "timestamp"]) == "2024-01-01 03:00:00+00:00"
    assert result["is_valid"].tolist() == [True, False]


def test_temperature_conversion() -> None:
    result = convert_temperature_to_celsius(pd.Series([273.15, 20]), pd.Series(["K", "degC"]))
    assert result.tolist() == pytest.approx([0, 20])


def test_missing_columns_are_reported(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame({"timestamp": ["2024-01-01"]}).to_csv(path, index=False)
    with pytest.raises(ObservationDataError, match="missing required columns"):
        read_observations(path)
