"""Execute already-installed WPS/WRF programs with durable logs."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from weather_sim.errors import ExternalCommandError


def run_external(executable: str | Path, working_directory: str | Path, arguments: Sequence[str] = ()) -> Path:
    executable_path = Path(executable).resolve()
    run_directory = Path(working_directory).resolve()
    if not executable_path.is_file():
        raise ExternalCommandError(f"executable does not exist: {executable_path}")
    if not run_directory.is_dir():
        raise ExternalCommandError(f"working directory does not exist: {run_directory}")
    log_path = run_directory / f"{executable_path.name}.log"
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            [str(executable_path), *arguments],
            cwd=run_directory,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        raise ExternalCommandError(
            f"{executable_path.name} exited with status {result.returncode}; see {log_path}"
        )
    return log_path
