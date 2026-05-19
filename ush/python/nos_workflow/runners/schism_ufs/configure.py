"""Patch the four UFS-Coastal configure files based on cycle anchor values."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Tuple

from . import patches
from .context import SchismRunContext
from .stage_files import _is_ufs

logger = logging.getLogger(__name__)


_DEFAULT_LEN_NOWCAST_HOURS = 6
_DEFAULT_LEN_FORECAST_HOURS = 48


def _resolve_phase_anchors(
    ctx: SchismRunContext,
    phase: str,
) -> Tuple[int, str]:
    """Resolve ``(nhours, sim_start_yyyymmddhh)`` for the given phase."""
    if phase == "nowcast":
        nhours_str = ctx.len_nowcast or str(_DEFAULT_LEN_NOWCAST_HOURS)
        sim_start = ctx.time_hotstart
        if not sim_start:
            raise RuntimeError(
                "configure: nowcast requires ctx.time_hotstart "
                "(populated by prep job in $COMOUT/time_hotstart.<cycle>)"
            )
    elif phase == "forecast":
        nhours_str = ctx.len_forecast or str(_DEFAULT_LEN_FORECAST_HOURS)
        sim_start = ctx.time_nowcastend
        if not sim_start:
            if not (ctx.pdy and ctx.cyc):
                raise RuntimeError(
                    "configure: forecast requires ctx.time_nowcastend or "
                    "ctx.pdy + ctx.cyc"
                )
            sim_start = f"{ctx.pdy}{ctx.cyc}"
    else:
        raise ValueError(
            f"configure: unknown phase {phase!r} (expected nowcast/forecast)"
        )

    try:
        nhours = int(nhours_str)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"configure: LEN_{phase.upper()} must be an integer "
            f"(got {nhours_str!r})"
        ) from exc

    if len(sim_start) != 10 or not sim_start.isdigit():
        raise RuntimeError(
            f"configure: sim_start must be a 10-char YYYYMMDDHH string "
            f"(got {sim_start!r})"
        )

    return nhours, sim_start


def _split_yyyymmddhh(s: str) -> Tuple[str, str, str, str]:
    """Split a YYYYMMDDHH string into (year, month, day, hour) substrings."""
    return s[0:4], s[4:6], s[6:8], s[8:10]


def patch_param_nml(ctx: SchismRunContext, phase: str) -> int:
    """Patch $DATA/param.nml with phase-appropriate rnday/start_*/ihot values.

    Returns the total number of replacements applied across sub-patches.
    """
    target = ctx.data / "param.nml"
    if not target.is_file() or target.stat().st_size == 0:
        # ERROR (not WARNING): SCHISM aborts at schism_nuopc_cap.F90:316
        # if param.nml is absent. Silent skip would crash MPI startup.
        logger.error(
            "patch_param_nml: %s missing or empty -- SCHISM will "
            "abort at schism_nuopc_cap.F90:316. Check that "
            "stage_ufs_configs staged $RUNTIME_CTL and that the "
            "bare-name rename step ran in stage_files.run_python.",
            target,
        )
        return 0

    nhours, sim_start = _resolve_phase_anchors(ctx, phase)
    rnday = nhours / 24.0
    sim_yyyy, sim_mm, sim_dd, sim_hh = _split_yyyymmddhh(sim_start)

    n_total = patches.substitute_placeholders(
        target,
        {
            "rnday_value": str(rnday),
            "start_year_value": sim_yyyy,
            "start_month_value": str(int(sim_mm)),
            "start_day_value": str(int(sim_dd)),
            "start_hour_value": sim_hh,
        },
    )

    n_total += patches.patch_fortran_namelist(
        target,
        {
            "rnday": rnday,
            "start_year": sim_yyyy,
            "start_month": int(sim_mm),
            "start_day": int(sim_dd),
            "start_hour": int(sim_hh),
        },
    )

    # UFS: ihot=1 forces hotstart with clock reset; required for the
    # UFS-Coastal NUOPC clock to drive the SCHISM cap correctly.
    # Standalone (no NUOPC clock): mirror operational pschism --
    # nowcast ihot=1, forecast ihot=2 (continues from nowcast hotstart
    # without resetting the clock); also force nws=2 (sflux, not DATM).
    if _is_ufs():
        simple = {"ihot": 1}
    else:
        simple = {"ihot": 1 if phase == "nowcast" else 2, "nws": 2}
    n_total += patches.patch_fortran_namelist_simple(target, simple)

    logger.info(
        "  Patched param.nml: rnday=%s, start=%s-%s-%s %sZ, %s",
        rnday, sim_yyyy, sim_mm, sim_dd, sim_hh,
        ", ".join(f"{k}={v}" for k, v in simple.items()),
    )
    return n_total


def _read_datm_forcing_dims(forcing_path: Path) -> Tuple[int, int]:
    """Read ``(nx, ny)`` dimensions from a DATM forcing NetCDF.

    Priority order: longitude/x first, then latitude/y (matches ncdump
    declaration order for DATM forcing files).
    """
    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        raise RuntimeError(
            f"_read_datm_forcing_dims: netCDF4 not installed ({exc})"
        ) from exc

    ds = Dataset(str(forcing_path), "r")
    try:
        x_candidates = ("longitude", "x")
        y_candidates = ("latitude", "y")
        nx = None
        ny = None
        for name in x_candidates:
            if name in ds.dimensions:
                nx = len(ds.dimensions[name])
                break
        for name in y_candidates:
            if name in ds.dimensions:
                ny = len(ds.dimensions[name])
                break
        if nx is None or ny is None:
            raise RuntimeError(
                f"_read_datm_forcing_dims: {forcing_path} lacks expected "
                f"dimensions (need one of x_candidates={x_candidates} and "
                f"one of y_candidates={y_candidates}; have {list(ds.dimensions.keys())!r})"
            )
        return nx, ny
    finally:
        ds.close()


def patch_datm_in(ctx: SchismRunContext, phase: str) -> int:
    """Patch $DATA/datm_in nx_global/ny_global to match actual forcing dims.

    Dims come from the actual forcing file (after blending/regridding), not
    from the YAML or template; CDEPS decomposes forcing on these dims.
    """
    del phase

    datm_in = ctx.data / "datm_in"
    if not datm_in.is_file() or datm_in.stat().st_size == 0:
        logger.warning("patch_datm_in: %s missing or empty; skipping", datm_in)
        return 0

    datm_dir_name = os.environ.get("DATM_INPUT_DIR") or "INPUT"
    forcing_path = ctx.data / datm_dir_name / "datm_forcing.nc"
    if not forcing_path.is_file() or forcing_path.stat().st_size == 0:
        logger.warning(
            "patch_datm_in: forcing file %s missing; skipping",
            forcing_path,
        )
        return 0

    try:
        nx, ny = _read_datm_forcing_dims(forcing_path)
    except RuntimeError as exc:
        logger.warning(
            "patch_datm_in: could not read forcing dims (%s); skipping",
            exc,
        )
        return 0

    n = patches.patch_fortran_namelist_simple(
        datm_in,
        {
            "nx_global": nx,
            "ny_global": ny,
        },
    )
    logger.info("  Patched datm_in: nx_global=%d, ny_global=%d", nx, ny)
    return n


def patch_model_configure(ctx: SchismRunContext, phase: str) -> int:
    """Patch $DATA/model_configure with nhours_fcst and start_* fields."""
    target = ctx.data / "model_configure"
    if not target.is_file() or target.stat().st_size == 0:
        logger.warning(
            "patch_model_configure: %s missing or empty; skipping", target,
        )
        return 0

    nhours, sim_start = _resolve_phase_anchors(ctx, phase)
    sim_yyyy, sim_mm, sim_dd, sim_hh = _split_yyyymmddhh(sim_start)

    n = patches.patch_fv3_configure(
        target,
        {
            "nhours_fcst": nhours,
            "start_year": sim_yyyy,
            "start_month": sim_mm,
            "start_day": sim_dd,
            "start_hour": sim_hh,
        },
    )
    logger.info(
        "  Patched model_configure: nhours_fcst=%d, start=%s-%s-%s %sZ",
        nhours, sim_yyyy, sim_mm, sim_dd, sim_hh,
    )
    return n


def patch_ufs_configure(ctx: SchismRunContext, phase: str) -> int:
    """Patch $DATA/ufs.configure with stop_n, start_type, orb_iyear[_align]."""
    target = ctx.data / "ufs.configure"
    if not target.is_file() or target.stat().st_size == 0:
        logger.warning(
            "patch_ufs_configure: %s missing or empty; skipping", target,
        )
        return 0

    nhours, sim_start = _resolve_phase_anchors(ctx, phase)
    sim_yyyy, _sim_mm, _sim_dd, _sim_hh = _split_yyyymmddhh(sim_start)
    # UFS-Coastal NUOPC always uses startup-mode init (we always reset
    # the clock via ihot=1, so warm-restart mode would mis-anchor).
    start_type = "startup"

    n = patches.patch_ufs_configure(
        target,
        {
            "stop_n": nhours,
            "start_type": start_type,
            "orb_iyear": sim_yyyy,
            "orb_iyear_align": sim_yyyy,
        },
    )
    logger.info(
        "  Patched ufs.configure: stop_n=%d, start_type=%s, orb_iyear=%s",
        nhours, start_type, sim_yyyy,
    )
    return n


__all__ = [
    "patch_param_nml",
    "patch_datm_in",
    "patch_model_configure",
    "patch_ufs_configure",
    "_resolve_phase_anchors",
    "_split_yyyymmddhh",
    "_read_datm_forcing_dims",
]
