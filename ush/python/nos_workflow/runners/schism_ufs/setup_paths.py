"""Python port of ``_schism_setup_paths`` from ``ush/nos_run.sh``.

Builds a :class:`SchismRunContext` for the SCHISM-UFS pipeline. Replaces
the 50+ env-var exports the shell function does. Reads grid + runtime
control files from ``$FIXofs`` into ``$DATA``, computes filename
conventions for ``$COMOUT`` artifacts, derives time anchors via
:mod:`_dateutils` (pure Python; no NDATE / NHOUR subprocess).

Shell counterpart: lines 128-285 of ``ush/nos_run.sh``.

This module does NOT yet dispatch from the stages -- PR 5 lands the
implementation + parity tests only. Wire-in happens in PR 7c (after
``stage_files`` port lands).

Public API::

    compute_paths(env: NCOEnv, phase: str, runtype: str = "nowcast")
        -> SchismRunContext

Where:

- ``env``: :class:`NCOEnv` from :mod:`nos_workflow.env` (carries PDY,
  cyc, COMOUT, etc.).
- ``phase``: ``"nowcast"`` or ``"forecast"``.
- ``runtype``: ``"nowcast"`` | ``"forecast"`` | ``"prep"``. ``"prep"``
  mode raises :class:`NotImplementedError` -- that triggers
  ``_schism_find_hotstart`` which lands in PR 6.

The shell function exports a single ``PDY1`` derived from ``time_nowcastend``;
since ``time_nowcastend == PDY||cyc`` by default, ``PDY1 == PDY`` here.
The Python port uses ``env.pdy`` directly for filename construction.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from . import _dateutils
from .context import SchismRunContext

if TYPE_CHECKING:
    from ...env import NCOEnv

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional fix-file env vars consumed by _schism_setup_paths.
#
# Keyed by env-var name; value is True if the file is REQUIRED (return 1
# if missing) or False if optional (warning only). This list maps 1:1 to
# the file-staging block in lines 142-199 of nos_run.sh.
# ---------------------------------------------------------------------------
_REQUIRED_FIX_FILES = ("GRIDFILE", "STA_OUT_CTL", "RUNTIME_CTL")
_OPTIONAL_FIX_FILES = (
    "GRIDFILE_LL",
    "Nudging_weight",
    "VGRID_CTL",
    "VGRID_NU_CTL",
    "RUNTIME_CTL_FOR",
    "NWM_REACHID_FILE",
)


def _stage_fix_files(env: "NCOEnv") -> None:
    """Copy required + optional fix files from ``$FIXofs`` to ``$DATA``.

    Matches the file-staging logic of ``_schism_setup_paths`` lines
    142-199. Missing required files log an ERROR and the caller decides
    whether to raise (the shell's ``err_chk`` semantics let the dispatcher
    handle the failure). Missing optional files log a WARNING.

    The VGRID_FAKE_CTL case is special: when set, the fake vgrid is copied
    OVER the canonical VGRID_CTL name in $DATA (see launch.sh:154 + the
    intentional override at nos_run.sh:171).
    """
    fixofs = env.fixofs
    data = env.data
    data.mkdir(parents=True, exist_ok=True)
    (data / "outputs").mkdir(parents=True, exist_ok=True)
    (data / "sflux").mkdir(parents=True, exist_ok=True)

    # Required files
    for ev_name in _REQUIRED_FIX_FILES:
        fname = os.environ.get(ev_name, "")
        if not fname:
            logger.warning(
                "setup_paths: required env var %s not set; skipping fix-file copy",
                ev_name,
            )
            continue
        src = fixofs / fname
        if not src.is_file() or src.stat().st_size == 0:
            logger.error(
                "setup_paths: required fix file %s not found (or empty) in %s",
                fname, fixofs,
            )
            continue
        shutil.copy2(src, data / src.name)

    # Optional files
    for ev_name in _OPTIONAL_FIX_FILES:
        fname = os.environ.get(ev_name, "")
        if not fname:
            continue
        src = fixofs / fname
        if not src.is_file() or src.stat().st_size == 0:
            logger.warning(
                "setup_paths: optional fix file %s (%s) not found in %s",
                ev_name, fname, fixofs,
            )
            continue
        shutil.copy2(src, data / src.name)

    # vgrid.fake -> vgrid.in (intentional override; see nos_run.sh:171)
    vgrid_fake = os.environ.get("VGRID_FAKE_CTL", "")
    vgrid_ctl = os.environ.get("VGRID_CTL", "")
    if vgrid_fake and vgrid_ctl:
        src = fixofs / vgrid_fake
        if src.is_file() and src.stat().st_size > 0:
            shutil.copy2(src, data / vgrid_ctl)

    # PREFIXNOS-prefixed nudge index files (lines 172-175)
    prefixnos = os.environ.get("PREFIXNOS", "")
    if prefixnos:
        for bare_name in ("nobc_nudge_index.dat", "nudge_point_at_ofs_grid.dat"):
            src = fixofs / f"{prefixnos}.{bare_name}"
            if src.is_file() and src.stat().st_size > 0:
                shutil.copy2(src, data / bare_name)

    # Tidal harmonic constants (conditional on CREATE_TIDEFORCING + DBASE_WL_NOW)
    create_tide = os.environ.get("CREATE_TIDEFORCING", "0")
    dbase_wl_now = os.environ.get("DBASE_WL_NOW", "OBS")
    try:
        create_tide_int = int(create_tide)
    except (TypeError, ValueError):
        create_tide_int = 0
    if create_tide_int > 0 and dbase_wl_now != "OBS":
        hc_file = os.environ.get("HC_FILE_OBC", "")
        if hc_file:
            src = fixofs / hc_file
            if src.is_file() and src.stat().st_size > 0:
                shutil.copy2(src, data / src.name)
            else:
                logger.error(
                    "setup_paths: HC_FILE_OBC %s not found in %s (CREATE_TIDEFORCING=%s)",
                    hc_file, fixofs, create_tide,
                )


def _compute_filenames(prefix: str, cycle: str, pdy1: str) -> dict:
    """Build the filename convention dict that the shell exports as
    ``OBC_FORCING_FILE``, ``RST_OUT_NOWCAST``, etc.

    Mirrors lines 234-278 of ``nos_run.sh``. Returns a dict keyed by the
    NCO env var name so callers can either drop the names into
    :class:`SchismRunContext` (via the snake_case mapping) or merge into
    ``os.environ`` for shell compatibility.
    """
    base = f"{prefix}.{cycle}.{pdy1}"
    return {
        # Forcing artifacts
        "OBC_FORCING_FILE":      f"{base}.obc.tar",
        "RIVER_FORCING_FILE":    f"{base}.river.th.tar",
        "NWM_SOURCE_SINK_NOW":   f"{base}.nwm.source.sink.now.tar",
        "NWM_SOURCE_SINK_FORE":  f"{base}.nwm.source.sink.fore.tar",
        "BCTIDES_IN":            f"{base}.bctides.in",
        "OBC_TIDALFORCING_FILE": f"{base}.roms.tides.nc",
        "NUDG_FORCING_FILE":     f"{base}.clim.nc",
        "OBC_FORCING_FILE_EL":   f"{base}.obc.el.tar",
        "OBC_FORCING_FILE_TS":   f"{base}.obc.ts.tar",
        # Met forcing tarballs
        "MET_NETCDF_1_NOWCAST":    f"{base}.met.nowcast.nc.tar",
        "MET_NETCDF_1_FORECAST":   f"{base}.met.forecast.nc.tar",
        "MET_NETCDF_1_NOWCAST_2":  f"{base}.met.nowcast.nc.2.tar",
        "MET_NETCDF_1_FORECAST_2": f"{base}.met.forecast.nc.2.tar",
        "MET_NETCDF_2_NOWCAST":    f"{base}.hflux.nowcast.nc",
        "MET_NETCDF_2_FORECAST":   f"{base}.hflux.forecast.nc",
        # Restart / initial files
        "INI_FILE_NOWCAST":  f"{base}.init.nowcast.nc",
        "RST_OUT_NOWCAST":   f"{base}.rst.nowcast.nc",
        "RST_OUT_FORECAST":  f"{base}.rst.forecast.nc",
        # INI_FILE_FORECAST == RST_OUT_NOWCAST (nos_run.sh:257)
        "INI_FILE_FORECAST": f"{base}.rst.nowcast.nc",
        # Output products
        "HIS_OUT_NOWCAST":   f"{base}.fields.nowcast.nc",
        "HIS_OUT_FORECAST":  f"{base}.fields.forecast.nc",
        "STA_OUT_NOWCAST":   f"{base}.stations.nowcast.nc",
        "STA_OUT_FORECAST":  f"{base}.stations.forecast.nc",
        "HIS_2D_NOWCAST":    f"{base}.surface.nowcast.nc",
        "HIS_2D_FORECAST":   f"{base}.surface.forecast.nc",
        "MODEL_LOG_NOWCAST": f"{base}.nowcast.log",
        "MODEL_LOG_FORECAST": f"{base}.forecast.log",
        # Runtime control
        "RUNTIME_CTL_NOWCAST":                  f"{base}.nowcast.in",
        "RUNTIME_CTL_FORECAST":                 f"{base}.forecast.in",
        "RUNTIME_MET_CTL_NOWCAST":              f"{base}.met_ctl.nowcast.in",
        "RUNTIME_MET_CTL_FORECAST":             f"{base}.met_ctl.forecast.in",
        "RUNTIME_COMBINE_RST_NOWCAST":          f"{base}.combine.hotstart.nowcast.in",
        "RUNTIME_COMBINE_NETCDF_NOWCAST":       f"{base}.combine.netcdf.nowcast.in",
        "RUNTIME_COMBINE_NETCDF_FORECAST":      f"{base}.combine.netcdf.forecast.in",
        "RUNTIME_COMBINE_NETCDF_STA_NOWCAST":   f"{base}.combine.netcdf.sta.nowcast.in",
        "RUNTIME_COMBINE_NETCDF_STA_FORECAST":  f"{base}.combine.netcdf.sta.forecast.in",
    }


def _compute_time_anchors(
    pdy: str,
    cyc: str,
    len_nowcast: int,
    len_forecast: int,
    delt_model: float,
) -> dict:
    """Compute time anchors + step counts.

    The shell does most of this inside :func:`_schism_find_hotstart`
    (lines 330-367), but the non-prep code path only needs the basic
    anchors derived from ``time_nowcastend = PDY||cyc``:

    - ``BASE_DATE``: time_nowcastend - LEN_NOWCAST hours (cold-start anchor)
    - ``time_hotstart``: same as BASE_DATE for the simple case
    - ``time_nowcastend``: PDY || cyc
    - ``time_forecastend``: time_nowcastend + LEN_FORECAST hours
    - ``NSTEP_NOWCAST``: LEN_NOWCAST * 3600 / DELT_MODEL
    - ``NSTEP_FORECAST``: LEN_FORECAST * 3600 / DELT_MODEL

    PR 6 will replace the cold-start ``BASE_DATE`` here with the
    ``_schism_find_hotstart`` walk-back result.
    """
    time_nowcastend = f"{pdy}{cyc}"
    time_hotstart = _dateutils.ndate(-len_nowcast, time_nowcastend)
    time_forecastend = _dateutils.ndate(len_forecast, time_nowcastend)
    base_date = time_hotstart  # cold-start anchor; PR 6 overrides via COM-hunt

    nstep_nowcast = int(len_nowcast * 3600 / delt_model) if delt_model > 0 else 0
    nstep_forecast = int(len_forecast * 3600 / delt_model) if delt_model > 0 else 0

    # DSTART_FORECAST in decimal days from BASE_DATE -- shell does
    # ``echo "scale=4;$DAY0+${NH_NOWCAST}/24.0" | bc`` (nos_run.sh:367).
    # DAY0=0 from the synthetic time_initial.dat (line 347), so
    # DSTART_FORECAST == LEN_NOWCAST/24.
    dstart_nowcast = "0.0"
    dstart_forecast = f"{len_nowcast / 24.0:.4f}"

    return {
        "BASE_DATE":        base_date,
        "time_hotstart":    time_hotstart,
        "time_nowcastend":  time_nowcastend,
        "time_forecastend": time_forecastend,
        "NSTEP_NOWCAST":    str(nstep_nowcast),
        "NSTEP_FORECAST":   str(nstep_forecast),
        "NTIMES_NOWCAST":   str(nstep_nowcast),
        "NTIMES_FORECAST":  str(nstep_forecast),
        "DSTART_NOWCAST":   dstart_nowcast,
        "DSTART_FORECAST":  dstart_forecast,
        "COLD_START":       "F",  # default; PR 6 will set "T" when COM-hunt fails
    }


def compute_paths(
    env: "NCOEnv",
    phase: str,
    runtype: str = "nowcast",
) -> SchismRunContext:
    """Build a :class:`SchismRunContext` for the SCHISM-UFS pipeline.

    Args:
        env: :class:`NCOEnv` with PDY, cyc, COMOUT, FIXofs, DATA, RUN, etc.
        phase: ``"nowcast"`` or ``"forecast"`` -- mirrors the
            ``stage_model_files``/``execute_model`` phase contract.
            Filenames are identical for both phases; ``phase`` only
            affects the :class:`SchismRunContext.phase` field.
        runtype: ``"nowcast"`` | ``"forecast"`` | ``"prep"``. ``"prep"``
            mode invokes :func:`_schism_find_hotstart` -- not yet ported
            (PR 6 wires this).

    Returns:
        Fully-populated :class:`SchismRunContext`.

    Raises:
        NotImplementedError: if ``runtype="prep"`` (PR 6 wires this).
    """
    if runtype == "prep" or runtype == "PREP":
        raise NotImplementedError(
            "_schism_setup_paths in prep mode calls _schism_find_hotstart; "
            "port lands in PR 6"
        )

    # ---- Fix-file staging -----------------------------------------------
    _stage_fix_files(env)

    # ---- Identity fields ------------------------------------------------
    pdy = env.pdy
    cyc = env.cyc  # already zero-padded by NCOEnv
    cycle = env.cycle
    prefix = os.environ.get("PREFIXNOS") or f"nos.{env.ofs}"
    pdy1 = pdy  # time_nowcastend = PDY||cyc -> YYYY-MM-DD == PDY

    # ---- Runtime config (env-driven) ------------------------------------
    len_nowcast = int(os.environ.get("LEN_NOWCAST", "6"))
    len_forecast = int(os.environ.get("LEN_FORECAST", "48"))
    delt_model_str = os.environ.get("DELT_MODEL", "120")
    try:
        delt_model_float = float(delt_model_str)
    except (TypeError, ValueError):
        delt_model_float = 120.0

    # ---- Filename conventions + time anchors ----------------------------
    filenames = _compute_filenames(prefix, cycle, pdy1)
    times = _compute_time_anchors(
        pdy=pdy, cyc=cyc,
        len_nowcast=len_nowcast,
        len_forecast=len_forecast,
        delt_model=delt_model_float,
    )

    # ---- Build the SchismRunContext --------------------------------------
    return SchismRunContext(
        # Required identity fields
        comout=env.comout,
        data=env.data,
        phase=phase,
        run=env.run,
        cycle=cycle,
        # Optional identity / path fields
        pdy=pdy,
        cyc=cyc,
        prefixnos=prefix,
        homenos=env.homenos,
        fixofs=env.fixofs,
        execnos=env.execnos,
        ushnos=env.ushnos,
        comoutroot=env.comoutroot,
        dataroot=env.dataroot,
        # Hotstart filenames (mapped from filenames dict)
        ini_file_nowcast=filenames["INI_FILE_NOWCAST"],
        ini_file_forecast=filenames["INI_FILE_FORECAST"],
        rst_out_nowcast=filenames["RST_OUT_NOWCAST"],
        rst_out_forecast=filenames["RST_OUT_FORECAST"],
        ini_file=None,        # PR 6 will set this (from _schism_find_hotstart)
        rst_file=os.environ.get("RST_FILE") or None,  # shell: RST_FILE=${RST_FILE:-}
        # Time anchors
        base_date=times["BASE_DATE"],
        time_hotstart=times["time_hotstart"],
        time_nowcastend=times["time_nowcastend"],
        time_forecastend=times["time_forecastend"],
        dstart_nowcast=times["DSTART_NOWCAST"],
        dstart_forecast=times["DSTART_FORECAST"],
        nstep_nowcast=times["NSTEP_NOWCAST"],
        nstep_forecast=times["NSTEP_FORECAST"],
        ntimes_nowcast=times["NTIMES_NOWCAST"],
        ntimes_forecast=times["NTIMES_FORECAST"],
        cold_start=times["COLD_START"],
        # Forcing artifact filenames
        # NOTE: nos_run.sh exports BCTIDES_IN (single), not _NOWCAST/_FORECAST
        # split. We populate the split fields with the same value -- downstream
        # consumers will fall back to BCTIDES_IN if either is None.
        bctides_in_nowcast=filenames["BCTIDES_IN"],
        bctides_in_forecast=filenames["BCTIDES_IN"],
        nwm_source_sink_nowcast=filenames["NWM_SOURCE_SINK_NOW"],
        nwm_source_sink_forecast=filenames["NWM_SOURCE_SINK_FORE"],
        # Same: shell exports OBC_FORCING_FILE (single), we split for type safety
        obc_forcing_file_nowcast=filenames["OBC_FORCING_FILE"],
        obc_forcing_file_forecast=filenames["OBC_FORCING_FILE"],
        river_forcing_file=filenames["RIVER_FORCING_FILE"],
        met_netcdf_nowcast=filenames["MET_NETCDF_1_NOWCAST"],
        met_netcdf_forecast=filenames["MET_NETCDF_1_FORECAST"],
        # Misc runtime control + timing
        runtime_ctl=os.environ.get("RUNTIME_CTL") or None,
        sta_out_ctl=os.environ.get("STA_OUT_CTL") or None,
        delt_model=delt_model_str,
        len_nowcast=str(len_nowcast),
        len_forecast=str(len_forecast),
    )


def to_shell_filenames(
    prefix: str,
    cycle: str,
    pdy1: str,
) -> dict:
    """Public wrapper around :func:`_compute_filenames`.

    Useful for tests and for callers that just want the filename dict
    without building a full :class:`SchismRunContext` (e.g., the
    parity-test harness comparing against the shell's exported env).
    """
    return _compute_filenames(prefix, cycle, pdy1)


__all__ = ["compute_paths", "to_shell_filenames"]
