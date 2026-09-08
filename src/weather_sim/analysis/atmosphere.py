"""WRF volume diagnostics and explicitly defined cloud column products."""
from __future__ import annotations

import numpy as np
import xarray as xr

from weather_sim.errors import WRFOutputError

GRAVITY = 9.81
RD = 287.0
CP = 1004.5
EPSILON = 0.622
CLOUD_REQUIRED = {'CLDFRA', 'QCLOUD', 'QICE', 'PH', 'PHB', 'P', 'PB', 'T', 'QVAPOR', 'HGT'}
VOLUME_REQUIRED = CLOUD_REQUIRED | {'U', 'V', 'W', 'COSALPHA', 'SINALPHA', 'XLAT', 'XLONG'}


def require_variables(dataset: xr.Dataset, names: set[str]) -> None:
    missing = names - set(dataset.variables)
    if missing:
        raise WRFOutputError('3D/cloud diagnostics require: ' + ', '.join(sorted(missing)))


def unstagger(values: np.ndarray, axis: int) -> np.ndarray:
    lower, upper = [slice(None)] * values.ndim, [slice(None)] * values.ndim
    lower[axis], upper[axis] = slice(None, -1), slice(1, None)
    return (values[tuple(lower)] + values[tuple(upper)]) * 0.5


def thermodynamics(frame: xr.Dataset, *, include_humidity: bool = True) -> dict[str, np.ndarray]:
    """Single time, native mass grid. RH is relative to liquid water."""
    pressure = np.asarray(frame.P + frame.PB)
    temperature = (np.asarray(frame.T) + 300.0) * (pressure / 100000.0) ** (RD / CP)
    mixing_ratio = np.asarray(frame.QVAPOR)
    interface_height = np.asarray(frame.PH + frame.PHB) / GRAVITY
    height = unstagger(interface_height, 0)
    thickness = np.diff(interface_height, axis=0)
    if np.any(thickness <= 0):
        raise WRFOutputError('non-positive WRF layer thickness')
    result = dict(pressure=pressure, temperature=temperature, height=height,
                thickness=thickness,
                dry_density=pressure / (RD * temperature * (1 + mixing_ratio / EPSILON)))
    if include_humidity:
        vapor_pressure = mixing_ratio * pressure / (EPSILON + mixing_ratio)
        saturation = 611.2 * np.exp(17.67 * (temperature - 273.15) / (temperature - 29.65))
        result['humidity'] = np.clip(100 * vapor_pressure / saturation, 0, 100)
    return result


def cloud_overlap(fraction: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Maximum overlap within adjacent cloudy layers, random across clear gaps.

    Axis 0 is vertical. Missing data in a selected layer gives a missing column.
    An empty altitude band is missing, not clear sky.
    """
    included = np.ones_like(fraction, dtype=bool) if mask is None else mask
    if mask is not None:
        # Exterior excluded layers contribute only multiplication by one and
        # zero blocks. Trim those layers, keeping every interior clear gap.
        active = np.flatnonzero(np.any(included, axis=tuple(range(1, included.ndim))))
        if not active.size:
            return np.full(fraction.shape[1:], np.nan)
        band = slice(active[0], active[-1] + 1)
        fraction, included = fraction[band], included[band]
    valid = np.isfinite(fraction)
    values = np.where(included & valid, np.clip(fraction, 0, 1), 0)
    clear_probability = np.ones(fraction.shape[1:], dtype=np.float64)
    block = np.zeros_like(clear_probability)
    for layer in values:
        gap = layer <= 0
        clear_probability *= np.where(gap, 1 - block, 1)
        block = np.where(gap, 0, np.maximum(block, layer))
    cover = 1 - clear_probability * (1 - block)
    return np.where(included.any(axis=0) & ~(included & ~valid).any(axis=0), cover * 100, np.nan)


def cloud_columns(dataset: xr.Dataset) -> xr.Dataset:
    """Process one time at a time; all native levels enter the integrals.

    AGL bands: low 300–2000 m (excludes fog), middle 2000–6000 m,
    high >=6000 m. Total includes fog. LWP/IWP exclude rain/snow/graupel.
    """
    require_variables(dataset, CLOUD_REQUIRED)
    names = ['cloud_total', 'cloud_low', 'cloud_mid', 'cloud_high', 'cloud_water_path', 'cloud_ice_path']
    frames: dict[str, list[np.ndarray]] = {name: [] for name in names}
    for index in range(dataset.sizes['Time']):
        frame = dataset.isel(Time=index)
        thermo = thermodynamics(frame, include_humidity=False)
        height_agl = thermo['height'] - np.asarray(frame.HGT)
        fraction = np.asarray(frame.CLDFRA)
        masks = [None, (height_agl >= 300) & (height_agl < 2000),
                 (height_agl >= 2000) & (height_agl < 6000), height_agl >= 6000]
        for name, mask in zip(names[:4], masks):
            frames[name].append(cloud_overlap(fraction, mask).astype('float32'))
        for name, raw in [('cloud_water_path', 'QCLOUD'), ('cloud_ice_path', 'QICE')]:
            mass = np.asarray(frame[raw]) * thermo['dry_density'] * thermo['thickness']
            frames[name].append(np.sum(np.where(mass >= 0, mass, np.nan), axis=0).astype('float32'))
    result = xr.Dataset(coords={'Time': dataset.Time})
    for name, values in frames.items():
        result[name] = xr.DataArray(np.stack(values), dims=('Time', 'south_north', 'west_east'))
        result[name].attrs.update(units='kg m-2' if name.endswith('path') else '%',
                                  cloud_overlap='maximum-random', vertical_reference='AGL')
    return result


def volume_frame(frame: xr.Dataset) -> dict[str, np.ndarray]:
    """Return mass-point winds rotated to east/north, heights MSL, physical T."""
    require_variables(frame, VOLUME_REQUIRED)
    thermo = thermodynamics(frame)
    u = unstagger(np.asarray(frame.U), 2)
    v = unstagger(np.asarray(frame.V), 1)
    w = unstagger(np.asarray(frame.W), 0)
    cos, sin = np.asarray(frame.COSALPHA), np.asarray(frame.SINALPHA)
    east, north = u * cos - v * sin, v * cos + u * sin
    return {
        'height': thermo['height'] / 1000, 'temperature': thermo['temperature'] - 273.15,
        'humidity': thermo['humidity'], 'pressure': thermo['pressure'] / 100,
        'wind': np.sqrt(east**2 + north**2 + w**2), 'east': east, 'north': north,
        'W': w, 'QCLOUD': np.asarray(frame.QCLOUD) * 1000,
        'QICE': np.asarray(frame.QICE) * 1000, 'CLDFRA': np.asarray(frame.CLDFRA) * 100,
    }
