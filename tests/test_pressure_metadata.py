import numpy as np
from pathlib import Path
import pandas as pd
import pytest
import xarray as xr

from weather_sim.analysis.observation_verification import evaluate_real_observations
from weather_sim.analysis.verification_diagnostics import pressure_at_height
from weather_sim.errors import ObservationDataError
from weather_sim.observations.station_metadata import read_station_metadata


def test_height_comparison_keeps_original_pressure_and_uses_confirmed_metadata(tmp_path):
    times = pd.date_range("2026-09-04T03:00Z", periods=2, freq="10min")
    ds = xr.Dataset(coords={"Time": times})
    for name, value in {"T2": 298., "Q2": .014, "HGT": 81., "surface_pressure_hpa": 1000.,
                        "XLAT": 35., "XLONG": 139.}.items():
        ds[name] = (("Time", "south_north", "west_east"), np.full((2, 1, 1), value))
    observed = pressure_at_height(1000., 298., .014, 17.5).item()
    rows = pd.DataFrame(dict(timestamp=times, station_id="school", latitude=35., longitude=139.,
                             elevation_m=np.nan, variable="pressure", value=observed, unit="hPa", is_valid=True))
    metadata = {"school": dict(latitude=35., longitude=139., ground_elevation_m=83.5,
                                pressure_sensor_height_m=15., pressure_type="station")}
    def evaluate(meta):
        return evaluate_real_observations(ds, rows, tmp_path, start=times[0], end=times[-1],
                                         tolerance=pd.Timedelta(0), station_metadata=meta).set_index("variable")
    result = evaluate(metadata)
    assert result.loc["pressure", "bias"] > 1.9
    assert result.loc["pressure_sensor_height", "rmse"] == pytest.approx(0., abs=1e-12)
    assert result.loc["pressure_sensor_height", "pressure_sensor_elevation_m"] == 98.5
    assert (ds.surface_pressure_hpa == 1000.).all()
    assert "pressure_sensor_height" not in evaluate(None).index
    metadata["school"]["pressure_type"] = "sea_level"
    assert "pressure_sensor_height" not in evaluate(metadata).index
    metadata["school"]["latitude"] = 36.
    with pytest.raises(ObservationDataError, match="coordinates"):
        evaluate(metadata)


def test_station_metadata_requires_finite_height_and_pressure_type(tmp_path):
    info = read_station_metadata(Path("config/station_metadata.yaml"))
    assert info["school"]["ground_elevation_m"] + info["school"]["pressure_sensor_height_m"] == 98.5
    path = tmp_path / "bad.yaml"
    path.write_text("school: {latitude: 35, longitude: 139, ground_elevation_m: 83.5, pressure_sensor_height_m: .nan, pressure_type: station}")
    with pytest.raises(ObservationDataError, match="finite"):
        read_station_metadata(path)
