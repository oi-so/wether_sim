"""Export WRF temperature and wind animation to MP4 or GIF."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr


def create_temperature_animation(dataset: xr.Dataset, output_path: str | Path, fps: int = 6) -> Path:
    target = Path(output_path)
    if target.suffix.lower() not in {".mp4", ".gif"}:
        raise ValueError("animation output must end in .mp4 or .gif")
    target.parent.mkdir(parents=True, exist_ok=True)
    temperature = dataset["temperature_2m_c"]
    latitude = dataset["XLAT"].isel(Time=0) if "Time" in dataset["XLAT"].dims else dataset["XLAT"]
    longitude = dataset["XLONG"].isel(Time=0) if "Time" in dataset["XLONG"].dims else dataset["XLONG"]
    finite = temperature.values[np.isfinite(temperature.values)]
    if not finite.size:
        raise ValueError("temperature contains no finite values")
    vmin, vmax = np.percentile(finite, [2, 98])
    if vmin == vmax:
        vmax = vmin + 1
    figure, axis = plt.subplots(figsize=(9, 7), constrained_layout=True)
    mesh = axis.pcolormesh(longitude, latitude, temperature.isel(Time=0), shading="auto", cmap="turbo", vmin=vmin, vmax=vmax)
    figure.colorbar(mesh, ax=axis, label="2 m temperature (°C)")
    title = axis.set_title("")
    axis.set(xlabel="Longitude", ylabel="Latitude")

    def update(index: int):
        mesh.set_array(temperature.isel(Time=index).values.ravel())
        title.set_text(pd.Timestamp(dataset["Time"].values[index]).strftime("%Y-%m-%d %H:%M UTC"))
        return mesh, title

    movie = animation.FuncAnimation(figure, update, frames=temperature.sizes["Time"], interval=1000 / fps, blit=False)
    writer = animation.PillowWriter(fps=fps) if target.suffix.lower() == ".gif" else animation.FFMpegWriter(fps=fps)
    movie.save(target, writer=writer, dpi=120)
    plt.close(figure)
    return target
