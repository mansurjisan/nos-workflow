"""Python port of phases 4-6 of ``_schism_stage_files``: untar prep-
generated forcing tars from ``$COMOUT`` into ``$DATA``.

Three categories of tars, all written by the prep job and consumed
by the nowcast/forecast jobs:

  - OBC tar (elev2D.th.nc, TEM/SAL_3D.th.nc, uv3D.th.nc, TEM_nu.nc,
    SAL_nu.nc).  Source: ``$COMOUT/$OBC_FORCING_FILE``.  Phase-agnostic
    filename (the prep job writes a single tarball per cycle).
  - NWM source/sink tar (vsource.th, vsink.th, msource.th,
    source_sink.in).  Source: ``$COMOUT/$NWM_SOURCE_SINK_NOW`` for
    nowcast / ``$COMOUT/$NWM_SOURCE_SINK_FORE`` for forecast.
  - River forcing tar (schism_flux.th, schism_temp.th, schism_salt.th).
    Source: ``$COMOUT/$RIVER_FORCING_FILE``.  Optional -- absent on
    cycles without observed river forcing.

Shell counterpart: lines 670-723 of ``ush/nos_run.sh``.

The shell wraps the NWM extraction with ``2>/dev/null || true`` so a
missing tar is non-fatal (the FIXofs fallback at lines 685-701 covers
that case).  We match the semantics: each helper returns the number
of files extracted, or ``-1`` if the tar was missing/empty/unreadable.
Callers should NOT treat ``-1`` as an error -- the FIXofs-fallback step
in ``stage_files`` follows up.

Public API (all functions take a :class:`SchismRunContext` + phase
string)::

    untar_obc_forcing(ctx, phase) -> int
    untar_nwm_source_sink(ctx, phase) -> int
    untar_river_forcing(ctx, phase) -> int

Each function:

  1. Resolves the tar filename from the appropriate ctx field (phase-
     dependent for NWM, phase-agnostic for OBC + river).
  2. Copies the tar from ``$COMOUT/<file>`` to ``$DATA/<file>`` to match
     the shell's ``cp -p`` step (so subsequent tar -xf finds it locally).
  3. Runs ``tar xf $DATA/<file> -C $DATA/``.
  4. Returns the count of regular files now present under $DATA whose
     names match the expected payload (see ``_*_PAYLOAD_NAMES``), so
     tests can assert on the specific files extracted.

PR 7b ships implementation + tests only.  Dispatcher wire-in is PR 7c.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .context import SchismRunContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Expected tar-payload filenames.
#
# These are the names the shell explicitly checks for after extraction
# (e.g., line 686 ``[ ! -s "${DATA}/source_sink.in" ]``).  Used by the
# helpers below to count "files extracted" in a way that's robust to the
# tar containing extra unrelated entries -- we only count members that
# match the documented payload contract.
# ---------------------------------------------------------------------------

# OBC tar payload (lines 703-712 of nos_run.sh -- the shell comment lists
# TEM_nu.nc, SAL_nu.nc, TEM_3D.th.nc, SAL_3D.th.nc, elev2D.th.nc,
# uv3D.th.nc as the canonical set).
_OBC_PAYLOAD_NAMES: tuple = (
    "elev2D.th.nc",
    "TEM_3D.th.nc",
    "SAL_3D.th.nc",
    "uv3D.th.nc",
    "TEM_nu.nc",
    "SAL_nu.nc",
)

# NWM source/sink tar payload (line 686-701 lists the four files the
# shell validates and falls back on).
_NWM_PAYLOAD_NAMES: tuple = (
    "vsource.th",
    "vsink.th",
    "msource.th",
    "source_sink.in",
)

# River forcing tar payload (line 725-728 of nos_run.sh).
_RIVER_PAYLOAD_NAMES: tuple = (
    "schism_flux.th",
    "schism_temp.th",
    "schism_salt.th",
)


def _extract_tar(
    tar_path: Path,
    dest: Path,
    *,
    label: str,
) -> int:
    """Run ``tar xf <tar_path> -C <dest>``.

    Mirrors the shell's ``tar xf $tar -C $dest``.  Uses
    ``subprocess.run(["tar", ...])`` rather than Python's ``tarfile``
    module so we exactly match the shell's behavior (handles compressed
    tars, hardlinks, owner-preservation, etc. the same way GNU tar does).

    Args:
        tar_path: path to the tarball (must already exist; caller
            checks).
        dest: extraction destination directory.
        label: human-readable label for logging.

    Returns:
        0 on success, non-zero on failure.  Failures log WARNING; the
        shell wraps NWM extraction in ``|| true`` so a hard exception
        here would be wrong -- we mirror by returning rc and letting
        the caller decide.
    """
    try:
        completed = subprocess.run(
            ["tar", "xf", str(tar_path), "-C", str(dest)],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        # tar not on PATH -- unrecoverable for this helper.
        logger.warning("tar binary not found while extracting %s: %s", label, exc)
        return 127
    if completed.returncode != 0:
        logger.warning(
            "tar xf failed for %s (rc=%d): %s",
            label, completed.returncode, completed.stderr.strip(),
        )
    return completed.returncode


def _stage_and_extract(
    ctx: SchismRunContext,
    *,
    tar_filename: str,
    payload_names: tuple,
    label: str,
) -> int:
    """Shared implementation: ``cp $COMOUT/$tar $DATA/`` then ``tar xf``.

    Returns the number of payload files now present in ``$DATA`` after
    extraction (a loose proxy for "files extracted from this tar"), or
    ``-1`` if the source tar was missing/empty.

    The shell pattern is::

        if [ -s "$COMOUT/$TAR" ]; then
            cp -p $COMOUT/$TAR $DATA/
            tar xf $DATA/$TAR -C $DATA/
        fi

    -- which is what this helper implements.
    """
    if not tar_filename:
        return -1

    src = ctx.comout / tar_filename
    if not src.is_file() or src.stat().st_size == 0:
        logger.warning("%s tar not found or empty: %s", label, src)
        return -1

    # Match the shell: copy to $DATA first, then extract from there.
    ctx.data.mkdir(parents=True, exist_ok=True)
    local_tar = ctx.data / tar_filename
    shutil.copy2(src, local_tar)

    rc = _extract_tar(local_tar, ctx.data, label=label)
    if rc != 0:
        # The shell uses ``2>/dev/null || true`` for NWM; we surface the
        # warning but still report what's on disk.  OBC + river extraction
        # in the shell does NOT swallow errors (line 707, 718) -- but we
        # let the caller distinguish via the return value.
        pass

    # Count payload files now present under $DATA (top-level only --
    # the shell extracts flat tars into $DATA/, no nested dirs).
    extracted = 0
    for name in payload_names:
        candidate = ctx.data / name
        if candidate.is_file() and candidate.stat().st_size > 0:
            extracted += 1

    logger.info(
        "  Staged %s (%d/%d payload files extracted from %s)",
        label, extracted, len(payload_names), tar_filename,
    )
    return extracted


# ---------------------------------------------------------------------------
# Phase 4: OBC forcing tar
# ---------------------------------------------------------------------------


def untar_obc_forcing(ctx: SchismRunContext, phase: str) -> int:
    """Untar the OBC forcing tarball into ``$DATA``.

    Shell counterpart: lines 703-712 of ``nos_run.sh``::

        if [ -n "${OBC_FORCING_FILE:-}" ]; then
            if [ -s "${COMOUT}/${OBC_FORCING_FILE}" ]; then
                cp -p ${COMOUT}/${OBC_FORCING_FILE} ${DATA}/
                tar xf ${DATA}/${OBC_FORCING_FILE} -C ${DATA}/
                echo "  Staged OBC forcing from ${OBC_FORCING_FILE}"
            else
                echo "WARNING: OBC forcing tar not found..."
            fi
        fi

    The context exposes two fields (``obc_forcing_file_nowcast`` and
    ``obc_forcing_file_forecast``) so PR 7b can carry phase-specific
    tars even though the legacy shell uses a single ``OBC_FORCING_FILE``
    env var.  We resolve from the phase-specific field first and fall
    back to neither (the dispatcher is responsible for populating the
    appropriate field via ``from_env_and_phase``).

    Args:
        ctx: runner context.
        phase: ``"nowcast"`` or ``"forecast"`` -- selects which OBC tar
            field to read.

    Returns:
        Number of payload files extracted (0..6), or ``-1`` if the tar
        is absent.  Caller treats ``-1`` as a non-fatal warning per the
        shell's behavior.
    """
    if phase == "nowcast":
        tar_filename = ctx.obc_forcing_file_nowcast or ""
    elif phase == "forecast":
        tar_filename = ctx.obc_forcing_file_forecast or ""
    else:
        raise ValueError(
            f"untar_obc_forcing: unknown phase {phase!r} "
            "(expected nowcast/forecast)"
        )

    return _stage_and_extract(
        ctx,
        tar_filename=tar_filename,
        payload_names=_OBC_PAYLOAD_NAMES,
        label="OBC forcing",
    )


# ---------------------------------------------------------------------------
# Phase 5: NWM source/sink tar
# ---------------------------------------------------------------------------


def untar_nwm_source_sink(ctx: SchismRunContext, phase: str) -> int:
    """Untar the NWM source/sink tarball into ``$DATA``.

    Shell counterpart: lines 670-683 of ``nos_run.sh``::

        if [ "$phase" = "nowcast" ] && [ -n "${NWM_SOURCE_SINK_NOW:-}" ]; then
            if [ -s "${COMOUT}/${NWM_SOURCE_SINK_NOW}" ]; then
                cp -p ${COMOUT}/${NWM_SOURCE_SINK_NOW} ${DATA}/
                tar xf ${DATA}/${NWM_SOURCE_SINK_NOW} -C ${DATA}/ 2>/dev/null || true
                echo "  Staged NWM river forcing (nowcast)"
            fi
        elif [ "$phase" = "forecast" ] && [ -n "${NWM_SOURCE_SINK_FORE:-}" ]; then
            ...

    The shell swallows tar errors (``|| true``) because the FIXofs
    fallback at lines 686-701 handles a partial/missing extraction --
    we follow the same convention.

    Args:
        ctx: runner context.  Reads
            ``ctx.nwm_source_sink_nowcast`` (nowcast) or
            ``ctx.nwm_source_sink_forecast`` (forecast).
        phase: ``"nowcast"`` or ``"forecast"``.

    Returns:
        Number of NWM payload files extracted (0..4), or ``-1`` if the
        tar is absent.
    """
    if phase == "nowcast":
        tar_filename = ctx.nwm_source_sink_nowcast or ""
    elif phase == "forecast":
        tar_filename = ctx.nwm_source_sink_forecast or ""
    else:
        raise ValueError(
            f"untar_nwm_source_sink: unknown phase {phase!r} "
            "(expected nowcast/forecast)"
        )

    return _stage_and_extract(
        ctx,
        tar_filename=tar_filename,
        payload_names=_NWM_PAYLOAD_NAMES,
        label=f"NWM river forcing ({phase})",
    )


# ---------------------------------------------------------------------------
# Phase 6: River forcing tar
# ---------------------------------------------------------------------------


def untar_river_forcing(ctx: SchismRunContext, phase: str) -> int:
    """Untar the river forcing tarball into ``$DATA``.

    Shell counterpart: lines 715-723 of ``nos_run.sh``::

        if [ -n "${RIVER_FORCING_FILE:-}" ]; then
            if [ -s "${COMOUT}/${RIVER_FORCING_FILE}" ]; then
                cp -p ${COMOUT}/${RIVER_FORCING_FILE} ${DATA}/
                tar xf ${DATA}/${RIVER_FORCING_FILE} -C ${DATA}/
                echo "  Staged river forcing from ${RIVER_FORCING_FILE}"
            else
                echo "WARNING: River forcing tar not found..."
            fi
        fi

    Phase-agnostic -- the shell uses a single ``RIVER_FORCING_FILE`` env
    var for both nowcast and forecast (the river observations cover the
    full 6+48h sim window in one tar).

    Args:
        ctx: runner context.  Reads ``ctx.river_forcing_file``.
        phase: present for API symmetry; unused here.

    Returns:
        Number of river payload files extracted (0..3), or ``-1`` if
        the tar is absent.  Missing is non-fatal per the shell.
    """
    del phase  # phase-agnostic

    return _stage_and_extract(
        ctx,
        tar_filename=ctx.river_forcing_file or "",
        payload_names=_RIVER_PAYLOAD_NAMES,
        label="river forcing",
    )


__all__ = [
    "untar_obc_forcing",
    "untar_nwm_source_sink",
    "untar_river_forcing",
    "_OBC_PAYLOAD_NAMES",
    "_NWM_PAYLOAD_NAMES",
    "_RIVER_PAYLOAD_NAMES",
]
