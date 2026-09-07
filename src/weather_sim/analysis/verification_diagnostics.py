"""Independent moisture diagnostics and like-for-like rainfall intervals."""
from __future__ import annotations

import numpy as np
import pandas as pd


def pressure_at_height(pressure_hpa, temperature_k, mixing_ratio, height_difference_m: float):
    """Hydrostatic short-column reduction using model virtual temperature.

    Positive height_difference_m means an elevated sensor, hence lower pressure.
    The constant-layer-Tv approximation is restricted to |dz| <= 100 m.
    Observed pressure/temperature never enter this model-side transformation.
    """
    if not np.isfinite(height_difference_m) or abs(height_difference_m) > 100:
        raise ValueError("pressure height difference requires a finite value within 100 m; use a vertical profile for larger offsets")
    p, t, r = np.broadcast_arrays(*(np.asarray(value, dtype=np.float64) for value in
                                   (pressure_hpa, temperature_k, mixing_ratio)))
    valid = np.isfinite(p) & np.isfinite(t) & np.isfinite(r) & (p > 0) & (t > 0) & (r >= 0)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        virtual_temperature = t * (1 + r / .622) / (1 + r)
        pressure = p * np.exp(-9.80665 * height_difference_m / (287.05 * virtual_temperature))
    return np.where(valid, pressure, np.nan)


def humidity_components(temperature: pd.DataFrame, humidity: pd.DataFrame) -> pd.DataFrame:
    """Decompose RH error at the observed T, retaining actual model values.

    T and RH must share both model and observation timestamps. The thermal
    contribution is a diagnostic counterfactual, never a bias-corrected forecast.
    """
    keys = ['model_timestamp', 'observation_timestamp']
    frame = temperature[keys + ['model', 'observed']].merge(
        humidity[keys + ['model', 'observed']], on=keys, suffixes=('_t', '_rh'), validate='one_to_one'
    ).dropna()
    frame = frame.loc[
        np.isfinite(frame[['model_t', 'observed_t', 'model_rh', 'observed_rh']]).all(axis=1)
        & frame.model_rh.between(0, 100, inclusive='right')
        & frame.observed_rh.between(0, 100, inclusive='right')
    ].copy()
    def saturation(t):
        return 611.2 * np.exp(17.67 * t / (t + 243.5))
    for prefix in ('model', 'observed'):
        e = frame[f'{prefix}_rh'] / 100 * saturation(frame[f'{prefix}_t'])
        logarithm = np.log(e / 611.2)
        frame[f'{prefix}_vapor_pressure_pa'] = e
        frame[f'{prefix}_dewpoint_c'] = 243.5 * logarithm / (17.67 - logarithm)
    frame['rh_at_observed_temperature'] = 100 * frame.model_vapor_pressure_pa / saturation(frame.observed_t)
    frame['thermal_rh_error_points'] = frame.model_rh - frame.rh_at_observed_temperature
    frame['moisture_rh_error_points'] = frame.rh_at_observed_temperature - frame.observed_rh
    frame['dewpoint_error_c'] = frame.model_dewpoint_c - frame.observed_dewpoint_c
    return frame


def cumulative_intervals(
    cumulative: pd.Series, ends: pd.DatetimeIndex, hours: np.ndarray,
) -> pd.Series:
    """Difference exact accumulation endpoints; reject resets and data gaps.

    No interpolation/extrapolation of rainfall or nearest-time endpoint matching.
    Expected cadence is inferred from the median positive observation spacing.
    """
    cumulative = cumulative.sort_index()
    if cumulative.index.has_duplicates:
        raise ValueError('cumulative precipitation timestamps must be unique')
    values = []
    cadence = cumulative.index.to_series().diff().median()
    for end, duration in zip(ends, hours, strict=True):
        if not np.isfinite(duration) or duration <= 0:
            values.append(np.nan)
            continue
        start = end - pd.Timedelta(hours=float(duration))
        window = cumulative.loc[start:end]
        invalid = (
            len(window) < 2 or window.index[0] != start or window.index[-1] != end
            or not np.isfinite(window.to_numpy()).all() or (window.diff().dropna() < 0).any()
            or (window.index.to_series().diff().dropna() > cadence * 1.5).any()
        )
        values.append(np.nan if invalid else float(window.iloc[-1] - window.iloc[0]))
    return pd.Series(values, index=ends, name='observed')
