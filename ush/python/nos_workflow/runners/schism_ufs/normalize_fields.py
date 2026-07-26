"""Normalize OLDIO per-rank field output into global stacks.

The coupled UFS build writes OLDIO per-rank ``schout_<rank>_<stack>.nc``;
the standalone scribed build writes global ``out2d_*`` / per-variable
files directly. This step makes the two paths converge before archiving:
per-rank files are combined into global ``schout_<stack>.nc`` via
``combine_output11_MPI`` (serial fallback) through the nos_run.sh shell
wrapper -- the exe needs the hpc-stack module env, same as the hotstart
combine. Scribed runs pass through untouched. Gated by
``post.archive_fields`` / ``$NOS_ARCHIVE_FIELDS`` so the default
workflow is unchanged.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from ...bash_compat import run_shell_function
from ...post.registry import resolve_archive_fields
from .context import SchismRunContext

logger = logging.getLogger(__name__)

# SCHISM writes per-rank files with a fixed 6-digit rank (i6.6), and the
# shell combine wrapper globs schout_000000_* -- keep the two consistent.
_PER_RANK_SCHOUT_RE = re.compile(r"schout_\d{6}_\d+\.nc$")


def normalize_field_outputs(ctx: SchismRunContext, phase: str) -> int:
    """Combine per-rank schout files when field archiving is enabled.

    Returns 0 on success or no-op; non-zero only when a needed combine
    failed (callers treat it as non-fatal -- fields are products, never
    a reason to fail the model run).
    """
    if not resolve_archive_fields(os.environ):
        logger.info("normalize_fields: archive_fields disabled; skipping")
        return 0

    outputs_dir = ctx.data / "outputs"
    if not outputs_dir.is_dir():
        logger.warning(
            "normalize_fields: $DATA/outputs missing at %s", outputs_dir,
        )
        return 0

    if any(outputs_dir.glob("out2d_[0-9]*.nc")):
        logger.info(
            "normalize_fields: scribed outputs present; no combine needed",
        )
        return 0

    if not _has_per_rank_schout(outputs_dir):
        logger.info(
            "normalize_fields: no per-rank schout files in %s; nothing to do",
            outputs_dir,
        )
        return 0

    logger.info(
        "normalize_fields: dispatching fields combine for phase=%s", phase,
    )
    return _invoke_shell_wrapper(ctx, phase)


def _has_per_rank_schout(outputs_dir: Path) -> bool:
    """True when OLDIO per-rank ``schout_<rank>_<stack>.nc`` files exist."""
    for f in outputs_dir.glob("schout_*_*.nc"):
        if _PER_RANK_SCHOUT_RE.match(f.name):
            return True
    return False


def _invoke_shell_wrapper(ctx: SchismRunContext, phase: str) -> int:
    """Source nos_run.sh and call ``_schism_run_combine_fields``."""
    ushnos_env = os.environ.get("USHnos")
    if not ushnos_env:
        if ctx.ushnos is None:
            logger.error(
                "normalize_fields: USHnos not set in env or ctx; "
                "cannot invoke shell helper"
            )
            return 1
        ushnos = ctx.ushnos
    else:
        ushnos = Path(ushnos_env)
    nos_run = ushnos / "nos_run.sh"
    if not nos_run.is_file():
        logger.error(
            "normalize_fields: nos_run.sh not found at %s", nos_run,
        )
        return 1
    return run_shell_function(
        script=nos_run,
        function="_schism_run_combine_fields",
        args=(phase,),
        env=os.environ.copy(),
        cwd=ctx.data,
    )


__all__ = ["normalize_field_outputs"]
