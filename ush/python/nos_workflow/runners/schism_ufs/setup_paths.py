"""Build a SchismRunContext: stage fix files, compute filenames, derive anchors."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from . import _dateutils
from .context import SchismRunContext

if TYPE_CHECKING:
    from ...env import NCOEnv

logger = logging.getLogger(__name__)


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
    """Copy required and optional fix files from $FIXofs to $DATA."""
    fixofs = env.fixofs
    data = env.data
    data.mkdir(parents=True, exist_ok=True)
    (data / "outputs").mkdir(parents=True, exist_ok=True)
    (data / "sflux").mkdir(parents=True, exist_ok=True)

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

    # VGRID_FAKE_CTL intentionally overrides VGRID_CTL when both are set.
    vgrid_fake = os.environ.get("VGRID_FAKE_CTL", "")
    vgrid_ctl = os.environ.get("VGRID_CTL", "")
    if vgrid_fake and vgrid_ctl:
        src = fixofs / vgrid_fake
        if src.is_file() and src.stat().st_size > 0:
            shutil.copy2(src, data / vgrid_ctl)

    prefixnos = os.environ.get("PREFIXNOS", "")
    if prefixnos:
        for bare_name in ("nobc_nudge_index.dat", "nudge_point_at_ofs_grid.dat"):
            src = fixofs / f"{prefixnos}.{bare_name}"
            if src.is_file() and src.stat().st_size > 0:
                shutil.copy2(src, data / bare_name)

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
    """Build the per-cycle filename dict (forcing, restart, output products)."""
    base = f"{prefix}.{cycle}.{pdy1}"
    return {
        "OBC_FORCING_FILE":      f"{base}.obc.tar",
        "RIVER_FORCING_FILE":    f"{base}.river.th.tar",
        "NWM_SOURCE_SINK_NOW":   f"{base}.nwm.source.sink.now.tar",
        "NWM_SOURCE_SINK_FORE":  f"{base}.nwm.source.sink.fore.tar",
        "BCTIDES_IN":            f"{base}.bctides.in",
        "OBC_TIDALFORCING_FILE": f"{base}.roms.tides.nc",
        "NUDG_FORCING_FILE":     f"{base}.clim.nc",
        "OBC_FORCING_FILE_EL":   f"{base}.obc.el.tar",
        "OBC_FORCING_FILE_TS":   f"{base}.obc.ts.tar",
        "MET_NETCDF_1_NOWCAST":    f"{base}.met.nowcast.nc.tar",
        "MET_NETCDF_1_FORECAST":   f"{base}.met.forecast.nc.tar",
        "MET_NETCDF_1_NOWCAST_2":  f"{base}.met.nowcast.nc.2.tar",
        "MET_NETCDF_1_FORECAST_2": f"{base}.met.forecast.nc.2.tar",
        "MET_NETCDF_2_NOWCAST":    f"{base}.hflux.nowcast.nc",
        "MET_NETCDF_2_FORECAST":   f"{base}.hflux.forecast.nc",
        "INI_FILE_NOWCAST":  f"{base}.init.nowcast.nc",
        "RST_OUT_NOWCAST":   f"{base}.rst.nowcast.nc",
        "RST_OUT_FORECAST":  f"{base}.rst.forecast.nc",
        # INI_FILE_FORECAST equals RST_OUT_NOWCAST (forecast hotstarts from nowcast).
        "INI_FILE_FORECAST": f"{base}.rst.nowcast.nc",
        "HIS_OUT_NOWCAST":   f"{base}.fields.nowcast.nc",
        "HIS_OUT_FORECAST":  f"{base}.fields.forecast.nc",
        "STA_OUT_NOWCAST":   f"{base}.stations.nowcast.nc",
        "STA_OUT_FORECAST":  f"{base}.stations.forecast.nc",
        "HIS_2D_NOWCAST":    f"{base}.surface.nowcast.nc",
        "HIS_2D_FORECAST":   f"{base}.surface.forecast.nc",
        "MODEL_LOG_NOWCAST": f"{base}.nowcast.log",
        "MODEL_LOG_FORECAST": f"{base}.forecast.log",
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


def _read_comout_time_file(comout: Path, basename: str, cycle: str) -> Optional[str]:
    """Read $COMOUT/<basename>.<cycle> and return its stripped contents."""
    path = comout / f"{basename}.{cycle}"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _read_comout_time_anchors(
    comout: Path,
    cycle: str,
    len_nowcast: int,
    len_forecast: int,
    delt_model: float,
    pdy: str,
    cyc: str,
) -> Optional[dict]:
    """Read time anchors from prep-written $COMOUT/time_*.${cycle} files.

    Returns None if ``time_hotstart.${cycle}`` is absent (caller falls back
    to formula-based computation).
    """
    time_hotstart = _read_comout_time_file(comout, "time_hotstart", cycle)
    if not time_hotstart:
        return None

    time_nowcastend = (
        _read_comout_time_file(comout, "time_nowcastend", cycle)
        or f"{pdy}{cyc}"
    )

    time_forecastend = (
        _read_comout_time_file(comout, "time_forecastend", cycle)
        or _dateutils.ndate(len_forecast, time_nowcastend)
    )

    base_date = (
        _read_comout_time_file(comout, "base_date", cycle)
        or time_hotstart
    )

    nstep_nowcast = int(len_nowcast * 3600 / delt_model) if delt_model > 0 else 0
    nstep_forecast = int(len_forecast * 3600 / delt_model) if delt_model > 0 else 0

    # NH_NOWCAST = time_nowcastend - time_hotstart (hours). When prep wrote
    # a non-standard time_hotstart (warm-start at unusual offset), this can
    # differ from len_nowcast.
    nh_nowcast = _dateutils.nhour(time_nowcastend, time_hotstart)
    dstart_nowcast = "0.0"
    dstart_forecast = f"{nh_nowcast / 24.0:.4f}"

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
        "COLD_START":       "F",
    }


def _compute_time_anchors(
    pdy: str,
    cyc: str,
    len_nowcast: int,
    len_forecast: int,
    delt_model: float,
) -> dict:
    """Fallback time anchors derived from ``time_nowcastend = PDY||cyc``.

    Used when $COMOUT/time_hotstart.${cycle} is absent (dev/test paths).
    """
    time_nowcastend = f"{pdy}{cyc}"
    time_hotstart = _dateutils.ndate(-len_nowcast, time_nowcastend)
    time_forecastend = _dateutils.ndate(len_forecast, time_nowcastend)
    base_date = time_hotstart

    nstep_nowcast = int(len_nowcast * 3600 / delt_model) if delt_model > 0 else 0
    nstep_forecast = int(len_forecast * 3600 / delt_model) if delt_model > 0 else 0

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
        "COLD_START":       "F",
    }


def compute_paths(
    env: "NCOEnv",
    phase: str,
    runtype: str = "nowcast",
) -> SchismRunContext:
    """Build a SchismRunContext for the SCHISM-UFS pipeline.

    ``runtype="prep"`` invokes the COM-hunt walk-back via find_hotstart;
    non-prep runtypes read prep-written time anchors from $COMOUT.
    """
    _stage_fix_files(env)

    pdy = env.pdy
    cyc = env.cyc
    cycle = env.cycle
    prefix = os.environ.get("PREFIXNOS") or f"nos.{env.ofs}"
    pdy1 = pdy

    len_nowcast = int(os.environ.get("LEN_NOWCAST", "6"))
    len_forecast = int(os.environ.get("LEN_FORECAST", "48"))
    delt_model_str = os.environ.get("DELT_MODEL", "120")
    try:
        delt_model_float = float(delt_model_str)
    except (TypeError, ValueError):
        delt_model_float = 120.0

    filenames = _compute_filenames(prefix, cycle, pdy1)

    rst_file_for_ctx: Optional[str]
    ini_file_for_ctx: Optional[str]
    runtype_norm = (runtype or "").lower()
    if runtype_norm == "prep":
        from .hotstart import find_hotstart, write_time_files

        result = find_hotstart(
            env, phase=phase,
            len_nowcast=len_nowcast,
            len_forecast=len_forecast,
            delt_model=delt_model_float,
        )
        write_time_files(result, env.comout, cycle)

        base_date = result.base_date
        time_hotstart = result.time_hotstart
        time_nowcastend = result.time_nowcastend
        time_forecastend = result.time_forecastend
        cold_start = result.cold_start
        # Stored as str to preserve YYYYMMDDHH zero-padding and the
        # shell-compatible decimal precision downstream consumers expect.
        dstart_nowcast = f"{result.dstart_nowcast:.4f}"
        dstart_forecast = f"{result.dstart_forecast:.4f}"
        nstep_nowcast_s = str(result.nstep_nowcast)
        nstep_forecast_s = str(result.nstep_forecast)
        ntimes_nowcast_s = str(result.ntimes_nowcast)
        ntimes_forecast_s = str(result.ntimes_forecast)
        rst_file_for_ctx = str(result.rst_file) if result.rst_file is not None else None
        ini_file_for_ctx = str(result.ini_file) if result.ini_file is not None else None
    else:
        # Prefer prep-written $COMOUT files: warm-start cycles whose prep
        # discovered a restart at a non-standard offset would otherwise be
        # overwritten by the formula and produce a param.nml whose start_*
        # mismatches the staged hotstart.
        times = _read_comout_time_anchors(
            comout=env.comout,
            cycle=cycle,
            len_nowcast=len_nowcast,
            len_forecast=len_forecast,
            delt_model=delt_model_float,
            pdy=pdy,
            cyc=cyc,
        )
        if times is None:
            logger.warning(
                "setup_paths: $COMOUT/time_hotstart.%s not found; "
                "falling back to formula-based time anchors "
                "(only OK for dev/test).",
                cycle,
            )
            times = _compute_time_anchors(
                pdy=pdy, cyc=cyc,
                len_nowcast=len_nowcast,
                len_forecast=len_forecast,
                delt_model=delt_model_float,
            )
        base_date = times["BASE_DATE"]
        time_hotstart = times["time_hotstart"]
        time_nowcastend = times["time_nowcastend"]
        time_forecastend = times["time_forecastend"]
        cold_start = times["COLD_START"]
        dstart_nowcast = times["DSTART_NOWCAST"]
        dstart_forecast = times["DSTART_FORECAST"]
        nstep_nowcast_s = times["NSTEP_NOWCAST"]
        nstep_forecast_s = times["NSTEP_FORECAST"]
        ntimes_nowcast_s = times["NTIMES_NOWCAST"]
        ntimes_forecast_s = times["NTIMES_FORECAST"]
        rst_file_for_ctx = os.environ.get("RST_FILE") or None
        ini_file_for_ctx = None

    return SchismRunContext(
        comout=env.comout,
        data=env.data,
        phase=phase,
        run=env.run,
        cycle=cycle,
        pdy=pdy,
        cyc=cyc,
        prefixnos=prefix,
        homenos=env.homenos,
        fixofs=env.fixofs,
        execnos=env.execnos,
        ushnos=env.ushnos,
        comoutroot=env.comoutroot,
        dataroot=env.dataroot,
        ini_file_nowcast=filenames["INI_FILE_NOWCAST"],
        ini_file_forecast=filenames["INI_FILE_FORECAST"],
        rst_out_nowcast=filenames["RST_OUT_NOWCAST"],
        rst_out_forecast=filenames["RST_OUT_FORECAST"],
        ini_file=ini_file_for_ctx,
        rst_file=rst_file_for_ctx,
        base_date=base_date,
        time_hotstart=time_hotstart,
        time_nowcastend=time_nowcastend,
        time_forecastend=time_forecastend,
        dstart_nowcast=dstart_nowcast,
        dstart_forecast=dstart_forecast,
        nstep_nowcast=nstep_nowcast_s,
        nstep_forecast=nstep_forecast_s,
        ntimes_nowcast=ntimes_nowcast_s,
        ntimes_forecast=ntimes_forecast_s,
        cold_start=cold_start,
        bctides_in_nowcast=filenames["BCTIDES_IN"],
        bctides_in_forecast=filenames["BCTIDES_IN"],
        nwm_source_sink_nowcast=filenames["NWM_SOURCE_SINK_NOW"],
        nwm_source_sink_forecast=filenames["NWM_SOURCE_SINK_FORE"],
        obc_forcing_file_nowcast=filenames["OBC_FORCING_FILE"],
        obc_forcing_file_forecast=filenames["OBC_FORCING_FILE"],
        river_forcing_file=filenames["RIVER_FORCING_FILE"],
        met_netcdf_nowcast=filenames["MET_NETCDF_1_NOWCAST"],
        met_netcdf_forecast=filenames["MET_NETCDF_1_FORECAST"],
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
    """Public wrapper around _compute_filenames for callers and tests."""
    return _compute_filenames(prefix, cycle, pdy1)


__all__ = [
    "compute_paths",
    "to_shell_filenames",
    "_read_comout_time_anchors",
    "_read_comout_time_file",
]
