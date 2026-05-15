"""Copy SCHISM time-series outputs to $COMOUT after MPI completes."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .context import SchismRunContext

logger = logging.getLogger(__name__)


def run_python(ctx: SchismRunContext, phase: str) -> int:
    """Archive SCHISM outputs to $COMOUT. Returns 0 always."""
    if phase == "nowcast":
        target_subdir = f"{ctx.run}.{ctx.cycle}.restart_outputs"
    elif phase == "forecast":
        target_subdir = f"{ctx.run}.{ctx.cycle}.forecast_outputs"
    else:
        logger.warning("archive_outputs: unknown phase=%r, skipping", phase)
        return 0

    target = ctx.comout / target_subdir
    target.mkdir(parents=True, exist_ok=True)

    # After nowcast the shell renames outputs/ -> outputs_nowcast/; check both.
    candidates = [ctx.data / "outputs", ctx.data / "outputs_nowcast"]
    source = next((c for c in candidates if c.is_dir()), None)
    if source is None:
        logger.warning(
            "archive_outputs: no outputs dir in %s (checked %s); skipping",
            ctx.data, [str(c) for c in candidates],
        )
        return 0

    copied = 0
    for pattern in ("staout_*", "mirror.out", "flux.out"):
        for src in source.glob(pattern):
            dst = target / src.name
            shutil.copy2(src, dst)
            copied += 1

    logger.info(
        "archive_outputs: copied %d files from %s to %s",
        copied, source, target,
    )
    return 0


__all__ = ["run_python"]
