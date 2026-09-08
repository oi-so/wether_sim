"""Shared surface fields and fixed radar-style scales for movies and HTML."""
from __future__ import annotations

import numpy as np
import xarray as xr
from matplotlib.colors import BoundaryNorm, ListedColormap

from weather_sim.analysis.atmosphere import CLOUD_REQUIRED, cloud_columns

RAIN_BOUNDS = [0., 1., 5., 10., 20., 30., 50., 80., 1000.]
RAIN_COLORS = ['#d7e3eb', '#a0d2ff', '#218cff', '#0041ff', '#faf500', '#ff9900', '#ff2800', '#b40068']
# name, variable, unit label, title, palette, limits, zero-based, vectors
SURFACE_FIELDS = (
    ('temperature', 'temperature_2m_c', '高度2 m 気温（°C）', '高度2 m 気温', 'turbo', None, False, False),
    ('wind', 'wind_speed_10m_ms', '高度10 m 風速（m/s）', '高度10 m 風向・風速', 'viridis', None, True, True),
    ('humidity', 'relative_humidity_2m_percent', '高度2 m 相対湿度（%）', '高度2 m 相対湿度', 'YlGnBu', (0., 100.), False, False),
    ('precipitation', 'precipitation_rate_mmh', '区間平均の降水強度（mm/h）', '降水強度（モデル予測）', 'radar', (0., 80.), True, False),
    ('precipitation_interval', 'precipitation_interval_mm', '区間降水量（mm/実出力間隔）', '区間降水量', 'radar', (0., 80.), True, False),
    ('pressure', 'surface_pressure_hpa', '地表気圧（hPa）', '地表気圧', 'coolwarm', None, False, False),
    ('skin_temperature', 'skin_temperature_c', '地表面温度（°C）', '地表面温度', 'inferno', None, False, False),
    ('cloud_total', 'cloud_total', '総雲量（%）', '総雲量・最大ランダム重なり', 'Greys_r', (0., 100.), False, False),
    ('cloud_low', 'cloud_low', '下層雲量（%）', '下層雲量・地上300〜2000 m', 'Greys_r', (0., 100.), False, False),
    ('cloud_mid', 'cloud_mid', '中層雲量（%）', '中層雲量・地上2000〜6000 m', 'Greys_r', (0., 100.), False, False),
    ('cloud_high', 'cloud_high', '上層雲量（%）', '上層雲量・地上6000 m以上', 'Greys_r', (0., 100.), False, False),
    ('cloud_water_path', 'cloud_water_path', '雲水鉛直積算量（kg/m²）', '雲水鉛直積算量', 'Greys_r', None, True, False),
    ('cloud_ice_path', 'cloud_ice_path', '雲氷鉛直積算量（kg/m²）', '雲氷鉛直積算量', 'Greys_r', None, True, False),
)


def surface_fields(dataset: xr.Dataset, *, include_clouds: bool = True) -> xr.Dataset:
    result = dataset
    if 'precipitation_interval_mm' in result and 'precipitation_interval_hours' in result:
        hours = result.precipitation_interval_hours
        result = result.assign(precipitation_rate_mmh=result.precipitation_interval_mm / hours.where(hours > 0))
        result.precipitation_rate_mmh.attrs.update(units='mm h-1', long_name='mean rate over actual output interval')
    if include_clouds and CLOUD_REQUIRED.issubset(result.variables):
        result = result.assign(cloud_columns(result))
    return result


def radar_style():
    cmap = ListedColormap(RAIN_COLORS, name='wrf_radar')
    cmap = cmap.with_extremes(over=RAIN_COLORS[-1], bad=(0, 0, 0, 0))
    return cmap, BoundaryNorm(RAIN_BOUNDS, cmap.N, clip=False)


def field_limits(values, limits=None, zero_based=False):
    if limits is not None:
        return list(limits)
    finite = np.asarray(values)[np.isfinite(values)]
    if not finite.size:
        return [0., 1.]
    if zero_based:
        positive = finite[finite > 0]
        return [0., max(float(np.percentile(positive, 98)) if positive.size else 1., .01)]
    low, high = np.percentile(finite, [2, 98])
    return [float(low), float(high if high > low else low + 1)]
