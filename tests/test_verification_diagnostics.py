import numpy as np
import pandas as pd
import pytest
from weather_sim.analysis.verification_diagnostics import cumulative_intervals, humidity_components


def test_humidity_decomposition_separates_temperature_from_vapor():
    times=pd.date_range('2026-09-04T03:00Z',periods=2,freq='10min')
    t=pd.DataFrame({'model_timestamp':times,'observation_timestamp':times,'model':[25.,20.],'observed':[20.,20.]})
    saturation=lambda x:611.2*np.exp(17.67*x/(x+243.5))
    rh=pd.DataFrame({'model_timestamp':times,'observation_timestamp':times,'model':[80*saturation(20)/saturation(25),60.],'observed':[80.,80.]})
    result=humidity_components(t,rh)
    assert result.moisture_rh_error_points.iloc[0] == pytest.approx(0,abs=1e-10)
    assert result.dewpoint_error_c.iloc[0] == pytest.approx(0,abs=1e-10)
    assert result.thermal_rh_error_points.iloc[1] == pytest.approx(0)
    assert result.moisture_rh_error_points.iloc[1] == pytest.approx(-20)
    np.testing.assert_allclose(result.thermal_rh_error_points+result.moisture_rh_error_points, rh.model-rh.observed)
    rh.observation_timestamp += pd.Timedelta(minutes=1)
    assert humidity_components(t,rh).empty


def test_rain_accumulation_rejects_resets_missing_boundaries_and_gaps():
    times=pd.date_range('2026-09-04T03:00Z',periods=21,freq='1min')
    s=pd.Series(np.arange(21)*.1,index=times)
    ends=times[[0,10,20]]
    result=cumulative_intervals(s,ends,np.full(3,1/6))
    assert np.isnan(result.iloc[0])
    np.testing.assert_allclose(result.iloc[1:],[1,1])
    reset=s.copy();reset.iloc[15]=0
    assert np.isnan(cumulative_intervals(reset,ends,np.full(3,1/6)).iloc[-1])
    gap=s.drop(times[5])
    assert np.isnan(cumulative_intervals(gap,ends,np.full(3,1/6)).iloc[1])


def test_moisture_candidate_changes_only_one_physics_parameter():
    from dataclasses import asdict
    from weather_sim.config import load_config
    a=asdict(load_config('config/msm_guided.yaml'));b=asdict(load_config('config/msm_guided_moisture.yaml'))
    a.pop('source_path');b.pop('source_path')
    assert b['wrf']['nudging_moisture_s']==5e-5
    b['wrf']['nudging_moisture_s']=a['wrf']['nudging_moisture_s']
    assert a==b
