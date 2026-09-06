"""Multi-variable verification against real station observations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from weather_sim.analysis.metrics import calculate_metrics
from weather_sim.analysis.spatial import extract_nearest_series
from weather_sim.analysis.verification_diagnostics import cumulative_intervals, humidity_components
from weather_sim.observations.csv_reader import convert_temperature_to_celsius

matplotlib.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


@dataclass(frozen=True)
class VerificationVariable:
    observation_variable: str
    model_variable: str
    output_name: str
    label_ja: str
    unit: str


VARIABLES = (
    VerificationVariable("temperature", "temperature_2m_c", "temperature", "気温", "°C"),
    VerificationVariable("relative_humidity", "relative_humidity_2m_percent", "humidity", "相対湿度", "%"),
    VerificationVariable("wind_speed", "wind_speed_10m_ms", "wind_speed", "風速", "m/s"),
    VerificationVariable("pressure", "surface_pressure_hpa", "pressure", "地表気圧", "hPa"),
    VerificationVariable("precipitation", "precipitation_interval_mm", "precipitation", "時間降水量", "mm"),
    VerificationVariable("precipitation_accumulated", "precipitation_interval_mm", "precipitation_accumulation_difference", "区間降水量（積算観測差分）", "mm"),
    VerificationVariable("precipitation_rate", "precipitation_rate_mm_h", "precipitation_rate", "降水強度", "mm/h"),
)

STATION_NAMES = {"school": "学校", "amedas_fuchu": "府中アメダス"}


def _observation_values(rows: pd.DataFrame, specification: VerificationVariable) -> pd.Series:
    if specification.observation_variable == "temperature":
        return convert_temperature_to_celsius(rows["value"], rows["unit"])
    values = pd.to_numeric(rows["value"], errors="coerce")
    if specification.observation_variable == "pressure":
        units = rows["unit"].astype(str).str.lower()
        values = values.where(~units.eq("pa"), values / 100.0)
    return values


def _model_series(
    dataset: xr.Dataset,
    specification: VerificationVariable,
    latitude: float,
    longitude: float,
) -> tuple[pd.Series, xr.DataArray]:
    source_name = specification.model_variable
    if source_name == "precipitation_rate_mm_h":
        source_name = "precipitation_interval_mm"
    extracted = extract_nearest_series(dataset[source_name], dataset["XLAT"], dataset["XLONG"], latitude, longitude)
    times = pd.DatetimeIndex(pd.to_datetime(dataset["Time"].values, utc=True))
    values = np.asarray(extracted.values, dtype=float)
    if specification.model_variable == "precipitation_rate_mm_h":
        hours = (
            dataset["precipitation_interval_hours"].values
            if "precipitation_interval_hours" in dataset
            else pd.Series(times).diff().dt.total_seconds().to_numpy() / 3600.0
        )
        values = values / hours
    return pd.Series(values, index=times, name="model"), extracted


def _align_at_model_times(model: pd.Series, observed: pd.Series, tolerance: pd.Timedelta) -> pd.DataFrame:
    model_frame = model.sort_index().rename_axis("model_timestamp").reset_index()
    observation_frame = observed.sort_index().rename("observed").rename_axis("observation_timestamp").reset_index()
    model_frame["model_timestamp"] = pd.to_datetime(model_frame["model_timestamp"], utc=True)
    observation_frame["observation_timestamp"] = pd.to_datetime(observation_frame["observation_timestamp"], utc=True)
    paired = pd.merge_asof(
        model_frame,
        observation_frame,
        left_on="model_timestamp",
        right_on="observation_timestamp",
        direction="nearest",
        tolerance=tolerance,
    )
    paired["time_offset_seconds"] = (
        paired["observation_timestamp"] - paired["model_timestamp"]
    ).dt.total_seconds()
    paired["error"] = paired["model"] - paired["observed"]
    return paired


def _plot_pairs(
    paired: pd.DataFrame,
    target: Path,
    station_id: str,
    specification: VerificationVariable,
) -> None:
    valid = paired.dropna(subset=["model", "observed"])
    times = valid["model_timestamp"].dt.tz_convert("Asia/Tokyo")
    figure, axis = plt.subplots(figsize=(11, 5), constrained_layout=True)
    axis.plot(times, valid["observed"], marker="o", markersize=3, label="実観測")
    axis.plot(times, valid["model"], linewidth=1.8, label="WRF")
    station_name = STATION_NAMES.get(station_id, station_id)
    axis.set(
        title=f"{station_name}：{specification.label_ja}の実観測とWRF比較",
        xlabel="時刻（JST）",
        ylabel=f"{specification.label_ja}（{specification.unit}）",
    )
    axis.grid(alpha=0.3)
    axis.legend()
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=150)
    plt.close(figure)


def evaluate_real_observations(
    dataset: xr.Dataset,
    observations: pd.DataFrame,
    output_directory: str | Path,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    tolerance: pd.Timedelta,
) -> pd.DataFrame:
    """Evaluate every supported station/variable pair and write auditable products."""
    output = Path(output_directory)
    pairs_directory = output / "pairs"
    plots_directory = output / "plots"
    records: list[dict[str, object]] = []
    moisture_records: list[dict[str, object]] = []
    available = set(dataset.variables)
    for station_id in sorted(observations["station_id"].astype(str).unique()):
        station = observations[
            (observations["station_id"].astype(str) == station_id)
            & observations["is_valid"]
        ].copy()
        if station.empty:
            continue
        latitude = float(station["latitude"].iloc[0])
        longitude = float(station["longitude"].iloc[0])
        elevation = pd.to_numeric(station["elevation_m"], errors="coerce").dropna()
        station_pairs: dict[str, pd.DataFrame] = {}
        for specification in VARIABLES:
            source_name = (
                "precipitation_interval_mm"
                if specification.model_variable == "precipitation_rate_mm_h"
                else specification.model_variable
            )
            rows = station[station["variable"].astype(str) == specification.observation_variable].copy()
            if rows.empty or source_name not in available:
                continue
            rows["normalized_value"] = _observation_values(rows, specification)
            observed = rows.set_index("timestamp")["normalized_value"]
            observed.index = pd.to_datetime(observed.index, utc=True)
            model, extracted = _model_series(dataset, specification, latitude, longitude)
            model = model.loc[(model.index >= start) & (model.index <= end)]
            if specification.observation_variable == 'precipitation_accumulated':
                if 'precipitation_interval_hours' not in dataset:
                    continue
                durations = pd.Series(dataset['precipitation_interval_hours'].values,
                                      index=pd.to_datetime(dataset.Time.values, utc=True)).reindex(model.index)
                observed = cumulative_intervals(observed, model.index, durations.to_numpy())
            else:
                observed = observed.loc[(observed.index >= start) & (observed.index <= end)]
            if observed.empty or model.empty:
                continue
            paired = _align_at_model_times(model, observed, tolerance)
            station_pairs[specification.output_name] = paired
            metrics = calculate_metrics(paired["model"], paired["observed"])
            valid_pairs = paired.loc[np.isfinite(paired["model"]) & np.isfinite(paired["observed"])]
            base_name = f"{station_id}_{specification.output_name}"
            pairs_directory.mkdir(parents=True, exist_ok=True)
            paired.to_csv(pairs_directory / f"{base_name}.csv", index=False)
            _plot_pairs(paired, plots_directory / f"{base_name}.png", station_id, specification)
            grid_y = int(extracted.attrs["grid_y"])
            grid_x = int(extracted.attrs["grid_x"])
            model_elevation = None
            if "HGT" in dataset:
                height = dataset["HGT"]
                if "Time" in height.dims:
                    height = height.isel(Time=0)
                model_elevation = float(height.isel(south_north=grid_y, west_east=grid_x))
            records.append(
                {
                    "station_id": station_id,
                    "station_name": STATION_NAMES.get(station_id, station_id),
                    "variable": specification.output_name,
                    "variable_name": specification.label_ja,
                    "unit": specification.unit,
                    **metrics.as_dict(),
                    "mean_model": float(valid_pairs["model"].mean()),
                    "mean_observed": float(valid_pairs["observed"].mean()),
                    "grid_y": grid_y + int(dataset.attrs.get("grid_y_offset", 0)),
                    "grid_x": grid_x + int(dataset.attrs.get("grid_x_offset", 0)),
                    "grid_distance_km": float(extracted.attrs["grid_distance_km"]),
                    "observation_elevation_m": float(elevation.iloc[0]) if not elevation.empty else None,
                    "model_elevation_m": model_elevation,
                }
            )
        if {'temperature', 'humidity'}.issubset(station_pairs):
            moisture = humidity_components(station_pairs['temperature'], station_pairs['humidity'])
            moisture.to_csv(pairs_directory / f'{station_id}_moisture_diagnostics.csv', index=False)
            dew = calculate_metrics(moisture.model_dewpoint_c, moisture.observed_dewpoint_c)
            moisture_records.append({
                'station_id': station_id, 'dewpoint_bias_c': dew.bias, 'dewpoint_rmse_c': dew.rmse, 'n': dew.n,
                'thermal_rh_error_points': float(moisture.thermal_rh_error_points.mean()),
                'moisture_rh_error_points': float(moisture.moisture_rh_error_points.mean()),
            })
    summary = pd.DataFrame.from_records(records)
    output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output / "verification_summary.csv", index=False)
    pd.DataFrame(moisture_records).to_csv(output / 'moisture_summary.csv', index=False)
    (output / "verification_summary.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    return summary
