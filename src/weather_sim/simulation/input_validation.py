"""Validate finite surface inputs without mistaking masked ocean soil for land."""
from pathlib import Path

import numpy as np
import xarray as xr

from weather_sim.errors import ExternalCommandError


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
