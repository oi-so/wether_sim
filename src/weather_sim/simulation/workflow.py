"""End-to-end WPS/WRF workflow for an arbitrary configured time window."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import xarray as xr

from weather_sim.analysis.wrf import open_wrfout
from weather_sim.config.models import ExperimentConfig
from weather_sim.data.forecast import PreparedForecastData, prepare_forecast_data
from weather_sim.errors import ExternalCommandError, ObservationDataError
from weather_sim.observations.jma_download import download_fuchu_amedas
from weather_sim.simulation.namelists import write_namelists
from weather_sim.visualization.animation import create_standard_animations
from weather_sim.visualization.plots import plot_surface_field


def default_case_name(config: ExperimentConfig) -> str:
    start = config.time.target_start.astimezone(config.time.target_start.tzinfo)
    end = config.time.target_end.astimezone(config.time.target_end.tzinfo)
    return f"case_{start:%Y%m%dT%H%M}_{end:%Y%m%dT%H%M}"


def _grib_label(index: int) -> str:
    if index >= 26**3:
        raise ValueError("too many GRIB files for WPS link naming")
    return "".join(chr(ord("A") + (index // 26**power) % 26) for power in (2, 1, 0))


def _replace_symlink(target: Path, source: Path) -> None:
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        raise ExternalCommandError(f"refusing to replace non-symlink file: {target}")
    target.symlink_to(source.resolve())


def _run(command: list[str], directory: Path, log_name: str, env: dict[str, str] | None = None) -> None:
    log_path = directory / log_name
    print(f"Running {' '.join(command)} (log: {log_path})")
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            cwd=directory,
            env=merged_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if result.returncode:
        raise ExternalCommandError(f"{' '.join(command)} failed; see {log_path}")


def _prepare_ungrib(
    config: ExperimentConfig,
    case_directory: Path,
    geog_directory: Path,
    files: tuple[Path, ...],
    prefix: str,
    vtable: Path,
    ungrib: Path,
) -> Path:
    directory = case_directory / f"ungrib_{prefix.lower()}"
    directory.mkdir(parents=True, exist_ok=True)
    write_namelists(
        config,
        directory,
        str(geog_directory),
        ungrib_prefix=prefix,
    )
    _replace_symlink(directory / "Vtable", vtable)
    for index, source in enumerate(files):
        _replace_symlink(directory / f"GRIBFILE.{_grib_label(index)}", source)
    _run([str(ungrib)], directory, "ungrib.stdout.log", {"OMPI_MCA_btl": "self,vader"})
    return directory


def _prepare_wps(
    config: ExperimentConfig,
    project_root: Path,
    case_directory: Path,
    data: PreparedForecastData,
) -> Path:
    wps_root = project_root / "wrf/WPS-4.7.0"
    wps_bin = wps_root / "install_clang/bin"
    for executable in (wps_bin / "geogrid", wps_bin / "ungrib", wps_bin / "metgrid"):
        if not executable.is_file():
            raise ExternalCommandError(f"WPS executable is missing: {executable}")

    directory = case_directory / "wps"
    directory.mkdir(parents=True, exist_ok=True)
    write_namelists(
        config,
        directory,
        str(data.geographic_directory),
        metgrid_sources=("MSM", "GFS"),
    )
    # WPS resolves these tables below its default ``geogrid/`` and
    # ``metgrid/`` paths.  A link in the case root is not sufficient.
    (directory / "geogrid").mkdir(exist_ok=True)
    (directory / "metgrid").mkdir(exist_ok=True)
    _replace_symlink(
        directory / "geogrid/GEOGRID.TBL",
        wps_root / "geogrid/GEOGRID.TBL.ARW",
    )
    _replace_symlink(
        directory / "metgrid/METGRID.TBL",
        wps_root / "metgrid/METGRID.TBL.ARW",
    )
    _run([str(wps_bin / "geogrid")], directory, "geogrid.stdout.log", {"OMPI_MCA_btl": "self,vader"})

    msm = _prepare_ungrib(
        config,
        case_directory,
        data.geographic_directory,
        data.msm_files,
        "MSM",
        wps_root / "ungrib/Variable_Tables/Vtable.JMAGSM",
        wps_bin / "ungrib",
    )
    gfs = _prepare_ungrib(
        config,
        case_directory,
        data.geographic_directory,
        data.gfs_files,
        "GFS",
        wps_root / "ungrib/Variable_Tables/Vtable.GFS",
        wps_bin / "ungrib",
    )
    for source_directory, prefix in ((msm, "MSM"), (gfs, "GFS")):
        for valid_time in data.valid_times:
            name = f"{prefix}:{valid_time:%Y-%m-%d_%H}"
            _replace_symlink(directory / name, source_directory / name)
    _run([str(wps_bin / "metgrid")], directory, "metgrid.stdout.log", {"OMPI_MCA_btl": "self,vader"})
    _validate_metgrid_inputs(directory, config)
    return directory


def _validate_metgrid_inputs(
    wps_directory: Path,
    config: ExperimentConfig,
) -> None:
    """Reject corrupt land/surface initialization before an expensive WRF run.

    WRF soil temperatures are Kelvin. Values outside this broad physical
    range indicate a failed GRIB bitmap/interpolation conversion, not a
    plausible weather event. The MSM near-surface temperature and humidity
    are also required so ``real.exe`` does not fall back to a pressure level.
    Ocean points are excluded because GFS soil fields are intentionally
    missing there.
    """
    first_time = config.simulation_start_utc.replace(tzinfo=None)
    inner_domain = len(config.domains)
    met_em = wps_directory / f"met_em.d{inner_domain:02d}.{first_time:%Y-%m-%d_%H:%M:%S}.nc"
    if not met_em.is_file():
        raise ExternalCommandError(f"metgrid did not create expected inner-domain input: {met_em}")

    try:
        dataset = xr.open_dataset(met_em, decode_times=False)
    except (OSError, ValueError) as exc:
        raise ExternalCommandError(f"could not inspect metgrid output {met_em}: {exc}") from exc
    try:
        required = {"ST", "LANDSEA", "TT", "RH"}
        missing = sorted(required.difference(dataset.variables))
        if missing:
            raise ExternalCommandError(
                f"metgrid output is missing required soil fields: {', '.join(missing)}"
            )
        land = dataset["LANDSEA"] > 0.5
        soil = dataset["ST"].where(land)
        minimum = float(soil.min(skipna=True))
        maximum = float(soil.max(skipna=True))
        if not 180.0 <= minimum <= maximum <= 350.0:
            raise ExternalCommandError(
                "invalid metgrid land soil temperature: "
                f"range={minimum:.2f}..{maximum:.2f} K in {met_em}; "
                "do not run WRF with corrupt surface initialization"
            )
        surface_temperature = dataset["TT"].isel(num_metgrid_levels=0).where(land)
        surface_humidity = dataset["RH"].isel(num_metgrid_levels=0).where(land)
        temperature_range = (
            float(surface_temperature.min(skipna=True)),
            float(surface_temperature.max(skipna=True)),
        )
        humidity_range = (
            float(surface_humidity.min(skipna=True)),
            float(surface_humidity.max(skipna=True)),
        )
        if not 180.0 <= temperature_range[0] <= temperature_range[1] <= 350.0:
            raise ExternalCommandError(
                "invalid or missing metgrid near-surface air temperature: "
                f"range={temperature_range[0]:.2f}..{temperature_range[1]:.2f} K in {met_em}"
            )
        if not 0.0 <= humidity_range[0] <= humidity_range[1] <= 100.0:
            raise ExternalCommandError(
                "invalid or missing metgrid near-surface relative humidity: "
                f"range={humidity_range[0]:.2f}..{humidity_range[1]:.2f} % in {met_em}"
            )
    finally:
        dataset.close()


def _prepare_wrf_run(config: ExperimentConfig, project_root: Path, case_directory: Path, wps: Path) -> Path:
    runtime = project_root / "wrf/WRFV4.8.0/install_clang/run"
    if not runtime.is_dir():
        raise ExternalCommandError(f"WRF runtime is missing: {runtime}")
    directory = case_directory / "wrf_run"
    directory.mkdir(parents=True, exist_ok=True)
    for source in runtime.iterdir():
        target = directory / source.name
        if not target.exists() and not target.is_symlink():
            target.symlink_to(source.resolve())
    write_namelists(config, directory, str(project_root / "data/geographic/WPS_GEOG"))
    for met_em in sorted(wps.glob("met_em.d0*.nc")):
        _replace_symlink(directory / met_em.name, met_em)
    return directory


def _visualize(config: ExperimentConfig, run_directory: Path, case_directory: Path) -> Path:
    start = config.simulation_start_utc.replace(tzinfo=None)
    wrfout = run_directory / f"wrfout_d03_{start:%Y-%m-%d_%H:%M:%S}"
    dataset = open_wrfout(wrfout)
    try:
        analysis = dataset.sel(
            Time=slice(pd.Timestamp(config.time.target_start_utc), pd.Timestamp(config.time.target_end_utc))
        )
        output = case_directory / "analysis"
        output.mkdir(parents=True, exist_ok=True)
        plot_surface_field(
            analysis,
            output / "temperature_map.png",
            center=(config.center.latitude, config.center.longitude),
            radius_km=config.analysis.radius_km,
        )
        if config.visualization.animation:
            create_standard_animations(
                analysis,
                output,
                suffix=config.visualization.animation_format,
                fps=config.visualization.fps,
                basemap_cache=run_directory.parents[2] / "data/geographic/gsi_tiles",
                center=(config.center.latitude, config.center.longitude),
            )
        return output
    finally:
        dataset.close()


def run_case(
    config: ExperimentConfig,
    project_root: Path,
    *,
    case_name: str | None = None,
    processes: int = 4,
    download_only: bool = False,
) -> Path:
    """Download inputs and optionally run WPS, WRF, and visualization."""
    if processes < 1:
        raise ValueError("processes must be positive")
    resolved_name = case_name or default_case_name(config)
    if Path(resolved_name).name != resolved_name:
        raise ValueError("case-name must be a single directory name")
    case_directory = project_root / "output" / resolved_name
    case_directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "target_start": config.time.target_start.isoformat(),
        "target_end": config.time.target_end.isoformat(),
        "timezone": config.time.timezone_name,
        "spinup_hours": config.time.spinup_hours,
        "simulation_start_utc": config.simulation_start_utc.isoformat(),
        "simulation_end_utc": config.simulation_end_utc.isoformat(),
        "center": {"latitude": config.center.latitude, "longitude": config.center.longitude},
        "mpi_processes": processes,
        "analysis_radius_km": config.analysis.radius_km,
        "output_interval_minutes": config.analysis.output_interval_minutes,
        "animation_format": config.visualization.animation_format,
        "animation_fps": config.visualization.fps,
    }
    (case_directory / "case.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if config.observations.use_amedas and config.time.target_start_utc < datetime.now(timezone.utc):
        try:
            download_fuchu_amedas(
                config,
                project_root / "data/observations/amedas",
                case_directory / "observations/amedas_fuchu.csv",
            )
        except ObservationDataError as exc:
            (case_directory / "observations_warning.txt").write_text(str(exc) + "\n", encoding="utf-8")
    print("Preparing date-matched MSM, GFS, and geographic inputs")
    data = prepare_forecast_data(config, project_root)
    if download_only:
        return case_directory
    wps = _prepare_wps(config, project_root, case_directory, data)
    run_directory = _prepare_wrf_run(config, project_root, case_directory, wps)
    _run([str(run_directory / "real.exe")], run_directory, "real.stdout.log", {"OMPI_MCA_btl": "self,vader"})
    _run(
        ["mpirun", "-np", str(processes), str(run_directory / "wrf.exe")],
        run_directory,
        "wrf.stdout.log",
        {"OMPI_MCA_btl": "self,vader"},
    )
    _visualize(config, run_directory, case_directory)
    return case_directory
