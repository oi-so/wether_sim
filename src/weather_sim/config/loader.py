"""YAML configuration loader."""

from pathlib import Path

import yaml

from weather_sim.config.models import ExperimentConfig
from weather_sim.errors import ConfigurationError


def load_config(path: str | Path) -> ExperimentConfig:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigurationError(f"configuration file does not exist: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("configuration root must be a mapping")
    return ExperimentConfig.from_dict(raw, config_path.resolve())
