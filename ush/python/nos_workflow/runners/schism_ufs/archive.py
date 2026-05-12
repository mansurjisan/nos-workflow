"""Python port of ``_schism_archive_outputs`` from ``ush/nos_run.sh``.

Copies SCHISM time-series outputs (staout_*, mirror.out, flux.out) into
``$COMOUT/{run}.{cycle}.{restart_outputs|forecast_outputs}/`` after MPI
completes. Pure file operations -- no MPI, no module loads, no Fortran.

Dispatched from ``stages/nowcast.py`` and ``stages/forecast.py`` when
``NOS_WORKFLOW_PYTHON_ARCHIVE=1`` (or the global runner flag).

Shell counterpart: lines 1080-1124 of ush/nos_run.sh.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .context import SchismRunContext

logger = logging.getLogger(__name__)


def run_python(ctx: SchismRunContext, phase: str) -> int:
    """Archive SCHISM outputs to $COMOUT. Returns 0 always (matches
    shell: missing outputs is a non-fatal warning)."""
    # Determine output dir name based on phase.
    if phase == "nowcast":
        target_subdir = f"{ctx.run}.{ctx.cycle}.restart_outputs"
    elif phase == "forecast":
        target_subdir = f"{ctx.run}.{ctx.cycle}.forecast_outputs"
    else:
        logger.warning("archive_outputs: unknown phase=%r, skipping", phase)
        return 0

    target = ctx.comout / target_subdir
    target.mkdir(parents=True, exist_ok=True)

    # Find the source outputs dir. After nowcast, the shell renames
    # outputs/ -> outputs_nowcast/ (see MEMORY.md lesson #16). For
    # forecast it's still outputs/. Check both.
    candidates = [ctx.data / "outputs", ctx.data / "outputs_nowcast"]
    source = next((c for c in candidates if c.is_dir()), None)
    if source is None:
        logger.warning(
            "archive_outputs: no outputs dir in %s (checked %s); skipping",
            ctx.data, [str(c) for c in candidates],
        )
        return 0

    # Copy SCHISM time-series outputs. Match the shell's globbing
    # (staout_*, mirror.out, flux.out).
    copied = 0
    for pattern in ("staout_*", "mirror.out", "flux.out"):
        for src in source.glob(pattern):
            dst = target / src.name
            shutil.copy2(src, dst)  # preserves mtime + perms
            copied += 1

    logger.info(
        "archive_outputs: copied %d files from %s to %s",
        copied, source, target,
    )
    return 0


__all__ = ["run_python"]
