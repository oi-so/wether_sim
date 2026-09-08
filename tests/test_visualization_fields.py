import base64
import json

import numpy as np
import pytest
import xarray as xr
from PIL import Image

from weather_sim.visualization.fields import surface_fields, SURFACE_FIELDS, radar_style
from weather_sim.visualization.basemap import terrain_texture
from weather_sim.visualization.volume import create_volume_animation, VolumeOptions
from test_atmosphere import atmosphere


def test_rate_uses_real_intervals_without_modifying_amount_or_missing():
    ds = xr.Dataset({'precipitation_interval_mm': (('Time','y','x'), np.array([1., 6., np.nan, 2.])[:,None,None]),
                     'precipitation_interval_hours': ('Time', [1/6, 1., 1., 0.])})
    original = ds.copy(deep=True)
    result = surface_fields(ds, include_clouds=False)
    np.testing.assert_allclose(result.precipitation_rate_mmh.values[:,0,0], [6.,6.,np.nan,np.nan])
    xr.testing.assert_identical(ds, original)
    cmap, norm = radar_style()
    assert norm(0.5) != norm(1.)
    assert norm(79.) != norm(80.)
    np.testing.assert_allclose(cmap(norm(80.)), cmap(norm(8000.)))


def test_map_uv_is_mercator_and_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr('weather_sim.visualization.basemap._tile_image', lambda *args: Image.new('RGB',(256,256),'red'))
    lat = np.array([[30.,30.],[40.,40.]])
    lon = np.array([[130.,140.],[130.,140.]])
    data = terrain_texture(lat, lon, tmp_path)
    uv = np.frombuffer(base64.b64decode(data['uv']),dtype='<f4').reshape(2,2,2)
    assert np.all((uv>=0)&(uv<=1))
    assert uv[0,0,0]<uv[0,1,0]  # East increases u.
    assert uv[1,0,1]<uv[0,0,1]  # North is the top of the image.
    assert max(data['pixels'])<=2048
    assert data['image'].startswith('data:image/jpeg;base64,')


def test_html_surface_export_preserves_native_grid_and_all_fields(tmp_path):
    ds = atmosphere()
    for _, variable, *_ in SURFACE_FIELDS:
        if variable not in ds and not variable.startswith('cloud_') and variable!='precipitation_rate_mmh':
            ds[variable] = (('Time','south_north','west_east'), np.ones((1,2,2)))
    ds['precipitation_interval_hours'] = ('Time', [1/6])
    original = ds.copy(deep=True)
    path = create_volume_animation(ds, tmp_path/'test.html', center=(35.,139.), radius_km=None,
                                   options=VolumeOptions(1,1))
    text = path.read_text()
    payload = json.loads(text.split('<script id="data" type="application/json">')[1].split('</script>')[0])
    assert set(payload['surface']['variables'])=={spec[0] for spec in SURFACE_FIELDS}
    assert payload['terrain']['shape']==[2,2]
    assert payload['full_domain'] is True
    rain = np.frombuffer(base64.b64decode(payload['surface']['fields']['precipitation']),dtype='<f4')
    np.testing.assert_allclose(rain,6.)
    xr.testing.assert_identical(ds,original)


def test_viewer_controls_in_node_without_browser(tmp_path):
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for viewer logic checks')
    ds = atmosphere()
    second = ds.assign_coords(Time=[np.datetime64('2026-09-04T03:10')])
    ds = xr.concat([ds, second], dim='Time')
    for _, variable, *_ in SURFACE_FIELDS:
        if variable not in ds and not variable.startswith('cloud_') and variable!='precipitation_rate_mmh':
            ds[variable] = (('Time','south_north','west_east'), np.ones((2,2,2)))
    for variable in ['eastward_wind_10m_ms','northward_wind_10m_ms']:
        ds[variable] = (('Time','south_north','west_east'), np.ones((2,2,2)))
    ds['precipitation_interval_hours'] = ('Time', [1/6,1/6])
    path = create_volume_animation(ds, tmp_path/'viewer.html', center=(35.,139.), radius_km=None,
                                   options=VolumeOptions(1,1))
    subprocess.run([node,str(Path(__file__).with_name('viewer_controls.cjs')),str(path)],check=True,capture_output=True,text=True)


def test_case_exports_each_domain_and_keeps_parent_end_step(monkeypatch,tmp_path):
    import pandas as pd
    import weather_sim.case_operations as ops
    root=tmp_path/'case';run=root/'wrf_run';run.mkdir(parents=True)
    (root/'case.json').write_text(json.dumps(dict(target_start='2026-09-04T12:00:00+09:00',target_end='2026-09-04T20:00:00+09:00',center=dict(latitude=35.,longitude=139.))))
    for domain in ('d01','d02','d03'):(run/f'wrfout_{domain}_test').touch()
    def opened(path):
        domain=path.name.split('_')[1]
        times=pd.date_range('2026-09-04T03:00:00Z',periods=9,freq='h')
        if domain!='d03':times=times[:-1].append(pd.DatetimeIndex([times[-1]+pd.Timedelta(seconds=36)]))
        return xr.Dataset(coords={'Time':times},attrs={'domain':domain})
    captured={}
    def export(ds,path,**kwargs):
        captured[ds.attrs['domain']]=(ds, path,kwargs)
        return path
    monkeypatch.setattr(ops,'open_wrfout',opened)
    monkeypatch.setattr(ops,'create_volume_animation',export)
    result=ops.animate_case(root,tmp_path,dimension='3d',basemap=False)
    assert set(result)=={'d01_atmosphere_3d','d02_atmosphere_3d','d03_atmosphere_3d'}
    for domain,(ds,path,kwargs) in captured.items():
        assert ds.sizes['Time']==9
        assert kwargs['radius_km'] is None
        assert kwargs['basemap_cache'] is None
        assert path.parent==root/'analysis'/(domain if domain!='d03' else '')
        assert set(kwargs['domain_links'])=={'d01','d02','d03'}
