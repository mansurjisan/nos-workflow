#!/usr/bin/env python3
"""Stage nos-workflow STOFS-2D-Global ops-mode surface forcing from the public NCO rerun files.

Reads the nine ops files stofs_2d_glo_{ncst,fcst1,fcst2}.{221,222,225}.nc and writes the six files
nos-workflow reads from $COMOUT/<CC>/rerun: stofs_2d_glo_ncst.* (same records) and stofs_2d_glo_fcst.*
(one hourly 180 h forecast: fcst1 records 0..120, then fcst2 every 3 h with the hours between linearly
interpolated). Output goes through nos-utils' own writer and the interpolation mirrors build_sfcf_forcing,
so the files are what nos-workflow would have built from the GFS sfcf files. Needs python3, numpy, netCDF4
and a nos-utils checkout (main >= 5496da0). Streams one record at a time. MJ (10/13/26)

    tools/stage_stofs_2d_glo_ops_forcing.py --ops-dir <dir with the 9 ops files> --out <rerun dir> [--nos-utils <checkout>]

--nos-utils defaults to this repo's ush/python/nos-utils, then $NOS_UTILS_DIR. tools/hercules_2d_glo_stage_forcing.sh
downloads the nine files and runs this. MJ (10/13/26)
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")  # Lustre rejects HDF5 file locks on read. MJ (10/13/26)

import numpy as np

PREFIX = "stofs_2d_glo"
N_FCST1, N_FCST2, N_FCST = 121, 21, 181  # fcst1 f000..f120 hourly, fcst2 f120..f180 every 3 h, merged hourly MJ (10/13/26)
NUMS = ("221", "222", "225")
_MEAN = "time: mean"
_NCO_ATTRS = ("history", "NCO")


class StageError(Exception):
    pass


def load_nos_utils(path):
    """adcirc_met.py by file path: importing the package would pull xarray/scipy/pyproj that Hercules lacks. MJ (10/13/26)"""
    rel = Path("nos_utils") / "forcing" / "adcirc_met.py"
    if path:
        f = Path(path) / rel
        if not f.is_file():
            raise StageError("{} not found: --nos-utils must be a nos-utils checkout".format(f))
    else:
        # the submodule beside this script wins over an inherited NOS_UTILS_DIR, as in the Slurm cards. MJ (10/13/26)
        cands = [Path(__file__).resolve().parent.parent / "ush" / "python" / "nos-utils"]
        if os.environ.get("NOS_UTILS_DIR"):
            cands.append(Path(os.environ["NOS_UTILS_DIR"]))
        found = [c / rel for c in cands if (c / rel).is_file()]
        if not found:
            raise StageError("no nos-utils checkout found (tried {}): give --nos-utils, set NOS_UTILS_DIR or run "
                             "git submodule update --init ush/python/nos-utils".format(", ".join(str(c) for c in cands)))
        f = found[0]
    spec = importlib.util.spec_from_file_location("_nos_utils_adcirc_met", str(f))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for need in ("_open_sfcf_output", "_interp_bracket", "sfcf_valid_times", "_write_sfcf_manifest", "SFC_OUTPUTS"):
        if not hasattr(mod, need):
            raise StageError("{} lacks {}: needs nos-utils main >= 5496da0 (single 180 h fcst)".format(f, need))
    return mod


class _SrcVar:
    """An ops variable seen as the sfcf variable the writer expects: the ncwa 'time: mean' is not yet in cell_methods. MJ (10/13/26)"""

    def __init__(self, v):
        self._v = v

    @property
    def dtype(self):
        return self._v.dtype

    def _cm(self, x):
        return x[:-len(_MEAN)].rstrip() if x == _MEAN or x.endswith(" " + _MEAN) else x

    def ncattrs(self):
        return [a for a in self._v.ncattrs() if not (a == "cell_methods" and not self._cm(self._v.getncattr(a)))]

    def getncattr(self, a):
        x = self._v.getncattr(a)
        return self._cm(x) if a == "cell_methods" else x

    def __getattr__(self, a):
        if a in self.ncattrs():
            return self.getncattr(a)
        raise AttributeError(a)

    def __getitem__(self, i):
        return self._v[...] if self._v.ndim == 0 else self._v[i]


class _SrcDs:
    """An ops file seen as the sfcf file _open_sfcf_output clones: no NCO history/NCO global attributes. MJ (10/13/26)"""
    __slots__ = ("dimensions", "variables", "__dict__")

    def __init__(self, ds):
        self.dimensions = ds.dimensions
        self.variables = {k: _SrcVar(v) for k, v in ds.variables.items()}
        self.__dict__.update({k: ds.getncattr(k) for k in ds.ncattrs() if k not in _NCO_ATTRS})


def _is_url(s):
    return str(s).startswith(("http://", "https://"))


def ops_path(ops_dir, seg, num):
    name = "{}_{}.{}.nc".format(PREFIX, seg, num)
    return ops_dir.rstrip("/") + "/" + name + "#mode=bytes" if _is_url(ops_dir) else str(Path(ops_dir) / name)


def _parse_units(units):
    m = re.match(r"hours since (\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)", units or "")
    if not m:
        raise StageError("unexpected time units {!r}".format(units))
    return datetime(*[int(g) for g in m.groups()])


def check_inputs(nc, ops_dir, ncst_records):
    """All nine ops files present with the expected records, variables and cycle; returns the cycle time."""
    if not _is_url(ops_dir):
        gone = [ops_path(ops_dir, s, n) for s in ("ncst", "fcst1", "fcst2") for n in NUMS
                if not Path(ops_path(ops_dir, s, n)).is_file()]
        if gone:
            raise StageError("missing ops input file(s):\n  " + "\n  ".join(gone))
    want = {"ncst": ncst_records, "fcst1": N_FCST1, "fcst2": N_FCST2}
    names = {"221": ("pressfc",), "222": ("ugrd10m", "vgrd10m"), "225": ("icec",)}
    times, shapes = {}, set()
    for seg in want:
        for n in NUMS:
            p = ops_path(ops_dir, seg, n)
            try:
                d = nc.Dataset(p)
            except (OSError, RuntimeError) as exc:
                raise StageError("cannot open {}: {}".format(p, exc))
            with d:
                if "record" not in d.dimensions or len(d.dimensions["record"]) != want[seg]:
                    have = len(d.dimensions["record"]) if "record" in d.dimensions else None
                    raise StageError("{} has {} records, expected {}".format(p, have, want[seg]))
                for v in names[n] + ("lat", "lon"):
                    if v not in d.variables or d.variables[v].dimensions != ("record", "grid_yt", "grid_xt"):
                        raise StageError("{}: variable {} missing or not (record, grid_yt, grid_xt)".format(p, v))
                if "time" not in d.variables or d.variables["time"].dimensions != ():
                    raise StageError("{}: no scalar time variable".format(p))
                times[(seg, n)] = (float(d.variables["time"][...]), d.variables["time"].getncattr("units"))
                shapes.add((len(d.dimensions["grid_yt"]), len(d.dimensions["grid_xt"])))
    if len(shapes) != 1:
        raise StageError("the ops files are on different grids: {}".format(sorted(shapes)))
    for n in NUMS:
        (t1, u1), (t2, u2) = times[("fcst1", n)], times[("fcst2", n)]
        if u1 != u2 or t2 - t1 != 120.0:
            raise StageError("fcst1/fcst2 .{} are not one cycle: time {} [{}] vs {} [{}], fcst2 must start 120 h after fcst1"
                             .format(n, t1, u1, t2, u2))
    t1, u1 = times[("fcst1", "221")]
    return _parse_units(u1) + timedelta(hours=t1)


def make_plan(am, nc, ops_dir, segment, cycle):
    """Per output record (valid, lo, hi, weight) with lo/hi = (ops segment, record); hi is None for a native copy."""
    if segment == "ncst":
        with nc.Dataset(ops_path(ops_dir, "ncst", "221")) as d:
            n = len(d.dimensions["record"])
        return [(cycle - timedelta(hours=n - 1 - i), ("ncst", i), None, 0.0) for i in range(n)]
    plan = []
    for valid in am.sfcf_valid_times(cycle, "fcst"):
        fh = int((valid - cycle).total_seconds() // 3600)
        br = am._interp_bracket(cycle, valid)
        if br:
            plan.append((valid, ("fcst2", (br[0] - 120) // 3), ("fcst2", (br[1] - 120) // 3), br[2]))
        elif fh <= 120:
            plan.append((valid, ("fcst1", fh), None, 0.0))
        else:
            plan.append((valid, ("fcst2", (fh - 120) // 3), None, 0.0))
    return plan


def interp(a0, a1, w, fv):
    """The expression in build_sfcf_forcing, verbatim. MJ (10/13/26)"""
    r = a0.astype(np.float64) * (1.0 - w) + a1.astype(np.float64) * w
    if fv is not None:
        r = np.where((a0 == fv) | (a1 == fv), fv, r)
    return r.astype(a0.dtype)


def write_output(am, nc, ops_dir, plan, num, part, out):
    """One output file (221, 222 or 225) written record by record from the ops file(s) in ``plan``."""
    src = {}
    try:
        for seg in {r[0] for _, lo, hi, _ in plan for r in (lo, hi) if r}:
            src[seg] = nc.Dataset(ops_path(ops_dir, seg, num))
            src[seg].set_auto_maskandscale(False)
        names = dict(am.SFC_OUTPUTS)[num]
        # the first record's file is the template (fcst1: time 0 in cycle units, as f000 gives the single fcst). MJ (10/13/26)
        o = am._open_sfcf_output(nc, part, _SrcDs(src[plan[0][1][0]]), names)
        try:
            for rec, (_, lo, hi, w) in enumerate(plan):
                ds = src[lo[0]]
                lat, lon = ds.variables["lat"][lo[1]], ds.variables["lon"][lo[1]]
                if hi and not (np.array_equal(src[hi[0]].variables["lat"][hi[1]], lat)
                               and np.array_equal(src[hi[0]].variables["lon"][hi[1]], lon)):
                    raise StageError("{}: record {} grid differs from record {}".format(num, hi[1], lo[1]))
                o.variables["lat"][rec], o.variables["lon"][rec] = lat, lon
                for v in names:
                    a0 = ds.variables[v][lo[1]]
                    if not hi:
                        o.variables[v][rec] = a0
                        continue
                    sv = ds.variables[v]
                    fv = sv.getncattr("_FillValue") if "_FillValue" in sv.ncattrs() else None
                    o.variables[v][rec] = interp(a0, src[hi[0]].variables[v][hi[1]], w, fv)
                if rec % 60 == 59:
                    out("  .{} {}/{} records".format(num, rec + 1, len(plan)))
        finally:
            o.close()
    finally:
        for d in src.values():
            d.close()


def summarize(nc, am, path, num, nrec):
    """Read back the first and last record of the finished (still .partial) file: proves it is complete and readable."""
    bits = []
    with nc.Dataset(str(path)) as d:
        d.set_auto_maskandscale(False)
        if len(d.dimensions["record"]) != nrec:
            raise StageError("{}: wrote {} records, expected {}".format(path, len(d.dimensions["record"]), nrec))
        for v in dict(am.SFC_OUTPUTS)[num]:
            sv = d.variables[v]
            fv = sv.getncattr("_FillValue") if "_FillValue" in sv.ncattrs() else None
            txt = []
            for i in (0, nrec - 1):
                a = sv[i]
                ok = np.isfinite(a) if fv is None else (np.isfinite(a) & (a != fv))
                txt.append("rec{} {}".format(i, "{:.6g}/{:.6g}".format(a[ok].min(), a[ok].max()) if ok.any() else "all fill"))
            bits.append("{} min/max {}".format(v, "; ".join(txt)))
    return "{} records, {}".format(nrec, " | ".join(bits))


def build_group(am, nc, ops_dir, out_dir, segment, cycle, force, out):
    """ncst or fcst: three .partial files, renamed once all are complete (221 last, the nos-workflow skip test)."""
    final = {n: out_dir / "{}_{}.{}.nc".format(PREFIX, segment, n) for n in NUMS}
    if final["221"].exists() and not force:
        out("skip {}: {} exists (use --force to rebuild)".format(segment, final["221"].name))
        return
    plan = make_plan(am, nc, ops_dir, segment, cycle)
    part = {n: p.with_name(p.name + ".partial") for n, p in final.items()}
    lines, done = {}, False
    try:
        for n in NUMS:
            t0 = time.time()
            write_output(am, nc, ops_dir, plan, n, part[n], out)
            lines[n] = "{}  {}  ({:.0f} s)".format(final[n].name, summarize(nc, am, part[n], n, len(plan)), time.time() - t0)
        for n in ("225", "222", "221"):
            os.replace(str(part[n]), str(final[n]))
        done = True
    finally:
        if not done:
            for p in part.values():
                if p.exists():
                    p.unlink()
    for n in NUMS:
        out(lines[n])
    if not _is_url(ops_dir):
        used = [(valid, Path(ops_path(ops_dir, r[0], "221"))) for valid, lo, hi, _ in plan for r in (lo, hi) if r]
        am._write_sfcf_manifest(out_dir / "{}_{}.sfcf_manifest.json".format(PREFIX, segment), cycle, segment, used)


def stage(ops_dir, out_dir, nos_utils=None, ncst_records=7, force=False, check_only=False, out=print):
    am = load_nos_utils(nos_utils)
    import netCDF4 as nc
    cycle = check_inputs(nc, ops_dir, ncst_records)
    out("ops inputs ok: cycle {:%Y%m%d%H}, ncst {} / fcst1 {} / fcst2 {} records".format(cycle, ncst_records, N_FCST1, N_FCST2))
    if check_only:
        return
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for segment in ("ncst", "fcst"):
        build_group(am, nc, ops_dir, out_dir, segment, cycle, force, out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ops-dir", required=True, help="directory holding the 9 ops files (an https prefix is read by byte range)")
    ap.add_argument("--out", required=True, help="the rerun directory nos-workflow reads")
    ap.add_argument("--nos-utils", help="nos-utils checkout (default: this repo's ush/python/nos-utils, then $NOS_UTILS_DIR)")
    ap.add_argument("--ncst-records", type=int, default=7, help="ops ncst records (default 7: cycle-6h..cycle)")
    ap.add_argument("--force", action="store_true", help="rebuild a group whose outputs already exist")
    ap.add_argument("--check", action="store_true", help="validate the ops inputs and stop")
    a = ap.parse_args(argv)
    try:
        stage(a.ops_dir, a.out, a.nos_utils, a.ncst_records, a.force, a.check, lambda s: print(s, flush=True))
    except (StageError, OSError) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
