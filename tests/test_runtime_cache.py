from pathlib import Path

from weather_sim.simulation.runtime_cache import TABLE_NAMES, cache_thompson_tables, restore_thompson_tables


def test_tables_require_completed_run_matching_binary_and_checksums(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.mkdir()
    (original / "wrf.exe").write_bytes(b"binary-version-one")
    for name in TABLE_NAMES:
        (original / name).write_bytes(name.encode())
    cache = tmp_path / "cache"
    assert not cache_thompson_tables(original, cache)
    (original / "rsl.error.0000").write_text("SUCCESS COMPLETE WRF")
    assert cache_thompson_tables(original, cache)
    new = tmp_path / "new"
    new.mkdir()
    (new / "wrf.exe").write_bytes(b"binary-version-two")
    assert not restore_thompson_tables(new, cache)
    (new / "wrf.exe").write_bytes(b"binary-version-one")
    assert restore_thompson_tables(new, cache)
    for name in TABLE_NAMES:
        assert (new / name).read_bytes() == name.encode()
        assert not (new / name).is_symlink()
    next(cache.glob("*/freezeH2O.dat")).write_bytes(b"corruption")
    assert not restore_thompson_tables(new, cache)
