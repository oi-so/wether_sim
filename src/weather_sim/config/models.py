"""Typed experiment configuration and validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather_sim.errors import ConfigurationError


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ConfigurationError(f"'{name}' must be a mapping")
    return value


def _aware_datetime(value: Any, field: str, default_zone: ZoneInfo) -> datetime:
    if not isinstance(value, str):
        raise ConfigurationError(f"'{field}' must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ConfigurationError(f"'{field}' is not a valid ISO 8601 datetime: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_zone)
    return parsed


@dataclass(frozen=True)
class CenterConfig:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ConfigurationError("center.latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ConfigurationError("center.longitude must be between -180 and 180")


@dataclass(frozen=True)
class TimeConfig:
    target_start: datetime
    target_end: datetime
    timezone_name: str
    spinup_hours: float

    def __post_init__(self) -> None:
        if self.target_end <= self.target_start:
            raise ConfigurationError("time.target_end must be after time.target_start")
        if self.spinup_hours < 0:
            raise ConfigurationError("time.spinup_hours must be non-negative")

    @property
    def simulation_start(self) -> datetime:
        return self.target_start - timedelta(hours=self.spinup_hours)

    @property
    def simulation_start_utc(self) -> datetime:
        return self.simulation_start.astimezone(timezone.utc)

    @property
    def target_start_utc(self) -> datetime:
        return self.target_start.astimezone(timezone.utc)

    @property
    def target_end_utc(self) -> datetime:
        return self.target_end.astimezone(timezone.utc)


@dataclass(frozen=True)
class DomainConfig:
    name: str
    dx_m: int
    e_we: int
    e_sn: int
    parent: str | None = None
    parent_grid_ratio: int = 1

    def __post_init__(self) -> None:
        if self.dx_m <= 0:
            raise ConfigurationError(f"domains.{self.name}.dx_m must be positive")
        if self.e_we < 10 or self.e_sn < 10:
            raise ConfigurationError(f"domains.{self.name} needs at least 10 grid points per axis")
        if self.parent_grid_ratio < 1:
            raise ConfigurationError(f"domains.{self.name}.parent_grid_ratio must be positive")
        if self.parent is not None:
            if (self.e_we - 1) % self.parent_grid_ratio:
                raise ConfigurationError(
                    f"domains.{self.name}.e_we - 1 must be divisible by parent_grid_ratio"
                )
            if (self.e_sn - 1) % self.parent_grid_ratio:
                raise ConfigurationError(
                    f"domains.{self.name}.e_sn - 1 must be divisible by parent_grid_ratio"
                )

    @property
    def width_km(self) -> float:
        return (self.e_we - 1) * self.dx_m / 1000

    @property
    def height_km(self) -> float:
        return (self.e_sn - 1) * self.dx_m / 1000


@dataclass(frozen=True)
class AnalysisConfig:
    radius_km: float
    output_interval_minutes: int

    def __post_init__(self) -> None:
        if self.radius_km <= 0:
            raise ConfigurationError("analysis.radius_km must be positive")
        if self.output_interval_minutes <= 0:
            raise ConfigurationError("analysis.output_interval_minutes must be positive")


@dataclass(frozen=True)
class ObservationConfig:
    use_amedas: bool
    use_school: bool


@dataclass(frozen=True)
class VisualizationConfig:
    animation: bool
    animation_format: str
    fps: int

    def __post_init__(self) -> None:
        if self.animation_format not in {"mp4", "gif"}:
            raise ConfigurationError("visualization.animation_format must be 'mp4' or 'gif'")
        if self.fps <= 0:
            raise ConfigurationError("visualization.fps must be positive")


@dataclass(frozen=True)
class WRFConfig:
    input_interval_seconds: int
    time_step_seconds: int
    vertical_levels: int
    map_projection: str

    def __post_init__(self) -> None:
        if self.input_interval_seconds <= 0:
            raise ConfigurationError("wrf.input_interval_seconds must be positive")
        if self.time_step_seconds <= 0:
            raise ConfigurationError("wrf.time_step_seconds must be positive")
        if self.vertical_levels < 10:
            raise ConfigurationError("wrf.vertical_levels must be at least 10")
        if self.map_projection not in {"lambert"}:
            raise ConfigurationError("Version 1 currently supports only the Lambert projection")


@dataclass(frozen=True)
class ExperimentConfig:
    center: CenterConfig
    time: TimeConfig
    domains: tuple[DomainConfig, ...]
    analysis: AnalysisConfig
    observations: ObservationConfig
    visualization: VisualizationConfig
    wrf: WRFConfig
    source_path: Path | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: Path | None = None) -> "ExperimentConfig":
        center = _section(data, "center")
        time_data = _section(data, "time")
        timezone_name = str(time_data.get("timezone", "Asia/Tokyo"))
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"unknown timezone: {timezone_name}") from exc

        domains_data = _section(data, "domains")
        domains: list[DomainConfig] = []
        for name, raw in domains_data.items():
            if not isinstance(raw, dict):
                raise ConfigurationError(f"domains.{name} must be a mapping")
            domains.append(
                DomainConfig(
                    name=name,
                    dx_m=int(raw["dx_m"]),
                    e_we=int(raw["e_we"]),
                    e_sn=int(raw["e_sn"]),
                    parent=raw.get("parent"),
                    parent_grid_ratio=int(raw.get("parent_grid_ratio", 1)),
                )
            )
        if not domains or domains[0].parent is not None:
            raise ConfigurationError("the first domain must be a parent domain")
        known: set[str] = set()
        for index, domain in enumerate(domains):
            if domain.name in known:
                raise ConfigurationError(f"duplicate domain: {domain.name}")
            if index and domain.parent != domains[index - 1].name:
                raise ConfigurationError(f"{domain.name} must be nested directly in {domains[index - 1].name}")
            if index and domains[index - 1].dx_m != domain.dx_m * domain.parent_grid_ratio:
                raise ConfigurationError(f"{domain.name} resolution must match its parent_grid_ratio")
            known.add(domain.name)

        analysis = _section(data, "analysis")
        observations = _section(data, "observations")
        visualization = _section(data, "visualization")
        wrf = _section(data, "wrf")
        return cls(
            center=CenterConfig(float(center["latitude"]), float(center["longitude"])),
            time=TimeConfig(
                target_start=_aware_datetime(time_data["target_start"], "time.target_start", zone),
                target_end=_aware_datetime(time_data["target_end"], "time.target_end", zone),
                timezone_name=timezone_name,
                spinup_hours=float(time_data.get("spinup_hours", 12)),
            ),
            domains=tuple(domains),
            analysis=AnalysisConfig(
                radius_km=float(analysis.get("radius_km", 20)),
                output_interval_minutes=int(analysis.get("output_interval_minutes", 10)),
            ),
            observations=ObservationConfig(
                use_amedas=bool(observations.get("use_amedas", True)),
                use_school=bool(observations.get("use_school", True)),
            ),
            visualization=VisualizationConfig(
                animation=bool(visualization.get("animation", True)),
                animation_format=str(visualization.get("animation_format", "mp4")),
                fps=int(visualization.get("fps", 6)),
            ),
            wrf=WRFConfig(
                input_interval_seconds=int(wrf.get("input_interval_seconds", 10800)),
                time_step_seconds=int(wrf.get("time_step_seconds", 54)),
                vertical_levels=int(wrf.get("vertical_levels", 45)),
                map_projection=str(wrf.get("map_projection", "lambert")),
            ),
            source_path=source_path,
        )
