"""Orchestrate the UFS-Coastal execute stage (validation, mesh, mpi, archive)."""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from ...bash_compat import run_shell_function
from . import combine_hotstart, mesh, normalize_fields
from .context import SchismRunContext
from .stage_files import _is_ufs, _is_wave_enabled

logger = logging.getLogger(__name__)


_REQUIRED_CONFIGS: tuple = ("model_configure", "datm_in", "datm.streams", "ufs.configure")
# Wave systems only (see _is_wave_enabled) -- appended onto _REQUIRED_CONFIGS.
# The WAV ESMF mesh name is dynamic (ufs_coastal.wav_mesh), so it's added
# from $WAV_MESH rather than hardcoded here.
_REQUIRED_WAVE_CONFIGS: tuple = ("ww3_shel.nml", "mod_def.ww3")
_HOTSTART_IT_RE = re.compile(r"hotstart_it=(\d+)\.nc$")
_PETLIST_BOUNDS_RE = re.compile(
    r"^(MED|ATM|OCN|WAV)_petlist_bounds:\s*(\d+)\s+(\d+)\s*$", re.MULTILINE,
)
_RUNSEQ_INTERVAL_RE = re.compile(r"(?m)^@(\d+)\s*$")


def _hotstart_step(path: Path) -> int:
    """Parse the step number out of a hotstart_it=<N>.nc name; -1 if it doesn't match."""
    match = _HOTSTART_IT_RE.search(path.name)
    return int(match.group(1)) if match else -1


def run_python(ctx: SchismRunContext, phase: str) -> int:
    """Execute the UFS-Coastal stage end-to-end.

    Returns 0 on success, non-zero only if mpiexec or config validation fails.
    """
    rc = _validate_configs(ctx, phase)
    if rc != 0:
        return rc

    rc = _validate_wave_ufs_configure(ctx, phase)
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

    # OLDIO field normalization (no-op unless post.archive_fields is on).
    fields_rc = normalize_fields.normalize_field_outputs(ctx, phase)
    if fields_rc != 0:
        logger.warning(
            "execute: fields normalize returned rc=%d (non-fatal)", fields_rc,
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
    required = _REQUIRED_CONFIGS
    if _is_wave_enabled():
        required = required + _REQUIRED_WAVE_CONFIGS
        wav_mesh = os.environ.get("WAV_MESH")
        if wav_mesh:
            required = required + (wav_mesh,)
    missing = []
    for name in required:
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
        len(required), ctx.data,
    )
    return 0


def _validate_wave_ufs_configure(ctx: SchismRunContext, phase: str) -> int:
    """Sanity-check the staged 4-component ufs.configure before MPI launch.

    Wave systems only -- rc=0 immediately otherwise.

    The 4-component (DATM+SCHISM+WW3) PET-bounds/runSeq-interval patch
    requires a nos-utils pin that actually implements it
    (``ufs_wav_tasks``/``ufs_coupling_interval``, nos-utils
    feature/ufs-config-4component). A STALE pin silently falls back to
    the old 3-component patcher: it widens OCN across the WAV PETs it
    doesn't know about (an OCN/WAV overlap) and reverts the runSeq
    interval to ``@<model_dt>``, dropping the coarser wave coupling
    window -- exit code 0, at most one INFO line, and the model then runs
    3600 ranks on a corrupted PET layout. This check catches that class
    of bug here, before the MPI launch, rather than at a WW3/CDEPS abort
    deep into the coupled init.

    Checks, against the file nos-utils actually staged to $DATA (NOT the
    fix-file template -- a stale pin can still leave 4 lines present, just
    wrongly bounded):
      - all four ``*_petlist_bounds`` lines are present;
      - ATM/OCN/WAV are contiguous, non-overlapping, and together cover
        ``0..total_tasks-1`` (MED is NOT part of this partition by
        design -- it spans the FULL PET range as the mediator, see
        ``fix/secofs_ufs_ww3/ufs.configure`` -- so MED's span is checked
        separately below rather than folded into the non-overlap check);
      - MED's span is exactly ``0..total_tasks-1``;
      - the runSeq ``@<interval>`` line matches ``$COUPLING_INTERVAL``
        (``ufs_coastal.coupling_interval`` from the YAML).
    """
    del phase
    if not _is_wave_enabled():
        return 0

    target = ctx.data / "ufs.configure"
    if not target.is_file() or target.stat().st_size == 0:
        logger.error(
            "execute: %s missing or empty; cannot validate the wave PET "
            "layout", target,
        )
        return 1
    content = target.read_text()

    bounds = {
        comp: (int(lo), int(hi))
        for comp, lo, hi in _PETLIST_BOUNDS_RE.findall(content)
    }
    missing = [c for c in ("MED", "ATM", "OCN", "WAV") if c not in bounds]
    if missing:
        logger.error(
            "execute: staged ufs.configure is missing *_petlist_bounds "
            "for %s (found: %s). A wave system requires all four "
            "components. Likely cause: the ush/python/nos-utils pin "
            "predates ufs_wav_tasks support and silently applied the "
            "3-component patcher -- check the submodule pin.",
            missing, sorted(bounds),
        )
        return 1

    total_env = os.environ.get("TOTAL_TASKS") or os.environ.get("NPROCS")
    try:
        total_tasks = int(total_env)
    except (TypeError, ValueError):
        logger.error(
            "execute: TOTAL_TASKS/NPROCS not set or non-numeric (%r); "
            "cannot validate the wave PET layout", total_env,
        )
        return 1

    expected_lo = 0
    for comp in ("ATM", "OCN", "WAV"):
        lo, hi = bounds[comp]
        if lo != expected_lo or hi < lo:
            logger.error(
                "execute: wave PET layout is not contiguous/non-overlapping "
                "-- %s_petlist_bounds is %d %d, expected to start at %d. "
                "Likely cause: a stale ush/python/nos-utils pin (the "
                "3-component PET patcher widened OCN across WAV's "
                "untouched PETs). Full bounds: %s",
                comp, lo, hi, expected_lo, bounds,
            )
            return 1
        expected_lo = hi + 1

    if expected_lo != total_tasks:
        logger.error(
            "execute: wave PET layout covers 0..%d but total_tasks=%d "
            "(ATM+OCN+WAV must cover 0..total_tasks-1 exactly). Likely "
            "cause: a stale ush/python/nos-utils pin, or a "
            "datm/schism/wav/total_tasks mismatch in the YAML. Full "
            "bounds: %s",
            expected_lo - 1, total_tasks, bounds,
        )
        return 1

    med_lo, med_hi = bounds["MED"]
    if (med_lo, med_hi) != (0, total_tasks - 1):
        logger.error(
            "execute: MED_petlist_bounds is %d %d, expected 0 %d (the "
            "mediator spans the full PET range in a wave-coupled "
            "layout). Likely cause: a stale ush/python/nos-utils pin "
            "applied the 3-component patch (MED confined to the DATM "
            "PETs) -- check the submodule pin.",
            med_lo, med_hi, total_tasks - 1,
        )
        return 1

    interval_matches = _RUNSEQ_INTERVAL_RE.findall(content)
    configured_interval_env = os.environ.get("COUPLING_INTERVAL")
    if configured_interval_env:
        try:
            expected_interval = int(configured_interval_env)
        except ValueError:
            expected_interval = None
        if expected_interval and (
            len(interval_matches) != 1
            or int(interval_matches[0]) != expected_interval
        ):
            logger.error(
                "execute: runSeq coupling interval in ufs.configure is "
                "%s, expected @%d ($COUPLING_INTERVAL / "
                "ufs_coastal.coupling_interval). Likely cause: a stale "
                "ush/python/nos-utils pin reverted the interval to "
                "@<model_dt> (the 3-component patcher doesn't know about "
                "ufs_coupling_interval) -- check the submodule pin.",
                interval_matches, expected_interval,
            )
            return 1

    logger.info(
        "execute: validated 4-component wave PET layout (ATM=%s OCN=%s "
        "WAV=%s MED=%s), runSeq interval=@%s",
        bounds["ATM"], bounds["OCN"], bounds["WAV"], bounds["MED"],
        interval_matches[0] if interval_matches else "?",
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
    candidates = list(outputs_dir.glob("hotstart_it=*.nc"))
    if not candidates:
        logger.info(
            "execute: no hotstart_it=*.nc in %s; rst archive skipped",
            outputs_dir,
        )
        return 0
    # Step numbers sort lexicographically, not numerically ("1920" < "960"),
    # so pick the file with the largest parsed step rather than the last name.
    rst_src = max(candidates, key=_hotstart_step)
    rst_dst = ctx.comout / rst_dst_name
    rst_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rst_src, rst_dst)
    logger.info("execute: archived %s -> %s", rst_src, rst_dst)
    return 0


__all__ = ["run_python"]
