"""Untar prep-generated forcing tars from $COMOUT into $DATA.

Three forcing categories: OBC, NWM source/sink, and river forcing.
Each helper returns the number of payload files extracted, or -1 if the
tar was absent (non-fatal; caller handles fallback).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .context import SchismRunContext

logger = logging.getLogger(__name__)


_OBC_PAYLOAD_NAMES: tuple = (
    "elev2D.th.nc",
    "TEM_3D.th.nc",
    "SAL_3D.th.nc",
    "uv3D.th.nc",
    "TEM_nu.nc",
    "SAL_nu.nc",
)

_NWM_PAYLOAD_NAMES: tuple = (
    "vsource.th",
    "vsink.th",
    "msource.th",
    "source_sink.in",
)

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
    """Run ``tar xf <tar_path> -C <dest>``. Returns 0 on success."""
    try:
        completed = subprocess.run(
            ["tar", "xf", str(tar_path), "-C", str(dest)],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
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
    """Copy tar from $COMOUT to $DATA and extract it.

    Returns the number of payload files present in $DATA after extraction,
    or -1 if the source tar was missing or empty.
    """
    if not tar_filename:
        return -1

    src = ctx.comout / tar_filename
    if not src.is_file() or src.stat().st_size == 0:
        logger.warning("%s tar not found or empty: %s", label, src)
        return -1

    ctx.data.mkdir(parents=True, exist_ok=True)
    local_tar = ctx.data / tar_filename
    shutil.copy2(src, local_tar)

    rc = _extract_tar(local_tar, ctx.data, label=label)
    if rc != 0:
        pass

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


def untar_obc_forcing(ctx: SchismRunContext, phase: str) -> int:
    """Untar the OBC forcing tarball into $DATA.

    Returns count of payload files extracted (0..6), or -1 if absent.
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


def untar_nwm_source_sink(ctx: SchismRunContext, phase: str) -> int:
    """Untar the NWM source/sink tarball into $DATA.

    Returns count of payload files extracted (0..4), or -1 if absent.
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


def untar_river_forcing(ctx: SchismRunContext, phase: str) -> int:
    """Untar the river forcing tarball into $DATA (phase-agnostic).

    Returns count of payload files extracted (0..3), or -1 if absent.
    """
    del phase

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
