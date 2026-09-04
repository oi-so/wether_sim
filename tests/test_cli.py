import json

import numpy as np
import pandas as pd
import xarray as xr

from weather_sim.cli import main


def test_case_entrypoints_have_help() -> None:
    for command in ("animate-case", "prepare-observations", "evaluate-case", "cleanup-case"):
        try:
            main([command, "--help"])
        except SystemExit as exc:
            assert exc.code == 0


def test_analyze_command_writes_verification_products(tmp_path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """center: {latitude: 35.0, longitude: 139.0}
time:
  target_start: '2024-01-01T00:00:00Z'
  target_end: '2024-01-01T00:10:00Z'
  timezone: Asia/Tokyo
  spinup_hours: 0
domains:
  d01: {dx_m: 9000, e_we: 100, e_sn: 100}
analysis: {radius_km: 20, output_interval_minutes: 10}
observations: {use_amedas: true, use_school: true}
visualization: {animation: true, animation_format: gif, fps: 2}
wrf: {input_interval_seconds: 10800, time_step_seconds: 54, vertical_levels: 45, map_projection: lambert}
""",
        encoding="utf-8",
    )
    wrfout = tmp_path / "wrfout_d01_test"
    dims = ("Time", "south_north", "west_east")
    times = np.array([list("2024-01-01_00:00:00"), list("2024-01-01_00:10:00")], dtype="S1")
    temperature = np.array([[[293.15, 294.15], [293.15, 294.15]]] * 2)
    xr.Dataset(
        {
            "Times": (("Time", "DateStrLen"), times),
            "XLAT": (dims, np.array([[[35, 35], [36, 36]]] * 2)),
            "XLONG": (dims, np.array([[[139, 140], [139, 140]]] * 2)),
            "T2": (dims, temperature),
            "U10": (dims, np.full((2, 2, 2), 3.0)),
            "V10": (dims, np.full((2, 2, 2), 4.0)),
        }
    ).to_netcdf(wrfout)
    observations = tmp_path / "observations.csv"
    pd.DataFrame(
        {
            "timestamp": ["2024-01-01T00:00Z", "2024-01-01T00:10Z"] * 2,
            "station_id": ["school", "school", "amedas", "amedas"],
            "latitude": [35, 35, 35, 35], "longitude": [139, 139, 140, 140],
            "elevation_m": [10, 10, 20, 20], "variable": ["temperature"] * 4,
            "value": [19, 19, 20, 20], "unit": ["degC"] * 4, "quality": ["valid"] * 4,
        }
    ).to_csv(observations, index=False)
    output = tmp_path / "output"

    status = main(
        ["analyze", str(config), "--wrfout", str(wrfout), "--observations", str(observations),
         "--station-id", "school", "--reference-station-id", "amedas", "--output-dir", str(output)]
    )

    assert status == 0
    assert json.loads((output / "metrics.json").read_text())["n"] == 2
    assert json.loads((output / "temperature_difference_metrics.json").read_text())["rmse"] == 0
    assert (output / "temperature_map.png").stat().st_size > 0
    assert (output / "temperature_timeseries.png").stat().st_size > 0
