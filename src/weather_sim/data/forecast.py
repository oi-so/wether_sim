"""Download and prepare date-dependent MSM and GFS input data."""

from __future__ import annotations

import shutil
import json
from collections.abc import Callable
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather_sim.config.models import ExperimentConfig
from weather_sim.errors import ExternalCommandError
from weather_sim.network import open_trusted_url

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
    source_selection: dict | None = None


def _download(url: str, target: Path) -> Path:
    """Download once, using an atomic temporary file."""
    if target.is_file() and target.stat().st_size:
        return target
    print(f"Downloading {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "weather-sim/0.1"})
    try:
        with open_trusted_url(request, timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    except (OSError, urllib.error.URLError) as exc:
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
            temporary.unlink(missing_ok=True)
            raise ExternalCommandError(f"download failed (HTTP 404): {url}; data may not be published yet") from exc
        # Some archives do not send the intermediate certificate needed by
        # OpenSSL-based Python builds on macOS. Apple's curl uses the system
        # trust store and still performs full TLS certificate verification.
        temporary.unlink(missing_ok=True)
        command = [
            "curl",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--retry",
            "4",
            "--output",
            str(temporary),
            url,
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode or not temporary.is_file() or not temporary.stat().st_size:
            temporary.unlink(missing_ok=True)
            detail = result.stderr.strip() or str(exc)
            raise ExternalCommandError(f"download failed: {url}: {detail}") from exc
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


def _cycle_assignments(
    valid_times: tuple[datetime, ...],
    *,
    cycle_interval_hours: int,
    max_forecast_hours: int,
    now: datetime | None = None,
    available: Callable[[datetime, datetime], bool] | None = None,
    policy: str = "continuous",
) -> dict[datetime, datetime]:
    """Reuse published cycles, searching older forecasts when necessary.

    Future valid times are permitted; future initialization times are not.
    """
    if policy not in ("continuous", "latest"):
        raise ValueError("cycle policy must be continuous or latest")
    if cycle_interval_hours <= 0 or 24 % cycle_interval_hours:
        raise ValueError("cycle_interval_hours must be a positive divisor of 24")
    if max_forecast_hours < 0:
        raise ValueError("max_forecast_hours must be non-negative")

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or any(t.tzinfo is None for t in valid_times):
        raise ValueError('forecast selection requires timezone-aware times')
    now = now.astimezone(timezone.utc)
    valid_times = tuple(t.astimezone(timezone.utc) for t in valid_times)
    if list(valid_times) != sorted(set(valid_times)):
        raise ValueError('valid times must be increasing and unique')
    if any(t.minute or t.second or t.microsecond for t in valid_times):
        raise ValueError('forecast valid times must be whole hours')
    latest_cycle = now.replace(hour=now.hour - now.hour % cycle_interval_hours, minute=0, second=0, microsecond=0)
    if valid_times and valid_times[-1] > latest_cycle + timedelta(hours=max_forecast_hours):
        raise ExternalCommandError(
            f'requested boundary {valid_times[-1].isoformat()} exceeds the supported '
            f'{max_forecast_hours}-hour forecast range as of {now.isoformat()}; '
            'shorten the period or wait for newer data (includes spin-up and rounded end boundary)'
        )
    checked: dict[tuple[datetime, datetime], bool] = {}
    def usable(candidate: datetime, valid: datetime) -> bool:
        key = (candidate, valid)
        if key not in checked:
            checked[key] = available(candidate, valid) if available else True
        return checked[key]
    assignments: dict[datetime, datetime] = {}
    cycle: datetime | None = None
    # Reverse traversal anchors the forecast suffix to its freshest published cycle.
    # Reuse it backwards until its initialization, avoiding a cycle change at every boundary.
    ordered_times = reversed(valid_times) if policy == "latest" else valid_times
    for valid_time in ordered_times:
        if cycle is None or valid_time < cycle or valid_time - cycle > timedelta(hours=max_forecast_hours) or not usable(cycle, valid_time):
            upper = min(valid_time, now)
            candidate = upper.replace(
                hour=upper.hour - upper.hour % cycle_interval_hours,
                minute=0,
                second=0,
                microsecond=0,
            )
            while valid_time - candidate <= timedelta(hours=max_forecast_hours):
                if usable(candidate, valid_time):
                    cycle = candidate
                    break
                candidate -= timedelta(hours=cycle_interval_hours)
            else:
                raise ExternalCommandError(
                    f'no published forecast covers boundary {valid_time.isoformat()} '
                    f'as of {now.isoformat()} (forecast limit {max_forecast_hours} h); '
                    'data may be unpublished or absent from this archive; shorten the period or retry later'
                )
        assignments[valid_time] = cycle
    return {valid: assignments[valid] for valid in valid_times}


def _remote_exists(url: str) -> bool:
    """HEAD only; distinguish absence from connectivity/authentication errors."""
    request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'weather-sim/0.1'})
    try:
        with open_trusted_url(request, timeout=20) as response:
            if response.status != 200:
                raise ExternalCommandError(f'availability check failed (HTTP {response.status}): {url}')
            return response.headers.get('Content-Length') != '0'
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise ExternalCommandError(f'availability check failed (HTTP {exc.code}): {url}') from exc
    except (OSError, urllib.error.URLError):
        result = subprocess.run(['curl', '--head', '--location', '--silent', '--show-error',
                                 '--max-time', '20', '--output', '/dev/null', '--write-out', '%{http_code}', url],
                                text=True, capture_output=True, check=False)
        if result.returncode:
            raise ExternalCommandError(f'availability check connection failed: {url}: {result.stderr.strip()}')
        status = result.stdout.strip()
        if status in ('200', '404'):
            return status == '200'
        raise ExternalCommandError(f'availability check failed (HTTP {status}): {url}')


def _gfs_paths(cycle: datetime, valid: datetime, root: Path) -> tuple[str, Path]:
    hour = int((valid - cycle).total_seconds() // 3600)
    url = f'{GFS_ROOT}/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos/gfs.t{cycle:%H}z.sfluxgrbf{hour:03d}.grib2'
    target = root / valid.strftime('%Y-%m-%d') / f'gfs_surface_soil_{valid:%Y%m%d_%H%M}_from_{cycle:%Y%m%d_%H%M}.grib2'
    return url, target


def select_forecast_cycles(valid_times: tuple[datetime, ...], root: Path, model: str,
                           *, now: datetime | None = None, policy: str = "continuous") -> dict[datetime, datetime]:
    """Check publication/local cache before downloading; memoize HEAD requests."""
    if model not in ('msm', 'gfs'):
        raise ValueError('model must be msm or gfs')
    checks: dict[str, bool] = {}
    def exists(url: str, path: Path | None = None) -> bool:
        if path is not None and path.is_file() and path.stat().st_size:
            return True
        if url not in checks:
            checks[url] = _remote_exists(url)
        return checks[url]
    def available(cycle: datetime, valid: datetime) -> bool:
        if model == 'msm':
            return all(exists(f'{RISH_ROOT}/{cycle:%Y/%m/%d}/{name}', root / cycle.strftime('%Y-%m-%d') / name)
                       for name in _msm_names(cycle))
        url, target = _gfs_paths(cycle, valid, root)
        if target.is_file() and target.stat().st_size:
            return True
        return exists(url + '.idx') and exists(url)
    return _cycle_assignments(valid_times, cycle_interval_hours=3 if model == 'msm' else 6,
                              max_forecast_hours=15 if model == 'msm' else 120,
                              now=now, available=available, policy=policy)


def _msm_names(cycle: datetime) -> tuple[str, str]:
    stamp = cycle.strftime("%Y%m%d%H0000")
    return (
        f"Z__C_RJTD_{stamp}_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
        f"Z__C_RJTD_{stamp}_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin",
    )


def _normalize_msm_near_surface_levels(
    source: Path,
    target: Path,
    *,
    grib_set: str,
) -> None:
    """Expose JMA's 1.5 m temperature/RH to WPS as its 2 m surface level.

    MSM encodes these fields at 1.5 m using a scaled GRIB2 fixed-surface
    value. WPS 4.7 ignores that scale and only accepts a raw level of 2 m,
    otherwise ``real.exe`` silently falls back to the lowest pressure level.
    """
    temperature_adjusted = target.with_suffix(target.suffix + ".temperature.part")
    final_part = target.with_suffix(target.suffix + ".part")
    temperature_adjusted.unlink(missing_ok=True)
    final_part.unlink(missing_ok=True)
    commands = (
        [
            grib_set,
            "-w",
            "shortName=t,typeOfLevel=heightAboveGround",
            "-s",
            "scaleFactorOfFirstFixedSurface=0,scaledValueOfFirstFixedSurface=2",
            str(source),
            str(temperature_adjusted),
        ],
        [
            grib_set,
            "-w",
            "shortName=r,typeOfLevel=heightAboveGround",
            "-s",
            "scaleFactorOfFirstFixedSurface=0,scaledValueOfFirstFixedSurface=2",
            str(temperature_adjusted),
            str(final_part),
        ],
    )
    try:
        for command in commands:
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            if result.returncode:
                raise ExternalCommandError(
                    f"failed to normalize MSM near-surface level: {result.stderr.strip()}"
                )
        if not final_part.is_file() or not final_part.stat().st_size:
            raise ExternalCommandError("MSM near-surface normalization created no data")
        final_part.replace(target)
    finally:
        temperature_adjusted.unlink(missing_ok=True)
        final_part.unlink(missing_ok=True)


def download_msm(
    valid_times: tuple[datetime, ...],
    root: Path,
    grib_copy: str = "grib_copy",
    grib_set: str = "grib_set",
    *, assignments: dict[datetime, datetime] | None = None,
) -> tuple[Path, ...]:
    # JMA MSM archives provide 3-hourly cycles with FH00-15 in these files.
    if assignments is None:
        assignments = select_forecast_cycles(valid_times, root, 'msm')
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
            / f"msm_{valid_time:%Y%m%d_%H%M}_from_{cycle:%Y%m%d_%H%M}_wps2m.grib2"
        )
        if target.is_file() and target.stat().st_size:
            prepared.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        extracted = target.with_suffix(target.suffix + ".extracted.part")
        extracted.unlink(missing_ok=True)
        command = [
            grib_copy,
            "-w",
            f"validityDate={valid_time:%Y%m%d},validityTime={int(valid_time.strftime('%H%M'))}",
            *(str(path) for path in cycle_files[cycle]),
            str(extracted),
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode or not extracted.is_file() or not extracted.stat().st_size:
            extracted.unlink(missing_ok=True)
            raise ExternalCommandError(f"failed to extract MSM valid time {valid_time.isoformat()}: {result.stderr.strip()}")
        try:
            _normalize_msm_near_surface_levels(extracted, target, grib_set=grib_set)
        finally:
            extracted.unlink(missing_ok=True)
        prepared.append(target)
    return tuple(prepared)


def _read_url_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "weather-sim/0.1"})
    try:
        with open_trusted_url(request, timeout=60) as response:
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
                output_position = output.tell()
                for attempt in range(4):
                    try:
                        request = urllib.request.Request(
                            url,
                            headers={"User-Agent": "weather-sim/0.1", "Range": range_value},
                        )
                        with open_trusted_url(request, timeout=120) as response:
                            if response.status != 206:
                                raise ExternalCommandError(
                                    f"GFS archive did not honor HTTP range {range_value}"
                                )
                            shutil.copyfileobj(response, output, length=1024 * 1024)
                        break
                    except (OSError, urllib.error.URLError, ExternalCommandError) as exc:
                        output.seek(output_position)
                        output.truncate()
                        if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                            raise
                        if attempt == 3:
                            raise
                        time.sleep(2**attempt)
    except (OSError, urllib.error.URLError, ExternalCommandError) as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, ExternalCommandError):
            raise
        raise ExternalCommandError(f"GFS range download failed: {url}: {exc}") from exc
    temporary.replace(target)
    return target


def download_gfs(valid_times: tuple[datetime, ...], root: Path, *,
                 assignments: dict[datetime, datetime] | None = None) -> tuple[Path, ...]:
    # Operational GFS cycles are 00/06/12/18 UTC. Keep one cycle for a
    # typical local case to avoid discontinuities between soil forecasts.
    if assignments is None:
        assignments = select_forecast_cycles(valid_times, root, 'gfs')
    prepared: list[Path] = []
    for valid_time in valid_times:
        cycle = assignments[valid_time]
        base, target = _gfs_paths(cycle, valid_time, root)
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
    now = datetime.now(timezone.utc)
    roots = {model: project_root / 'data/meteorological' / model for model in ('msm', 'gfs')}
    policy = config.wrf.source_cycle_policy
    if policy == "auto":
        policy = "latest" if config.time.target_end.astimezone(timezone.utc) > now else "continuous"
    assignments = {model: select_forecast_cycles(valid_times, root, model, now=now, policy=policy) for model, root in roots.items()}
    selection = {'selected_at_utc': now.isoformat(), 'cycle_policy': policy, 'models': {
        model: [{'valid_time_utc': valid.isoformat(), 'initialization_utc': cycle.isoformat(),
                 'forecast_hours': int((valid - cycle).total_seconds() / 3600)} for valid, cycle in mapping.items()]
        for model, mapping in assignments.items()}}
    print('Published input cycles: ' + json.dumps(selection['models']))
    geographic = ensure_geographic_data(project_root / "data/geographic")
    if config.wrf.urban_fraction_source == 'gaia2020':
        from weather_sim.data.urban import urban_geographic_overlay
        geographic = urban_geographic_overlay(project_root / "data/geographic", geographic, _download)
    return PreparedForecastData(
        valid_times=valid_times,
        msm_files=download_msm(valid_times, roots['msm'], assignments=assignments['msm']),
        gfs_files=download_gfs(valid_times, roots['gfs'], assignments=assignments['gfs']),
        geographic_directory=geographic,
        source_selection=selection,
    )
