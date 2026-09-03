from datetime import timezone

import pytest

from weather_sim.config import load_config
from weather_sim.config.models import ExperimentConfig
from weather_sim.errors import ConfigurationError


def test_default_config_loads_and_converts_jst_to_utc() -> None:
    config = load_config("config/default.yaml")
    assert config.time.target_start_utc.tzinfo == timezone.utc
    assert config.time.target_start_utc.hour == 3
    assert config.time.simulation_start_utc.hour == 15
    assert config.time.simulation_start_utc.day == 9
    assert [domain.width_km for domain in config.domains] == [891.0, 297.0, 99.0]


def test_naive_datetime_uses_configured_timezone() -> None:
    config = ExperimentConfig.from_dict(
        {
            "center": {"latitude": 35, "longitude": 139},
            "time": {"target_start": "2024-01-01T12:00:00", "target_end": "2024-01-01T13:00:00", "timezone": "Asia/Tokyo"},
            "domains": {"d01": {"dx_m": 9000, "e_we": 100, "e_sn": 100}},
            "analysis": {"radius_km": 20, "output_interval_minutes": 10},
            "observations": {}, "visualization": {}, "wrf": {},
        }
    )
    assert config.time.target_start_utc.hour == 3


def test_nested_grid_points_must_match_ratio() -> None:
    with pytest.raises(ConfigurationError, match="divisible"):
        ExperimentConfig.from_dict(
            {
                "center": {"latitude": 35, "longitude": 139},
                "time": {"target_start": "2024-01-01T00:00:00Z", "target_end": "2024-01-01T01:00:00Z"},
                "domains": {
                    "d01": {"dx_m": 9000, "e_we": 100, "e_sn": 100},
                    "d02": {"dx_m": 3000, "e_we": 101, "e_sn": 100, "parent": "d01", "parent_grid_ratio": 3},
                },
                "analysis": {}, "observations": {}, "visualization": {}, "wrf": {},
            }
        )
