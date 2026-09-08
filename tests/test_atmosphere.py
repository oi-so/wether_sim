import numpy as np
import pytest
import xarray as xr

from weather_sim.analysis.atmosphere import GRAVITY, cloud_overlap, cloud_columns, volume_frame, unstagger
from weather_sim.errors import WRFOutputError
from weather_sim.visualization.volume import VolumeOptions, create_volume_animation


def atmosphere():
    shape = (1, 3, 2, 2)
    dims = ('Time', 'bottom_top', 'south_north', 'west_east')
    frame = xr.Dataset(coords={'Time': [np.datetime64('2026-09-04T03:00')]})
    for name, value in {'P': 0., 'PB': 100000., 'T': 0., 'QVAPOR': 0., 'QCLOUD': .001, 'QICE': .002, 'CLDFRA': .5}.items():
        frame[name] = (dims, np.full(shape, value))
    zdims = ('Time', 'bottom_top_stag', 'south_north', 'west_east')
    heights = np.broadcast_to(np.array([0., 1000., 4000., 10000.])[None, :, None, None], (1,4,2,2))
    frame['PHB'] = (zdims, heights * GRAVITY)
    frame['PH'] = (zdims, np.zeros((1,4,2,2)))
    frame['W'] = (zdims, np.broadcast_to(np.arange(4)[None,:,None,None], (1,4,2,2)))
    frame['U'] = (('Time','bottom_top','south_north','west_east_stag'), np.ones((1,3,2,3)))
    frame['V'] = (('Time','bottom_top','south_north_stag','west_east'), np.zeros((1,3,3,2)))
    for name, value in {'HGT':0., 'COSALPHA':0., 'SINALPHA':1.}.items():
        frame[name] = (('Time','south_north','west_east'), np.full((1,2,2), value))
    frame['XLAT'] = (('Time','south_north','west_east'), [[[35.,35.],[35.01,35.01]]])
    frame['XLONG'] = (('Time','south_north','west_east'), [[[139.,139.01],[139.,139.01]]])
    return frame


def test_overlap_distinguishes_contiguous_clouds_and_clear_gaps():
    assert cloud_overlap(np.array([.5,.5,0,.5])[:,None,None]).item() == pytest.approx(75)
    assert cloud_overlap(np.array([.5,.7,.5])[:,None,None]).item() == pytest.approx(70)
    assert cloud_overlap(np.zeros((3,1,1))).item() == 0
    assert np.isnan(cloud_overlap(np.ones((3,1,1)), np.zeros((3,1,1), dtype=bool))).all()
    assert np.isnan(cloud_overlap(np.array([np.nan,.5])[:,None,None])).all()


def test_cloud_band_trimming_preserves_clear_gaps_missing_and_empty_columns():
    # Outside NaNs must be ignored; an interior clear layer separates clouds.
    fraction = np.array([[np.nan, .5, .5], [.5, .3, .5], [0., .4, .5],
                         [.5, np.nan, .5], [np.nan, .5, .5]])[:, None, :]
    mask = np.zeros_like(fraction, dtype=bool)
    mask[1:4, 0, :2] = True
    result = cloud_overlap(fraction, mask)
    assert result[0, 0] == 75.
    assert np.isnan(result[0, 1])  # Included missing layer.
    assert np.isnan(result[0, 2])  # No levels in band, not clear sky.


def test_temperature_wind_rotation_height_and_dry_mass_integral():
    dataset = atmosphere()
    frame = volume_frame(dataset.isel(Time=0))
    np.testing.assert_allclose(frame['temperature'],26.85)
    np.testing.assert_allclose(frame['height'][:,0,0],[.5,2.5,7])
    np.testing.assert_allclose(frame['east'],0)
    np.testing.assert_allclose(frame['north'],1)
    np.testing.assert_allclose(frame['W'][:,0,0],[.5,1.5,2.5])
    np.testing.assert_allclose(frame['QCLOUD'],1)
    cols=cloud_columns(dataset)
    for key in ['cloud_total','cloud_low','cloud_mid','cloud_high']:
        np.testing.assert_allclose(cols[key],50)
    expected=.001 * (100000/(287*300)) * 10000
    np.testing.assert_allclose(cols.cloud_water_path,expected,rtol=1e-6)
    np.testing.assert_allclose(cols.cloud_ice_path,2*expected,rtol=1e-6)
    assert unstagger(np.array([0,4,8]),0).tolist()==[2,6]


def test_volume_is_self_contained_and_validates_missing_variables(tmp_path):
    dataset=atmosphere()
    output=create_volume_animation(dataset,tmp_path/'viewer.html',center=(35.,139.), options=VolumeOptions(1,1))
    text=output.read_text()
    assert '__WRF_DATA__' not in text
    assert 'onpointermove' in text and 'onpointercancel' in text
    assert 'QCLOUD' in text and 'QICE' in text and 'CLDFRA' in text
    assert 'https://' not in text
    assert output.with_suffix('.json').is_file()
    with pytest.raises(WRFOutputError, match='CLDFRA'):
        create_volume_animation(dataset.drop_vars('CLDFRA'),tmp_path/'bad.html',center=(35.,139.))
    with pytest.raises(ValueError, match='positive'):
        VolumeOptions(horizontal_stride=0)
