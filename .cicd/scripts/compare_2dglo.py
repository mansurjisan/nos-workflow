#!/usr/bin/env python3
"""STOFS-2D-Global CI comparisons (called by stofs_2d_glo.sh verify). MJ (10/13/26)

regress: station files of this run against the frozen reference of the dataset. Per file: bitwise identical, else the largest
  |diff| over the time-dependent variables (zeta, u-vel, v-vel) must be <= --tol (default 1e-3, in the variable's unit: m or m/s);
  every other variable (time, x, y, station names) must be identical. A missing or unreadable file, a shape change, a different
  mask or a NaN in only one of the two files fails. Exit 1 if any file fails. Files: rerun/stofs_2d_glo_{tide,surf}.61.nc (ncst) and, at LEVEL=cycle
  (and full), the reference's stofs_2d_glo.t<CYC>z.points.*.nc.
ops: points.{htp,cwl.noanomaly,swl}.nc against the ops products (the cmp_points comparison: per-station max |dWL| over the common
  times, stations with ops |WL| > 20 m skipped). Reported only: a median above --warn-mm prints WARN and still exits 0; only a missing
  output of this run fails.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import netCDF4 as nc
import numpy as np

OPS_PRODUCTS = ("htp", "cwl.noanomaly", "swl")


def _day(root: Path, pdy: str) -> Path:
    return root / "nos" / f"stofs_2d_glo.{pdy}"


def regress_files(ref: Path, pdy: str, cyc: str, level: str) -> list:
    """Relative paths (under nos/stofs_2d_glo.<pdy>) the reference holds and this run must reproduce. MJ (10/13/26)"""
    day = _day(ref, pdy)
    names = [f"{cyc}/rerun/stofs_2d_glo_{s}.61.nc" for s in ("tide", "surf")]
    if level == "cycle":
        names += sorted(p.name for p in day.glob(f"stofs_2d_glo.t{cyc}z.points.*.nc"))
    return names


def _compare_var(name: str, a, b, tol: float):
    """(bitwise, maxdiff, problem) for one variable. MJ (10/13/26)"""
    if a.shape != b.shape:
        return False, 0.0, f"{name}: shape {a.shape} vs {b.shape}"
    ma, mb = np.ma.getmaskarray(a), np.ma.getmaskarray(b)
    if (ma != mb).any():
        return False, 0.0, f"{name}: mask differs at {int((ma != mb).sum())} points"
    da, db = np.ma.getdata(a)[~ma], np.ma.getdata(b)[~ma]
    if da.dtype.kind in "SUOb" or db.dtype.kind in "SUOb":
        return (True, 0.0, "") if np.array_equal(da, db) else (False, 0.0, f"{name}: values differ")
    if np.array_equal(da, db, equal_nan=True):
        return True, 0.0, ""
    fa, fb = da.astype("f8"), db.astype("f8")
    na, nb = np.isnan(fa), np.isnan(fb)
    if (na != nb).any():  # a NaN on one side only would vanish from a nan-ignoring maximum. MJ (10/13/26)
        return False, 0.0, f"{name}: NaN in only one of the two files at {int((na != nb).sum())} points"
    fa, fb = fa[~na], fb[~na]
    with np.errstate(invalid="ignore"):
        diff = np.where(fa == fb, 0.0, np.abs(fa - fb))
    return False, float(diff.max()) if diff.size else 0.0, ""


def compare_file(ref_path: Path, out_path: Path, tol) -> tuple:
    """(ok, text) for one file pair. tol is a float, or a {variable: tol} dict (a variable not in it must be bitwise). MJ (10/13/26)"""
    if not out_path.is_file():
        return False, "missing in this run"
    per_var = isinstance(tol, dict)  # per-variable tolerances, used by compare_atl.py. MJ (10/14/26)
    diffs = {}
    try:
        with nc.Dataset(ref_path) as r, nc.Dataset(out_path) as o:
            if set(r.variables) != set(o.variables):
                return False, f"variables differ: {sorted(set(r.variables) ^ set(o.variables))}"
            bitwise, worst, wvar, nvar = True, 0.0, "", 0
            for name in sorted(r.variables):
                nvar += 1
                vtol = tol.get(name, 0.0) if per_var else tol
                same, mx, problem = _compare_var(name, r.variables[name][:], o.variables[name][:], vtol)
                if problem:
                    return False, problem
                if same:
                    continue
                bitwise = False
                dims = r.variables[name].dimensions
                if not (dims and dims[0] == "time" and name != "time"):
                    return False, f"{name}: differs but is not a time-dependent variable (max |diff| {mx:.3g})"
                diffs[name] = mx
                if mx > worst:
                    worst, wvar = mx, name
                if mx > vtol:
                    return False, f"{name}: max |diff| {mx:.3g} > tol {vtol:g}"
    except (OSError, RuntimeError, KeyError, ValueError) as exc:
        return False, f"unreadable ({exc})"
    if bitwise:
        return True, f"bitwise identical ({nvar} variables)"
    if per_var:
        return True, "max |diff| " + ", ".join(f"{n} {d:.3g} (tol {tol[n]:g})" for n, d in diffs.items())
    return True, f"max |diff| {worst:.3g} ({wvar}) <= tol {tol:g}"


def regress(args) -> int:
    ref, out = Path(args.ref), Path(args.out)
    files = regress_files(ref, args.pdy, args.cyc, args.level)
    print(f"regress: LEVEL={args.level} {args.pdy}{args.cyc}: bitwise first, else max |diff| <= {args.tol:g} (m or m/s) on the time-dependent variables")
    ref_day, out_day = _day(ref, args.pdy), _day(out, args.pdy)
    fails = bit = near = 0
    for rel in files:
        r, o = ref_day / rel, out_day / rel
        if not r.is_file():
            print(f"FAIL  {rel}: not in the reference ({r})")
            fails += 1
            continue
        ok, text = compare_file(r, o, args.tol)
        print(f"{'PASS' if ok else 'FAIL'}  {rel}: {text}")
        fails += not ok
        bit += ok and text.startswith("bitwise")
        near += ok and not text.startswith("bitwise")
    print(f"regress: {len(files)} files, {bit} bitwise, {near} within tolerance, {fails} failed")
    return 1 if fails else 0


def _load(path: Path):
    d = nc.Dataset(path)
    t = d.variables["time"]
    sec = nc.date2num(nc.num2date(t[:], t.units, only_use_cftime_datetimes=False), "seconds since 1970-01-01")
    names = nc.chartostring(d.variables["station_name"][:]) if "station_name" in d.variables else None
    return d, np.round(np.asarray(sec)).astype("i8"), names


def cmp_points(ours: Path, ops: Path, warn_mm: float) -> None:
    """cmp_points: station water level over the common times, printed; WARN beyond warn_mm. MJ (10/13/26)"""
    a, ta, names = _load(ours)
    b, tb, _ = _load(ops)
    common, ia, ib = np.intersect1d(ta, tb, return_indices=True)
    if not len(common):
        print("  WARN no common times with the ops file")
        return
    za = np.ma.masked_outside(np.ma.masked_invalid(a.variables["zeta"][ia, :]), -900, 900)
    zb = np.ma.masked_outside(np.ma.masked_invalid(b.variables["zeta"][ib, :]), -900, 900)
    if za.shape[1] != zb.shape[1]:
        print(f"  WARN station counts differ: {za.shape[1]} (this run) vs {zb.shape[1]} (ops)")
        return
    d = np.ma.abs(za - zb).max(axis=0) * 1000.0
    odd = np.ma.filled((np.ma.abs(zb) > 20).any(axis=0), False)
    d[odd] = np.ma.masked
    print("  %d common times (%d this run, %d ops), %d stations compared, %d skipped (ops |WL| > 20 m)"
          % (len(common), len(ta), len(tb), d.count(), odd.sum()))
    med = float(np.ma.median(d))
    print("  per-station max |dWL|: median %.2f mm; within 1 mm %d, within 1 cm %d, over 10 cm %d"
          % (med, (d <= 1).sum(), (d <= 10).sum(), (d > 100).sum()))
    for i in [j for j in np.argsort(d.filled(-1))[::-1] if not np.ma.getmaskarray(d)[j]][:5]:
        print("    worst: %8.1f mm  %s" % (d[i], names[i].strip() if names is not None else i))
    if med > warn_mm:
        print(f"  WARN median {med:.1f} mm is above the {warn_mm:g} mm report threshold (not a failure)")


def ops(args) -> int:
    out_day = _day(Path(args.out), args.pdy)
    ops_dir = Path(args.ops_dir)
    fails = 0
    print(f"ops: {args.pdy}{args.cyc}: report only, a median per-station max |dWL| above {args.warn_mm:g} mm is flagged")
    for prod in OPS_PRODUCTS:
        name = f"stofs_2d_glo.t{args.cyc}z.points.{prod}.nc"
        mine, theirs = out_day / name, ops_dir / name
        if not mine.is_file() or mine.stat().st_size == 0:
            print(f"FAIL  {name}: missing in this run")
            fails += 1
            continue
        if not theirs.is_file():
            print(f"SKIP  {name}: no ops product in {ops_dir}")
            continue
        print(f"{name}")
        try:
            cmp_points(mine, theirs, args.warn_mm)
        except (OSError, RuntimeError, KeyError, ValueError) as exc:
            print(f"  WARN comparison failed: {exc}")
    return 1 if fails else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("regress", "ops"):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True, help="COMROOT_2DGLO of this run")
        s.add_argument("--pdy", required=True)
        s.add_argument("--cyc", required=True)
    s = sub.choices["regress"]
    s.add_argument("--ref", required=True, help="the dataset's ref/ directory (same layout as COMROOT_2DGLO)")
    s.add_argument("--level", choices=("smoke", "cycle"), required=True)
    s.add_argument("--tol", type=float, default=1e-3)
    s = sub.choices["ops"]
    s.add_argument("--ops-dir", required=True)
    s.add_argument("--warn-mm", type=float, default=500.0)
    args = p.parse_args(argv)
    return regress(args) if args.cmd == "regress" else ops(args)


if __name__ == "__main__":
    sys.exit(main())
