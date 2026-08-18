"""Patch the four UFS-Coastal configure files based on cycle anchor values."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Tuple

from . import _dateutils, patches
from .context import SchismRunContext
from .stage_files import _cmeps_restart_names, _is_ufs, _is_wave_enabled

logger = logging.getLogger(__name__)


_DEFAULT_LEN_NOWCAST_HOURS = 6
_DEFAULT_LEN_FORECAST_HOURS = 48

# ww3_shel.nml's DATE%RESTART stride (seconds), written for the forecast
# leg by patch_ww3_shel. NOTE: this value never actually reaches WW3's
# restart-write decision on the UFS-Coastal NUOPC coupled path -- see
# patch_ww3_shel's docstring. Kept as a far-beyond-FHMAX placeholder so
# the staged file stays internally consistent for anyone reading it.
_WAVE_FORECAST_RESTART_SENTINEL_SEC = 999999


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


def _wave_restart_staged(ctx: SchismRunContext) -> bool:
    """True when stage_wave_restarts (stage_files.py) placed all three
    wave-restart artifacts into $DATA for this cycle's nowcast-end stamp.

    patch_ufs_configure consults this (rather than threading a return
    value from stage_wave_restarts through run_python) so both the
    staging step and the start_type decision agree on a single source of
    truth: what actually landed in $DATA.
    """
    if not ctx.med_rst_out_nowcast or not ctx.wav_rst_out_nowcast:
        return False
    if not ctx.time_nowcastend:
        return False
    med = ctx.data / "RESTART" / ctx.med_rst_out_nowcast
    wav = ctx.data / ctx.wav_rst_out_nowcast
    stamp = _dateutils.cmeps_restart_stamp(ctx.time_nowcastend)
    pointer = ctx.data / f"rpointer.cpl.{stamp}"
    return (
        med.is_file() and med.stat().st_size > 0
        and wav.is_file() and wav.stat().st_size > 0
        and pointer.is_file() and pointer.stat().st_size > 0
    )


def _wave_restart_staged_nowcast(ctx: SchismRunContext) -> bool:
    """True when stage_wave_restarts placed all three wave-restart
    artifacts into $DATA for THIS nowcast leg's own start stamp.

    Mirrors _wave_restart_staged's role for the forecast leg, but keyed
    on ctx.time_hotstart (this nowcast's sim_start -- see
    _resolve_phase_anchors) rather than ctx.time_nowcastend: the nowcast
    warm start restores the PREVIOUS cycle's archived restart, always
    re-stamped on the way in to match what CMEPS/WW3 look for at THIS
    leg's init (see stage_files._stage_wave_restarts_nowcast). Off by
    default (forcing.waves.nowcast_warm_start) -- when the switch is off,
    or nothing was found, nothing lands at these paths and this is
    silently False, same as the pre-existing nowcast=startup behavior.
    """
    if not ctx.time_hotstart:
        return False
    stamp = _dateutils.cmeps_restart_stamp(ctx.time_hotstart)
    med_name, wav_name, pointer_name = _cmeps_restart_names(stamp)
    med = ctx.data / "RESTART" / med_name
    wav = ctx.data / wav_name
    pointer = ctx.data / pointer_name
    return (
        med.is_file() and med.stat().st_size > 0
        and wav.is_file() and wav.stat().st_size > 0
        and pointer.is_file() and pointer.stat().st_size > 0
    )


def patch_ufs_configure(ctx: SchismRunContext, phase: str) -> int:
    """Patch $DATA/ufs.configure with stop_n, start_type, orb_iyear[_align].

    Wave systems also get restart_n patched to this leg's own length (see
    below).
    """
    target = ctx.data / "ufs.configure"
    if not target.is_file() or target.stat().st_size == 0:
        logger.warning(
            "patch_ufs_configure: %s missing or empty; skipping", target,
        )
        return 0

    nhours, sim_start = _resolve_phase_anchors(ctx, phase)
    sim_yyyy, _sim_mm, _sim_dd, _sim_hh = _split_yyyymmddhh(sim_start)
    # UFS-Coastal NUOPC always resets the clock via ihot=1 at the start of
    # nowcast, so 'startup' is correct there for every system -- and for
    # every phase of every non-wave system (SCHISM/DATM/MED have nothing
    # to carry across the nowcast/forecast boundary; each leg is its own
    # NUOPC run). A wave system's forecast leg is different: SCHISM still
    # hotstarts (ihot=1) and the NUOPC clock still resets, but WW3 and the
    # CMEPS mediator cycle via their own CMEPS restarts
    # (ufs.cpld.{ww3,cpl}.r.*.nc + rpointer.cpl) written at the end of
    # THIS cycle's nowcast leg -- forecast must 'continue' from that state
    # rather than cold-start the wave spectrum and mediator fields. If
    # stage_wave_restarts (stage_files.py) found nothing to restore (the
    # system's first wave-coupled cycle -- nothing archived yet), fall
    # back to 'startup' rather than pointing CDEPS/WW3 at restart files
    # that were never staged.
    #
    # The nowcast leg is the same story, opt-in (forcing.waves.
    # nowcast_warm_start, off by default): when enabled and
    # stage_wave_restarts's nowcast branch restored the PREVIOUS cycle's
    # archived restart into $DATA, 'continue' picks it up instead of
    # cold-starting WW3 every nowcast. When the switch is off (the
    # default) or nothing landed in $DATA, this is silently 'startup' --
    # exactly today's behavior; stage_wave_restarts already logs loudly
    # on its own cold-start/partial-archive paths, so no warning is
    # duplicated here.
    if _is_wave_enabled() and phase == "forecast":
        if _wave_restart_staged(ctx):
            start_type = "continue"
        else:
            logger.warning(
                "patch_ufs_configure: no wave restart staged in %s; "
                "falling back to start_type=startup (cold start) for "
                "WW3 and the CMEPS mediator on this forecast leg.",
                ctx.data,
            )
            start_type = "startup"
    elif _is_wave_enabled() and phase == "nowcast":
        start_type = "continue" if _wave_restart_staged_nowcast(ctx) else "startup"
    else:
        start_type = "startup"

    replacements = {
        "stop_n": nhours,
        "start_type": start_type,
        "orb_iyear": sim_yyyy,
        "orb_iyear_align": sim_yyyy,
    }
    if _is_wave_enabled():
        # restart_n (ALLCOMP_attributes) drives BOTH the CMEPS mediator's
        # own restart cadence and WW3's -- WAV inherits the same NUOPC
        # restart_option/restart_n driver attributes (ModelSetRunClock in
        # wav_comp_nuopc.F90); ww3_shel.nml's restart stride does NOT
        # drive it (see patch_ww3_shel). The fix file hardcodes
        # restart_n=6, which is correct for the 6h nowcast leg but wrong
        # for the 48h forecast leg (writes every 6h -> 8 multi-GB restarts
        # across one forecast instead of the one at leg end that
        # start_type=continue actually needs next cycle). Setting it to
        # this leg's own nhours makes restart_option=nhours land exactly
        # once, at the end of the leg, for both phases.
        replacements["restart_n"] = nhours

    n = patches.patch_ufs_configure(target, replacements)
    logger.info(
        "  Patched ufs.configure: stop_n=%d, start_type=%s, orb_iyear=%s, "
        "restart_n=%s",
        nhours, start_type, sim_yyyy, replacements.get("restart_n", "n/a"),
    )
    return n


def patch_ww3_shel(ctx: SchismRunContext, phase: str) -> int:
    """Patch $DATA/ww3_shel.nml with phase-appropriate start/stop and restart cadence.

    Wave systems only -- a no-op (rc=0) when ww3_shel.nml wasn't staged
    (non-wave systems never have one; stage_wave_configs is itself gated
    on the same wave-enabled predicate this reuses ``_resolve_phase_anchors``
    from).

    NOTE -- this patching is a NO-OP on the UFS-Coastal coupled run path:
    ``waveinit_ufs`` (wav_comp_nuopc.F90) always calls WW3's namelist
    reader with ``time0_overwrite``/``timen_overwrite`` set from the ESMF
    driver clock, and ``read_shel_config`` (wav_shel_inp.F90) then
    overwrites every output type's start/stop -- including
    ``domain%start``/``domain%stop`` and ``date%restart%start/stop`` --
    with those values, so whatever this function writes for start/stop is
    discarded at run time. Likewise, with ``use_restartnc=true`` WW3's
    actual restart WRITE is driven by an ESMF alarm built from
    ufs.configure's ``restart_n``/``restart_option`` (ModelSetRunClock in
    wav_comp_nuopc.F90; see patch_ufs_configure), not by
    ``date%restart%stride`` here. This function is retained anyway so the
    staged ww3_shel.nml is internally consistent (a human or an
    ``ww3_shel`` standalone/offline run reading it sees a coherent
    start/stop/stride, not template placeholders) and in case a future,
    non-NUOPC invocation path ever reads it for real. ``date%{field,
    point}%stride`` (the actual output cadences) ARE live -- those are
    read directly from the namelist and not touched here.
    """
    target = ctx.data / "ww3_shel.nml"
    if not target.is_file() or target.stat().st_size == 0:
        logger.info(
            "patch_ww3_shel: %s missing or empty; skipping", target,
        )
        return 0

    nhours, sim_start = _resolve_phase_anchors(ctx, phase)
    stop = _dateutils.ndate(nhours, sim_start)

    y0, m0, d0, h0 = _split_yyyymmddhh(sim_start)
    y1, m1, d1, h1 = _split_yyyymmddhh(stop)
    cycle_start = f"{y0}{m0}{d0} {h0}0000"
    cycle_stop = f"{y1}{m1}{d1} {h1}0000"

    if phase == "nowcast":
        restart_stride = nhours * 3600
    else:
        restart_stride = _WAVE_FORECAST_RESTART_SENTINEL_SEC

    n = patches.substitute_placeholders(
        target,
        {
            "@[WW3_CYCLE_START]": cycle_start,
            "@[WW3_CYCLE_STOP]": cycle_stop,
            "@[WW3_RESTART_STRIDE_SEC]": str(restart_stride),
        },
    )
    logger.info(
        "  Patched ww3_shel.nml: start=%s, stop=%s, restart_stride=%ss",
        cycle_start, cycle_stop, restart_stride,
    )
    return n


__all__ = [
    "patch_param_nml",
    "patch_datm_in",
    "patch_model_configure",
    "patch_ufs_configure",
    "patch_ww3_shel",
    "_resolve_phase_anchors",
    "_split_yyyymmddhh",
    "_read_datm_forcing_dims",
]
