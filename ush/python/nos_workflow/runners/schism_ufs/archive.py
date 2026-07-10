"""Copy SCHISM time-series outputs to $COMOUT after MPI completes."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import List

from ...post.registry import resolve_archive_fields
from .context import SchismRunContext

logger = logging.getLogger(__name__)

# Global (scribe-shaped) field files staged when post.archive_fields is on.
_FIELD_PATTERNS = (
    "out2d_[0-9]*.nc",
    "temperature_[0-9]*.nc",
    "salinity_[0-9]*.nc",
    "horizontalVelX_[0-9]*.nc",
    "horizontalVelY_[0-9]*.nc",
    "zCoordinates_[0-9]*.nc",
    "verticalVelocity_[0-9]*.nc",
    "diffusivity_[0-9]*.nc",
)


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

    if resolve_archive_fields(os.environ):
        field_files = _global_field_files(source)
        for src in field_files:
            shutil.copy2(src, target / src.name)
        copied += len(field_files)
        logger.info(
            "archive_outputs: staged %d global field file(s) to %s",
            len(field_files), target,
        )

    logger.info(
        "archive_outputs: copied %d files from %s to %s",
        copied, source, target,
    )
    return 0


def _global_field_files(source: Path) -> List[Path]:
    """Global field stacks in ``source``: scribe files plus combined
    ``schout_<stack>.nc`` -- never the OLDIO per-rank
    ``schout_<rank>_<stack>.nc`` (those stay in $DATA)."""
    files: List[Path] = []
    for pattern in _FIELD_PATTERNS:
        files.extend(source.glob(pattern))
    for f in source.glob("schout_*.nc"):
        if f.name.count("_") == 1:  # schout_<stack>.nc, not per-rank
            files.append(f)
    return sorted(set(files))


__all__ = ["run_python"]
