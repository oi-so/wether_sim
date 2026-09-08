from pathlib import Path

import pytest

from weather_sim.simulation.metgrid_cache import input_signature, publish_metgrid, restore_metgrid, cache_key


def test_metgrid_cache_checks_inputs_outputs_and_preserves_independent_copies(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    inputs = {}
    for name in ("namelist.wps", "geo", "MSM", "table", "binary"):
        path = source / name
        path.write_bytes(name.encode())
        inputs[name] = path
    names = ["met_em.d01.2026-09-04_00:00:00.nc", "met_em.d02.2026-09-04_00:00:00.nc"]
    for name in names:
        (source / name).write_bytes(name.encode())
    signature = input_signature(inputs)
    cache = tmp_path / "cache"
    assert publish_metgrid(cache, signature, source, names)
    assert restore_metgrid(cache, signature, tmp_path / "restored", names)
    for name in names:
        assert (tmp_path / "restored" / name).read_bytes() == (source / name).read_bytes()
        assert not (tmp_path / "restored" / name).is_symlink()
    (tmp_path / "restored" / names[0]).write_bytes(b"changed independently")
    assert restore_metgrid(cache, signature, tmp_path / "second", names)
    for name in inputs:
        original = inputs[name].read_bytes()
        inputs[name].write_bytes(b"changed")
        assert not restore_metgrid(cache, input_signature(inputs), tmp_path / "miss", names)
        inputs[name].write_bytes(original)
    with pytest.raises(ValueError, match="overwrite"):
        restore_metgrid(cache, signature, tmp_path / "second", names)
    (cache / cache_key(signature) / names[1]).write_bytes(b"corrupt")
    assert not restore_metgrid(cache, signature, tmp_path / "corrupt", names)
    assert not (tmp_path / "corrupt").exists()


def test_metgrid_cache_rejects_incomplete_output_list(tmp_path):
    with pytest.raises(ValueError, match="basenames"):
        restore_metgrid(tmp_path, {}, tmp_path / "dest", ["../met_em.d01.bad.nc"])
    assert not restore_metgrid(tmp_path, {}, tmp_path / "dest", ["met_em.d01.test.nc"])
