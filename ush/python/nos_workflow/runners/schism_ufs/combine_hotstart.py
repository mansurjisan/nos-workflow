"""Combine per-rank SCHISM hotstart files via ``combine_hotstart7``.

After ``mpiexec`` finishes, SCHISM has written per-rank hotstart files at
``$DATA/outputs/hotstart_000000_<step>.nc`` (one per OCN rank, although
the rank-0 file is the canonical anchor for ``ls -1 hotstart_000000_*.nc``
discovery). The ``combine_hotstart7`` binary merges them into a single
``$DATA/outputs/hotstart_it=<step>.nc`` that the next cycle reads as its
initial condition.

This module finds the right step number, builds the
``combine_hotstart7`` command-line arg, and calls
``_schism_run_combine_hotstart`` (shell) to do the actual invocation.
The shell wrapper is required because ``combine_hotstart7`` is linked
against hpc-stack netcdf/4.7.4 and needs the ``LD_LIBRARY_PATH`` patch
from ``module load`` -- which doesn't survive a Python subprocess.

Public API:

    :func:`combine_hotstart_files` -- ``combine_hotstart_files(ctx,
    phase)`` -> ``int`` rc.

Shell counterpart: ``_schism_run_combine_hotstart`` in
``ush/nos_run.sh`` (extracted from ``_schism_execute_ufs_coastal``
lines 943-1006 in PR 8).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from ...bash_compat import run_shell_function
from .context import SchismRunContext

logger = logging.getLogger(__name__)


# Match shell's `hotstart_000000_*.nc` glob then capture the trailing
# step number. The legacy SCHISM convention is
# ``hotstart_<rank>_<step>.nc`` with rank zero-padded to 6 digits and
# step as a bare int (no padding); the regex captures both for future
# robustness even though we only use the step.
_HOTSTART_RANK_STEP_RE = re.compile(r"hotstart_(\d+)_(\d+)\.nc$")


def combine_hotstart_files(ctx: SchismRunContext, phase: str) -> int:
    """Find the last hotstart step, invoke ``combine_hotstart7`` via the
    shell wrapper.

    Args:
        ctx: runner context (uses ``ctx.data`` to locate the outputs
            directory; ``ctx.run`` / ``ctx.cycle`` / ``ctx.pdy`` are
            passed through to the shell wrapper via the inherited
            environment).
        phase: ``"nowcast"`` or ``"forecast"`` -- forwarded to the shell
            helper for use in the rst archive filename.

    Returns:
        0 on success; non-zero on missing outputs dir, no hotstart
        files, or shell-wrapper failure.

    Behavior matches the shell function:
      - Missing ``outputs/`` -> log WARNING, return 0 (non-fatal).
      - No ``hotstart_000000_*.nc`` files -> log WARNING, return 0.
      - Shell helper returns non-zero -> log WARNING, return that rc.
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
    """Find the highest step number among ``hotstart_000000_<step>.nc``
    files in ``outputs/``.

    Some SCHISM builds produce filenames like ``hotstart_000000_180.nc``
    (rank_step) while the rank field can have varying widths in older
    versions. The regex matches any all-digit rank + step combo and we
    pick the maximum step.

    Returns:
        The largest step number, or None if no matching files exist.
    """
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
    """Source ``nos_run.sh`` and call ``_schism_run_combine_hotstart``.

    Stays as a thin Python wrapper so tests can mock it independently
    of ``run_shell_function``. The shell helper is responsible for the
    hpc-stack LD_LIBRARY_PATH patch and the actual ``combine_hotstart7
    -i <step>`` invocation; we only marshal the args.
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
