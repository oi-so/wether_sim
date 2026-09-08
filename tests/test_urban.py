from dataclasses import replace
import io
import json
from pathlib import Path
import tarfile

import numpy as np
import pytest
import xarray as xr

from weather_sim.config import load_config
from weather_sim.data.urban import GAIA_NAME, extract_urban_archive, urban_geographic_overlay
from weather_sim.errors import ConfigurationError, ExternalCommandError
from weather_sim.simulation.input_validation import validate_urban_fraction_file
from weather_sim.simulation.namelists import render_namelist_input


def write_archive(path, bad=False):
    files = {'index': b'type=continuous\nunits="fraction"\n', '00001-01200.00001-01200': b'1234'}
    if bad:
        files['../outside'] = b'bad'
    with tarfile.open(path, 'w:gz') as bundle:
        for name, data in files.items():
            member = tarfile.TarInfo(f'{GAIA_NAME}/{name}')
            member.size = len(data)
            bundle.addfile(member, io.BytesIO(data))


def test_urban_overlay_is_opt_in_preserves_base_and_checks_partial_data(tmp_path):
    archive = tmp_path / 'archive.tar.gz'
    write_archive(archive)
    base = tmp_path / 'WPS_GEOG'
    base.mkdir()
    (base / 'terrain').mkdir()
    overlay = urban_geographic_overlay(tmp_path, base, lambda *a: archive)
    assert not (base / GAIA_NAME).exists()
    assert (overlay / 'terrain').resolve() == (base / 'terrain').resolve()
    assert (overlay / GAIA_NAME / 'index').is_file()
    assert json.loads((overlay / GAIA_NAME / 'provenance.json').read_text())['reference_year'] == 2020
    def no_download(*args):
        pytest.fail('complete data should not be downloaded again')
    assert urban_geographic_overlay(tmp_path, base, no_download) == overlay
    (overlay / GAIA_NAME / '00001-01200.00001-01200').unlink()
    with pytest.raises(ExternalCommandError, match='repair'):
        urban_geographic_overlay(tmp_path, base, no_download)


def test_urban_archive_rejects_unexpected_member_without_publication(tmp_path):
    archive = tmp_path / 'bad.tar.gz'
    write_archive(archive, bad=True)
    with pytest.raises(ExternalCommandError, match='unexpected'):
        extract_urban_archive(archive, tmp_path / 'dataset')
    assert not (tmp_path / 'dataset').exists()


def test_urban_candidate_and_source_must_be_consistent():
    config = load_config('config/msm_guided_urban.yaml')
    assert 'sf_urban_physics = 1, 1, 1,' in render_namelist_input(config)
    with pytest.raises(ConfigurationError, match='requires explicit'):
        replace(config.wrf, urban_fraction_source='none')
    with pytest.raises(ConfigurationError, match='requires explicit'):
        replace(config.wrf, urban_physics=0)
    assert load_config('config/msm_guided.yaml').wrf.urban_fraction_source == 'none'


def test_urban_validation_detects_missing_range_and_centre_fallback(tmp_path):
    path = tmp_path / 'met_em.nc'
    dims = ('Time', 'south_north', 'west_east')
    fields = {'FRC_URB2D': [[[.4, 0.]]], 'LU_INDEX': [[[13., 13.]]],
              'XLAT_M': [[[35., 36.]]], 'XLONG_M': [[[139., 140.]]]}
    data = xr.Dataset({name: (dims, values) for name, values in fields.items()}, attrs={'FLAG_FRC_URB2D': 1})
    data.to_netcdf(path)
    record = validate_urban_fraction_file(path, (35., 139.))
    assert record['zero_fraction_urban_cells'] == 1
    with pytest.raises(ExternalCommandError, match='analysis centre'):
        validate_urban_fraction_file(path, (36., 140.))
    data['FRC_URB2D'][0, 0, 0] = np.nan
    data.to_netcdf(path)
    with pytest.raises(ExternalCommandError, match='finite'):
        validate_urban_fraction_file(path, (35., 139.))
    data.drop_vars('FRC_URB2D').to_netcdf(path)
    with pytest.raises(ExternalCommandError, match='missing'):
        validate_urban_fraction_file(path, (35., 139.))
