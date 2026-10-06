"""STOFS-2D-GLO ops-mode POST_NCDIFF and POST_NCRCAT (the same NCO calls as exstofs_2d_glo_post_{ncdiff,ncrcat}.sh),
and POST_ANOMALY, POST_BIAS_CORRECTION, POST_GRIB2 (the unchanged ops ex-scripts run from the stofs.v3.1.5 package). MJ (10/06/26)"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import timedelta
from pathlib import Path
from typing import List, Sequence

from . import decomp
from .decomp import CommandRunner
from .ops import _data, _publish, rerun_dir
from .settings import AdcircConfigError, CycleContext

log = logging.getLogger(__name__)
FORCING_OUT = {"221": "pressfc", "222": "uvgrd10m", "225": "icec"}


def default_runner(cmd: Sequence[str], cwd: Path) -> int:
    if shutil.which(cmd[0]) is None:
        raise AdcircConfigError(f"{cmd[0]} not found on PATH (module load nco)")
    return decomp.default_runner(cmd, cwd)


def _link(src: Path, dst: Path) -> None:
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    dst.symlink_to(src)


def _run(runner: CommandRunner, cmds: Sequence[Sequence[str]], cwd: Path) -> None:
    for cmd in cmds:
        if runner(cmd, cwd) != 0:
            raise RuntimeError("FATAL ERROR: %s failed" % " ".join(cmd))


def _work(ctx: CycleContext) -> Path:
    d = _data(ctx)
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_ncdiff(ctx: CycleContext, runner: CommandRunner = default_runner) -> List[str]:
    now, work = ctx.cycle_time, _work(ctx)
    src = lambda kind, name: ctx.cycle_dir(now, "%s.%s.nc" % (kind, name))  # noqa: E731
    # Ops order: POST_ANOMALY and POST_BIAS_CORRECTION publish the corrected points/fields.cwl.nc over the raw ones
    # before this runs, so swl is corrected cwl minus htp. MJ (10/06/26)
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


def run_ncrcat(ctx: CycleContext, runner: CommandRunner = default_runner) -> List[str]:
    now, work, rr = ctx.cycle_time, _work(ctx), rerun_dir(ctx)
    if not (rr / ("%s_ncst.221.nc" % ctx.run)).is_file():
        raise RuntimeError("FATAL ERROR: GFS surface forcing does not exist")
    for seg in ("ncst", "fcst1", "fcst2"):
        for n in FORCING_OUT:
            _link(rr / ("%s_%s.%s.nc" % (ctx.run, seg, n)), work / ("%s.%s.nc" % (seg, n)))
    _run(runner, [["ncrcat", "ncst.%s.nc" % n, "fcst1.%s.nc" % n, "fcst2.%s.nc" % n, "fort.%s.nc" % n]
                  for n in FORCING_OUT], work)
    for n in FORCING_OUT:
        _publish(work / ("fort.%s.nc" % n), ctx.cycle_dir(now, FORCING_OUT[n] + ".nc"))
    return ["ncrcat"]


OPS_PKG = "/lfs/h1/ops/prod/packages/stofs.v3.1.5"
REGIONS = ("conus.east", "conus.west", "puertori", "alaska", "hawaii", "guam", "northpacific")
# segment: (ex-script, scratch-COMIN alias, package files that must exist, commands the script calls, NCPU/PPN, products it must make) MJ (10/06/26)
OPS_JOBS = {
    "anomaly": ("anomaly", {"points.cwl.nc": "points.cwl.noanomaly.nc"},
                ["exec/{r}/{r}_anomaly"] + ["fix/{r}/{r}_" + f for f in ("station.ctl", "cron.bnt", "ft03.dta", "ft07.dta")]
                + ["ush/{r}/" + f for f in ("archive.py", "etweb_database.py", "etweb_extract.py", "inter.awk", "transpose.awk")],
                ("mpirun", "ncdump", "ncgen", "python"), None, ["points.cwl.nc"]),
    "bias": ("bias_correction", {"fields.cwl.nc": "fields.cwl.noanomaly.nc"},
             ["ush/{r}/bias_correction_mpi_v6_selective.py", "fix/{r}/cloned_stations.csv", "fix/{r}/extracted_stations.txt"],
             ("mpirun", "python"), (256, 32), ["fields.cwl.nc"]),
    "grib2": ("grib2", {},
              ["exec/{r}/{r}_netcdf2shef", "exec/{r}/{r}_netcdf2grib", "fix/{r}/{r}_msl2mllw", "ush/{r}/make_ntc_file.pl"]
              + ["fix/{r}/{r}_%s.mask" % g for g in REGIONS]
              + ["parm/{r}/grib2_{r}_%s_%s" % (g, t) for g in REGIONS for t in ("cwl", "htp", "swl")],
              ("mpiexec", "cfp", "tocgrib2", "perl"), (7, 7), ["%s.f%03d.grib2" % (g, h) for g in REGIONS for h in (0, 180)]),
}
PROD_UTIL = ("postmsg", "err_chk", "prep_step", "startmsg", "cpreq", "cpfs")


def run_ops_script(ctx: CycleContext, runner: CommandRunner = default_runner) -> List[str]:
    """The ops J-job environment around the unchanged ex-script. The scripts call mpirun/mpiexec themselves, with the
    ecf NCPU/PPN, so the machine profile is not used; GRIB2 needs cfp, so Hercules needs a later variant. MJ (10/06/26)"""
    script, alias, need, tools, ranks, products = OPS_JOBS[ctx.segment]
    pkg, r = Path(os.environ.get("STOFS_RUNVER") or OPS_PKG + "/versions/run.ver").parent.parent, ctx.run
    ex = pkg / "scripts" / r / ("exstofs_2d_glo_post_%s.sh" % script)
    missing = [str(f) for f in [ex] + [pkg / n.format(r=r) for n in need] if not f.is_file()]
    missing += [t for t in tools + PROD_UTIL if shutil.which(t) is None]
    if missing:
        raise AdcircConfigError("ops package (STOFS_RUNVER=%s) or tools missing for post %s: %s"
                                % (pkg, ctx.segment, ", ".join(missing)))
    now, cyc = ctx.cycle_time, "t%02dz" % ctx.cycle_time.hour
    work = _work(ctx) / ("ops_" + ctx.segment)
    shutil.rmtree(str(work), ignore_errors=True)
    comin, comout = work / "comin", work / "comout"
    for d in (comin, comout / "wmo"):
        d.mkdir(parents=True)
    day = ctx.cycle_dir(now, "x").parent
    for f in day.glob("%s.%s.*" % (r, cyc)):
        if f.is_file() and not f.name.endswith(".partial"):
            _link(f, comin / f.name)
    for dst, src in alias.items():
        _link(ctx.cycle_dir(now, src), comin / ("%s.%s.%s" % (r, cyc, dst)))
    # Ops restores the tar from the previous day only at cyc=00 (script, via COM) and otherwise finds it in COMIN, where
    # it sits from the previous cycle's COMOUT. A first cycle has no tar and starts an empty database; to seed one, put
    # database.tar.gz into <COMOUTroot>/<run>.<PDYm1>/ (cyc 00) or the current day dir (other cycles). MJ (10/06/26)
    # A once-a-day run (12z) has no earlier cycle today, so it falls back to the previous day's tar. MJ (10/06/26)
    prev = ctx.comoutroot / ("%s.%s" % (r, (now - timedelta(days=1)).strftime("%Y%m%d"))) / "database.tar.gz"
    tar = [t for t in (day / "database.tar.gz", prev) if t.is_file()]
    if ctx.segment == "anomaly" and now.hour != 0 and tar:
        _link(tar[0], comin / "database.tar.gz")
    pdy, dcom = now.strftime("%Y%m%d"), os.environ.get("DCOMROOT", "/lfs/h1/ops/prod/dcom")
    env = {"NET": "stofs", "RUN": r, "PDY": pdy, "PDYm1": (now - timedelta(days=1)).strftime("%Y%m%d"),
           "cyc": "%02d" % now.hour, "cycle": cyc, "DATA": str(work), "COM": str(ctx.comoutroot), "COMIN": str(comin),
           "COMOUT": str(comout), "COMOUTwmo": str(comout / "wmo"), "HOMEstofs": str(pkg),
           "EXECstofs": str(pkg / "exec" / r), "FIXstofs": str(pkg / "fix" / r), "PARMstofs": str(pkg / "parm" / r),
           "USHstofs": str(pkg / "ush" / r), "LIBstofs": str(pkg / "ush" / r),
           "DCOMROOT": dcom, "DCOMIN": "%s/%s/coops_waterlvlobs" % (dcom, pdy),
           "SENDCOM": "YES", "SENDDBN": "NO", "SENDDBN_NTC": "NO", "SENDECF": "NO",
           "job": "%s_post_%s_%02d" % (r, ctx.segment, now.hour), "jobid": "post_%s.%d" % (ctx.segment, os.getpid()),
           "jlogfile": str(work / "jlogfile"), "pgmout": "OUTPUT.%d" % os.getpid(),
           "NDATE": os.environ.get("NDATE") or shutil.which("ndate") or "ndate"}
    if ranks:
        env.update(NCPU=str(ranks[0]), PPN=str(ranks[1]))
    (work / "jlogfile").touch()
    try:
        _run(runner, [["env"] + ["%s=%s" % kv for kv in env.items()] + ["bash", str(ex)]], work)
    finally:
        for n in (env["pgmout"], "errfile"):  # DATA is removed with KEEPDATA=NO, so keep the diagnostics in the job log MJ (10/06/26)
            if (work / n).is_file():
                log.info("%s tail:\n%s", n, "\n".join((work / n).read_text(errors="replace").splitlines()[-20:]))
    absent = ["%s.%s.%s" % (r, cyc, p) for p in products if not (comout / ("%s.%s.%s" % (r, cyc, p))).is_file()]
    if absent:
        raise RuntimeError("FATAL ERROR: post %s made no %s" % (ctx.segment, ", ".join(absent[:3])))
    # SENDDBN=NO also skips the SHEF WMO bulletins ops writes to wmo/ (known difference from ops). MJ (10/06/26)
    for f in sorted(comout.rglob("*")):
        if f.is_file():
            dst = day / f.relative_to(comout)
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(str(f), str(dst))  # a move on the same filesystem; the outputs are about 11 GB per cycle. MJ (10/06/26)
            except OSError:
                _publish(f, dst)
    return [ex.name]


def run_post(ctx: CycleContext, runner: CommandRunner = default_runner) -> List[str]:
    jobs = {"ncdiff": run_ncdiff, "ncrcat": run_ncrcat, **{k: run_ops_script for k in OPS_JOBS}}
    if ctx.segment not in jobs:
        raise AdcircConfigError("ADCIRC_SEGMENT must be one of %s for post, got %r" % (tuple(jobs), ctx.segment))
    return jobs[ctx.segment](ctx, runner)
