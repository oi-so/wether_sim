"""Verification metrics with explicit missing-value handling."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class VerificationMetrics:
    bias: float
    mae: float
    rmse: float
    n: int

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def calculate_metrics(predicted: object, observed: object) -> VerificationMetrics:
    """Calculate Bias, MAE, RMSE and N using only finite paired values."""
    prediction = np.asarray(predicted, dtype=float)
    observation = np.asarray(observed, dtype=float)
    if prediction.shape != observation.shape:
        raise ValueError("predicted and observed must have the same shape")
    valid = np.isfinite(prediction) & np.isfinite(observation)
    n = int(valid.sum())
    if n == 0:
        return VerificationMetrics(float("nan"), float("nan"), float("nan"), 0)
    error = prediction[valid] - observation[valid]
    return VerificationMetrics(
        bias=float(np.mean(error)),
        mae=float(np.mean(np.abs(error))),
        rmse=float(np.sqrt(np.mean(np.square(error)))),
        n=n,
    )
