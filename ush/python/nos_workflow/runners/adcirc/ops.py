"""STOFS-2D-GLO ops mode (ADCIRC_MODE=ops): the stofs.v3.1.5 run structure, one call per ops job.

Tide (NWS=0, chain file .hotstart) and surf (NWS=14014, chain file .restart) streams, each run as
ncst and one 180 h fcst (the ops fcst1 + fcst2 merged: hourly forcing, WTIMINC 3600); cold_adcprep (nod_equi + decomposition) runs in prep with
ADCIRC_SEGMENT=adcprep and cold_spinup in the nowcast stage with ADCIRC_SEGMENT=spinup. The arithmetic, file names and sed
chain follow exstofs_2d_glo_*.sh and stofs_2d_glo_multistart.sh. The surf segments read
$COMOUT/<cyc>/rerun/<RUN>_{ncst,fcst}.{221,222,225}.nc, which prep makes with ADCIRC_SEGMENT=ncst|fcst. MJ (10/11/26)
A job runs one step per ADCIRC_SEGMENT / ADCIRC_STREAM value (space separated lists, see stages/_adcirc.py); the functions here run one. MJ (10/14/26)
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Dict, List, NamedTuple, Tuple

from . import execute, hotstart
from .decomp import CommandRunner, archive_path, default_runner, pe_dirs, run_adcprep
from .prep import link_mesh_files
from .settings import AdcircConfigError, CycleContext

log = logging.getLogger(__name__)

SPINH, WNDH, NOWH, LSTH, NBACK = 162, 3, 6, 180, 20
# Substitution order of the ops sed chain; a token absent from the values is skipped, as in the scripts. MJ (10/05/26)
TOKEN_ORDER = (["cycle", "ihot", "winc", "rnday"]
               + ["%s%d" % (k, i) for i in range(1, 9) for k in ("fft", "facet")]
               + ["nout", "touts", "toutf", "nhstar", "nhsinc", "hh", "dd", "mm", "yyyy"])
CONSTITUENTS = ("K1", "O1", "P1", "Q1", "M2", "S2", "N2", "K2")  # the order the fort.15 templates expect MJ (10/05/26)
STREAMS = {"tide": ("hotstart", "hottime", "stofs_2d_glo_tide.15"),
           "surf": ("restart", "retime", "stofs_2d_glo_surf.15")}
FIX = (("stofs_2d_glo_body", "fort.24"), ("stofs_2d_glo_rotm", "fort.rotm"),
       ("stofs_2d_glo_elev_stat", "elev_stat.151"), ("stofs_2d_glo_elev_stat", "vel_stat.151"))  # ops has no separate velocity station file MJ (10/05/26)
RERUN = {"tide": [("fort.61.nc", "tide.61.nc"), ("fort.63.nc", "tide.63.nc")],
         "surf": [("fort.%d.nc" % n, "surf.%d.nc" % n) for n in (61, 62, 63, 64)]
         + [("%s.63.nc" % m, "%s.63.nc" % m) for m in ("maxele", "maxvel", "maxwvel")]}
SEGMENTS = {"prep": ("adcprep", "ncst", "fcst"), "nowcast": ("spinup", "ncst"), "forecast": ("fcst",),
            "post": ("anomaly", "bias", "ncdiff", "grib2", "ncrcat")}  # what each job takes, in the order a list must give them MJ (10/14/26)
PER_STREAM = {"nowcast": ("ncst",), "forecast": ("fcst",)}  # run once per stream; spinup is tide-only, so once MJ (10/14/26)
RETIRED = ("fcst1", "fcst2")
COLD_HINT = "run a cold start (launcher COLDSTART=YES on WCOSS2 or COLD=1 on Hercules, i.e. the adcprep and spinup segments)"  # MJ (10/14/26)
PRODUCTS = {"tide": [("fort.61.nc", "points.htp.nc"), ("fort.63.nc", "fields.htp.nc")],
            "surf": [("fort.61.nc", "points.cwl.nc"), ("fort.61.nc", "points.cwl.noanomaly.nc"),
                     ("fort.62.nc", "points.cwl.vel.nc"), ("fort.63.nc", "fields.cwl.nc"),
                     ("fort.63.nc", "fields.cwl.noanomaly.nc"), ("fort.64.nc", "fields.cwl.vel.nc"),
                     ("maxele.63.nc", "fields.cwl.maxele.nc"), ("maxele.63.nc", "fields.cwl.maxele.noanomaly.nc"),
                     ("maxvel.63.nc", "fields.cwl.maxvel.nc"), ("maxwvel.63.nc", "fields.cwl.maxwvel.nc")]}


def bc_div(num, den) -> Decimal:
    return (Decimal(num) / Decimal(den)).quantize(Decimal("0.00001"), rounding=ROUND_DOWN)  # bc scale=5 truncates MJ (10/05/26)


def bc_str(x: Decimal) -> str:
    """How bc prints a scale-5 value: no leading zero below one, bare 0 for zero. MJ (10/05/26)"""
    s = "%.5f" % x
    return "0" if x == 0 else s.replace("0.", ".", 1) if s.startswith(("0.", "-0.")) else s


def parity_ihot(time_s, divisor_h: int) -> int:
    return 368 if int(Decimal(time_s) / Decimal(divisor_h * 3600)) % 2 == 0 else 367


class Segment(NamedTuple):
    tokens: Dict[str, str]
    state_time: str


def spinup_tokens() -> Dict[str, str]:
    rnday = bc_str(bc_div(SPINH, 24))
    return {"ihot": "0", "rnday": rnday, "nout": "-3", "touts": "0.00000", "toutf": rnday,
            "nhstar": "3", "nhsinc": "1800"}


def ncst_segment(stream: str, time_hotstart, ncsth: int) -> Segment:
    ihot = parity_ihot(time_hotstart, WNDH)
    ncstd = bc_div(Decimal(time_hotstart) + Decimal(ncsth) * 3600, 86400)
    rnday = ncstd + bc_div(LSTH, 24)
    tok = {"ihot": str(ihot), "rnday": bc_str(ncstd), "nout": "-3",
           "touts": bc_str(rnday - bc_div(NOWH + LSTH, 24)), "toutf": bc_str(rnday),
           "nhstar": "3", "nhsinc": "1800"}
    if stream == "surf":
        tok["winc"] = "3600"
    return Segment(tok, "%.0f" % (ncstd * 86400))


def fcst_segment(stream: str, time_hotstart, touts: str, toutf: str) -> Segment:
    ihot = parity_ihot(time_hotstart, NOWH)
    rnday = bc_div(time_hotstart, 86400) + bc_div(LSTH, 24)  # ops fcst1 has lsth/36; one run for both gives lsth/24. MJ (10/11/26)
    tok = {"ihot": str(ihot), "rnday": bc_str(rnday), "nout": "3", "touts": touts, "toutf": toutf,
           "nhstar": "3", "nhsinc": "3600"}
    if stream == "surf":
        tok["winc"] = "3600"
    return Segment(tok, "%.0f" % (rnday * 86400))


def read_nod_equi(path: Path) -> Tuple[datetime, Dict[str, str]]:
    lines = Path(path).read_text().splitlines()
    hh, dd, mm, yyyy = (int(t) for t in lines[0].split()[:4])
    rows = [ln.split() for ln in lines[1:1 + len(CONSTITUENTS)]]
    if tuple(r[0] for r in rows) != CONSTITUENTS:
        raise AdcircConfigError(f"{path}: constituents must be {CONSTITUENTS}, the fort.15 templates depend on the order")
    tok = {"hh": "%02d" % hh, "dd": "%02d" % dd, "mm": "%02d" % mm, "yyyy": str(yyyy)}
    for i, (_n, fft, facet) in enumerate(rows, start=1):
        tok["fft%d" % i], tok["facet%d" % i] = fft, facet
    return datetime(yyyy, mm, dd, hh), tok


def render(template: str, nod_tokens: Dict[str, str], tokens: Dict[str, str], cycle: str) -> str:
    vals = dict(tokens, cycle=cycle, **nod_tokens)
    text = template
    for tok in TOKEN_ORDER:
        if tok in vals:
            text = text.replace(tok, vals[tok])
    return "".join(ln for ln in text.splitlines(True) if "DUMMY" not in ln)


def rerun_dir(ctx: CycleContext) -> Path:
    return ctx.comout / f"{ctx.cycle_time.hour:02d}" / "rerun"


def _nod_path(ctx: CycleContext) -> Path:
    return ctx.comges / f"{ctx.run}_nod_equi"


def _load_nod(ctx: CycleContext) -> Tuple[datetime, Dict[str, str]]:
    if not _nod_path(ctx).is_file():
        raise AdcircConfigError(f"FATAL ERROR: no {_nod_path(ctx)}; there are no tidal spin-up files, "
                                + COLD_HINT)
    return read_nod_equi(_nod_path(ctx))


def _time(f: Path) -> float:
    t = hotstart.file_time(f)
    if t is None:
        raise AdcircConfigError(f"FATAL ERROR: no usable time in chain file {f}")
    return t


def _publish(src: Path, dst: Path) -> None:
    """Copy through a .partial name so the multistart search never sees a half-written chain file. MJ (10/05/26)"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".partial")
    shutil.copyfile(str(src), str(tmp))
    os.replace(str(tmp), str(dst))


def _stage(ctx: CycleContext, stream: str, segment: str, tokens: Dict[str, str], cycle: str,
           nod: Dict[str, str], runner: CommandRunner, hot: Path = None, ihot: int = 0, copies=()) -> Path:
    """Stage one segment in $DATA (not COMOUT: four run dirs a cycle are ~150 GB) and decompose it. MJ (10/11/26)"""
    s = ctx.settings
    run_dir = _data(ctx) / f"{stream}_{segment}"
    shutil.rmtree(str(run_dir), ignore_errors=True)
    run_dir.mkdir(parents=True)
    link_mesh_files(ctx, run_dir, FIX + ((("stofs_2d_glo_met", "fort.22"),) if stream == "surf" else ()))
    if stream == "surf":
        for n in ("221", "222", "225"):
            src = rerun_dir(ctx) / f"{ctx.run}_{segment}.{n}.nc"
            if not src.is_file():
                raise AdcircConfigError(f"FATAL ERROR: GFS surface forcing does not exist: {src}")
            (run_dir / f"fort.{n}.nc").symlink_to(src)
    if ihot:
        shutil.copy2(str(hot), str(run_dir / f"fort.{ihot - 300}.nc"))  # copy: ADCIRC rewrites it MJ (10/05/26)
    for src, dst in copies:
        shutil.copy2(str(src), str(run_dir / dst))
    template = ctx.fixofs / STREAMS[stream][2]
    if not template.is_file():
        raise AdcircConfigError(f"missing fort.15 template {template} (tools/fetch_stofs_2d_glo_fix.sh)")
    (run_dir / "fort.15").write_text(render(template.read_text(), nod, tokens, cycle))
    run_adcprep(s.executable("adcprep", ctx.execnos), run_dir, s.ncpu_compute,
                archive_path(ctx.comges, ctx.run, s.ncpu_compute), runner)
    if not (run_dir / "PE0000" / "fort.24").is_file():
        raise AdcircConfigError(f"FATAL ERROR: {archive_path(ctx.comges, ctx.run, s.ncpu_compute)} is a single-mode "
                                "decomposition (no fort.24); delete it and its .json to rebuild, or " + COLD_HINT)
    return run_dir


def _launch(ctx: CycleContext, run_dir: Path, stream: str, segment: str, launcher, profile) -> List[str]:
    writers = int(ctx.settings.raw["adcirc"].get("ops_surf_writers", 0)) \
        if stream == "surf" and segment in ("ncst", "fcst") else 0
    argv = execute.run_padcirc(ctx, run_dir, False, launcher, profile, writers)
    for pe in pe_dirs(run_dir):
        shutil.rmtree(str(pe), ignore_errors=True)
    return argv


def _data(ctx: CycleContext) -> Path:
    if ctx.data is None:
        raise AdcircConfigError("DATA is not set")
    return ctx.data


def _need(run_dir: Path, name: str) -> Path:
    f = run_dir / name
    if not f.is_file():
        raise RuntimeError(f"ADCIRC finished without {name} in {run_dir}")
    return f


def check_tide_fac(ctx: CycleContext) -> Path:
    """Ops tide factors come from the Fortran stofs_2d_glo_tide_fac only: a float32/float64 difference would
    freeze different FFT/FACET into every segment for 365 days, so there is no Python fallback. MJ (10/05/26)"""
    exe = ctx.execnos / f"{ctx.run}_tide_fac" if ctx.execnos else None
    if exe is None or not os.access(str(exe), os.X_OK):
        raise AdcircConfigError(
            f"FATAL: {ctx.run}_tide_fac not found in EXECnos ({ctx.execnos}); WCOSS2: copy it from "
            "/lfs/h1/ops/prod/packages/stofs.v3.1.5/exec/stofs_2d_glo/, elsewhere build sorc/stofs_2d_glo_tide_fac.fd")
    return exe


def make_nod_equi(ctx: CycleContext, start: datetime, out: Path) -> None:
    exe = check_tide_fac(ctx)
    subprocess.run([str(exe), "--length", "365", "--year", str(start.year), "--month", "%02d" % start.month,
                    "--day", "%02d" % start.day, "--hour", "%02d" % start.hour, "--outputformat", "simple",
                    "--outputdir", str(out.parent), "--outputname", out.name], check=True, stdout=subprocess.DEVNULL)


def cold_adcprep(ctx: CycleContext, runner: CommandRunner = default_runner) -> None:
    check_tide_fac(ctx)
    ctx.comges.mkdir(parents=True, exist_ok=True)
    for p in (_nod_path(ctx), archive_path(ctx.comges, ctx.run, ctx.settings.ncpu_compute)):
        if p.exists():
            os.replace(str(p), str(p) + ".old")
    spi = ctx.cycle_time - timedelta(hours=NOWH + SPINH)
    _data(ctx).mkdir(parents=True, exist_ok=True)
    make_nod_equi(ctx, spi, _data(ctx) / _nod_path(ctx).name)
    shutil.copyfile(str(_data(ctx) / _nod_path(ctx).name), str(_nod_path(ctx)))
    _stage(ctx, "tide", "adcprep", spinup_tokens(), spi.strftime("%Y%m%d%H"), _load_nod(ctx)[1], runner)


def cold_spinup(ctx: CycleContext, launcher, profile, runner: CommandRunner) -> List[str]:
    beg = ctx.cycle_time - timedelta(hours=NOWH)
    base, nod = _load_nod(ctx)
    if base != beg - timedelta(hours=SPINH):
        raise AdcircConfigError(f"nod_equi starts {base} but this cycle's spin-up starts "
                                f"{beg - timedelta(hours=SPINH)}; run the adcprep segment for this cycle first (COLDSTART=YES / COLD=1)")
    run_dir = _stage(ctx, "tide", "spinup", spinup_tokens(), ctx.cycle_time.strftime("%Y%m%d%H"), nod, runner)
    argv = _launch(ctx, run_dir, "tide", "spinup", launcher, profile)
    ihot = parity_ihot(bc_div(SPINH, 24) * 86400, WNDH)
    f = _need(run_dir, f"fort.{ihot - 300}.nc")
    for kind in ("hotstart", "restart"):
        _publish(f, ctx.cycle_dir(beg, kind))
    return argv


def find_chain_start(ctx: CycleContext, kind: str) -> Tuple[datetime, Path]:
    t = ctx.cycle_time
    for _ in range(NBACK + 1):
        t = t - timedelta(hours=NOWH)
        if ctx.cycle_dir(t, kind).is_file():
            return t, ctx.cycle_dir(t, kind)
    raise AdcircConfigError(f"FATAL ERROR: there are no {kind} files, " + COLD_HINT)


def check_retired(segment: str) -> None:
    if segment in RETIRED:
        raise AdcircConfigError(f"ADCIRC_SEGMENT={segment} is retired: the forecast is one 180 h run, use ADCIRC_SEGMENT=fcst")


def _check(ctx: CycleContext, segments: Tuple[str, ...]) -> None:
    check_retired(ctx.segment)
    if ctx.stream not in STREAMS:
        raise AdcircConfigError(f"ADCIRC_STREAM must be one of {tuple(STREAMS)}, got {ctx.stream!r}")
    if ctx.segment not in segments:
        raise AdcircConfigError(f"ADCIRC_SEGMENT must be one of {segments} here, got {ctx.segment!r}")


def _export(ctx: CycleContext, run_dir: Path) -> None:
    for src, name in RERUN[ctx.stream]:
        _publish(_need(run_dir, src), rerun_dir(ctx) / f"{ctx.run}_{name}")


def _fort15_outputs(fort15: Path) -> Tuple[float, float, Dict[str, Tuple[float, float, int]]]:
    """DTDP, RNDY and per output unit (TOUTS s, TOUTF s, NSPOOL) read from the rendered fort.15, so the expected
    window is the one the run was configured with. MJ (10/15/26)"""
    import re
    dtdp = rnday = None
    units: Dict[str, Tuple[float, float, int]] = {}
    for ln in fort15.read_text().splitlines():
        if "!" not in ln:
            continue
        head, tag = ln.split("!", 1)
        f, m = head.split(), re.search(r"\(UNIT\s+(\d+)\)", tag)
        if tag.split()[:1] == ["DTDP"]:
            dtdp = float(f[0])
        elif tag.split()[:1] == ["RNDY"]:
            rnday = float(f[0])
        elif m and len(f) >= 4 and int(f[0]) != 0:
            units[m.group(1)] = (float(f[1]) * 86400, float(f[2]) * 86400, int(f[3]))
    if dtdp is None or rnday is None:
        raise AdcircConfigError(f"no DTDP or RNDY in {fort15}")
    return dtdp, rnday, units


def check_records(run_dir: Path, stream: str, step: str) -> None:
    """Fail a finished ncst/fcst whose time series lost an hourly record (a sporadic padcirc writer drop that otherwise
    surfaces only in post). Per fort.61-64 that exists: constant spacing of NSPOOL*DTDP, the first record at TOUTS or one
    interval after it, the last at min(TOUTF, RNDAY) (ADCIRC end of run); the expected count follows from that window and
    the first record found. Only the time variable is read. MJ (10/15/26)"""
    import numpy as np
    import netCDF4
    dtdp, rnday, units = _fort15_outputs(run_dir / "fort.15")
    redo = 'STAGES="nowcast forecast post"' if step == "ncst" else 'STAGES="forecast post"'
    for src, _name in RERUN[stream]:
        unit = src[len("fort."):-3]
        f = run_dir / src
        if not (src.startswith("fort.6") and f.is_file() and unit in units):
            continue
        touts, toutf, nspool = units[unit]
        step_s, end = nspool * dtdp, min(toutf, rnday * 86400)
        with netCDF4.Dataset(str(f)) as d:
            t = np.asarray(d.variables["time"][:], dtype="f8")
        if not t.size:
            raise RuntimeError(f"{src} ({stream} {step}) has no records; padcirc dropped an output record; "
                               f"re-run this step ({redo} STREAMS={stream})")
        first = t[0]
        if abs(first - touts) > 1.5:
            first = touts + step_s
        want = int(round((end - first) / step_s)) + 1
        bad = np.flatnonzero(np.abs(np.diff(t) - step_s) > 1.5)
        if t.size != want or bad.size or abs(t[-1] - end) > 1.5 or abs(t[0] - first) > 1.5:
            gaps = ", ".join("%.0f->%.0f s" % (t[i], t[i + 1]) for i in bad) or "none inside the series"
            raise RuntimeError(
                f"{src} ({stream} {step}) has {t.size} records, expected {want} (every {step_s:g} s, first {first:g} s, "
                f"last {end:g} s; found {t[0]:g} .. {t[-1]:g} s); gap times: {gaps}; padcirc dropped an output record; "
                f"re-run this step ({redo} STREAMS={stream})")


def _check_window(path: Path, want: int) -> None:
    import netCDF4
    if not path.is_file():
        return  # _stage names the missing file MJ (10/06/26)
    with netCDF4.Dataset(str(path)) as d:
        have = len(d.dimensions["record"])
    if have != want:
        raise AdcircConfigError(f"{path.name} has {have} records but the restart chain start needs {want}: the forcing window "
                                f"does not match it; delete rerun/{path.name[:-6]}22?.nc and re-run the GFS ncst prep")  # MJ (10/06/26)


def _ncst(ctx: CycleContext, launcher, profile, runner) -> List[str]:
    stream, now = ctx.stream, ctx.cycle_time
    chain, state = STREAMS[stream][:2]
    _base, nod = _load_nod(ctx)
    beg, hfile = find_chain_start(ctx, chain)
    seg = ncst_segment(stream, "%.15g" % _time(hfile), int((now - beg).total_seconds() // 3600))
    if stream == "surf":
        _check_window(rerun_dir(ctx) / f"{ctx.run}_ncst.221.nc", int((now - beg).total_seconds() // 3600) + 1)
    run_dir = _stage(ctx, stream, "ncst", seg.tokens, now.strftime("%Y%m%d%H"), nod, runner, hfile, int(seg.tokens["ihot"]))
    argv = _launch(ctx, run_dir, stream, "ncst", launcher, profile)
    check_records(run_dir, stream, "ncst")  # before anything is published or the state is written MJ (10/15/26)
    _publish(_need(run_dir, f"fort.{parity_ihot(seg.state_time, WNDH) - 300}.nc"), ctx.cycle_dir(now, chain))
    _export(ctx, run_dir)
    # Written last, after success; the leading 0 keeps the ops hottime.out/retime.out layout. MJ (10/05/26)
    (rerun_dir(ctx) / f"{ctx.run}_{state}.out").write_text(
        "0 %s %s %s\n" % (seg.state_time, seg.tokens["touts"], seg.tokens["toutf"]))
    return argv


def _fcst(ctx: CycleContext, launcher, profile, runner) -> List[str]:
    stream, segment, now, rr = ctx.stream, ctx.segment, ctx.cycle_time, rerun_dir(ctx)
    chain, state = STREAMS[stream][:2]
    _base, nod = _load_nod(ctx)
    sp = rr / f"{ctx.run}_{state}.out"
    st = sp.read_text().split() if sp.is_file() else []
    if len(st) < 4:
        raise AdcircConfigError(f"missing or empty {sp}; run the {stream} nowcast first")
    seg = fcst_segment(stream, st[1], st[2], st[3])
    hot = ctx.cycle_dir(now, chain)
    if abs(_time(hot) - float(st[1])) > 1:
        raise AdcircConfigError(f"FATAL ERROR: {sp} has advanced past this {segment} (its start is {st[1]} s, "
                                f"{hot.name} is at {_time(hot):g} s); redo the cycle from ncst")
    run_dir = _stage(ctx, stream, segment, seg.tokens, now.strftime("%Y%m%d%H"), nod, runner, hot, int(seg.tokens["ihot"]),
                     [(rr / f"{ctx.run}_{name}", src) for src, name in RERUN[stream]])
    argv = _launch(ctx, run_dir, stream, segment, launcher, profile)
    check_records(run_dir, stream, "fcst")  # before the products are published and before the state is advanced MJ (10/15/26)
    for src, name in PRODUCTS[stream]:
        _publish(_need(run_dir, src), ctx.cycle_dir(now, name))
    sp.write_text("0 %s %s %s\n" % (seg.state_time, st[2], st[3]))
    return argv


def _ncst_start(ctx: CycleContext) -> datetime:
    """The restart time the ncst window starts at. On a cold start prep runs before the spin-up, so no chain file of this cycle
    exists yet; when this cycle's adcprep made nod_equi, the spin-up will publish its restart at cycle - NOWH, whatever older
    chain file the lookback would find. Otherwise the newest chain file. MJ (10/14/26)"""
    nod = _nod_path(ctx)
    if nod.is_file() and read_nod_equi(nod)[0] == ctx.cycle_time - timedelta(hours=NOWH + SPINH):
        return ctx.cycle_time - timedelta(hours=NOWH)
    return find_chain_start(ctx, STREAMS["surf"][0])[0]


def gfs_source(ctx: CycleContext) -> str:
    """sfcf (the netCDF files of the WCOSS2 COMINgfs) or sflux (the public GRIB2 flux files): env ADCIRC_GFS_SOURCE, else the yaml
    adcirc.ops_gfs_source (read from settings.raw, as ops_gfs_wait_s is, so no yaml_to_env key). MJ (10/14/26)"""
    src = (os.environ.get("ADCIRC_GFS_SOURCE") or ctx.settings.raw["adcirc"].get("ops_gfs_source") or "sfcf").strip()
    if src not in ("sfcf", "sflux"):
        raise AdcircConfigError(f"ADCIRC_GFS_SOURCE / adcirc.ops_gfs_source must be sfcf or sflux, got {src!r}")
    return src


def gfs_forcing(ctx: CycleContext) -> None:
    """One ops GFS job: the ncst window starts at the multistart restart time, as exstofs_2d_glo_gfs.sh. MJ (10/06/26)"""
    from nos_utils.forcing.adcirc_met import build_sfcf_forcing

    seg, rr = ctx.segment, rerun_dir(ctx)
    if (rr / f"{ctx.run}_{seg}.221.nc").is_file():
        log.info("surface forcing files for gfs.%s already exist", seg)
        return
    if not ctx.comin_gfs:
        raise AdcircConfigError("COMINgfs is not set; the GFS sfcf files are the surf forcing source")
    start = _ncst_start(ctx) if seg == "ncst" else None
    wait = float((ctx.settings.raw["adcirc"].get("ops_gfs_wait_s") or {}).get(seg, 0))
    # source is passed only for sflux, so the sfcf path runs unchanged on a nos-utils that predates the keyword. MJ (10/14/26)
    extra = {} if gfs_source(ctx) == "sfcf" else {"source": "sflux"}
    build_sfcf_forcing(ctx.comin_gfs, ctx.cycle_time, seg, rr, ctx.run, start=start, wait_s=wait, **extra)


def run_prep(ctx: CycleContext, runner: CommandRunner = default_runner) -> int:
    """One prep step. A cold start is the explicit adcprep segment, never the COLDSTART env var: the ops run.ver exports
    COLDSTART=YES into every job. MJ (10/14/26)"""
    check_retired(ctx.segment)
    if ctx.segment in ("ncst", "fcst"):
        gfs_forcing(ctx)
    elif ctx.segment == "adcprep":
        cold_adcprep(ctx, runner)
    else:
        raise AdcircConfigError(f"ADCIRC_SEGMENT must be one of {SEGMENTS['prep']} here, got {ctx.segment!r}")
    return 0


def run_nowcast(ctx: CycleContext, launcher=execute.default_launcher, profile=None,
                runner: CommandRunner = default_runner) -> List[str]:
    if ctx.segment == "spinup":
        return cold_spinup(ctx, launcher, profile, runner)
    _check(ctx, ("ncst",))
    return _ncst(ctx, launcher, profile, runner)


def run_forecast(ctx: CycleContext, launcher=execute.default_launcher, profile=None,
                 runner: CommandRunner = default_runner) -> List[str]:
    _check(ctx, ("fcst",))
    return _fcst(ctx, launcher, profile, runner)
