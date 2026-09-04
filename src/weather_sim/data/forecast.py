"""Download and prepare date-dependent MSM and GFS input data."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from weather_sim.config.models import ExperimentConfig
from weather_sim.errors import ExternalCommandError

RISH_ROOT = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
GFS_ROOT = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
WPS_GEOG_URL = "https://www2.mmm.ucar.edu/wrf/src/wps_files/geog_high_res_mandatory.tar.gz"

_GFS_FIELDS = {
    ("TMP", "surface"),
    ("TSOIL", "0-0.1 m below ground"),
    ("TSOIL", "0.1-0.4 m below ground"),
    ("TSOIL", "0.4-1 m below ground"),
    ("TSOIL", "1-2 m below ground"),
    ("SOILW", "0-0.1 m below ground"),
    ("SOILW", "0.1-0.4 m below ground"),
    ("SOILW", "0.4-1 m below ground"),
    ("SOILW", "1-2 m below ground"),
    ("WEASD", "surface"),
    ("LAND", "surface"),
    ("ICEC", "surface"),
}


@dataclass(frozen=True)
class PreparedForecastData:
    valid_times: tuple[datetime, ...]
    msm_files: tuple[Path, ...]
    gfs_files: tuple[Path, ...]
    geographic_directory: Path


def _download(url: str, target: Path) -> Path:
    """Download once, using an atomic temporary file."""
    if target.is_file() and target.stat().st_size:
        return target
    print(f"Downloading {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "weather-sim/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    except (OSError, urllib.error.URLError) as exc:
        temporary.unlink(missing_ok=True)
        raise ExternalCommandError(f"download failed: {url}: {exc}") from exc
    temporary.replace(target)
    return target


def _three_hour_times(config: ExperimentConfig) -> tuple[datetime, ...]:
    start = config.simulation_start_utc
    end = config.simulation_end_utc
    interval = timedelta(seconds=config.wrf.input_interval_seconds)
    if config.wrf.input_interval_seconds != 10_800:
        raise ValueError("automatic MSM preparation currently requires wrf.input_interval_seconds=10800")
    result: list[datetime] = []
    current = start
    while current <= end:
        result.append(current)
        current += interval
    return tuple(result)


def _cycle_assignments(valid_times: tuple[datetime, ...]) -> dict[datetime, datetime]:
    """Use one MSM/GFS initialization for up to its 15-hour forecast horizon."""
    assignments: dict[datetime, datetime] = {}
    cycle: datetime | None = None
    for valid_time in valid_times:
        if cycle is None or valid_time - cycle > timedelta(hours=15):
            cycle = valid_time
        assignments[valid_time] = cycle
    return assignments


def _msm_names(cycle: datetime) -> tuple[str, str]:
    stamp = cycle.strftime("%Y%m%d%H0000")
    return (
        f"Z__C_RJTD_{stamp}_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
        f"Z__C_RJTD_{stamp}_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin",
    )


def download_msm(valid_times: tuple[datetime, ...], root: Path, grib_copy: str = "grib_copy") -> tuple[Path, ...]:
    assignments = _cycle_assignments(valid_times)
    cycle_files: dict[datetime, tuple[Path, Path]] = {}
    for cycle in sorted(set(assignments.values())):
        directory = root / cycle.strftime("%Y-%m-%d")
        remote_directory = f"{RISH_ROOT}/{cycle:%Y/%m/%d}"
        pressure_name, surface_name = _msm_names(cycle)
        cycle_files[cycle] = (
            _download(f"{remote_directory}/{pressure_name}", directory / pressure_name),
            _download(f"{remote_directory}/{surface_name}", directory / surface_name),
        )

    prepared: list[Path] = []
    for valid_time in valid_times:
        cycle = assignments[valid_time]
        target = (
            root
            / valid_time.strftime("%Y-%m-%d")
            / "wps_steps"
            / f"msm_{valid_time:%Y%m%d_%H%M}_from_{cycle:%Y%m%d_%H%M}.grib2"
        )
        if target.is_file() and target.stat().st_size:
            prepared.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [
            grib_copy,
            "-w",
            f"validityDate={valid_time:%Y%m%d},validityTime={int(valid_time.strftime('%H%M'))}",
            *(str(path) for path in cycle_files[cycle]),
            str(target),
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode or not target.is_file() or not target.stat().st_size:
            target.unlink(missing_ok=True)
            raise ExternalCommandError(f"failed to extract MSM valid time {valid_time.isoformat()}: {result.stderr.strip()}")
        prepared.append(target)
    return tuple(prepared)


def _read_url_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "weather-sim/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8")
    except (OSError, urllib.error.URLError) as exc:
        raise ExternalCommandError(f"download failed: {url}: {exc}") from exc


def _selected_gfs_ranges(index_text: str) -> list[tuple[int, int | None]]:
    rows: list[tuple[int, int, str, str]] = []
    for line in index_text.splitlines():
        parts = line.split(":")
        if len(parts) < 5:
            continue
        rows.append((int(parts[0]), int(parts[1]), parts[3], parts[4]))
    selected: list[tuple[int, int | None]] = []
    for position, (_, start, variable, level) in enumerate(rows):
        if (variable, level) not in _GFS_FIELDS:
            continue
        end = rows[position + 1][1] - 1 if position + 1 < len(rows) else None
        selected.append((start, end))
    if len(selected) != len(_GFS_FIELDS):
        raise ExternalCommandError(
            f"GFS index contains {len(selected)} of {len(_GFS_FIELDS)} required surface/soil fields"
        )
    return selected


def _download_gfs_ranges(url: str, target: Path, ranges: list[tuple[int, int | None]]) -> Path:
    if target.is_file() and target.stat().st_size:
        return target
    print(f"Downloading required GFS records to {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with temporary.open("wb") as output:
            for start, end in ranges:
                range_value = f"bytes={start}-{'' if end is None else end}"
                request = urllib.request.Request(
                    url, headers={"User-Agent": "weather-sim/0.1", "Range": range_value}
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.status != 206:
                        raise ExternalCommandError(f"GFS archive did not honor HTTP range {range_value}")
                    shutil.copyfileobj(response, output, length=1024 * 1024)
    except (OSError, urllib.error.URLError, ExternalCommandError) as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, ExternalCommandError):
            raise
        raise ExternalCommandError(f"GFS range download failed: {url}: {exc}") from exc
    temporary.replace(target)
    return target


def download_gfs(valid_times: tuple[datetime, ...], root: Path) -> tuple[Path, ...]:
    assignments = _cycle_assignments(valid_times)
    prepared: list[Path] = []
    for valid_time in valid_times:
        cycle = assignments[valid_time]
        forecast_hour = int((valid_time - cycle).total_seconds() // 3600)
        base = (
            f"{GFS_ROOT}/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos/"
            f"gfs.t{cycle:%H}z.sfluxgrbf{forecast_hour:03d}.grib2"
        )
        target = (
            root
            / valid_time.strftime("%Y-%m-%d")
            / f"gfs_surface_soil_{valid_time:%Y%m%d_%H%M}_from_{cycle:%Y%m%d_%H%M}.grib2"
        )
        if target.is_file() and target.stat().st_size:
            prepared.append(target)
            continue
        ranges = _selected_gfs_ranges(_read_url_text(base + ".idx"))
        prepared.append(_download_gfs_ranges(base, target, ranges))
    return tuple(prepared)


def ensure_geographic_data(root: Path) -> Path:
    destination = root / "WPS_GEOG"
    if destination.is_dir() and any(destination.iterdir()):
        return destination
    archive = root / "downloads" / "geog_high_res_mandatory.tar.gz"
    _download(WPS_GEOG_URL, archive)
    root.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(root, filter="data")
    except (OSError, tarfile.TarError) as exc:
        raise ExternalCommandError(f"could not extract WPS geographic data: {exc}") from exc
    if not destination.is_dir():
        raise ExternalCommandError(f"geographic archive did not create {destination}")
    return destination


def prepare_forecast_data(config: ExperimentConfig, project_root: Path) -> PreparedForecastData:
    valid_times = _three_hour_times(config)
    return PreparedForecastData(
        valid_times=valid_times,
        msm_files=download_msm(valid_times, project_root / "data/meteorological/msm"),
        gfs_files=download_gfs(valid_times, project_root / "data/meteorological/gfs"),
        geographic_directory=ensure_geographic_data(project_root / "data/geographic"),
    )
