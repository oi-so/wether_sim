"""Reproducible, non-interactive Version 1 plots."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from weather_sim.analysis.spatial import radius_mask


def plot_surface_field(
    dataset: xr.Dataset,
    output_path: str | Path,
    *,
    time_index: int = 0,
    center: tuple[float, float] | None = None,
    radius_km: float | None = None,
    show_wind: bool = True,
) -> Path:
    temperature = dataset["temperature_2m_c"].isel(Time=time_index)
    latitude = dataset["XLAT"].isel(Time=0) if "Time" in dataset["XLAT"].dims else dataset["XLAT"]
    longitude = dataset["XLONG"].isel(Time=0) if "Time" in dataset["XLONG"].dims else dataset["XLONG"]
    values = temperature.values.copy()
    if center is not None and radius_km is not None:
        values = np.where(radius_mask(latitude, longitude, center[0], center[1], radius_km), values, np.nan)
    figure, axis = plt.subplots(figsize=(9, 7), constrained_layout=True)
    field = axis.pcolormesh(longitude, latitude, values, shading="auto", cmap="turbo")
    figure.colorbar(field, ax=axis, label="2 m temperature (°C)")
    if show_wind:
        step = max(1, min(values.shape) // 20)
        axis.quiver(
            longitude.values[::step, ::step], latitude.values[::step, ::step],
            dataset["U10"].isel(Time=time_index).values[::step, ::step],
            dataset["V10"].isel(Time=time_index).values[::step, ::step],
            color="black", alpha=0.7,
        )
    if center is not None:
        axis.scatter(center[1], center[0], marker="x", color="white", s=60, label="center")
        axis.legend()
    timestamp = pd.Timestamp(dataset["Time"].values[time_index]).strftime("%Y-%m-%d %H:%M UTC")
    axis.set(title=f"WRF surface field — {timestamp}", xlabel="Longitude", ylabel="Latitude")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=150)
    plt.close(figure)
    return target


def plot_timeseries(aligned: pd.DataFrame, output_path: str | Path, station_name: str) -> Path:
    figure, axis = plt.subplots(figsize=(10, 5), constrained_layout=True)
    axis.plot(aligned["timestamp"], aligned["observed"], marker="o", label="Observation")
    axis.plot(aligned["timestamp"], aligned["model"], label="WRF")
    axis.set(title=f"2 m temperature — {station_name}", xlabel="Time (UTC)", ylabel="Temperature (°C)")
    axis.grid(alpha=0.3)
    axis.legend()
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=150)
    plt.close(figure)
    return target
