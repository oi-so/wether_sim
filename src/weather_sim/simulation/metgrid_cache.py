"""Content-addressed reuse of metgrid output for repeated physics experiments.

Inputs are the actual geo_em/intermediate files, WPS namelist, METGRID.TBL and
executable. Output checksums and independent copies prevent shared mutation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def input_signature(inputs: dict[str, Path]) -> dict[str, str]:
    return {name: digest(path) for name, path in sorted(inputs.items())}


def cache_key(signature: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps({"version": 1, "inputs": signature}, sort_keys=True).encode()).hexdigest()


def _valid_names(names: list[str]) -> bool:
    return bool(names) and len(set(names)) == len(names) and all(
        Path(name).name == name and name.startswith("met_em.d") and name.endswith(".nc") for name in names
    )


def restore_metgrid(cache_root: Path, signature: dict[str, str], target: Path, names: list[str]) -> bool:
    if not _valid_names(names):
        raise ValueError("expected metgrid output names must be unique basenames")
    source = cache_root / cache_key(signature)
    try:
        manifest = json.loads((source / "manifest.json").read_text())
        hashes = manifest["outputs"]
        if manifest["inputs"] != signature or set(hashes) != set(names):
            return False
        if any(digest(source / name) != hashes[name] for name in names):
            return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if any((target / name).exists() or (target / name).is_symlink() for name in names):
        raise ValueError("refusing to overwrite existing metgrid outputs")
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copyfile(source / name, target / name)
    return True


def publish_metgrid(cache_root: Path, signature: dict[str, str], source: Path, names: list[str]) -> bool:
    """Publish only after the caller has validated every expected met_em file."""
    if not _valid_names(names):
        raise ValueError("expected metgrid output names must be unique basenames")
    cache_root.mkdir(parents=True, exist_ok=True)
    destination = cache_root / cache_key(signature)
    if destination.exists():
        return False  # Never mutate an entry another run may be reading.
    temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=cache_root))
    try:
        hashes = {}
        for name in names:
            shutil.copyfile(source / name, temporary / name)
            hashes[name] = digest(temporary / name)
        (temporary / "manifest.json").write_text(json.dumps({"inputs": signature, "outputs": hashes}, indent=2) + "\n")
        try:
            temporary.rename(destination)
        except FileExistsError:
            return False
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return True
