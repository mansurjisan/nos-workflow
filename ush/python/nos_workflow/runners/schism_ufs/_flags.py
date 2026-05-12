"""Per-step + global feature flags for the Python migration of nos_run.sh.

Each helper in ``ush/nos_run.sh`` has a per-step env var that selects
whether the stage dispatches to the Python implementation or the legacy
shell function. A global ``NOS_WORKFLOW_PYTHON_RUNNER=1`` flips all
per-step flags at once (useful for blast-radius testing).

Default for every step is OFF (shell). Operators opt in cycle-by-cycle.

The 4 step names mirror the 4-step contract in ``stages/nowcast.py`` and
``stages/forecast.py``::

    stage_model_files
    prepare_restart
    execute_model
    archive_outputs
"""
from __future__ import annotations

import os
from typing import FrozenSet

STEPS: FrozenSet[str] = frozenset({
    "stage_model_files",
    "prepare_restart",
    "execute_model",
    "archive_outputs",
})

# Per-step env var names. 1:1 mapping so operators can reason about
# which flag controls which helper without reading code.
_PER_STEP_VARS = {
    "stage_model_files": "NOS_WORKFLOW_PYTHON_STAGE_FILES",
    "prepare_restart":   "NOS_WORKFLOW_PYTHON_PREPARE",
    "execute_model":     "NOS_WORKFLOW_PYTHON_EXECUTE",
    "archive_outputs":   "NOS_WORKFLOW_PYTHON_ARCHIVE",
}

_GLOBAL_VAR = "NOS_WORKFLOW_PYTHON_RUNNER"


def _is_truthy(val: str | None) -> bool:
    """``1/true/yes/on`` (case-insensitive) means enabled; everything else
    — including unset, empty, and ``0/false/no/off`` — means disabled."""
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def is_python_enabled(step: str) -> bool:
    """Return True iff the Python implementation for ``step`` should run.

    Precedence (highest first):

    1. Global ``NOS_WORKFLOW_PYTHON_RUNNER`` if truthy — Python.
    2. Per-step var (e.g., ``NOS_WORKFLOW_PYTHON_STAGE_FILES``) — Python
       if truthy, shell otherwise.
    3. Default — shell.

    Args:
        step: One of ``STEPS``. Unknown values raise ``ValueError`` so
            dispatcher typos surface in tests, not at 3 AM on WCOSS2.
    """
    if step not in STEPS:
        raise ValueError(
            f"unknown step {step!r}; expected one of {sorted(STEPS)}"
        )
    if _is_truthy(os.environ.get(_GLOBAL_VAR)):
        return True
    return _is_truthy(os.environ.get(_PER_STEP_VARS[step]))


__all__ = ["STEPS", "is_python_enabled"]
