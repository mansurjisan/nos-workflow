"""STOFS-2D-GLO ops mode (ADCIRC_MODE=ops): the stofs.v3.1.5 run structure, one call per ops job.

Tide (NWS=0, chain file .hotstart) and surf (NWS=14014, chain file .restart) streams, each run as
ncst, fcst1 (+120 h), fcst2 (+60 h); cold_adcprep (nod_equi + decomposition) runs in prep and
cold_spinup in the nowcast stage with ADCIRC_SEGMENT=spinup. The arithmetic, file names and sed
chain follow exstofs_2d_glo_*.sh and stofs_2d_glo_multistart.sh. Surf forcing is not made here: the
surf segments read $COMOUT/<cyc>/rerun/<RUN>_{ncst,fcst1,fcst2}.{221,222,225}.nc. MJ (10/05/26)
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


def fcst_segment(stream: str, segment: str, time_hotstart, touts: str, toutf: str) -> Segment:
    div, nhsinc, winc = (36, "3600", "3600") if segment == "fcst1" else (72, "7200", "10800")
    ihot = parity_ihot(time_hotstart, NOWH)
    rnday = bc_div(time_hotstart, 86400) + bc_div(LSTH, div)
    tok = {"ihot": str(ihot), "rnday": bc_str(rnday), "nout": "3", "touts": touts, "toutf": toutf,
           "nhstar": "3", "nhsinc": nhsinc}
    if stream == "surf":
        tok["winc"] = winc
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
                                "please restart with COLDSTART=YES")
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
    """Stage one segment in $DATA (not COMOUT: six run dirs a cycle are ~150 GB) and decompose it. MJ (10/05/26)"""
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
                                "decomposition (no ops station files); re-run cold_adcprep with COLDSTART=YES")
    return run_dir


def _launch(ctx: CycleContext, run_dir: Path, stream: str, segment: str, launcher, profile) -> List[str]:
    writers = int(ctx.settings.raw["adcirc"].get("ops_surf_writers", 0)) \
        if stream == "surf" and segment in ("ncst", "fcst1") else 0
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
                                f"{beg - timedelta(hours=SPINH)}; run cold_adcprep for this cycle first")
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
    raise AdcircConfigError(f"FATAL ERROR: there are no {kind} files, please restart with COLDSTART=YES")


def _check(ctx: CycleContext, segments: Tuple[str, ...]) -> None:
    if ctx.stream not in STREAMS:
        raise AdcircConfigError(f"ADCIRC_STREAM must be one of {tuple(STREAMS)}, got {ctx.stream!r}")
    if ctx.segment not in segments:
        raise AdcircConfigError(f"ADCIRC_SEGMENT must be one of {segments} here, got {ctx.segment!r}")


def _export(ctx: CycleContext, run_dir: Path) -> None:
    for src, name in RERUN[ctx.stream]:
        _publish(_need(run_dir, src), rerun_dir(ctx) / f"{ctx.run}_{name}")


def _ncst(ctx: CycleContext, launcher, profile, runner) -> List[str]:
    stream, now = ctx.stream, ctx.cycle_time
    chain, state = STREAMS[stream][:2]
    _base, nod = _load_nod(ctx)
    beg, hfile = find_chain_start(ctx, chain)
    seg = ncst_segment(stream, "%.15g" % _time(hfile), int((now - beg).total_seconds() // 3600))
    # A stale fcst1-end hotstart from an earlier run of this cycle must not reach fcst1/fcst2. MJ (10/05/26)
    h68 = rerun_dir(ctx) / f"{ctx.run}_{stream}.68.nc"
    if h68.exists():
        h68.unlink()
    run_dir = _stage(ctx, stream, "ncst", seg.tokens, now.strftime("%Y%m%d%H"), nod, runner, hfile, int(seg.tokens["ihot"]))
    argv = _launch(ctx, run_dir, stream, "ncst", launcher, profile)
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
    seg = fcst_segment(stream, segment, st[1], st[2], st[3])
    hot = ctx.cycle_dir(now, chain) if segment == "fcst1" else rr / f"{ctx.run}_{stream}.68.nc"
    if abs(_time(hot) - float(st[1])) > 1:
        raise AdcircConfigError(f"FATAL ERROR: {sp} has advanced past this {segment} (its start is {st[1]} s, "
                                f"{hot.name} is at {_time(hot):g} s); redo the cycle from ncst")
    run_dir = _stage(ctx, stream, segment, seg.tokens, now.strftime("%Y%m%d%H"), nod, runner, hot, int(seg.tokens["ihot"]),
                     [(rr / f"{ctx.run}_{name}", src) for src, name in RERUN[stream]])
    argv = _launch(ctx, run_dir, stream, segment, launcher, profile)
    if segment == "fcst1":
        _publish(_need(run_dir, f"fort.{parity_ihot(seg.state_time, NOWH) - 300}.nc"),
                 rr / f"{ctx.run}_{stream}.68.nc")
        _export(ctx, run_dir)
    else:
        for src, name in PRODUCTS[stream]:
            _publish(_need(run_dir, src), ctx.cycle_dir(now, name))
    sp.write_text("0 %s %s %s\n" % (seg.state_time, st[2], st[3]))
    return argv


def run_prep(ctx: CycleContext, runner: CommandRunner = default_runner) -> int:
    if ctx.coldstart:
        cold_adcprep(ctx, runner)
    else:
        _load_nod(ctx)
    return 0


def run_nowcast(ctx: CycleContext, launcher=execute.default_launcher, profile=None,
                runner: CommandRunner = default_runner) -> List[str]:
    if ctx.segment == "spinup":
        return cold_spinup(ctx, launcher, profile, runner)
    _check(ctx, ("ncst",))
    return _ncst(ctx, launcher, profile, runner)


def run_forecast(ctx: CycleContext, launcher=execute.default_launcher, profile=None,
                 runner: CommandRunner = default_runner) -> List[str]:
    _check(ctx, ("fcst1", "fcst2"))
    return _fcst(ctx, launcher, profile, runner)
