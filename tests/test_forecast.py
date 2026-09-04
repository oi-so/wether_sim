from datetime import datetime, timezone

from weather_sim.data.forecast import _cycle_assignments


def _utc(day: int, hour: int) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


def test_msm_accepts_21_utc_initialization_cycle() -> None:
    valid_times = tuple([_utc(3, 21), *(_utc(4, hour) for hour in (0, 3, 6, 9, 12))])

    assignments = _cycle_assignments(
        valid_times,
        cycle_interval_hours=3,
        max_forecast_hours=15,
    )

    assert set(assignments.values()) == {_utc(3, 21)}


def test_gfs_uses_previous_supported_six_hour_cycle() -> None:
    valid_times = tuple([_utc(3, 21), *(_utc(4, hour) for hour in (0, 3, 6, 9, 12))])

    assignments = _cycle_assignments(
        valid_times,
        cycle_interval_hours=6,
        max_forecast_hours=120,
    )

    assert set(assignments.values()) == {_utc(3, 18)}
    assert [int((valid_time - assignments[valid_time]).total_seconds() / 3600) for valid_time in valid_times] == [
        3,
        6,
        9,
        12,
        15,
        18,
    ]
