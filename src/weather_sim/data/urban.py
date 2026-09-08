"""Isolated optional GAIA urban-fraction geography for Noah + SLUCM.

Keep the mandatory geographic tree unchanged so baseline experiments remain
reproducible. The archive supplies impervious fractions, not building geometry.
"""
from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from weather_sim.errors import ExternalCommandError
from weather_sim.simulation.metgrid_cache import digest

GAIA_NAME = 'urbfrac_gaia2020_30s'
GAIA_URL = f'https://www2.mmm.ucar.edu/wrf/src/wps_files/{GAIA_NAME}.tar.gz'


def extract_urban_archive(archive: Path, destination: Path) -> None:
    """Validate member layout and publish a complete dataset atomically."""
    if destination.exists():
        raise ExternalCommandError(f'refusing to replace urban data: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.gaia-', dir=destination.parent))
    try:
        with tarfile.open(archive, 'r:gz') as bundle:
            members = bundle.getmembers()
            files = [m for m in members if m.isfile()]
            allowed_file = re.compile(rf'{GAIA_NAME}/(?:index|\d{{5}}-\d{{5}}\.\d{{5}}-\d{{5}})')
            if any(not (m.isdir() and m.name.rstrip('/') == GAIA_NAME) and
                   not (m.isfile() and allowed_file.fullmatch(m.name)) for m in members):
                raise ExternalCommandError('unexpected paths or links in GAIA archive')
            if len(files) < 2 or sum(m.name == f'{GAIA_NAME}/index' for m in files) != 1:
                raise ExternalCommandError('GAIA archive is missing its index or tiles')
            if len(set(m.name for m in files)) != len(files):
                raise ExternalCommandError('duplicate files in GAIA archive')
            bundle.extractall(temporary, filter='data')
        extracted = temporary / GAIA_NAME
        index = (extracted / 'index').read_text()
        if 'type=continuous' not in index or 'fraction' not in index:
            raise ExternalCommandError('unexpected GAIA index: expected continuous fractional coverage')
        provenance = {'source_url': GAIA_URL, 'reference_year': 2020,
                      'archive_sha256': digest(archive), 'index_sha256': digest(extracted / 'index'),
                      'files': {Path(m.name).name: m.size for m in files}}
        (extracted / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        extracted.rename(destination)
    except (OSError, tarfile.TarError) as exc:
        raise ExternalCommandError(f'could not prepare GAIA urban fractions: {exc}') from exc
    finally:
        shutil.rmtree(temporary)


def urban_geographic_overlay(root: Path, base: Path, download: Callable[[str, Path], Path]) -> Path:
    dataset = root / 'optional' / GAIA_NAME
    if not dataset.exists():
        archive = download(GAIA_URL, root / 'downloads' / f'{GAIA_NAME}.tar.gz')
        extract_urban_archive(archive, dataset)
    try:
        provenance = json.loads((dataset / 'provenance.json').read_text())
        if digest(dataset / 'index') != provenance['index_sha256'] or any(
            (dataset / name).stat().st_size != size for name, size in provenance['files'].items()
        ):
            raise ValueError('incomplete or changed dataset')
    except (OSError, ValueError, KeyError) as exc:
        raise ExternalCommandError(f'urban geography requires repair: {dataset}: {exc}') from exc
    overlay = root / 'WPS_GEOG_urban_gaia2020'
    overlay.mkdir(exist_ok=True)
    sources = {p.name: p for p in base.iterdir()}
    sources[GAIA_NAME] = dataset
    for name, source in sources.items():
        target = overlay / name
        if target.exists() or target.is_symlink():
            if not target.is_symlink() or target.resolve() != source.resolve():
                raise ExternalCommandError(f'conflicting geographic overlay entry: {target}')
        else:
            target.symlink_to(source.resolve(), target_is_directory=source.is_dir())
    return overlay
