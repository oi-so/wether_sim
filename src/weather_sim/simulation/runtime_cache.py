"""Reuse Thompson lookup tables only with the identical WRF executable."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

TABLE_NAMES = ("qr_acr_qg_V4.dat", "qr_acr_qsV2.dat", "freezeH2O.dat")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cache_thompson_tables(run_directory: Path, cache_root: Path) -> bool:
    """Publish tables from a completed run; a manifest is written last."""
    log = run_directory / "rsl.error.0000"
    if not log.is_file() or "SUCCESS COMPLETE WRF" not in log.read_text(errors="replace"):
        return False
    if not all((run_directory / name).is_file() and (run_directory / name).stat().st_size for name in TABLE_NAMES):
        return False
    destination = cache_root / _digest(run_directory / "wrf.exe")
    destination.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in TABLE_NAMES:
        source = run_directory / name
        hashes[name] = _digest(source)
        # Tables are independent copies, so cleanup of a case cannot break a cache.
        if not (destination / name).is_file() or _digest(destination / name) != hashes[name]:
            shutil.copyfile(source, destination / name)
    (destination / "manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
    return True


def restore_thompson_tables(run_directory: Path, cache_root: Path) -> bool:
    """Verify all checksums before copying; never let WRF modify shared tables."""
    source = cache_root / _digest(run_directory / "wrf.exe")
    manifest = source / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        hashes = json.loads(manifest.read_text())
    except (ValueError, OSError):
        return False  # Cache miss: WRF can generate the tables normally.
    if not isinstance(hashes, dict) or any(
        not (source / name).is_file() or _digest(source / name) != hashes.get(name)
        for name in TABLE_NAMES
    ):
        return False
    for name in TABLE_NAMES:
        target = run_directory / name
        if target.is_symlink():
            target.unlink()
        shutil.copyfile(source / name, target)
    return True
