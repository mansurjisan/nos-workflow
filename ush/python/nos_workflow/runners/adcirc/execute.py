"""padcirc launch, crash detection and run-directory checks.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/stofs_2d_global), adcircmodel.py _run_adcirc. The launch line comes from
the nos-workflow machine profile (mpiexec -n N -ppn P --cpu-bind core on WCOSS2,
srun on Hercules), starts ``-W`` writers when ncpu_writer > 0, and applies the
operational crash check: a clean return code is not enough when the log says
"ADCIRC stopping" or "Terminating".
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from ...machine.profile import MachineProfile
from . import decomp
from .settings import AdcircConfigError, AdcircSettings, CycleContext

log = logging.getLogger(__name__)

CRASH_PATTERN = re.compile(r"ADCIRC stopping|Terminating")
LOG_FILES = ("adcirc.out", "adcirc.err")
SRUN_CPU_BIND = "--cpu-bind=cores"

Launcher = Callable[[Sequence[str], Path], int]


def padcirc_argv(settings: AdcircSettings, profile: MachineProfile, executable: str,
                 ranks_per_node_by_machine: Optional[dict] = None,
                 writers: Optional[int] = None) -> List[str]:
    """Full launch argv: compute plus writer ranks, packed per the machine profile."""
    if writers is None:
        writers = settings.ncpu_writer
    rpn = profile.ranks_per_node_for(ranks_per_node_by_machine)
    exe_args = ["-W", str(writers)] if writers > 0 else []
    argv = profile.mpi_argv(settings.ncpu_compute + writers, executable, exe_args, ranks_per_node=rpn)
    if profile.mpi.launcher == "srun" and not any(a.startswith("--cpu-bind") for a in argv):
        argv.insert(argv.index(str(executable)), SRUN_CPU_BIND)
    return argv


def run_uses_met(run_dir: Path, default: bool) -> bool:
    """True when the run's fort.15 NWS is non-zero (a cold-start nowcast is tide-only). MJ (10/05/26)"""
    f = Path(run_dir) / "fort.15"
    if f.is_file():
        for line in f.read_text().splitlines():
            if line.rstrip().endswith("! NWS"):
                return int(line.split("!")[0].split()[0]) != 0
    return default


def check_inputs(run_dir: Path, ncpu: int, hotstart: bool, atmospheric: bool) -> None:
    run_dir = Path(run_dir)
    need = ["fort.14", "fort.13", "fort.15"]
    if hotstart:
        need.append("fort.67.nc")
    if atmospheric:
        need += ["fort.22", "fort.221.nc", "fort.222.nc"]
    missing = [n for n in need if not (run_dir / n).exists()]
    if missing:
        raise AdcircConfigError(f"{run_dir}: missing inputs {missing}")
    n = len(decomp.pe_dirs(run_dir))
    if n != ncpu:
        raise AdcircConfigError(f"{run_dir}: {n} PE directories, expected {ncpu}")


def crash_lines(run_dir: Path) -> List[str]:
    hits: List[str] = []
    for name in LOG_FILES:
        p = Path(run_dir) / name
        if p.is_file():
            with open(p, errors="replace") as fh:
                hits += [f"{name}: {ln.rstrip()}" for ln in fh if CRASH_PATTERN.search(ln)]
    return hits


def default_launcher(argv: Sequence[str], cwd: Path) -> int:
    with open(Path(cwd) / LOG_FILES[0], "w") as out, open(Path(cwd) / LOG_FILES[1], "w") as err:
        return subprocess.run(list(argv), cwd=str(cwd), stdout=out, stderr=err,
                              shell=False, check=False).returncode


def run_padcirc(ctx: CycleContext, run_dir: Path, hotstart: bool,
                launcher: Launcher = default_launcher,
                profile: Optional[MachineProfile] = None,
                writers: Optional[int] = None) -> List[str]:
    s = ctx.settings
    check_inputs(run_dir, s.ncpu_compute, hotstart,
                 run_uses_met(run_dir, s.atmospheric_forcing))
    profile = profile or MachineProfile.load(validate=False)
    rpn_map = (s.raw.get("resources") or {}).get("ranks_per_node")
    argv = padcirc_argv(s, profile, s.executable("padcirc", ctx.execnos),
                        rpn_map if isinstance(rpn_map, dict) else None, writers)
    ranks = s.ncpu_compute + (s.ncpu_writer if writers is None else writers)
    # The cards export the allocation size; a launch that cannot fit must stop here, not hang in the launcher. MJ (10/05/26)
    if ranks > int(os.environ.get("ADCIRC_ALLOC_RANKS") or ranks):
        raise AdcircConfigError(f"{ranks} ranks (compute + writers) exceed the {os.environ['ADCIRC_ALLOC_RANKS']}"
                                " allocated; raise the node count at submit time")
    log.info("padcirc: %s (cwd %s)", " ".join(argv), run_dir)
    rc = launcher(argv, Path(run_dir))
    if rc != 0:
        raise RuntimeError(f"ADCIRC execution failed with return code {rc}")
    hits = crash_lines(run_dir)
    if hits:
        raise RuntimeError("ADCIRC crashed (rc=0 but log reports): " + "; ".join(hits[:3]))
    return argv
