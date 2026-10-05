"""STOFS-2D-GLO prep: mesh staging, forcing, fort.15 and adcprep for one phase.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/stofs_2d_global), adcircmodel.py prep_nowcast / prep_forecast. Tides and
GFS-to-OWI meteorology come from nos-utils; the run directories live under
$COMOUT because the prep and model jobs are separate and share nothing else.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from . import hotstart as hs
from .decomp import CommandRunner, archive_path, default_runner, run_adcprep
from .fort15 import Fort15Spec, write_fort15
from .mesh import read_mesh_info
from .settings import CycleContext, AdcircConfigError

log = logging.getLogger(__name__)


def link_mesh_files(ctx: CycleContext, run_dir: Path) -> None:
    """Link the fix files as fort.14 / fort.13; adcprep only accepts those exact names."""
    s = ctx.settings
    for src_name, dst_name in ((s.grid_file, "fort.14"), (s.attr_file, "fort.13")):
        src = ctx.fixofs / src_name
        if not src.is_file():
            raise AdcircConfigError(f"missing fix file {src} (tools/fetch_stofs_2d_glo_fix.sh)")
        dst = run_dir / dst_name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src.resolve())


def compute_tides(ctx: CycleContext, coldstart: datetime, end: datetime) -> Dict[str, object]:
    from nos_utils.forcing.adcirc_tides import compute_adcirc_tides

    s = ctx.settings
    run_days = (end - coldstart).total_seconds() / 86400.0
    tides = compute_adcirc_tides(
        s.tide_constituents, coldstart, run_days, nodal_reference=s.nodal_reference)
    return {t.name.upper(): t for t in tides}


def acquire_met(ctx: CycleContext, phase: str, start: datetime, end: datetime, run_dir: Path):
    from nos_utils.forcing.adcirc_met import AdcircMetProcessor

    if not ctx.comin_gfs:
        raise AdcircConfigError("COMINgfs is not set; atmospheric_forcing needs the GFS tank")
    proc = AdcircMetProcessor(ctx.comin_gfs, variables=ctx.settings.met_variables or None)
    return proc.process(start, end, run_dir, phase=phase)


def build_fort15(ctx: CycleContext, run_dir: Path, coldstart: datetime, start: datetime,
                 end: datetime, hotstart_unit: int) -> Path:
    s = ctx.settings
    mesh = read_mesh_info(run_dir / "fort.14", ctx.comges / f"{ctx.run}_mesh_info.json")
    spec = Fort15Spec(
        name="gstofs",
        mesh_name=s.mesh_name,
        coldstart_time=coldstart,
        start_time=start,
        end_time=end,
        dt=s.dt,
        physics=s.physics,
        attributes=s.attributes,
        mesh=mesh,
        tides=compute_tides(ctx, coldstart, end),
        tide_constituents=s.tide_constituents,
        hotstart_unit=hotstart_unit,
        nws=14 if s.atmospheric_forcing else 0,
        ice=s.atmospheric_forcing,
        ramp=s.ramp,
        output_minutes=s.output_minutes,
        wind_dt=s.wind_dt,
        projection_center=(tuple(s.physics["projection_center"])
                           if s.physics.get("projection_center") else None),
    )
    out = run_dir / "fort.15"
    write_fort15(spec, out)
    return out


def _finish(ctx: CycleContext, run_dir: Path, runner: CommandRunner) -> str:
    s = ctx.settings
    archive = (archive_path(ctx.comges, ctx.run, s.ncpu_compute)
               if s.decomposition_cache else None)
    return run_adcprep(s.executable("adcprep", ctx.execnos), run_dir, s.ncpu_compute,
                       archive, runner)


def _met(ctx, phase, start, end, run_dir, acquire):
    if ctx.settings.atmospheric_forcing:
        acquire(ctx, phase, start, end, run_dir)
    else:
        log.info("atmospheric_forcing disabled; tide-only %s (NWS=0)", phase)


def prep_nowcast(ctx: CycleContext, runner: CommandRunner = default_runner,
                 acquire: Callable = acquire_met) -> hs.HotstartInfo:
    run_dir = ctx.run_dir("nowcast")
    run_dir.mkdir(parents=True, exist_ok=True)
    link_mesh_files(ctx, run_dir)
    info = hs.resolve_nowcast_hotstart(
        ctx.prev_nowcast_dir, ctx.cycle_time, ctx.nowcast_start,
        ctx.settings.coldstart_spinup_days)
    if info.is_coldstart:
        log.info("cold start: no restart in %s, spin-up from %s",
                 ctx.prev_nowcast_dir, info.coldstart_time.isoformat())
    hs.stage_hotstart(info, run_dir)
    hs.write_timing(run_dir, info.coldstart_time, info.start_time, ctx.cycle_time,
                    info.hotstart_file)
    _met(ctx, "nowcast", info.start_time, ctx.cycle_time, run_dir, acquire)
    build_fort15(ctx, run_dir, info.coldstart_time, info.start_time, ctx.cycle_time, info.unit)
    log.info("nowcast adcprep: %s", _finish(ctx, run_dir, runner))
    return info


def prep_forecast(ctx: CycleContext, runner: CommandRunner = default_runner,
                  acquire: Callable = acquire_met) -> None:
    """Forecast inputs; the nowcast restart is linked by the forecast stage once it exists."""
    nowcast_timing = hs.read_timing(ctx.run_dir("nowcast"))
    if nowcast_timing is None:
        raise RuntimeError("prep_forecast needs the nowcast timing.json; run prep_nowcast first")
    coldstart = datetime.fromisoformat(nowcast_timing["coldstart_time"])
    run_dir = ctx.run_dir("forecast")
    run_dir.mkdir(parents=True, exist_ok=True)
    link_mesh_files(ctx, run_dir)
    hs.write_timing(run_dir, coldstart, ctx.cycle_time, ctx.forecast_end, None)
    _met(ctx, "forecast", ctx.cycle_time, ctx.forecast_end, run_dir, acquire)
    build_fort15(ctx, run_dir, coldstart, ctx.cycle_time, ctx.forecast_end, 67)
    log.info("forecast adcprep: %s", _finish(ctx, run_dir, runner))


def run_prep(ctx: CycleContext, runner: CommandRunner = default_runner,
             acquire: Callable = acquire_met) -> int:
    prep_nowcast(ctx, runner, acquire)
    prep_forecast(ctx, runner, acquire)
    return 0
