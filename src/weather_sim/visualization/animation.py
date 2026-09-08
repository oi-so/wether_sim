"""Export standard WRF surface-field animations to MP4 or GIF."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from weather_sim.visualization.basemap import add_gsi_basemap
from weather_sim.visualization.fields import SURFACE_FIELDS, surface_fields, radar_style

matplotlib.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False


def _coordinates(dataset: xr.Dataset) -> tuple[xr.DataArray, xr.DataArray]:
    latitude = dataset["XLAT"].isel(Time=0) if "Time" in dataset["XLAT"].dims else dataset["XLAT"]
    longitude = dataset["XLONG"].isel(Time=0) if "Time" in dataset["XLONG"].dims else dataset["XLONG"]
    return latitude, longitude


def _color_limits(
    field: xr.DataArray,
    *,
    fixed_limits: tuple[float, float] | None = None,
    zero_based: bool = False,
) -> tuple[float, float]:
    if fixed_limits is not None:
        return fixed_limits
    values = field.values
    finite = values[np.isfinite(values)]
    if not finite.size:
        raise ValueError(f"{field.name or 'field'} contains no finite values")
    if zero_based:
        positive = finite[finite > 0]
        vmax = float(np.percentile(positive, 98)) if positive.size else 1.0
        return 0.0, max(vmax, 0.01)
    vmin, vmax = (float(value) for value in np.percentile(finite, [2, 98]))
    if vmin == vmax:
        vmax = vmin + 1
    return vmin, vmax


def create_field_animation(
    dataset: xr.Dataset,
    variable: str,
    output_path: str | Path,
    *,
    label: str,
    title: str,
    cmap: str,
    fps: int = 6,
    fixed_limits: tuple[float, float] | None = None,
    zero_based: bool = False,
    wind_vectors: bool = False,
    basemap_cache: str | Path | None = None,
    center: tuple[float, float] | None = None,
) -> Path:
    """Animate one 2-D surface variable using one fixed scale for all times."""
    target = Path(output_path)
    if target.suffix.lower() not in {".mp4", ".gif"}:
        raise ValueError("animation output must end in .mp4 or .gif")
    if variable not in dataset:
        raise ValueError(f"dataset does not contain {variable}")
    target.parent.mkdir(parents=True, exist_ok=True)
    field = dataset[variable]
    latitude, longitude = _coordinates(dataset)
    vmin, vmax = _color_limits(field, fixed_limits=fixed_limits, zero_based=zero_based)

    figure, axis = plt.subplots(figsize=(9, 7), constrained_layout=True)
    extent = (
        float(longitude.min()),
        float(longitude.max()),
        float(latitude.min()),
        float(latitude.max()),
    )
    if basemap_cache is not None:
        add_gsi_basemap(axis, extent, basemap_cache)
    style = dict(vmin=vmin, vmax=vmax, cmap=cmap)
    if cmap == 'radar':
        palette, norm = radar_style()
        style = dict(cmap=palette, norm=norm)
    mesh = axis.pcolormesh(
        longitude,
        latitude,
        field.isel(Time=0),
        shading="auto",
        **style,
        alpha=0.62 if basemap_cache is not None else 1.0,
        zorder=1,
    )
    figure.colorbar(mesh, ax=axis, label=label, **({'boundaries': [0,1,5,10,20,30,50,80], 'extend': 'max', 'ticks': [0,1,5,10,20,30,50,80], 'spacing': 'uniform'} if cmap == 'radar' else {}))
    timestamp_title = axis.set_title("")
    axis.set(xlabel="経度", ylabel="緯度")
    if center is not None:
        axis.scatter(center[1], center[0], marker="x", color="red", s=60, linewidths=2, zorder=4)
        axis.annotate(
            "予測地点（学校）",
            (center[1], center[0]),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=9,
            color="black",
            bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "none"},
            zorder=4,
        )
    quiver = None
    vector_step = max(1, min(field.shape[-2:]) // 20)
    if wind_vectors:
        quiver = axis.quiver(
            longitude.values[::vector_step, ::vector_step],
            latitude.values[::vector_step, ::vector_step],
            dataset["eastward_wind_10m_ms"].isel(Time=0).values[::vector_step, ::vector_step],
            dataset["northward_wind_10m_ms"].isel(Time=0).values[::vector_step, ::vector_step],
            color="black",
            alpha=0.7,
        )

    def update(index: int):
        mesh.set_array(field.isel(Time=index).values.ravel())
        timestamp = pd.Timestamp(dataset["Time"].values[index])
        timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        timestamp = timestamp.tz_convert("Asia/Tokyo")
        timestamp = timestamp.strftime("%Y年%m月%d日 %H:%M JST")
        timestamp_title.set_text(f"{title} · d{int(dataset.attrs.get('GRID_ID', 3)):02d} ({float(dataset.attrs.get('DX', 1000)) / 1000:g} km) — {timestamp}")
        artists: list[object] = [mesh, timestamp_title]
        if quiver is not None:
            quiver.set_UVC(
                dataset["eastward_wind_10m_ms"].isel(Time=index).values[::vector_step, ::vector_step],
                dataset["northward_wind_10m_ms"].isel(Time=index).values[::vector_step, ::vector_step],
            )
            artists.append(quiver)
        return artists

    movie = animation.FuncAnimation(
        figure,
        update,
        frames=field.sizes["Time"],
        interval=1000 / fps,
        blit=False,
    )
    writer = animation.PillowWriter(fps=fps) if target.suffix.lower() == ".gif" else animation.FFMpegWriter(fps=fps)
    movie.save(target, writer=writer, dpi=120)
    plt.close(figure)
    return target


def create_temperature_animation(
    dataset: xr.Dataset,
    output_path: str | Path,
    fps: int = 6,
    *,
    basemap_cache: str | Path | None = None,
    center: tuple[float, float] | None = None,
) -> Path:
    return create_field_animation(
        dataset,
        "temperature_2m_c",
        output_path,
        label="高度2 m 気温（°C）",
        title="高度2 m 気温",
        cmap="turbo",
        fps=fps,
        basemap_cache=basemap_cache,
        center=center,
    )


def create_standard_animations(
    dataset: xr.Dataset,
    output_directory: str | Path,
    *,
    suffix: str = "mp4",
    fps: int = 6,
    basemap_cache: str | Path | None = None,
    center: tuple[float, float] | None = None,
    skip_existing: bool = False,
) -> dict[str, Path]:
    """Create all standard surface animations available in a wrfout."""
    output = Path(output_directory)
    cloud_names = ('cloud_total', 'cloud_low', 'cloud_mid', 'cloud_high', 'cloud_water_path', 'cloud_ice_path')
    cloud_pending = any(
        not (output / f'{name}_animation.{suffix}').is_file()
        or (output / f'{name}_animation.{suffix}').stat().st_size == 0
        for name in cloud_names
    )
    dataset = surface_fields(dataset, include_clouds=not skip_existing or cloud_pending)
    specifications = SURFACE_FIELDS
    created: dict[str, Path] = {}
    for name, variable, label, title, cmap, limits, zero_based, vectors in specifications:
        if variable not in dataset:
            continue
        target = output / f"{name}_animation.{suffix}"
        if skip_existing and target.is_file() and target.stat().st_size > 0:
            continue
        created[name] = create_field_animation(
            dataset,
            variable,
            target,
            label=label,
            title=title,
            cmap=cmap,
            fps=fps,
            fixed_limits=limits,
            zero_based=zero_based,
            wind_vectors=vectors,
            basemap_cache=basemap_cache,
            center=center,
        )
    return created
