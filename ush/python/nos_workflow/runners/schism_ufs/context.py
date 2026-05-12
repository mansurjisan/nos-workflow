"""SchismRunContext: typed state passed through the SCHISM-UFS runner chain.

This is the Python replacement for the bag of 50+ env vars that
``_schism_setup_paths`` exports in nos_run.sh. Each runner helper takes
a ``SchismRunContext`` instance and reads typed fields instead of
fishing values out of os.environ.

PR 2 ships the minimal stub (just the fields archive_outputs needs).
PR 3 extends to the full schema with from_env_and_phase + to_shell_env
round-trip support.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchismRunContext:
    """Stub: only the fields needed by archive_outputs. Extended in PR 3."""
    comout: Path           # $COMOUT
    data: Path             # $DATA
    phase: str             # "nowcast" or "forecast"
    run: str               # $RUN (e.g., "nos.secofs_ufs")
    cycle: str             # $cycle (e.g., "t00z")


__all__ = ["SchismRunContext"]
