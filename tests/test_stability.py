import json

import numpy as np
from test_atmosphere import atmosphere
from weather_sim.analysis.stability import inspect_wrfout
from weather_sim.cli import main


def _output(path):
    ds = atmosphere().drop_vars("Time")
    ds["PB"][:] = np.broadcast_to(np.array([100000., 80000., 50000.])[None, :, None, None], (1, 3, 2, 2))
    for name, value in {"T2": 300., "PSFC": 100000., "U10": 1., "V10": 0., "Q2": .01}.items():
        ds[name] = (("Time", "south_north", "west_east"), np.full((1, 2, 2), value))
    ds.attrs["SIMULATION_START_DATE"] = "2026-09-04_03:00:00"
    ds["XTIME"] = ("Time", [0.])
    ds.to_netcdf(path)
    return ds


def test_stability_detects_nan_negative_water_and_inverted_layer(tmp_path):
    path = tmp_path / "wrfout"
    ds = _output(path)
    good = inspect_wrfout(path)
    assert not good["missing_required"]
    assert all(not s["nonfinite"] and not s["out_of_range"] for s in good["fields"].values())
    ds["Q2"][0, 0, 0] = np.nan
    ds["QCLOUD"][0, 0, 0, 0] = -.01
    ds["PHB"][0, 1, 0, 0] = -100.
    ds.to_netcdf(path)
    bad = inspect_wrfout(path)
    assert bad["fields"]["Q2"]["nonfinite"] == 1
    assert bad["fields"]["QCLOUD"]["out_of_range"] == 1
    assert bad["fields"]["layer_thickness_m"]["out_of_range"] == 1


def test_audit_cli_reports_missing_analysis_times_and_log_errors(tmp_path):
    run = tmp_path / "wrf_run"
    run.mkdir()
    _output(run / "wrfout_d01_test")
    (tmp_path / "case.json").write_text(json.dumps({
        "target_start": "2026-09-04T03:00:00Z", "target_end": "2026-09-04T03:10:00Z",
        "configuration": {"domains": [{"name": "d01"}]}, "output_interval_minutes": 10,
    }))
    (run / "rsl.error.0000").write_text("CFL exceeded\nFATAL error\n")
    assert main(["audit-case", str(tmp_path)]) == 1
    report = json.loads((tmp_path / "analysis/stability.json").read_text())
    assert not report["wrf_success"]
    assert report["log_counts"]["cfl"] == 1
    assert any("missing 1" in issue for issue in report["issues"])
