import json
from pathlib import Path

import pandas as pd

from weather_sim.case_operations import (
    cleanup_candidates,
    cleanup_case,
    prepare_case_observations,
)


def _case(directory: Path) -> Path:
    directory.mkdir()
    (directory / "case.json").write_text(
        json.dumps(
            {
                "target_start": "2026-09-01T15:00:00+09:00",
                "target_end": "2026-09-01T15:10:00+09:00",
                "timezone": "Asia/Tokyo",
                "center": {"latitude": 35.69247912845154, "longitude": 139.41296806119965},
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_prepare_case_observations_combines_school_and_amedas(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    school_directory = tmp_path / "school"
    school_directory.mkdir()
    columns = [f"column_{index}" for index in range(14)]
    pd.DataFrame(
        [["2026/09/01 15:00:00", 30.0, 60, 180, 190, 170, 2.0, 3.0, 1.0, 1005, 0, 0, 0, 0]],
        columns=columns,
    ).to_csv(school_directory / "WSN.csv", index=False, encoding="cp932")
    amedas_directory = case / "observations"
    amedas_directory.mkdir()
    pd.DataFrame(
        {
            "timestamp": ["2026-09-01T06:00:00Z"],
            "station_id": ["amedas_fuchu"],
            "latitude": [35.6833],
            "longitude": [139.4833],
            "elevation_m": [59],
            "variable": ["temperature"],
            "value": [29.0],
            "unit": ["degC"],
            "quality": ["valid"],
            "source": ["jma_amedas"],
        }
    ).to_csv(amedas_directory / "amedas_fuchu.csv", index=False)

    output = prepare_case_observations(case, tmp_path, school_directory=school_directory)

    result = pd.read_csv(output)
    assert set(result["station_id"]) == {"school", "amedas_fuchu"}
    assert list(result.columns) == [
        "timestamp", "station_id", "latitude", "longitude", "elevation_m",
        "variable", "value", "unit", "quality", "source",
    ]


def test_cleanup_is_dry_run_until_execute(tmp_path: Path) -> None:
    case = _case(tmp_path / "case")
    (case / "ungrib_msm").mkdir()
    (case / "ungrib_msm/data").write_bytes(b"123")
    run = case / "wrf_run"
    run.mkdir()
    d03 = run / "wrfout_d03_2026-09-01_06:00:00"
    d03.write_bytes(b"output")
    (run / "wrfinput_d01").write_bytes(b"input")
    analysis = case / "analysis"
    analysis.mkdir()
    (analysis / "temperature_animation.mp4").write_bytes(b"movie")

    items = cleanup_candidates(
        case,
        discard_resimulation=True,
        discard_reevaluation=True,
    )
    cleanup_case(items, execute=False)
    assert d03.exists()
    assert (case / "ungrib_msm").exists()

    cleanup_case(items, execute=True)
    assert not d03.exists()
    assert not (case / "ungrib_msm").exists()
    assert (analysis / "temperature_animation.mp4").exists()
