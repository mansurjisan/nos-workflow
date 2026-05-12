"""Python port of phase 7 of ``_schism_stage_files``: patch the four
UFS-Coastal configure files based on the cycle's anchor values.

Patches applied per file:

    param.nml          rnday, start_year/month/day/hour, ihot
    datm_in            nx_global, ny_global (from actual forcing dims)
    model_configure    nhours_fcst, start_year/month/day/hour
    ufs.configure      stop_n, start_type, orb_iyear, orb_iyear_align

Uses the patcher API from :mod:`patches` (PR 7a) for byte-equivalent
sed-replacement.  This module is the "wire it up with phase-specific
values" layer -- the sed pattern logic lives in ``patches.py``.

Shell counterpart: lines 491-565 of ``ush/nos_run.sh``.

Two phase-driven values flow through this module:

  - ``nhours``:
      * nowcast  -> ``LEN_NOWCAST`` (default 6)
      * forecast -> ``LEN_FORECAST`` (default 48)
  - ``sim_start`` (YYYYMMDDHH):
      * nowcast  -> ``time_hotstart`` (set by prep; cold-start fallback
                    is ``$NDATE -${LEN_NOWCAST} ${PDY}${cyc}``)
      * forecast -> ``time_nowcastend`` (set by nowcast; fallback is
                    ``${PDY}${cyc}``)

These map to the param.nml ``rnday``, ``start_year``, ``start_month``,
``start_day``, ``start_hour`` fields; to model_configure's
``nhours_fcst`` and ``start_*``; and to ufs.configure's ``stop_n`` and
``orb_iyear`` / ``orb_iyear_align``.

PR 7b ships implementation + tests only.  Dispatcher wire-in is PR 7c.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Tuple

from . import patches
from .context import SchismRunContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase-driven value resolution
# ---------------------------------------------------------------------------


# Default forecast/nowcast hour lengths -- match the shell's ``${LEN_*:-N}``
# defaults at lines 501 / 504 of nos_run.sh.
_DEFAULT_LEN_NOWCAST_HOURS = 6
_DEFAULT_LEN_FORECAST_HOURS = 48


def _resolve_phase_anchors(
    ctx: SchismRunContext,
    phase: str,
) -> Tuple[int, str]:
    """Resolve ``(nhours, sim_start_yyyymmddhh)`` for the given phase.

    Mirrors lines 500-510 of nos_run.sh::

        if [ "$phase" = "nowcast" ]; then
            nhours=${LEN_NOWCAST:-6}
            sim_start=${time_hotstart:-...}
        else
            nhours=${LEN_FORECAST:-48}
            sim_start=${time_nowcastend:-${PDY}${cyc}}
        fi

    The shell falls back to ``$NDATE -${LEN_NOWCAST} ${PDY}${cyc}`` for
    nowcast when ``time_hotstart`` is unset -- that's an operational
    safety net for cold starts where prep didn't run.  For PR 7b's
    scope we don't replicate the NDATE shell-out; if ``time_hotstart``
    is None and we're in nowcast, we raise (the dispatcher in PR 7c
    will populate it from $COMOUT/time_hotstart.<cycle>).

    Args:
        ctx: runner context.
        phase: ``"nowcast"`` or ``"forecast"``.

    Returns:
        ``(nhours, sim_start)`` -- nhours is an int (hours of run
        duration), sim_start is a 10-char YYYYMMDDHH string.

    Raises:
        ValueError: phase not in {nowcast, forecast}.
        RuntimeError: required time anchor missing from ctx.
    """
    if phase == "nowcast":
        nhours_str = ctx.len_nowcast or str(_DEFAULT_LEN_NOWCAST_HOURS)
        sim_start = ctx.time_hotstart
        if not sim_start:
            # Shell fallback uses NDATE; we require the field be set
            # (the dispatcher reads $COMOUT/time_hotstart.<cycle>).
            raise RuntimeError(
                "configure: nowcast requires ctx.time_hotstart "
                "(populated by prep job in $COMOUT/time_hotstart.<cycle>)"
            )
    elif phase == "forecast":
        nhours_str = ctx.len_forecast or str(_DEFAULT_LEN_FORECAST_HOURS)
        sim_start = ctx.time_nowcastend
        if not sim_start:
            # Shell fallback: ${PDY}${cyc}.  We honor that here since
            # the dispatcher always populates pdy + cyc.
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
    """Split a YYYYMMDDHH string into (year, month, day, hour) strings.

    Returns the substrings in the same form the shell uses at lines
    507-510::

        sim_yyyy=$(echo $sim_start | cut -c1-4)
        sim_mm=$(  echo $sim_start | cut -c5-6)
        sim_dd=$(  echo $sim_start | cut -c7-8)
        sim_hh=$(  echo $sim_start | cut -c9-10)

    Each substring keeps its leading zero (so "01" not "1") -- the
    shell strips zeros via ``${sim_mm#0}`` later only for param.nml,
    not for model_configure or ufs.configure.
    """
    return s[0:4], s[4:6], s[6:8], s[8:10]


# ---------------------------------------------------------------------------
# Phase 7a: param.nml
# ---------------------------------------------------------------------------


def patch_param_nml(ctx: SchismRunContext, phase: str) -> int:
    """Patch ``$DATA/param.nml`` with phase-appropriate values.

    Shell counterpart: lines 538-551 of nos_run.sh (plus line 661 for
    the forecast-only ``ihot=1`` re-patch -- both calls are folded into
    this single helper).

    Patches applied:

      1. Placeholder substitutions (template tokens in a fresh
         param.nml copied from $FIXofs / $RUNTIME_CTL):

            rnday_value       -> str(nhours / 24.0)
            start_year_value  -> sim_yyyy
            start_month_value -> str(int(sim_mm))  # zero-stripped
            start_day_value   -> str(int(sim_dd))  # zero-stripped
            start_hour_value  -> sim_hh

         These match lines 540-545 of nos_run.sh (with the ``${X#0}``
         zero-stripping converted to ``int()``).

      2. Literal Fortran-namelist patches for any pre-existing numeric
         values in the file (handles the case where param.nml was a
         live config rather than a template):

            rnday        = <float>
            start_year   = <yyyy>
            start_month  = <int(mm)>
            start_day    = <int(dd)>
            start_hour   = <int(hh)>
            ihot         = 1

         Mirrors lines 541, 546-549, 550 of nos_run.sh.  The shell uses
         ``sed -i "s/^\\(\\s*KEY\\s*=\\s*\\)[0-9.]*\\(.*\\)/\\1NEW\\2/"``
         which is what :func:`patches.patch_fortran_namelist` implements.

      3. ``ihot = 1`` permissive patch (line 550 + 661 of nos_run.sh).
         For both nowcast and forecast, ihot is forced to 1 -- the
         legacy COMF semantic: ihot=1 means "hotstart with clock reset"
         which is required for the UFS-Coastal NUOPC clock to drive the
         SCHISM cap correctly.

    If ``$DATA/param.nml`` is missing or empty, the function logs a
    WARNING and returns 0 (the shell does the same via ``[ -s ... ]``).

    Args:
        ctx: runner context (reads time_hotstart / time_nowcastend /
            len_nowcast / len_forecast / pdy / cyc as appropriate).
        phase: ``"nowcast"`` or ``"forecast"``.

    Returns:
        Total number of replacements applied across all sub-patches
        (sum of return values from the three patches.* calls).
    """
    target = ctx.data / "param.nml"
    if not target.is_file() or target.stat().st_size == 0:
        logger.warning(
            "patch_param_nml: %s missing or empty; skipping", target,
        )
        return 0

    nhours, sim_start = _resolve_phase_anchors(ctx, phase)
    rnday = nhours / 24.0
    sim_yyyy, sim_mm, sim_dd, sim_hh = _split_yyyymmddhh(sim_start)

    # ---- 1. Template placeholders (lines 540-545 of nos_run.sh)
    # The shell uses ``${sim_mm#0}`` / ``${sim_dd#0}`` to strip a leading
    # zero, but NOT ``${sim_hh#0}`` for the hour-value placeholder (the
    # hour placeholder is set to the full two-char form, line 545).
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

    # ---- 2. Live namelist values (lines 541, 546-549 of nos_run.sh)
    # The shell's strict pattern keeps leading whitespace + trailing
    # comment; the helper :func:`patches.patch_fortran_namelist` does
    # the same.
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

    # ---- 3. ihot = 1 (lines 550 + 661 of nos_run.sh)
    # The permissive form is used here because the shell's line 550 sed
    # is ``s/ihot = [0-9]*/ihot = ${ihot_val}/`` (no anchor, no capture).
    n_total += patches.patch_fortran_namelist_simple(
        target,
        {"ihot": 1},
    )

    logger.info(
        "  Patched param.nml: rnday=%s, start=%s-%s-%s %sZ, ihot=1",
        rnday, sim_yyyy, sim_mm, sim_dd, sim_hh,
    )
    return n_total


# ---------------------------------------------------------------------------
# Phase 7b: datm_in (nx_global, ny_global from forcing dims)
# ---------------------------------------------------------------------------


def _read_datm_forcing_dims(forcing_path: Path) -> Tuple[int, int]:
    """Read ``(nx, ny)`` dimensions from a DATM forcing NetCDF.

    The shell uses::

        ncdump -h $forcing_nc | grep -oP '(x|y|longitude|latitude)\\s*=\\s*\\K[0-9]+' | head -2

    -- which returns the FIRST two dim sizes whose name is one of
    ``{x, y, longitude, latitude}``.  We mirror by checking the same
    names in the same priority order.

    Args:
        forcing_path: path to the NetCDF forcing file.

    Returns:
        ``(nx, ny)`` -- two ints, in the order ncdump prints them
        (longitude/x first, latitude/y second).  This matches the shell
        because ncdump always lists dims in declaration order, which for
        DATM forcing is consistently longitude before latitude.

    Raises:
        RuntimeError: if the forcing file doesn't have the expected
            dimensions, or netCDF4 isn't installed.
    """
    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        raise RuntimeError(
            f"_read_datm_forcing_dims: netCDF4 not installed ({exc})"
        ) from exc

    ds = Dataset(str(forcing_path), "r")
    try:
        # Priority order matches the shell's grep alternation.  We pick
        # the first matching name for "x-like" then for "y-like".
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
    """Patch ``$DATA/datm_in`` ``nx_global`` / ``ny_global`` to match
    the actual forcing-file dimensions.

    Shell counterpart: lines 555-565 of nos_run.sh::

        if [ -s "${DATA}/datm_in" ] && [ -s "${DATA}/${DATM_DIR}/datm_forcing.nc" ]; then
            _dims=$(ncdump -h ... | grep -oP '...' | head -2)
            _nx=$(echo $_dims | awk '{print $1}')
            _ny=$(echo $_dims | awk '{print $2}')
            sed -i "s/nx_global = [0-9]*/nx_global = ${_nx}/" ${DATA}/datm_in
            sed -i "s/ny_global = [0-9]*/ny_global = ${_ny}/" ${DATA}/datm_in
        fi

    The dims come from the actual forcing file (after any HRRR/GFS
    blending or RRFS regridding), NOT from the YAML or template.  This
    matters because the blender + regridder can produce different grid
    sizes per cycle (MEMORY.md lesson #14), and CDEPS decomposes
    forcing based on these dims.

    Args:
        ctx: runner context.
        phase: present for API symmetry; unused (datm_in dims don't
            change between nowcast and forecast within a single cycle).

    Returns:
        Number of replacements applied (0 if datm_in or the forcing
        file is missing -- non-fatal; warning logged).
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


# ---------------------------------------------------------------------------
# Phase 7c: model_configure (FV3 key:value)
# ---------------------------------------------------------------------------


def patch_model_configure(ctx: SchismRunContext, phase: str) -> int:
    """Patch ``$DATA/model_configure`` with ``nhours_fcst`` + ``start_*``.

    Shell counterpart: lines 516-522 of nos_run.sh::

        if [ -s "${DATA}/model_configure" ]; then
            sed -i "s/nhours_fcst:.*/nhours_fcst:             ${nhours}/" file
            sed -i "s/start_year:.*/start_year:              ${sim_yyyy}/" file
            sed -i "s/start_month:.*/start_month:             ${sim_mm}/"  file
            sed -i "s/start_day:.*/start_day:               ${sim_dd}/"    file
            sed -i "s/start_hour:.*/start_hour:              ${sim_hh}/"   file
        fi

    Uses :func:`patches.patch_fv3_configure` which handles the
    13-space-pad alignment exactly as the shell hard-codes it.

    Note the shell does NOT strip leading zeros from ``$sim_mm`` /
    ``$sim_dd`` for this file (in contrast to param.nml's ``${X#0}``
    treatment) -- model_configure expects two-digit month/day strings.

    Args:
        ctx: runner context.
        phase: ``"nowcast"`` or ``"forecast"``.

    Returns:
        Number of replacements applied (0 if model_configure absent).
    """
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


# ---------------------------------------------------------------------------
# Phase 7d: ufs.configure (key = value)
# ---------------------------------------------------------------------------


def patch_ufs_configure(ctx: SchismRunContext, phase: str) -> int:
    """Patch ``$DATA/ufs.configure`` with ``stop_n`` + ``start_type`` +
    ``orb_iyear`` + ``orb_iyear_align``.

    Shell counterpart: lines 523-528 of nos_run.sh::

        if [ -s "${DATA}/ufs.configure" ]; then
            sed -i "s/stop_n = .*/stop_n = ${nhours}/"             file
            sed -i "s/start_type = .*/start_type = ${start_type}/" file
            sed -i "s/orb_iyear = .*/orb_iyear = ${sim_yyyy}/"     file
            sed -i "s/orb_iyear_align = .*/orb_iyear_align = ${sim_yyyy}/" file
        fi

    ``start_type`` is hard-coded to ``"startup"`` -- the shell sets
    ``local start_type="startup"`` at line 498 and never changes it.
    UFS-Coastal NUOPC requires startup-mode initialization for both
    nowcast (with hotstart) and forecast (with previous nowcast's
    restart) because we always reset the clock via ihot=1.

    Args:
        ctx: runner context.
        phase: ``"nowcast"`` or ``"forecast"``.

    Returns:
        Number of replacements applied (0 if ufs.configure absent).
    """
    target = ctx.data / "ufs.configure"
    if not target.is_file() or target.stat().st_size == 0:
        logger.warning(
            "patch_ufs_configure: %s missing or empty; skipping", target,
        )
        return 0

    nhours, sim_start = _resolve_phase_anchors(ctx, phase)
    sim_yyyy, _sim_mm, _sim_dd, _sim_hh = _split_yyyymmddhh(sim_start)
    start_type = "startup"  # hard-coded at shell line 498

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
