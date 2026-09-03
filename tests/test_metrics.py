import math

from weather_sim.analysis.metrics import calculate_metrics


def test_metrics_ignore_unpaired_missing_values() -> None:
    result = calculate_metrics([2, 4, float("nan"), 10], [1, 6, 3, float("nan")])
    assert result.n == 2
    assert result.bias == -0.5
    assert result.mae == 1.5
    assert result.rmse == math.sqrt(2.5)


def test_metrics_return_nan_when_no_pairs() -> None:
    result = calculate_metrics([float("nan")], [1])
    assert result.n == 0
    assert math.isnan(result.bias)
