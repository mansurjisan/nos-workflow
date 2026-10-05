"""STOFS-2D-GLO nowcast and forecast: restart handoff, launch, archive.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/stofs_2d_global): the nowcast runs where prep staged it, the forecast
takes the restart the nowcast just wrote, and each finished run directory is
validated and summarised in COMOUT.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import List

from . import hotstart as hs
from .decomp import pe_dirs
from .execute import Launcher, default_launcher, run_padcirc
from .settings import CycleContext

log = logging.getLogger(__name__)

OUTPUTS = ("fort.61.nc", "fort.62.nc", "fort.63.nc", "fort.64.nc", "fort.67.nc", "fort.68.nc",
           "maxele.63.nc", "maxvel.63.nc", "maxwvel.63.nc", "fort.15", "timing.json",
           "adcirc.out", "adcirc.err")


def prepare_forecast_restart(ctx: CycleContext) -> Path:
    """Copy the nowcast restart into the forecast run directory as fort.67.nc."""
    nowcast_dir, run_dir = ctx.run_dir("nowcast"), ctx.run_dir("forecast")
    restart, coldstart = hs.forecast_restart(nowcast_dir)
    shutil.copy2(restart, run_dir / "fort.67.nc")
    timing = hs.read_timing(run_dir) or {}
    hs.write_timing(run_dir, coldstart, ctx.cycle_time, ctx.forecast_end, str(restart))
    log.info("forecast hotstart from %s (was %s)", restart, timing.get("hotstart_file"))
    return restart


def archive(ctx: CycleContext, phase: str, keep_decomposition: bool = False) -> dict:
    """Validate the restart written by this run, list outputs, drop the PE directories."""
    run_dir = ctx.run_dir(phase)
    if phase == "nowcast" and hs.select_restart_file(run_dir) is None:
        raise RuntimeError(f"{run_dir}: nowcast finished without a valid fort.67/68.nc restart")
    outputs = {n: (run_dir / n).stat().st_size for n in OUTPUTS if (run_dir / n).is_file()}
    summary = {"run": ctx.run, "phase": phase, "cycle": ctx.cycle_time.strftime("%Y%m%d%H"),
               "outputs": outputs}
    (run_dir / f"{ctx.run}.t{ctx.cycle_time.hour:02d}z.{phase}.done.json").write_text(
        json.dumps(summary, indent=2) + "\n")
    if not keep_decomposition:
        for pe in pe_dirs(run_dir):
            shutil.rmtree(pe, ignore_errors=True)
    return summary


def run_nowcast(ctx: CycleContext, launcher: Launcher = default_launcher, profile=None) -> List[str]:
    run_dir = ctx.run_dir("nowcast")
    timing = hs.read_timing(run_dir)
    if timing is None:
        raise RuntimeError(f"{run_dir}: no timing.json; run prep first")
    argv = run_padcirc(ctx, run_dir, bool(timing["hotstart_file"]), launcher, profile)
    archive(ctx, "nowcast")
    return argv


def run_forecast(ctx: CycleContext, launcher: Launcher = default_launcher, profile=None) -> List[str]:
    prepare_forecast_restart(ctx)
    argv = run_padcirc(ctx, ctx.run_dir("forecast"), True, launcher, profile)
    archive(ctx, "forecast")
    return argv
