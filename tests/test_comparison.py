import pandas as pd

from weather_sim.analysis.comparison import align_and_evaluate, station_temperature_difference


def test_align_and_evaluate_nearest_time() -> None:
    model = pd.Series([11.0, 13.0], index=pd.to_datetime(["2024-01-01T00:00Z", "2024-01-01T00:10Z"]))
    observed = pd.Series([10.0, 12.0], index=pd.to_datetime(["2024-01-01T00:01Z", "2024-01-01T00:09Z"]))
    aligned, metrics = align_and_evaluate(model, observed, tolerance="2min")
    assert aligned["model"].tolist() == [11.0, 13.0]
    assert metrics.bias == 1
    assert metrics.n == 2


def test_school_minus_amedas() -> None:
    index = pd.to_datetime(["2024-01-01T00:00Z"])
    result = station_temperature_difference(pd.Series([12], index=index), pd.Series([10], index=index))
    assert result.iloc[0] == 2
