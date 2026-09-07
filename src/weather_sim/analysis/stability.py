"""Read-only checks of saved WRF fields, without clipping or resimulation.

Screening bounds are deliberately broad; passing them is not proof of physical
accuracy. History output cannot resolve oscillations faster than its cadence.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from weather_sim.analysis.wrf import _decode_times
from weather_sim.errors import WRFOutputError

# Broad screening bounds in native units, not tunable model parameters.
FIELD_BOUNDS = {
    "T2": (150., 350.), "TSK": (150., 380.), "PSFC": (10000., 120000.),
    "U10": (-150., 150.), "V10": (-150., 150.),
    "U": (-150., 150.), "V": (-150., 150.), "W": (-100., 100.),
    "Q2": (-1e-10, .1), "QVAPOR": (-1e-10, .1),
    "QCLOUD": (-1e-10, .1), "QICE": (-1e-10, .1),
    "QRAIN": (-1e-10, .1), "QSNOW": (-1e-10, .1), "QGRAUP": (-1e-10, .1),
    "CLDFRA": (-1e-6, 1.000001), "RAINC": (0., None), "RAINNC": (0., None),
    "pressure_pa": (0., 120000.), "temperature_k": (150., 350.),
    "layer_thickness_m": (0., None), "pressure_drop_pa": (0., None),
}
REQUIRED = {"T2", "PSFC", "U10", "V10", "Q2", "P", "PB", "T", "PH", "PHB", "QVAPOR", "W"}


def inspect_wrfout(path: str | Path) -> dict:
    """Scan every saved cell/time with memory bounded by a single frame."""
    path = Path(path)
    with xr.open_dataset(path, decode_times=False) as dataset:
        times = _decode_times(dataset)
        if not len(times) or times.has_duplicates or not times.is_monotonic_increasing:
            raise WRFOutputError(f"invalid WRF time ordering: {path}")
        stats: dict[str, dict] = {}
        series = []
        rain_decreases = 0
        previous_rain = None
        for i, timestamp in enumerate(times):
            frame = dataset.isel(Time=i)
            # Load only inspected fields, one frame at a time. Preserve precision.
            names = (set(FIELD_BOUNDS) | {"P", "PB", "T", "PH", "PHB"}) & set(frame.variables)
            arrays = {name: np.asarray(frame[name].values) for name in names}
            if {"P", "PB", "T"}.issubset(arrays):
                pressure = arrays["P"] + arrays["PB"]
                arrays["pressure_pa"] = pressure
                arrays["pressure_drop_pa"] = -np.diff(pressure, axis=0)
                with np.errstate(invalid="ignore"):
                    arrays["temperature_k"] = (arrays["T"] + 300.) * (pressure / 100000.) ** (287. / 1004.5)
            if {"PH", "PHB"}.issubset(arrays):
                arrays["layer_thickness_m"] = np.diff((arrays["PH"] + arrays["PHB"]) / 9.81, axis=0)
            row = {"timestamp_utc": timestamp.isoformat()}
            for name, (low, high) in FIELD_BOUNDS.items():
                if name not in arrays:
                    continue
                values = arrays[name]
                finite = np.isfinite(values)
                valid = values[finite]
                entry = stats.setdefault(name, dict(min=None, max=None, nonfinite=0, out_of_range=0, count=0))
                entry["count"] += values.size
                entry["nonfinite"] += int((~finite).sum())
                outside = valid <= low if name in {"layer_thickness_m", "pressure_pa", "pressure_drop_pa"} else valid < low
                if high is not None:
                    outside |= valid > high
                entry["out_of_range"] += int(outside.sum())
                if outside.any() or (~finite).any():
                    entry.setdefault("first_flagged_utc", timestamp.isoformat())
                if valid.size:
                    minimum, maximum = float(valid.min()), float(valid.max())
                    entry["min"] = minimum if entry["min"] is None else min(entry["min"], minimum)
                    entry["max"] = maximum if entry["max"] is None else max(entry["max"], maximum)
                    if name in {"T2", "PSFC", "W"}:
                        row[name] = float(valid.mean(dtype=np.float64))
            if {"RAINC", "RAINNC"}.issubset(arrays):
                rain = arrays["RAINC"] + arrays["RAINNC"]
                if previous_rain is not None:
                    rain_decreases += int(np.count_nonzero(rain < previous_rain - 1e-6))
                previous_rain = rain
            series.append(row)
        deltas = {}
        time_series = pd.DataFrame(series)
        for name in ("T2", "PSFC", "W"):
            if name in time_series:
                delta = time_series[name].diff().dropna()
                deltas[name] = {
                    "max_abs_saved_step_change": float(delta.abs().max()) if len(delta) else None,
                    "sign_reversals": int((delta * delta.shift() < 0).sum()),
                }
        seconds = (times[1:] - times[:-1]).total_seconds()
        return {
            "path": str(path.resolve()), "frames": len(times),
            "start_utc": times[0].isoformat(), "end_utc": times[-1].isoformat(),
            "timestamps_utc": [t.isoformat() for t in times],
            "interval_seconds": sorted(set(float(v) for v in seconds)),
            "missing_required": sorted(REQUIRED - set(dataset.variables)),
            "fields": stats, "rain_decrease_cells": rain_decreases,
            "domain_mean_step_changes": deltas, "domain_mean_series": series,
        }


def audit_case(case_directory: str | Path, output_path: str | Path | None = None) -> dict:
    """Inspect all retained domains and logs; do not alter model outputs."""
    case = Path(case_directory).resolve()
    manifest = json.loads((case / "case.json").read_text())
    paths = sorted((case / "wrf_run").glob("wrfout_d0*"))
    if not paths:
        raise WRFOutputError(f"no saved wrfout files in {case}")
    files = [inspect_wrfout(path) for path in paths]
    logs = list((case / "wrf_run").glob("rsl.error.*"))
    patterns = {"cfl": r"\bcfl\b", "fatal": r"FATAL|SIGSEGV|SIGFPE|segmentation fault", "nan": r"\bNaN\b"}
    log_counts = dict.fromkeys(patterns, 0)
    completed = False
    for path in logs:
        content = path.read_text(errors="replace")
        completed |= "SUCCESS COMPLETE WRF" in content
        for key, pattern in patterns.items():
            log_counts[key] += len(re.findall(pattern, content, re.IGNORECASE))
    issues = []
    if not completed:
        issues.append("WRF success marker not found; output may be incomplete")
    if any(log_counts.values()):
        issues.append("CFL/fatal/NaN log messages need review")
    for record in files:
        if record["missing_required"]:
            issues.append(f'{Path(record["path"]).name}: required fields missing')
        if any(s["nonfinite"] or s["out_of_range"] for s in record["fields"].values()):
            issues.append(f'{Path(record["path"]).name}: invalid values or screening bounds exceeded')
        if record["rain_decrease_cells"]:
            issues.append(f'{Path(record["path"]).name}: cumulative rain decreases (check resets/buckets)')
    domain_count = len(manifest.get("configuration", {}).get("domains", []))
    if domain_count:
        for domain in range(1, domain_count + 1):
            if not any(Path(r["path"]).name.startswith(f"wrfout_d{domain:02d}_") for r in files):
                issues.append(f"d{domain:02d} output missing; this domain cannot be checked")
        # History times are anchored to integration start, not target_start.
        # A target such as 12:03 legitimately starts with the 12:10 frame.
        anchor = manifest.get("simulation_start_utc", files[0]["start_utc"])
        expected = pd.date_range(pd.Timestamp(anchor).tz_convert("UTC"), pd.Timestamp(manifest["target_end"]).tz_convert("UTC"),
                                 freq=pd.Timedelta(minutes=manifest.get("output_interval_minutes", 10)))
        expected = expected[expected >= pd.Timestamp(manifest["target_start"])]
        inner_times = [t for r in files if Path(r["path"]).name.startswith(f"wrfout_d{domain_count:02d}_")
                       for t in r["timestamps_utc"]]
        actual = pd.DatetimeIndex(pd.to_datetime(inner_times, utc=True))
        missing = expected.tz_convert("UTC").difference(actual)
        if len(missing):
            issues.append(f"innermost domain missing {len(missing)} expected analysis timestamps")
        if actual.has_duplicates:
            issues.append("innermost domain has overlapping timestamps across files")
    report = {"case": str(case), "wrf_success": completed, "log_counts": log_counts,
              "issues": issues, "files": files, "screening_bounds": FIELD_BOUNDS,
              "limitation": "Saved-frame screening only; does not prove sub-output-step stability or forecast accuracy."}
    target = Path(output_path) if output_path else case / "analysis/stability.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return report
