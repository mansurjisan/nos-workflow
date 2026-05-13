"""Combine per-rank SCHISM hotstart files via ``combine_hotstart7``."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from ...bash_compat import run_shell_function
from .context import SchismRunContext

logger = logging.getLogger(__name__)


# SCHISM filename convention is ``hotstart_<rank>_<step>.nc``.
_HOTSTART_RANK_STEP_RE = re.compile(r"hotstart_(\d+)_(\d+)\.nc$")


def combine_hotstart_files(ctx: SchismRunContext, phase: str) -> int:
    """Find the last hotstart step and invoke ``combine_hotstart7`` via shell.

    Returns 0 on success or non-fatal skip; non-zero only on shell-wrapper
    failure.
    """
    outputs_dir = ctx.data / "outputs"
    if not outputs_dir.is_dir():
        logger.warning(
            "combine_hotstart: $DATA/outputs missing at %s", outputs_dir,
        )
        return 0

    last_step = _find_last_hotstart_step(outputs_dir)
    if last_step is None:
        logger.warning(
            "combine_hotstart: no hotstart_000000_*.nc files in %s",
            outputs_dir,
        )
        return 0

    logger.info(
        "combine_hotstart: dispatching shell wrapper for step=%d phase=%s",
        last_step, phase,
    )
    return _invoke_shell_wrapper(ctx, str(last_step), phase)


def _find_last_hotstart_step(outputs_dir: Path) -> "int | None":
    """Return the highest step number among ``hotstart_000000_<step>.nc`` files."""
    max_step = -1
    for f in outputs_dir.glob("hotstart_000000_*.nc"):
        m = _HOTSTART_RANK_STEP_RE.match(f.name)
        if m:
            try:
                step = int(m.group(2))
            except ValueError:
                continue
            if step > max_step:
                max_step = step
    return max_step if max_step >= 0 else None


def _invoke_shell_wrapper(
    ctx: SchismRunContext,
    step: str,
    phase: str,
) -> int:
    """Source nos_run.sh and call ``_schism_run_combine_hotstart``.

    Required because combine_hotstart7 needs the hpc-stack module-load
    LD_LIBRARY_PATH which doesn't survive a Python subprocess.
    """
    ushnos_env = os.environ.get("USHnos")
    if not ushnos_env:
        if ctx.ushnos is None:
            logger.error(
                "combine_hotstart: USHnos not set in env or ctx; "
                "cannot invoke shell helper"
            )
            return 1
        ushnos = ctx.ushnos
    else:
        ushnos = Path(ushnos_env)
    nos_run = ushnos / "nos_run.sh"
    if not nos_run.is_file():
        logger.error(
            "combine_hotstart: nos_run.sh not found at %s", nos_run,
        )
        return 1
    return run_shell_function(
        script=nos_run,
        function="_schism_run_combine_hotstart",
        args=(step, phase),
        env=os.environ.copy(),
        cwd=ctx.data,
    )


__all__ = ["combine_hotstart_files"]
