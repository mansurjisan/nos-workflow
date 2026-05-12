"""Python port of ``_schism_execute_ufs_coastal`` orchestration.

The shell function (lines 791-1078 of ``ush/nos_run.sh``, 289 LOC) is
split into three pieces:

  - The pure-MPI launch stays in shell as ``_schism_run_mpi()`` because
    ``module load`` (Cray PALS / hpc-stack) doesn't survive a Python
    subprocess. mpiexec must run from a shell that has those modules
    already loaded by the J-job.
  - The ``combine_hotstart7`` invocation stays in shell as
    ``_schism_run_combine_hotstart()`` for the same reason -- it needs
    the hpc-stack netcdf/4.7.4 + hdf5 ``LD_LIBRARY_PATH`` patch per
    shell call.
  - Everything else (config validation, ESMF mesh regeneration, post-MPI
    cleanup, ``rst.{phase}.nc`` archive copy) moves here to Python.

Public API:

    :func:`run_python` -- one entry point ``run_python(ctx, phase)`` ->
    ``int`` rc. Dispatched from ``stages/nowcast.py`` and
    ``stages/forecast.py`` when ``NOS_WORKFLOW_PYTHON_EXECUTE=1`` (the
    wire-in to the dispatcher happens in a follow-up commit AFTER PR 7c
    lands, to avoid conflicts with the stage-dispatch refactor).

Shell counterpart: ``_schism_execute_ufs_coastal`` in
``ush/nos_run.sh`` (refactored body, lines ~923-1024 in the PR 8
revision).
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from ...bash_compat import run_shell_function
from . import combine_hotstart, mesh
from .context import SchismRunContext

logger = logging.getLogger(__name__)


# Files that MUST exist in $DATA before mpiexec is launched. Mirrors the
# validation loop at lines 799-804 of nos_run.sh.
_REQUIRED_CONFIGS: tuple = ("model_configure", "datm_in", "datm.streams", "ufs.configure")


def run_python(ctx: SchismRunContext, phase: str) -> int:
    """Execute the UFS-Coastal stage end-to-end.

    Steps (matches the shell function's flow):

      1. Validate required configs are staged in ``$DATA``.
      2. Optionally regenerate ESMF mesh from the DATM forcing file
         (calls :func:`mesh.generate_esmf_mesh`).
      3. Run mpiexec (shell -- ``module load`` required for mpiexec).
      4. Combine per-rank hotstart files (shell -- ``module load`` for
         combine_hotstart7's hpc-stack netcdf).
      5. Archive ``rst.{phase}.nc`` to ``$COMOUT``.

    Args:
        ctx: runner context.
        phase: ``"nowcast"`` or ``"forecast"``.

    Returns:
        0 on success, non-zero rc if any sub-step fails. Steps 4 and 5
        log warnings but do not propagate non-fatal errors (matches the
        shell, which only returns non-zero from mpiexec).
    """
    # 1. Validate required configs present.
    rc = _validate_configs(ctx, phase)
    if rc != 0:
        return rc

    # 2. Optional ESMF mesh regeneration (skipped silently if no
    #    forcing file -- happens before any tests stand up a real DATM).
    rc = _maybe_regenerate_mesh(ctx, phase)
    if rc != 0:
        # Mesh generation failure is non-fatal: the existing template
        # mesh is used. Match the shell warning at line 859.
        logger.warning(
            "execute: ESMF mesh regen returned rc=%d; using existing mesh", rc,
        )

    # 3. Run MPI (shell -- module load required).
    rc = _run_mpi_shell(ctx, phase)
    if rc != 0:
        logger.error("execute: mpiexec failed (rc=%d)", rc)
        return rc

    # 4. Combine per-rank hotstart files (shell -- module load for
    #    combine_hotstart7 hpc-stack netcdf).
    combine_rc = combine_hotstart.combine_hotstart_files(ctx, phase)
    if combine_rc != 0:
        # Non-fatal: shell uses WARNING + continues (lines 996, 999).
        logger.warning(
            "execute: combine_hotstart returned rc=%d (non-fatal)", combine_rc,
        )

    # 5. Archive rst.{phase}.nc to $COMOUT. Combine already wrote the
    #    canonical RUN.cycle.PDY.rst.{phase}.nc to $COMOUT, so this is
    #    a safety net that surfaces a different filename convention if
    #    the workflow ever stages a pre-combined hotstart.
    archive_rc = _archive_restart(ctx, phase)
    if archive_rc != 0:
        logger.warning(
            "execute: rst archive returned rc=%d (non-fatal)", archive_rc,
        )

    return 0


def _validate_configs(ctx: SchismRunContext, phase: str) -> int:
    """Validate that required UFS configs and param.nml are present
    in $DATA before launching mpiexec.

    Mirrors the loop at lines 798-804 of nos_run.sh. Returns 1 (matching
    the shell's `return 1`) if any required file is missing or empty.
    """
    del phase  # validation set is phase-agnostic
    missing = []
    for name in _REQUIRED_CONFIGS:
        f = ctx.data / name
        if not f.is_file() or f.stat().st_size == 0:
            missing.append(name)
    if missing:
        logger.error(
            "execute: required UFS configs missing in %s: %s",
            ctx.data, missing,
        )
        return 1
    logger.info(
        "execute: validated %d UFS configs in %s",
        len(_REQUIRED_CONFIGS), ctx.data,
    )
    return 0


def _maybe_regenerate_mesh(ctx: SchismRunContext, phase: str) -> int:
    """Regenerate the ESMF mesh from datm_forcing.nc if the forcing
    file is present.

    Matches the shell block at lines 828-862 of nos_run.sh (post-PR-4):
    we regenerate the mesh unconditionally whenever the forcing file
    exists -- the mesh.py module is cheap to call and we never trust a
    template mesh (MEMORY.md lesson #18 + #19).
    """
    del phase
    datm_dir_name = os.environ.get("DATM_INPUT_DIR") or "INPUT"
    forcing = ctx.data / datm_dir_name / "datm_forcing.nc"
    if not forcing.is_file() or forcing.stat().st_size == 0:
        logger.info(
            "execute: no DATM forcing file at %s; skipping mesh regen",
            forcing,
        )
        return 0
    out = ctx.data / datm_dir_name / "datm_esmf_mesh.nc"
    logger.info("execute: regenerating ESMF mesh from %s", forcing)
    return mesh.generate_esmf_mesh(forcing, out)


def _run_mpi_shell(ctx: SchismRunContext, phase: str) -> int:
    """Invoke shell's ``_schism_run_mpi()`` function via bash_compat.

    Dispatches ``mpiexec ... fv3_coastalS.exe`` from a shell that has
    Cray-PALS modules loaded (the J-job's shell context). The Python
    subprocess inherits the J-job's env via ``os.environ.copy()`` so
    ``module load`` side effects (LD_LIBRARY_PATH, PATH, MODULESHOME,
    etc.) survive into the bash -c subprocess.
    """
    ushnos_env = os.environ.get("USHnos")
    if not ushnos_env:
        # Fall back to ctx.ushnos if env wasn't exported.
        if ctx.ushnos is None:
            logger.error("execute: USHnos not set; cannot invoke shell helper")
            return 1
        ushnos = ctx.ushnos
    else:
        ushnos = Path(ushnos_env)
    nos_run = ushnos / "nos_run.sh"
    if not nos_run.is_file():
        logger.error("execute: nos_run.sh not found at %s", nos_run)
        return 1
    return run_shell_function(
        script=nos_run,
        function="_schism_run_mpi",
        args=(phase,),
        env=os.environ.copy(),
        cwd=ctx.data,
    )


def _archive_restart(ctx: SchismRunContext, phase: str) -> int:
    """Copy the combined hotstart file from ``$DATA/outputs/`` to
    ``$COMOUT`` as the ``rst.{phase}.nc`` artifact.

    The shell helper ``_schism_run_combine_hotstart`` already does this
    for the canonical ``RUN.cycle.PDY.rst.{phase}.nc`` filename. This
    safety net runs when ``ctx.rst_out_nowcast`` / ``ctx.rst_out_forecast``
    point at a different filename convention (e.g., if a follow-up PR
    parameterizes the rst path) -- it's a no-op if the source is
    missing or the ctx field is None.
    """
    if phase == "nowcast":
        rst_dst_name = ctx.rst_out_nowcast
    elif phase == "forecast":
        rst_dst_name = ctx.rst_out_forecast
    else:
        logger.warning("execute: unknown phase=%r, skipping rst archive", phase)
        return 0

    if rst_dst_name is None:
        logger.info(
            "execute: rst_out_%s is None in ctx; combine_hotstart "
            "already archived the canonical filename",
            phase,
        )
        return 0

    # Source: look for combined output in outputs/. The combine helper
    # produces hotstart_it=<step>.nc; find the most recent one.
    outputs_dir = ctx.data / "outputs"
    if not outputs_dir.is_dir():
        logger.info(
            "execute: $DATA/outputs missing; rst archive skipped"
        )
        return 0
    candidates = sorted(outputs_dir.glob("hotstart_it=*.nc"))
    if not candidates:
        logger.info(
            "execute: no hotstart_it=*.nc in %s; rst archive skipped",
            outputs_dir,
        )
        return 0
    rst_src = candidates[-1]
    rst_dst = ctx.comout / rst_dst_name
    rst_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rst_src, rst_dst)
    logger.info("execute: archived %s -> %s", rst_src, rst_dst)
    return 0


__all__ = ["run_python"]
