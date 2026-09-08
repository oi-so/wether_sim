from datetime import datetime, timezone

import pytest
from weather_sim.errors import ExternalCommandError

from weather_sim.data.forecast import _cycle_assignments


def _utc(day: int, hour: int) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


def test_msm_accepts_21_utc_initialization_cycle() -> None:
    valid_times = tuple([_utc(3, 21), *(_utc(4, hour) for hour in (0, 3, 6, 9, 12))])

    assignments = _cycle_assignments(
        valid_times,
        cycle_interval_hours=3,
        max_forecast_hours=15,
        now=_utc(8, 6),
    )

    assert set(assignments.values()) == {_utc(3, 21)}


def test_gfs_uses_previous_supported_six_hour_cycle() -> None:
    valid_times = tuple([_utc(3, 21), *(_utc(4, hour) for hour in (0, 3, 6, 9, 12))])

    assignments = _cycle_assignments(
        valid_times,
        cycle_interval_hours=6,
        max_forecast_hours=120,
        now=_utc(8, 6),
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


def test_reported_1552_case_uses_published_forecast_for_1800_boundary():
    # 08:00-16:00 JST with 6 h spin-up rounds to 00:00-18:00 JST.
    valid = (_utc(7, 15), _utc(7, 18), _utc(7, 21), *(_utc(8, h) for h in (0, 3, 6, 9)))
    now = _utc(8, 6).replace(minute=52)
    probed = []
    def available(cycle, valid):
        probed.append(cycle)
        return cycle <= _utc(8, 3)  # 15 JST cycle not fully published yet.
    selected = _cycle_assignments(valid, cycle_interval_hours=3, max_forecast_hours=15, now=now, available=available)
    assert selected[_utc(8, 9)] == _utc(8, 3)  # 12 JST +6 h forecast.
    assert all(cycle <= now for cycle in probed)
    assert all(0 <= (t-c).total_seconds() <= 15*3600 for t,c in selected.items())


def test_entire_future_window_can_use_an_existing_cycle():
    selected = _cycle_assignments((_utc(8, 9), _utc(8, 12), _utc(8, 15)),
                                 cycle_interval_hours=3, max_forecast_hours=15,
                                 now=_utc(8, 6), available=lambda c,t: c <= _utc(8, 3))
    assert set(selected.values()) == {_utc(8, 3)}


def test_far_future_fails_before_any_network_probe():
    def no_probe(*args):
        pytest.fail('impossible horizon must be rejected before probes')
    with pytest.raises(ExternalCommandError, match='exceeds.*forecast range'):
        _cycle_assignments((_utc(9, 0),), cycle_interval_hours=3, max_forecast_hours=15,
                           now=_utc(8, 6), available=no_probe)


def test_unpublished_range_and_connection_errors_are_different():
    with pytest.raises(ExternalCommandError, match='no published forecast'):
        _cycle_assignments((_utc(8, 9),), cycle_interval_hours=3, max_forecast_hours=15,
                           now=_utc(8, 6), available=lambda c,t: False)
    def broken(*args):
        raise ExternalCommandError('connection failed')
    with pytest.raises(ExternalCommandError, match='connection failed'):
        _cycle_assignments((_utc(8, 9),), cycle_interval_hours=3, max_forecast_hours=15,
                           now=_utc(8, 6), available=broken)


def test_msm_requires_both_files_and_memoizes_head(tmp_path, monkeypatch):
    from weather_sim.data import forecast
    urls = []
    def probe(url):
        urls.append(url)
        return not ('20260908060000' in url and 'Lsurf' in url)
    monkeypatch.setattr(forecast, '_remote_exists', probe)
    selected = forecast.select_forecast_cycles((_utc(8,6),_utc(8,9)), tmp_path, 'msm', now=_utc(8,6))
    assert set(selected.values()) == {_utc(8,3)}
    assert len(urls) == len(set(urls)) == 4


def test_gfs_checks_forecast_lead_index_and_data(tmp_path, monkeypatch):
    from weather_sim.data import forecast
    urls = []
    def probe(url):
        urls.append(url)
        return 't06z.sfluxgrbf003' not in url
    monkeypatch.setattr(forecast, '_remote_exists', probe)
    selected = forecast.select_forecast_cycles((_utc(8,9),_utc(8,12)),tmp_path,'gfs',now=_utc(8,6))
    assert set(selected.values()) == {_utc(8,0)}
    assert any('t00z.sfluxgrbf009.grib2.idx' in u for u in urls)
    assert any(u.endswith('t00z.sfluxgrbf012.grib2') for u in urls)


def test_local_cache_can_be_used_without_remote_access(tmp_path, monkeypatch):
    from weather_sim.data import forecast
    folder=tmp_path/'2026-09-08'
    folder.mkdir()
    for name in forecast._msm_names(_utc(8,3)):
        (folder/name).write_bytes(b'cached data')
    monkeypatch.setattr(forecast, '_remote_exists', lambda url: pytest.fail('unexpected probe'))
    assert forecast.select_forecast_cycles((_utc(8,3),_utc(8,6)),tmp_path,'msm',now=_utc(8,6))[_utc(8,6)] == _utc(8,3)


def test_head_404_is_absent_but_503_is_error(monkeypatch):
    import urllib.error
    from weather_sim.data import forecast
    def fail404(*args,**kw):
        raise urllib.error.HTTPError('https://example.test',404,'absent',{},None)
    monkeypatch.setattr(forecast,'open_trusted_url',fail404)
    assert not forecast._remote_exists('https://example.test')
    def fail503(*args,**kw):
        raise urllib.error.HTTPError('https://example.test',503,'unavailable',{},None)
    monkeypatch.setattr(forecast,'open_trusted_url',fail503)
    with pytest.raises(ExternalCommandError,match='HTTP 503'):
        forecast._remote_exists('https://example.test')


def test_download_404_is_not_retried_with_curl(tmp_path,monkeypatch):
    import urllib.error
    from weather_sim.data import forecast
    def absent(*args,**kw):
        raise urllib.error.HTTPError('https://example.test',404,'absent',{},None)
    monkeypatch.setattr(forecast,'open_trusted_url',absent)
    monkeypatch.setattr(forecast.subprocess,'run',lambda *a,**kw: pytest.fail('must not retry 404'))
    with pytest.raises(ExternalCommandError,match='HTTP 404'):
        forecast._download('https://example.test',tmp_path/'data')


def test_preflight_failure_precedes_geography_and_data_downloads(monkeypatch,tmp_path):
    from weather_sim.config import load_config
    from weather_sim.data import forecast
    def select(times,root,model,**kw):
        if model=='gfs':
            raise ExternalCommandError('no GFS forecast')
        return {t:t for t in times}
    monkeypatch.setattr(forecast,'select_forecast_cycles',select)
    monkeypatch.setattr(forecast,'ensure_geographic_data',lambda *a: pytest.fail('must preflight first'))
    monkeypatch.setattr(forecast,'download_msm',lambda *a,**kw: pytest.fail('must preflight first'))
    with pytest.raises(ExternalCommandError,match='no GFS'):
        forecast.prepare_forecast_data(load_config('config/msm_guided.yaml'),tmp_path)


def test_head_system_trust_fallback_and_empty_response(monkeypatch):
    import urllib.error
    import subprocess
    from weather_sim.data import forecast
    def tls_failure(*a,**kw):
        raise urllib.error.URLError('certificate verification failed')
    monkeypatch.setattr(forecast,'open_trusted_url',tls_failure)
    def head(command,**kwargs):
        assert '--head' in command
        assert '--retry' not in command
        return subprocess.CompletedProcess(command,0,stdout='404',stderr='')
    monkeypatch.setattr(forecast.subprocess,'run',head)
    assert not forecast._remote_exists('https://example.test')
    from contextlib import nullcontext
    from types import SimpleNamespace
    response=SimpleNamespace(status=200,headers={'Content-Length':'0'})
    monkeypatch.setattr(forecast,'open_trusted_url',lambda *a,**kw:nullcontext(response))
    assert not forecast._remote_exists('https://example.test')
    response.headers['Content-Length']='123'
    assert forecast._remote_exists('https://example.test')


def test_successful_plan_is_used_and_recorded_before_downloads(monkeypatch,tmp_path):
    from weather_sim.config import load_config
    from weather_sim.data import forecast
    selected={}
    def select(times,root,model,**kwargs):
        selected[model]={t:times[0] for t in times}
        return selected[model]
    monkeypatch.setattr(forecast,'select_forecast_cycles',select)
    monkeypatch.setattr(forecast,'ensure_geographic_data',lambda root: root)
    def download(times,root,*,assignments):
        assert assignments is selected[root.name]
        return ()
    monkeypatch.setattr(forecast,'download_msm',download)
    monkeypatch.setattr(forecast,'download_gfs',download)
    result=forecast.prepare_forecast_data(load_config('config/msm_guided.yaml'),tmp_path)
    assert set(result.source_selection['models'])=={'msm','gfs'}
    assert result.source_selection['models']['msm'][0]['forecast_hours']==0
