"""Orchestrate the UFS-Coastal execute stage (validation, mesh, mpi, archive)."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from ...bash_compat import run_shell_function
from . import combine_hotstart, mesh
from .context import SchismRunContext
from .stage_files import _is_ufs

logger = logging.getLogger(__name__)


_REQUIRED_CONFIGS: tuple = ("model_configure", "datm_in", "datm.streams", "ufs.configure")


def run_python(ctx: SchismRunContext, phase: str) -> int:
    """Execute the UFS-Coastal stage end-to-end.

    Returns 0 on success, non-zero only if mpiexec or config validation fails.
    """
    rc = _validate_configs(ctx, phase)
    if rc != 0:
        return rc

    rc = _maybe_regenerate_mesh(ctx, phase)
    if rc != 0:
        logger.warning(
            "execute: ESMF mesh regen returned rc=%d; using existing mesh", rc,
        )

    # mpiexec stays in shell; module load doesn't survive a Python subprocess.
    rc = _run_mpi_shell(ctx, phase)
    if rc != 0:
        logger.error("execute: mpiexec failed (rc=%d)", rc)
        return rc

    # combine_hotstart7 also stays in shell for the hpc-stack module load.
    combine_rc = combine_hotstart.combine_hotstart_files(ctx, phase)
    if combine_rc != 0:
        logger.warning(
            "execute: combine_hotstart returned rc=%d (non-fatal)", combine_rc,
        )

    archive_rc = _archive_restart(ctx, phase)
    if archive_rc != 0:
        logger.warning(
            "execute: rst archive returned rc=%d (non-fatal)", archive_rc,
        )

    return 0


def _validate_configs(ctx: SchismRunContext, phase: str) -> int:
    """Validate that required UFS configs exist and are non-empty in $DATA.

    Standalone SCHISM (pschism) needs none of the UFS configs -> rc=0.
    """
    del phase
    if not _is_ufs():
        return 0
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
    """Regenerate the ESMF mesh from datm_forcing.nc if the forcing file exists.

    Standalone SCHISM has no DATM/ESMF mesh -> rc=0 (nothing to regen).
    """
    del phase
    if not _is_ufs():
        return 0
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
    """Invoke ``_schism_run_mpi`` from a shell context with module load active."""
    ushnos_env = os.environ.get("USHnos")
    if not ushnos_env:
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
    """Copy the combined hotstart to $COMOUT as the rst.{phase}.nc artifact."""
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
