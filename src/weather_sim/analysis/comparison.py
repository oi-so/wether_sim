"""Align model and observation series and compute verification results."""

from __future__ import annotations

import pandas as pd

from weather_sim.analysis.metrics import VerificationMetrics, calculate_metrics


def align_and_evaluate(
    model: pd.Series,
    observations: pd.Series,
    *,
    tolerance: str | pd.Timedelta = "5min",
) -> tuple[pd.DataFrame, VerificationMetrics]:
    """Nearest-time join in UTC followed by paired-value verification."""
    model_frame = model.rename("model").sort_index().rename_axis("timestamp").reset_index()
    observation_frame = observations.rename("observed").sort_index().rename_axis("timestamp").reset_index()
    for frame in (model_frame, observation_frame):
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    aligned = pd.merge_asof(
        observation_frame,
        model_frame,
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta(tolerance),
    )
    aligned["error"] = aligned["model"] - aligned["observed"]
    metrics = calculate_metrics(aligned["model"], aligned["observed"])
    return aligned, metrics


def station_temperature_difference(school: pd.Series, amedas: pd.Series) -> pd.Series:
    """Return school minus AMeDAS temperature at exactly shared timestamps."""
    paired = pd.concat([school.rename("school"), amedas.rename("amedas")], axis=1, join="inner")
    return (paired["school"] - paired["amedas"]).rename("school_minus_amedas_c")
