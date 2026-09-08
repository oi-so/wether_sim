"""Export an offline, touch-friendly 3D WRF animation without a server or CDN."""
from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from weather_sim.analysis.atmosphere import VOLUME_REQUIRED, require_variables, volume_frame
from weather_sim.analysis.spatial import haversine_km
from weather_sim.visualization.basemap import terrain_texture
from weather_sim.visualization.fields import SURFACE_FIELDS, surface_fields, field_limits, RAIN_BOUNDS, RAIN_COLORS


@dataclass(frozen=True)
class VolumeOptions:
    horizontal_stride: int = 3
    vertical_stride: int = 2
    time_stride: int = 1
    max_height_km: float = 15.0

    def __post_init__(self) -> None:
        if min(self.horizontal_stride, self.vertical_stride, self.time_stride) < 1:
            raise ValueError('3D sampling strides must be positive')
        if not np.isfinite(self.max_height_km) or self.max_height_km <= 0:
            raise ValueError('3D max height must be positive')


def _packed(array: object) -> str:
    return base64.b64encode(np.asarray(array, dtype='<f4').tobytes()).decode('ascii')


def create_volume_animation(
    dataset: xr.Dataset, output_path: str | Path, *, center: tuple[float, float],
    radius_km: float | None = 20, options: VolumeOptions | None = None,
    basemap_cache: str | Path | None = None, domain_links: dict[str, str] | None = None,
) -> Path:
    """All time frames are embedded; only display sampling changes the data size."""
    options = options or VolumeOptions()
    require_variables(dataset, VOLUME_REQUIRED)
    if radius_km is not None and (not np.isfinite(radius_km) or radius_km <= 0):
        raise ValueError('3D radius must be positive')
    if dataset.sizes.get('Time', 0) == 0:
        raise ValueError('3D animation needs at least one time')
    first = dataset.isel(Time=0)
    lat, lon = np.asarray(first.XLAT), np.asarray(first.XLONG)
    distances = haversine_km(lat, lon, *center)
    ys, xs = np.where(np.ones_like(distances, dtype=bool) if radius_km is None else distances <= radius_km)
    if not len(ys):
        raise ValueError('3D analysis area does not intersect the WRF grid')
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    cut = dataset.isel(south_north=slice(y0, y1), west_east=slice(x0, x1),
                       south_north_stag=slice(y0, y1 + 1), west_east_stag=slice(x0, x1 + 1))
    first = cut.isel(Time=0)
    lat, lon = np.asarray(first.XLAT), np.asarray(first.XLONG)
    x = (lon - center[1]) * (np.pi / 180 * 6371.0088 * np.cos(np.deg2rad(center[0])))
    y = (lat - center[0]) * (np.pi / 180 * 6371.0088)
    ground = np.asarray(first.HGT) / 1000
    hs, vs = options.horizontal_stride, options.vertical_stride
    sample = (slice(None, None, vs), slice(None, None, hs), slice(None, None, hs))
    time_indices = list(range(0, cut.sizes['Time'], options.time_stride))
    if time_indices[-1] != cut.sizes['Time'] - 1:
        time_indices.append(cut.sizes['Time'] - 1)
    arrays: dict[str, list[np.ndarray]] = {}
    for index in time_indices:
        fields = volume_frame(cut.isel(Time=index))
        for name, values in fields.items():
            arrays.setdefault(name, []).append(values[sample].astype('<f4'))
    arrays_stacked = {key: np.stack(value) for key, value in arrays.items()}
    metadata = {
        'temperature': ['気温', '°C'], 'humidity': ['相対湿度（水面基準）', '%'],
        'wind': ['3次元風速・風ベクトル', 'm/s'], 'QCLOUD': ['QCLOUD · 雲水混合比', 'g/kg'],
        'QICE': ['QICE · 雲氷混合比', 'g/kg'], 'CLDFRA': ['CLDFRA · 格子内雲量', '%'],
        'W': ['W · 鉛直流（上昇が正）', 'm/s'], 'pressure': ['気圧', 'hPa'],
    }
    scales = {}
    for name in metadata:
        values = arrays_stacked[name]
        finite = values[np.isfinite(values)]
        low, high = (float(finite.min()), float(finite.max())) if finite.size else (0., 1.)
        if name in {'humidity', 'CLDFRA'}:
            low, high = 0., 100.
        elif name == 'W':
            high = max(abs(low), abs(high), .01); low = -high
        elif name in {'QCLOUD', 'QICE', 'wind'}:
            low = 0.
        scales[name] = [low, max(high, low + 1e-6)]
    shape = arrays_stacked['height'].shape
    timestamps = [pd.Timestamp(cut.Time.values[i]).tz_localize('UTC')
                  if pd.Timestamp(cut.Time.values[i]).tzinfo is None else pd.Timestamp(cut.Time.values[i])
                  for i in time_indices]
    surface = surface_fields(cut)
    surface_data, surface_meta, surface_scales, palettes = {}, {}, {}, {}
    for name, variable, label, title, palette, limits, zero_based, vectors in SURFACE_FIELDS:
        if variable not in surface:
            continue
        values = surface[variable].isel(Time=time_indices).values
        surface_data[name] = _packed(values)
        surface_meta[name] = [title, label]
        surface_scales[name] = field_limits(values, limits, zero_based)
        palettes[name] = palette
    for name, variable in [('east', 'eastward_wind_10m_ms'), ('north', 'northward_wind_10m_ms')]:
        if variable in surface:
            surface_data[name] = _packed(surface[variable].isel(Time=time_indices).values)
    texture = terrain_texture(lat, lon, basemap_cache) if basemap_cache is not None else None
    payload = dict(
        shape=list(shape), fields={key: _packed(value) for key, value in arrays_stacked.items()},
        xy=[_packed(x[::hs, ::hs]), _packed(y[::hs, ::hs])],
        latlon=[_packed(lat[::hs, ::hs]), _packed(lon[::hs, ::hs])],
        terrain=dict(shape=list(ground.shape), x=_packed(x), y=_packed(y), z=_packed(ground),
                     lat=_packed(lat), lon=_packed(lon), texture=texture),
        surface=dict(fields=surface_data, variables=surface_meta, scales=surface_scales, palettes=palettes),
        radar=dict(bounds=RAIN_BOUNDS, colors=RAIN_COLORS), domain_links=domain_links or {},
        full_domain=radius_km is None, dx_km=float(dataset.attrs.get('DX', 1000))/1000,
        times=[t.tz_convert('Asia/Tokyo').strftime('%Y/%m/%d %H:%M:%S JST') for t in timestamps],
        variables=metadata, scales=scales, options=asdict(options), center=list(center), radius_km=float(max(np.ptp(x), np.ptp(y))/2) if radius_km is None else radius_km,
        source_domain=f"d{int(dataset.attrs.get('GRID_ID', 3)):02d}",
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    template = Path(__file__).with_name('volume_viewer.html').read_text(encoding='utf-8')
    target.write_text(template.replace('__WRF_DATA__', json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')), encoding='utf-8')
    manifest = {key: value for key, value in payload.items() if key not in {'fields', 'xy', 'latlon', 'terrain', 'surface'}}
    manifest.update(file=target.name, bytes=target.stat().st_size, terrain_shape=list(ground.shape),
                    surface_variables=surface_meta, map_zoom=texture['zoom'] if texture else None,
                    method='connected native mass-layer triangles; display-only interpolation; surface native grid; local tangent east/north km')
    target.with_suffix('.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return target
