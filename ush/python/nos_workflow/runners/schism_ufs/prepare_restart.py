"""Python port of ``_schism_prepare_restart`` from ``ush/nos_run.sh``.

The shell function is a no-op (lines 770-781 of nos_run.sh) — actual
restart-file staging happens inside ``_schism_stage_files`` step 6.
This Python port mirrors that: it's intentionally a no-op + log entry.
Future restructuring may move real restart-prep work here (e.g., dynamic
IC fallback if COMF restart semantics change).

Dispatched from ``stages/nowcast.py`` and ``stages/forecast.py`` when
``NOS_WORKFLOW_PYTHON_PREPARE=1`` (or the global runner flag).
"""
from __future__ import annotations

import logging

from .context import SchismRunContext

logger = logging.getLogger(__name__)


def run_python(ctx: SchismRunContext, phase: str) -> int:
    """No-op restart preparation (matches shell). Returns 0 always.

    Real restart-file staging happens in ``stage_model_files`` (step 6
    of ``_schism_stage_files``). This stub exists for API parity with
    the legacy shell and as a hook for future restart logic.
    """
    logger.info(
        "prepare_restart: no-op (phase=%s, data=%s) — restart staging "
        "happens in stage_model_files",
        phase, ctx.data,
    )
    return 0


__all__ = ["run_python"]
