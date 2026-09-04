"""Post-process, verify, and safely clean one completed WRF case."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from weather_sim.analysis.observation_verification import evaluate_real_observations
from weather_sim.analysis.wrf import open_wrfout
from weather_sim.errors import ObservationDataError, WeatherSimError, WRFOutputError
from weather_sim.observations.csv_reader import read_observations
from weather_sim.observations.jma_download import download_fuchu_amedas_period
from weather_sim.observations.school_wsn import read_school_wsn
from weather_sim.visualization.animation import create_standard_animations
from weather_sim.visualization.plots import plot_surface_field


CANONICAL_COLUMNS = (
    "timestamp", "station_id", "latitude", "longitude", "elevation_m",
    "variable", "value", "unit", "quality", "source",
)


@dataclass(frozen=True)
class CaseContext:
    directory: Path
    manifest: dict[str, Any]
    start: pd.Timestamp
    end: pd.Timestamp
    latitude: float
    longitude: float


@dataclass(frozen=True)
class CleanupItem:
    path: Path
    size_bytes: int
    reason: str


def load_case(case_directory: str | Path) -> CaseContext:
    """Read and validate the stable metadata written by ``run-case``."""
    directory = Path(case_directory).expanduser().resolve()
    manifest_path = directory / "case.json"
    if not manifest_path.is_file():
        raise WeatherSimError(f"case.json does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        start = pd.Timestamp(manifest["target_start"])
        end = pd.Timestamp(manifest["target_end"])
        latitude = float(manifest["center"]["latitude"])
        longitude = float(manifest["center"]["longitude"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise WeatherSimError(f"invalid case manifest {manifest_path}: {exc}") from exc
    if start.tzinfo is None or end.tzinfo is None:
        raise WeatherSimError(f"case timestamps must include timezone information: {manifest_path}")
    if end <= start:
        raise WeatherSimError(f"case target_end must be later than target_start: {manifest_path}")
    return CaseContext(directory, manifest, start.tz_convert("UTC"), end.tz_convert("UTC"), latitude, longitude)


def find_inner_wrfout(case: CaseContext) -> Path:
    """Find the single d03 output belonging to a completed case."""
    outputs = sorted(path for path in (case.directory / "wrf_run").glob("wrfout_d03_*") if path.is_file())
    if not outputs:
        raise WRFOutputError(f"d03 WRF output is missing below {case.directory / 'wrf_run'}")
    if len(outputs) > 1:
        names = ", ".join(path.name for path in outputs)
        raise WRFOutputError(f"multiple d03 WRF outputs found; specify one case per directory: {names}")
    return outputs[0]


def _target_dataset(case: CaseContext):
    dataset = open_wrfout(find_inner_wrfout(case))
    analysis = dataset.sel(Time=slice(case.start, case.end))
    if analysis.sizes.get("Time", 0) == 0:
        dataset.close()
        raise WRFOutputError(
            f"WRF output has no timestamps in the case analysis period {case.start.isoformat()}..{case.end.isoformat()}"
        )
    return dataset, analysis


def animate_case(
    case_directory: str | Path,
    project_root: str | Path,
    *,
    force: bool = False,
    suffix: str | None = None,
    fps: int | None = None,
) -> dict[str, Path]:
    """Create only missing standard animations unless ``force`` is requested."""
    case = load_case(case_directory)
    extension = suffix or str(case.manifest.get("animation_format", "mp4"))
    frame_rate = fps or int(case.manifest.get("animation_fps", 6))
    dataset, analysis = _target_dataset(case)
    try:
        output = case.directory / "analysis"
        output.mkdir(parents=True, exist_ok=True)
        map_path = output / "temperature_map.png"
        created: dict[str, Path] = {}
        if force or not map_path.is_file():
            plot_surface_field(
                analysis,
                map_path,
                center=(case.latitude, case.longitude),
                radius_km=float(case.manifest.get("analysis_radius_km", 20)),
            )
            created["temperature_map"] = map_path
        created.update(create_standard_animations(
            analysis,
            output,
            suffix=extension,
            fps=frame_rate,
            basemap_cache=Path(project_root).resolve() / "data/geographic/gsi_tiles",
            center=(case.latitude, case.longitude),
            skip_existing=not force,
        ))
        return created
    finally:
        dataset.close()


def _canonical_frame(path: Path, timezone_name: str) -> pd.DataFrame:
    frame = read_observations(path, timezone_name=timezone_name)
    return frame.loc[:, list(CANONICAL_COLUMNS)]


def prepare_case_observations(
    case_directory: str | Path,
    project_root: str | Path,
    *,
    school_directory: str | Path | None = None,
    school_elevation_m: float | None = None,
    output_path: str | Path | None = None,
    download_amedas: bool = True,
) -> Path:
    """Convert school logs and merge any downloaded AMeDAS into one canonical CSV."""
    case = load_case(case_directory)
    root = Path(project_root).resolve()
    zone = str(case.manifest.get("timezone", "Asia/Tokyo"))
    source_directory = Path(school_directory).resolve() if school_directory else root / "data/observations/school"
    frames: list[pd.DataFrame] = []

    school_paths = sorted(source_directory.glob("*.csv"))
    if school_paths:
        school = read_school_wsn(
            school_paths,
            latitude=case.latitude,
            longitude=case.longitude,
            elevation_m=school_elevation_m,
            timezone_name=zone,
        )
        frames.append(school.loc[(school["timestamp"] >= case.start) & (school["timestamp"] <= case.end)])

    amedas_path = case.directory / "observations/amedas_fuchu.csv"
    amedas_error: ObservationDataError | None = None
    if download_amedas and not amedas_path.is_file():
        try:
            download_fuchu_amedas_period(
                case.start.to_pydatetime(),
                case.end.to_pydatetime(),
                zone,
                root / "data/observations/amedas",
                amedas_path,
            )
        except ObservationDataError as exc:
            amedas_error = exc
            warning = case.directory / "observations/observations_prepare_warning.txt"
            warning.parent.mkdir(parents=True, exist_ok=True)
            warning.write_text(str(exc) + "\n", encoding="utf-8")
    if amedas_path.is_file():
        frames.append(_canonical_frame(amedas_path, zone))

    nonempty = [frame.loc[:, list(CANONICAL_COLUMNS)] for frame in frames if not frame.empty]
    if not nonempty:
        period = f"{case.start.tz_convert(zone).isoformat()}..{case.end.tz_convert(zone).isoformat()}"
        detail = f"; AMeDAS download failed: {amedas_error}" if amedas_error else ""
        raise ObservationDataError(
            "no school or AMeDAS observations are available in the case period " + period + detail
        )
    combined = pd.concat(nonempty, ignore_index=True)
    combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
    combined = combined.drop_duplicates(
        subset=["timestamp", "station_id", "variable", "source"], keep="last"
    ).sort_values(["timestamp", "station_id", "variable"])
    destination = Path(output_path).resolve() if output_path else case.directory / "observations/observations.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(destination, index=False)
    return destination


def evaluate_case(
    case_directory: str | Path,
    *,
    observations_path: str | Path | None = None,
    output_directory: str | Path | None = None,
    tolerance_minutes: float | None = None,
) -> pd.DataFrame:
    """Evaluate d03 over the case target period using a canonical observation CSV."""
    case = load_case(case_directory)
    observation_file = (
        Path(observations_path).resolve()
        if observations_path
        else case.directory / "observations/observations.csv"
    )
    observations = read_observations(
        observation_file,
        timezone_name=str(case.manifest.get("timezone", "Asia/Tokyo")),
    )
    interval = float(case.manifest.get("output_interval_minutes", 10))
    tolerance = pd.Timedelta(minutes=tolerance_minutes if tolerance_minutes is not None else interval / 2)
    dataset, analysis = _target_dataset(case)
    try:
        destination = (
            Path(output_directory).resolve()
            if output_directory
            else case.directory / "analysis/verification"
        )
        return evaluate_real_observations(
            analysis,
            observations,
            destination,
            start=case.start,
            end=case.end,
            tolerance=tolerance,
        )
    finally:
        dataset.close()


def _path_size(path: Path) -> int:
    if path.is_symlink():
        return 0
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())
    return 0


def cleanup_candidates(
    case_directory: str | Path,
    *,
    discard_resimulation: bool,
    discard_reevaluation: bool,
) -> list[CleanupItem]:
    """Return large case-local files that are unnecessary for the selected future work."""
    if not discard_resimulation and not discard_reevaluation:
        raise WeatherSimError("select --discard-resimulation and/or --discard-reevaluation")
    case = load_case(case_directory)
    wrfout = find_inner_wrfout(case)
    targets: list[tuple[Path, str]] = []
    if discard_resimulation:
        targets.extend(
            [
                (case.directory / "ungrib_msm", "MSMの展開済み中間データ"),
                (case.directory / "ungrib_gfs", "GFSの展開済み中間データ"),
                (case.directory / "wps", "WPSの中間データ"),
            ]
        )
        run = case.directory / "wrf_run"
        for pattern in ("wrfinput_d0*", "wrfbdy_d01", "met_em.d0*.nc", "wrfout_d01_*", "wrfout_d02_*"):
            targets.extend((path, "再シミュレーション用WRF中間データ") for path in run.glob(pattern))
        for name in ("freezeH2O.dat", "qr_acr_qg_V4.dat", "qr_acr_qsV2.dat"):
            targets.append((run / name, "WRFが再生成できる巨大lookupデータ"))
    if discard_reevaluation:
        analysis = case.directory / "analysis"
        products = [*analysis.glob("*_animation.mp4"), *analysis.glob("*_animation.gif")]
        products.extend(analysis.glob("verification/verification_summary.csv"))
        if not products:
            raise WeatherSimError(
                "refusing to discard d03: no animation or verification result exists in the case analysis directory"
            )
        targets.append((wrfout, "再評価・動画再生成用のd03 WRF出力"))

    unique: dict[Path, str] = {}
    for path, reason in targets:
        if path.exists() or path.is_symlink():
            unique[path] = reason
    return [CleanupItem(path, _path_size(path), reason) for path, reason in sorted(unique.items())]


def cleanup_case(items: list[CleanupItem], *, execute: bool) -> int:
    """Print a cleanup plan and optionally remove exactly those resolved paths."""
    total = sum(item.size_bytes for item in items)
    for item in items:
        print(f"{'DELETE' if execute else 'WOULD DELETE'}\t{item.size_bytes}\t{item.path}\t{item.reason}")
    if execute:
        for item in items:
            if item.path.is_symlink() or item.path.is_file():
                item.path.unlink(missing_ok=True)
            elif item.path.is_dir():
                shutil.rmtree(item.path)
    return total
