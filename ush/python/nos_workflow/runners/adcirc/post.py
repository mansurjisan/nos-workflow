"""STOFS-2D-GLO ops-mode POST_NCDIFF and POST_NCRCAT: the same NCO calls as exstofs_2d_glo_post_{ncdiff,ncrcat}.sh. MJ (10/06/26)"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Sequence

from .ops import _publish, rerun_dir
from .settings import AdcircConfigError, CycleContext

Runner = Callable[[Sequence[str], Path], int]
FORCING = ("221", "222", "225")
FORCING_OUT = {"221": "pressfc", "222": "uvgrd10m", "225": "icec"}


def default_runner(cmd: Sequence[str], cwd: Path) -> int:
    if shutil.which(cmd[0]) is None:
        raise AdcircConfigError(f"{cmd[0]} not found on PATH (module load nco)")
    return subprocess.run(list(cmd), cwd=str(cwd)).returncode


def _link(src: Path, dst: Path) -> None:
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    dst.symlink_to(src)


def _run(runner: Runner, cmds: Sequence[Sequence[str]], cwd: Path) -> None:
    for cmd in cmds:
        if runner(cmd, cwd) != 0:
            raise RuntimeError("FATAL ERROR: %s failed" % " ".join(cmd))


def _work(ctx: CycleContext) -> Path:
    if ctx.data is None:
        raise AdcircConfigError("DATA is not set")
    ctx.data.mkdir(parents=True, exist_ok=True)
    return ctx.data


def run_ncdiff(ctx: CycleContext, runner: Runner = default_runner) -> List[str]:
    now, work = ctx.cycle_time, _work(ctx)
    src = lambda kind, name: ctx.cycle_dir(now, "%s.%s.nc" % (kind, name))  # noqa: E731
    # Ops differences the bias-corrected fields.cwl.nc that POST_BIAS_CORRECTION (not ported) rewrites; until
    # then this subtracts the uncorrected surf cwl published by surf fcst2. MJ (10/06/26)
    if src("points", "cwl").is_file():
        for kind, n in (("points", "61"), ("fields", "63")):
            for m in ("cwl", "htp"):
                _link(src(kind, m), work / ("%s.fort.%s.nc" % (m, n)))
    if not (work / "cwl.fort.63.nc").is_file() and not (work / "htp.fort.63.nc").is_file():
        raise RuntimeError("FATAL ERROR: cwl.fort.63.nc and htp.fort.63.nc files did not existed")
    _run(runner, [["ncdiff", "cwl.fort.61.nc", "htp.fort.61.nc", "swl.fort.61.nc"],
                  ["ncdiff", "-v", "zeta", "cwl.fort.63.nc", "htp.fort.63.nc", "swl.fort.63.nc"],
                  ["ncks", "-A", "-v", "x,y", "cwl.fort.61.nc", "swl.fort.61.nc"],
                  ["ncks", "-A", "-v", "x,y", "cwl.fort.63.nc", "swl.fort.63.nc"]], work)
    _publish(work / "swl.fort.61.nc", src("points", "swl"))
    _publish(work / "swl.fort.63.nc", src("fields", "swl"))
    return ["ncdiff", "ncks"]


def run_ncrcat(ctx: CycleContext, runner: Runner = default_runner) -> List[str]:
    now, work, rr = ctx.cycle_time, _work(ctx), rerun_dir(ctx)
    if not (rr / ("%s_ncst.221.nc" % ctx.run)).is_file():
        raise RuntimeError("FATAL ERROR: GFS surface forcing does not exist")
    for seg in ("ncst", "fcst1", "fcst2"):
        for n in FORCING:
            _link(rr / ("%s_%s.%s.nc" % (ctx.run, seg, n)), work / ("%s.%s.nc" % (seg, n)))
    _run(runner, [["ncrcat", "ncst.%s.nc" % n, "fcst1.%s.nc" % n, "fcst2.%s.nc" % n, "fort.%s.nc" % n]
                  for n in FORCING], work)
    for n in FORCING:
        _publish(work / ("fort.%s.nc" % n), ctx.cycle_dir(now, FORCING_OUT[n] + ".nc"))
    return ["ncrcat"]


def run_post(ctx: CycleContext, runner: Runner = default_runner) -> List[str]:
    jobs = {"ncdiff": run_ncdiff, "ncrcat": run_ncrcat}
    if ctx.segment not in jobs:
        raise AdcircConfigError("ADCIRC_SEGMENT must be one of %s for post, got %r" % (tuple(jobs), ctx.segment))
    return jobs[ctx.segment](ctx, runner)
