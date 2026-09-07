"""Command-line entry point for configuration, namelists, and analysis."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from weather_sim.analysis.comparison import align_and_evaluate, station_temperature_difference
from weather_sim.analysis.observation_verification import evaluate_real_observations
from weather_sim.analysis.spatial import extract_nearest_series
from weather_sim.analysis.wrf import open_wrfout
from weather_sim.analysis.stability import audit_case
from weather_sim.case_operations import (
    animate_case,
    cleanup_candidates,
    cleanup_case,
    evaluate_case,
    prepare_case_observations,
)
from weather_sim.config import load_config
from weather_sim.errors import WeatherSimError
from weather_sim.observations.csv_reader import convert_temperature_to_celsius, read_observations
from weather_sim.simulation.namelists import write_namelists
from weather_sim.simulation.workflow import run_case
from weather_sim.visualization.volume import VolumeOptions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weather-sim", description="WRF local weather simulation tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="validate and summarize an experiment YAML")
    validate.add_argument("config", type=Path)

    namelists = subparsers.add_parser("generate-namelists", help="generate namelist.wps and namelist.input")
    namelists.add_argument("config", type=Path)
    namelists.add_argument("--output-dir", type=Path, required=True)
    namelists.add_argument("--geog-data-path", required=True)

    analyze = subparsers.add_parser("analyze", help="compare one station with an existing wrfout file")
    analyze.add_argument("config", type=Path)
    analyze.add_argument("--wrfout", type=Path, required=True)
    analyze.add_argument("--observations", type=Path, required=True)
    analyze.add_argument("--station-id", required=True)
    analyze.add_argument(
        "--reference-station-id",
        help="optional AMeDAS/reference station used to verify the school-minus-reference temperature difference",
    )
    analyze.add_argument("--output-dir", type=Path, required=True)
    analyze.add_argument("--animation", action="store_true", help="also export the configured MP4/GIF")

    evaluate = subparsers.add_parser(
        "evaluate-observations",
        help="evaluate all supported WRF variables against real station observations",
    )
    evaluate.add_argument("config", type=Path)
    evaluate.add_argument("--wrfout", type=Path, required=True)
    evaluate.add_argument("--observations", type=Path, required=True)
    evaluate.add_argument("--output-dir", type=Path, required=True)

    run = subparsers.add_parser(
        "run-case",
        help="download date-matched MSM/GFS data and run WPS, WRF, and animation",
    )
    run.add_argument("--start", required=True, help="analysis start, e.g. 2026-09-01T15:00:00+09:00")
    run.add_argument("--end", required=True, help="analysis end, e.g. 2026-09-01T21:00:00+09:00")
    run.add_argument("--timezone", default="Asia/Tokyo", help="timezone for datetimes without an offset")
    run.add_argument("--spinup-hours", type=float, default=6)
    run.add_argument("--template", type=Path, default=Path("config/msm_guided.yaml"),
                     help="experiment template (default: MSM nudging and reduced parent output; accuracy under validation)")
    run.add_argument("--case-name", help="output directory name; generated from the requested period by default")
    run.add_argument("--processes", type=int, default=4, help="MPI process count for wrf.exe")
    run.add_argument("--download-only", action="store_true", help="download inputs without running WPS/WRF")
    run.add_argument("--no-animation", action="store_true", help="run WRF without exporting an animation")

    animate = subparsers.add_parser(
        "animate-case",
        help="create any missing Japanese/JST animations for an existing case",
    )
    animate.add_argument("case_directory", type=Path)
    animate.add_argument("--force", action="store_true", help="overwrite animations that already exist")
    animate.add_argument("--format", choices=("mp4", "gif"), dest="animation_format")
    animate.add_argument("--fps", type=int)
    animate.add_argument('--dimension', choices=('2d', '3d', 'both'), default='both')
    animate.add_argument('--horizontal-stride', type=int, default=3, help='3D horizontal display sampling')
    animate.add_argument('--vertical-stride', type=int, default=2, help='3D vertical display sampling')
    animate.add_argument('--time-stride', type=int, default=1, help='3D frame sampling')
    animate.add_argument('--max-height-km', type=float, default=15., help='3D upper display height MSL')

    prepare = subparsers.add_parser(
        "prepare-observations",
        help="convert school logs and merge case AMeDAS into the canonical observation CSV",
    )
    prepare.add_argument("case_directory", type=Path)
    prepare.add_argument("--school-dir", type=Path)
    prepare.add_argument("--school-elevation-m", type=float)
    prepare.add_argument("--output", type=Path)
    prepare.add_argument(
        "--no-download-amedas",
        action="store_true",
        help="do not download missing date-matched Fuchu AMeDAS observations",
    )

    case_evaluate = subparsers.add_parser(
        "evaluate-case",
        help="evaluate a completed case against its canonical real-observation CSV",
    )
    case_evaluate.add_argument("case_directory", type=Path)
    case_evaluate.add_argument("--observations", type=Path)
    case_evaluate.add_argument("--output-dir", type=Path)
    case_evaluate.add_argument("--tolerance-minutes", type=float)
    case_evaluate.add_argument("--station-metadata", type=Path, help="station height/pressure metadata YAML; default: case observations/station_metadata.yaml")

    audit = subparsers.add_parser("audit-case", help="scan saved fields and logs without running WRF")
    audit.add_argument("case_directory", type=Path)
    audit.add_argument("--output", type=Path)

    cleanup = subparsers.add_parser(
        "cleanup-case",
        help="show or delete case-local data that is no longer needed",
    )
    cleanup.add_argument("case_directory", type=Path)
    cleanup.add_argument(
        "--discard-resimulation",
        action="store_true",
        help="remove WPS/WRF intermediate data after deciding not to rerun the simulation",
    )
    cleanup.add_argument(
        "--discard-reevaluation",
        action="store_true",
        help="also remove d03 wrfout after deciding not to reevaluate or recreate videos",
    )
    cleanup.add_argument(
        "--execute",
        action="store_true",
        help="perform deletion; without this option only the deletion plan is printed",
    )
    return parser


def _validate(config_path: Path) -> int:
    config = load_config(config_path)
    summary = {
        "center": [config.center.latitude, config.center.longitude],
        "simulation_start_utc": config.simulation_start_utc.isoformat(),
        "analysis_start_utc": config.time.target_start_utc.isoformat(),
        "analysis_end_utc": config.time.target_end_utc.isoformat(),
        "simulation_end_utc": config.simulation_end_utc.isoformat(),
        "domains": [
            {"name": domain.name, "dx_m": domain.dx_m, "width_km": domain.width_km, "height_km": domain.height_km}
            for domain in config.domains
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _generate(config_path: Path, output_dir: Path, geog_data_path: str) -> int:
    paths = write_namelists(load_config(config_path), output_dir, geog_data_path)
    for path in paths:
        print(path.resolve())
    return 0


def _temperature_rows(observations: pd.DataFrame, station_id: str) -> pd.DataFrame:
    rows = observations[
        (observations["station_id"].astype(str) == str(station_id))
        & observations["variable"].astype(str).str.lower().isin({"temperature", "temperature_2m", "t2"})
        & observations["is_valid"]
    ].copy()
    if rows.empty:
        raise WeatherSimError(f"no valid temperature observations for station {station_id}")
    rows["temperature_c"] = convert_temperature_to_celsius(rows["value"], rows["unit"])
    return rows


def _model_series(dataset, rows: pd.DataFrame):
    extracted = extract_nearest_series(
        dataset["temperature_2m_c"], dataset["XLAT"], dataset["XLONG"],
        float(rows["latitude"].iloc[0]), float(rows["longitude"].iloc[0]),
    )
    return pd.Series(extracted.values, index=pd.to_datetime(dataset["Time"].values, utc=True)), extracted


def _analyze(args: argparse.Namespace) -> int:
    from weather_sim.visualization.animation import create_standard_animations
    from weather_sim.visualization.plots import plot_surface_field, plot_timeseries

    config = load_config(args.config)
    observations = read_observations(args.observations, timezone_name=config.time.timezone_name)
    station_rows = _temperature_rows(observations, args.station_id)
    station_name = str(args.station_id)

    dataset = open_wrfout(args.wrfout)
    try:
        model, extracted = _model_series(dataset, station_rows)
        observed = station_rows.set_index("timestamp")["temperature_c"]
        start = pd.Timestamp(config.time.target_start_utc)
        end = pd.Timestamp(config.time.target_end_utc)
        model = model.loc[(model.index >= start) & (model.index <= end)]
        observed = observed.loc[(observed.index >= start) & (observed.index <= end)]
        aligned, metrics = align_and_evaluate(
            model, observed, tolerance=pd.Timedelta(minutes=config.analysis.output_interval_minutes / 2)
        )

        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        aligned.to_csv(output_dir / "comparison.csv", index=False)
        report = {
            **metrics.as_dict(),
            "station_id": station_name,
            "unit": "degC",
            "grid_y": extracted.attrs["grid_y"],
            "grid_x": extracted.attrs["grid_x"],
            "grid_distance_km": extracted.attrs["grid_distance_km"],
        }
        (output_dir / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        plot_timeseries(aligned, output_dir / "temperature_timeseries.png", station_name)
        plot_surface_field(
            dataset, output_dir / "temperature_map.png", center=(config.center.latitude, config.center.longitude),
            radius_km=config.analysis.radius_km,
        )
        if args.animation:
            suffix = config.visualization.animation_format
            create_standard_animations(
                dataset,
                output_dir,
                suffix=suffix,
                fps=config.visualization.fps,
                basemap_cache=Path(__file__).resolve().parents[2] / "data/geographic/gsi_tiles",
                center=(config.center.latitude, config.center.longitude),
            )
        evaluate_real_observations(
            dataset,
            observations,
            output_dir / "verification",
            start=start,
            end=end,
            tolerance=pd.Timedelta(minutes=config.analysis.output_interval_minutes / 2),
        )
        if args.reference_station_id:
            reference_rows = _temperature_rows(observations, args.reference_station_id)
            reference_model, _ = _model_series(dataset, reference_rows)
            school_observed = station_rows.set_index("timestamp")["temperature_c"]
            reference_observed = reference_rows.set_index("timestamp")["temperature_c"]
            observed_difference = station_temperature_difference(school_observed, reference_observed)
            model_difference = station_temperature_difference(model, reference_model)
            difference_frame, _ = align_and_evaluate(
                model_difference, observed_difference,
                tolerance=pd.Timedelta(minutes=config.analysis.output_interval_minutes / 2),
            )
            difference_frame = difference_frame.loc[
                (difference_frame["timestamp"] >= start) & (difference_frame["timestamp"] <= end)
            ]
            difference_metrics = align_and_evaluate(
                difference_frame.set_index("timestamp")["model"],
                difference_frame.set_index("timestamp")["observed"], tolerance="0s"
            )[1]
            difference_frame.to_csv(output_dir / "temperature_difference_comparison.csv", index=False)
            difference_report = {
                **difference_metrics.as_dict(), "station_id": station_name,
                "reference_station_id": str(args.reference_station_id), "unit": "degC",
            }
            (output_dir / "temperature_difference_metrics.json").write_text(
                json.dumps(difference_report, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            plot_timeseries(
                difference_frame, output_dir / "temperature_difference_timeseries.png",
                f"{station_name} − {args.reference_station_id}",
            )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        dataset.close()
    return 0


def _evaluate_observations(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    observations = read_observations(args.observations, timezone_name=config.time.timezone_name)
    dataset = open_wrfout(args.wrfout)
    try:
        summary = evaluate_real_observations(
            dataset,
            observations,
            args.output_dir.resolve(),
            start=pd.Timestamp(config.time.target_start_utc),
            end=pd.Timestamp(config.time.target_end_utc),
            tolerance=pd.Timedelta(minutes=config.analysis.output_interval_minutes / 2),
        )
        print(summary.to_json(orient="records", force_ascii=False, indent=2))
    finally:
        dataset.close()
    return 0


def _cli_datetime(value: str, zone: ZoneInfo) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 datetime: {value}") from exc
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed


def _run_case(args: argparse.Namespace) -> int:
    zone = ZoneInfo(args.timezone)
    template = load_config(args.template)
    configured = replace(
        template,
        time=replace(
            template.time,
            target_start=_cli_datetime(args.start, zone),
            target_end=_cli_datetime(args.end, zone),
            timezone_name=args.timezone,
            spinup_hours=args.spinup_hours,
        ),
        visualization=replace(template.visualization, animation=not args.no_animation),
    )
    project_root = Path(__file__).resolve().parents[2]
    output = run_case(
        configured,
        project_root,
        case_name=args.case_name,
        processes=args.processes,
        download_only=args.download_only,
    )
    print(output.resolve())
    return 0


def _animate_case(args: argparse.Namespace) -> int:
    if args.fps is not None and args.fps <= 0:
        raise ValueError("fps must be positive")
    project_root = Path(__file__).resolve().parents[2]
    created = animate_case(
        args.case_directory,
        project_root,
        force=args.force,
        suffix=args.animation_format,
        fps=args.fps,
        dimension=args.dimension,
        volume_options=VolumeOptions(args.horizontal_stride, args.vertical_stride, args.time_stride, args.max_height_km),
    )
    if created:
        for name, path in created.items():
            print(f"created {name}: {path.resolve()}")
    else:
        print("all available animations already exist; nothing was changed")
    return 0


def _prepare_observations(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parents[2]
    output = prepare_case_observations(
        args.case_directory,
        project_root,
        school_directory=args.school_dir,
        school_elevation_m=args.school_elevation_m,
        output_path=args.output,
        download_amedas=not args.no_download_amedas,
    )
    rows = len(pd.read_csv(output))
    print(f"wrote {rows} canonical observation rows: {output.resolve()}")
    return 0


def _evaluate_case(args: argparse.Namespace) -> int:
    if args.tolerance_minutes is not None and args.tolerance_minutes < 0:
        raise ValueError("tolerance-minutes must be non-negative")
    summary = evaluate_case(
        args.case_directory,
        observations_path=args.observations,
        output_directory=args.output_dir,
        tolerance_minutes=args.tolerance_minutes,
        station_metadata_path=args.station_metadata,
    )
    if summary.empty:
        raise WeatherSimError("no comparable model/observation pairs were found in the case period")
    print(summary.to_json(orient="records", force_ascii=False, indent=2))
    return 0


def _cleanup_case(args: argparse.Namespace) -> int:
    items = cleanup_candidates(
        args.case_directory,
        discard_resimulation=args.discard_resimulation,
        discard_reevaluation=args.discard_reevaluation,
    )
    total = cleanup_case(items, execute=args.execute)
    gib = total / 1024**3
    verb = "deleted" if args.execute else "would delete"
    print(f"{verb} {len(items)} paths ({gib:.2f} GiB)")
    if not args.execute:
        print("dry-run only; add --execute to perform the deletion")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-config":
            return _validate(args.config)
        if args.command == "generate-namelists":
            return _generate(args.config, args.output_dir, args.geog_data_path)
        if args.command == "analyze":
            return _analyze(args)
        if args.command == "evaluate-observations":
            return _evaluate_observations(args)
        if args.command == "run-case":
            return _run_case(args)
        if args.command == "animate-case":
            return _animate_case(args)
        if args.command == "prepare-observations":
            return _prepare_observations(args)
        if args.command == "evaluate-case":
            return _evaluate_case(args)
        if args.command == "audit-case":
            report = audit_case(args.case_directory, args.output)
            print(json.dumps({key: report[key] for key in ("case", "wrf_success", "log_counts", "issues")}, indent=2))
            return 1 if report["issues"] else 0
        if args.command == "cleanup-case":
            return _cleanup_case(args)
    except (WeatherSimError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
