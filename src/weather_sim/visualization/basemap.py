"""Cached Japanese GSI tile backgrounds for scientific plots."""

from __future__ import annotations

import io
import math
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from weather_sim.network import open_trusted_url

GSI_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png"


def _tile_x(longitude: float, zoom: int) -> int:
    return int(math.floor((longitude + 180.0) / 360.0 * 2**zoom))


def _tile_y(latitude: float, zoom: int) -> int:
    clipped = max(-85.05112878, min(85.05112878, latitude))
    radians = math.radians(clipped)
    return int(math.floor((1.0 - math.asinh(math.tan(radians)) / math.pi) / 2.0 * 2**zoom))


def _longitude(x: int, zoom: int) -> float:
    return x / 2**zoom * 360.0 - 180.0


def _latitude(y: int, zoom: int) -> float:
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / 2**zoom))))


def _zoom_for_extent(west: float, east: float) -> int:
    span = max(east - west, 0.01)
    return max(5, min(13, round(math.log2(360.0 * 5.0 / span))))


def _tile_image(cache: Path, zoom: int, x: int, y: int) -> Image.Image:
    path = cache / "std" / str(zoom) / str(x) / f"{y}.png"
    if path.is_file() and path.stat().st_size:
        return Image.open(path).convert("RGB")
    url = GSI_TILE_URL.format(z=zoom, x=x, y=y)
    request = urllib.request.Request(url, headers={"User-Agent": "weather-sim/0.1 (research visualization)"})
    try:
        with open_trusted_url(request, timeout=30) as response:
            content = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(f"地理院タイルを取得できませんでした: {url}: {exc}") from exc
    image = Image.open(io.BytesIO(content)).convert("RGB")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return image


def add_gsi_basemap(axis, extent: tuple[float, float, float, float], cache: str | Path) -> None:
    """Draw standard GSI tiles under an existing lon/lat plot."""
    west, east, south, north = extent
    zoom = _zoom_for_extent(west, east)
    x_min, x_max = _tile_x(west, zoom), _tile_x(east, zoom)
    y_min, y_max = _tile_y(north, zoom), _tile_y(south, zoom)
    cache_path = Path(cache)
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            image = _tile_image(cache_path, zoom, x, y)
            axis.imshow(
                image,
                extent=(_longitude(x, zoom), _longitude(x + 1, zoom), _latitude(y + 1, zoom), _latitude(y, zoom)),
                origin="upper",
                interpolation="bilinear",
                zorder=0,
            )
    axis.set_xlim(west, east)
    axis.set_ylim(south, north)
    axis.text(
        0.995,
        0.005,
        "背景地図：国土地理院",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "none"},
        zorder=5,
    )
