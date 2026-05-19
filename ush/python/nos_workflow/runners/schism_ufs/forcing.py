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


def _legacy_combined_obc_tar(tar_filename: str) -> str:
    """Derive the legacy combined OBC tar name from a phase-specific name.

    Phase-specific names follow ``{base}.obc.{phase}.tar``; the legacy
    combined tar is ``{base}.obc.tar``. Returns an empty string when the
    input does not match the phase-specific pattern.
    """
    if not tar_filename:
        return ""
    for phase_suffix in (".obc.nowcast.tar", ".obc.forecast.tar"):
        if tar_filename.endswith(phase_suffix):
            return tar_filename[: -len(phase_suffix)] + ".obc.tar"
    return ""


def untar_obc_forcing(ctx: SchismRunContext, phase: str) -> int:
    """Untar the OBC forcing tarball into $DATA.

    Returns count of payload files extracted (0..6), or -1 if absent.

    Phase-specific tars (``{base}.obc.nowcast.tar`` / ``{base}.obc.forecast.tar``)
    are preferred. If absent, falls back to the legacy combined tar
    (``{base}.obc.tar``) for backward compatibility with prep runs that
    predate the phase split.
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

    src = ctx.comout / tar_filename if tar_filename else None
    if src is None or not src.is_file() or src.stat().st_size == 0:
        legacy = _legacy_combined_obc_tar(tar_filename)
        if legacy:
            legacy_src = ctx.comout / legacy
            if legacy_src.is_file() and legacy_src.stat().st_size > 0:
                logger.warning(
                    "OBC forcing: phase-specific tar %s not found in %s; "
                    "falling back to combined tar %s",
                    tar_filename, ctx.comout, legacy,
                )
                tar_filename = legacy

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


def _met_sflux_tar_names(ctx: SchismRunContext, phase: str) -> tuple:
    """Return ``(gfs_tar, hrrr_tar)`` $COMOUT filenames for ``phase``.

    The GFS (stack-1) name comes from the resolved ctx field
    (``MET_NETCDF_1_{PHASE}`` -> ``...met.{phase}.nc.tar``); the optional
    HRRR (stack-2) sibling is the same name with ``.nc.tar`` ->
    ``.nc.2.tar`` (matches setup_paths ``MET_NETCDF_1_{PHASE}_2``).
    """
    if phase == "nowcast":
        gfs = ctx.met_netcdf_nowcast or ""
    elif phase == "forecast":
        gfs = ctx.met_netcdf_forecast or ""
    else:
        raise ValueError(
            f"untar_met_sflux: unknown phase {phase!r} "
            "(expected nowcast/forecast)"
        )
    hrrr = gfs[:-7] + ".nc.2.tar" if gfs.endswith(".nc.tar") else ""
    return gfs, hrrr


def untar_met_sflux(ctx: SchismRunContext, phase: str) -> int:
    """Extract prep sflux met tar(s) from $COMOUT into $DATA/sflux/.

    Standalone SCHISM (nws=2) only. Mirrors :func:`untar_nwm_source_sink`'s
    $COMOUT discovery + ``tar`` extraction, but the destination is
    $DATA/sflux/ (created here) and the GFS stack-1 tar is mandatory --
    SCHISM aborts at sflux init without it. The HRRR stack-2 tar is
    optional (secondary forcing) and a non-fatal miss.

    Returns the number of ``sflux_*.nc`` files present after extraction.
    """
    gfs_tar, hrrr_tar = _met_sflux_tar_names(ctx, phase)

    src = ctx.comout / gfs_tar if gfs_tar else None
    if src is None or not src.is_file() or src.stat().st_size == 0:
        raise FileNotFoundError(
            f"untar_met_sflux: phase={phase} (standalone SCHISM nws=2) "
            f"requires the GFS sflux tar but it was not found.\n"
            f"  Expected: {ctx.comout / gfs_tar if gfs_tar else '(unset)'}\n"
            f"  Fix: ensure prep archived "
            f"$COMOUT/$PREFIXNOS.$cycle.$PDY.met.{phase}.nc.tar "
            f"(nos_utils.orchestrator.archive_to_comout)."
        )

    sflux_dir = ctx.data / "sflux"
    sflux_dir.mkdir(parents=True, exist_ok=True)

    local_tar = sflux_dir / gfs_tar
    shutil.copy2(src, local_tar)
    _extract_tar(local_tar, sflux_dir, label=f"GFS sflux ({phase})")

    if hrrr_tar:
        hrrr_src = ctx.comout / hrrr_tar
        if hrrr_src.is_file() and hrrr_src.stat().st_size > 0:
            local_hrrr = sflux_dir / hrrr_tar
            shutil.copy2(hrrr_src, local_hrrr)
            _extract_tar(local_hrrr, sflux_dir, label=f"HRRR sflux ({phase})")
        else:
            logger.info(
                "  HRRR sflux tar absent (optional secondary): %s", hrrr_src,
            )

    extracted = sum(
        1 for p in sflux_dir.glob("sflux_*.nc")
        if p.is_file() and p.stat().st_size > 0
    )
    logger.info(
        "  Staged sflux met (%d sflux_*.nc files into %s from %s)",
        extracted, sflux_dir, gfs_tar,
    )
    return extracted


__all__ = [
    "untar_obc_forcing",
    "untar_nwm_source_sink",
    "untar_river_forcing",
    "untar_met_sflux",
    "_OBC_PAYLOAD_NAMES",
    "_NWM_PAYLOAD_NAMES",
    "_RIVER_PAYLOAD_NAMES",
]
