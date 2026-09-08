"""Validate finite surface inputs without mistaking masked ocean soil for land."""
from pathlib import Path

import numpy as np
import xarray as xr

from weather_sim.errors import ExternalCommandError


def validate_urban_fraction_file(path: Path, center: tuple[float, float]) -> dict:
    """Reject absent/invalid urban data; report cells using WRF's table fallback.

Only the configured centre must have positive coverage when classified urban.
Other zero-fraction urban cells are counted explicitly for later diagnostics.
"""
    with xr.open_dataset(path, decode_times=False) as dataset:
        required = {'FRC_URB2D', 'LU_INDEX', 'XLAT_M', 'XLONG_M'}
        if required - set(dataset.variables) or dataset.attrs.get('FLAG_FRC_URB2D') != 1:
            raise ExternalCommandError(f'GAIA urban fraction missing from metgrid: {path}')
        fraction = dataset.FRC_URB2D.isel(Time=0).values
        urban = dataset.LU_INDEX.isel(Time=0).values == int(dataset.attrs.get('ISURBAN', 13))
        if not np.isfinite(fraction).all() or np.any((fraction < 0) | (fraction > 1)):
            raise ExternalCommandError(f'urban fraction must be finite and within 0..1: {path}')
        lat, lon = dataset.XLAT_M.isel(Time=0).values, dataset.XLONG_M.isel(Time=0).values
        distance = (lat - center[0]) ** 2 + ((lon - center[1]) * np.cos(np.deg2rad(center[0]))) ** 2
        y, x = np.unravel_index(np.argmin(distance), distance.shape)
        if urban[y, x] and fraction[y, x] <= 0:
            raise ExternalCommandError(f'urban fraction is zero at the urban analysis centre: {path}')
        return {'file': path.name, 'urban_cells': int(urban.sum()),
                'zero_fraction_urban_cells': int(np.count_nonzero(urban & (fraction == 0))),
                'minimum': float(fraction.min()), 'maximum': float(fraction.max()),
                'centre_fraction': float(fraction[y, x]), 'centre_is_urban': bool(urban[y, x])}


def validate_metgrid_file(path: Path) -> None:
    try:
        source = xr.open_dataset(path, decode_times=False)
    except (OSError, ValueError) as exc:
        raise ExternalCommandError(f"could not inspect metgrid output {path}: {exc}") from exc
    with source as dataset:
        missing = {"ST", "LANDSEA", "TT", "RH"} - set(dataset.variables)
        if missing:
            raise ExternalCommandError(f"metgrid output missing {sorted(missing)}: {path}")

        def check(values: np.ndarray, label: str, lower: float, upper: float) -> None:
            if not values.size:
                return  # e.g. soil in an all-ocean domain
            if not np.isfinite(values).all():
                raise ExternalCommandError(f"invalid {label}: non-finite values in {path}")
            if np.any((values < lower) | (values > upper)):
                raise ExternalCommandError(
                    f"invalid {label}: range={values.min():.3f}..{values.max():.3f} in {path}"
                )

        check(dataset.LANDSEA.values, "metgrid land mask", 0., 1.)
        land = dataset.LANDSEA > .5
        # Broadcasting retains named dimensions, including the soil axis.
        soil, mask = xr.broadcast(dataset.ST, land)
        check(soil.values[mask.values], "metgrid land soil temperature", 180., 350.)
        for name, label, lower, upper in (
            ("TT", "metgrid near-surface air temperature", 180., 350.),
            # Small supersaturation/interpolation overshoots are not corruption.
            # This is a broad screening bound; do not clip the actual input.
            ("RH", "metgrid near-surface relative humidity", 0., 110.),
        ):
            # Atmospheric fields are required over water as well as land.
            check(dataset[name].isel(num_metgrid_levels=0).values, label, lower, upper)
