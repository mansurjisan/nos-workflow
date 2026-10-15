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
fields: one 2D field file against the ops file of the same name (zeta over the common times, or zeta_max for maxele), streamed over time in
  chunks; per-node max |d| statistics, worst nodes, wet/dry mismatches, optional --map png. Reported only; a missing or unreadable file exits 1.
met: pressfc, uvgrd10m and icec of a cycle against ops: record count, time, bitwise per record else max/mean |d|. Same exit rule.
"""
from __future__ import annotations

import argparse
import re
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


def compare_file(ref_path: Path, out_path: Path, tol: float) -> tuple:
    """(ok, text) for one file pair. MJ (10/13/26)"""
    if not out_path.is_file():
        return False, "missing in this run"
    try:
        with nc.Dataset(ref_path) as r, nc.Dataset(out_path) as o:
            if set(r.variables) != set(o.variables):
                return False, f"variables differ: {sorted(set(r.variables) ^ set(o.variables))}"
            bitwise, worst, wvar, nvar = True, 0.0, "", 0
            for name in sorted(r.variables):
                nvar += 1
                same, mx, problem = _compare_var(name, r.variables[name][:], o.variables[name][:], tol)
                if problem:
                    return False, problem
                if same:
                    continue
                bitwise = False
                dims = r.variables[name].dimensions
                if not (dims and dims[0] == "time" and name != "time"):
                    return False, f"{name}: differs but is not a time-dependent variable (max |diff| {mx:.3g})"
                if mx > worst:
                    worst, wvar = mx, name
                if mx > tol:
                    return False, f"{name}: max |diff| {mx:.3g} > tol {tol:g}"
    except (OSError, RuntimeError, KeyError, ValueError) as exc:
        return False, f"unreadable ({exc})"
    if bitwise:
        return True, f"bitwise identical ({nvar} variables)"
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


FILL_LIMIT = 900.0  # |zeta| at or above this is a fill or dry value (-99999 in ADCIRC output). MJ (10/15/26)
MET_FILL = 1e20  # grid files carry 9.99e20 as the fill. MJ (10/15/26)
MET_VARS = {"pressfc": ("pressfc",), "uvgrd10m": ("ugrd10m", "vgrd10m"), "icec": ("icec",)}


def _epoch_seconds(var):
    """Time values as int64 epoch seconds; the units string may carry trailing text after '!' (ADCIRC). MJ (10/15/26)"""
    vals = np.asarray(var[:], dtype="f8")
    units = re.sub(r"\s+", " ", getattr(var, "units", "").split("!")[0]).strip()
    try:
        sec = nc.date2num(nc.num2date(vals, units, only_use_cftime_datetimes=False), "seconds since 1970-01-01")
    except (ValueError, TypeError):
        sec = vals
    return np.round(np.asarray(sec)).astype("i8")


def _open(path: Path):
    if not path.is_file() or path.stat().st_size == 0:
        raise OSError(f"{path}: missing or empty")
    d = nc.Dataset(path)
    d.set_auto_mask(False)
    return d


def _rows(var, idx):
    """Rows idx (ascending) of var as float64; one slice read when contiguous. MJ (10/15/26)"""
    idx = np.asarray(idx)
    if len(idx) and idx[-1] - idx[0] + 1 == len(idx):
        return np.asarray(var[int(idx[0]):int(idx[-1]) + 1], dtype="f8")
    return np.stack([np.asarray(var[int(i)], dtype="f8") for i in idx])


def _wet(a):
    with np.errstate(invalid="ignore"):
        return np.isfinite(a) & (np.abs(a) < FILL_LIMIT)


def field_stats(a, b, var="zeta", chunk=8):
    """Stream two ADCIRC files; dict of per-node and global statistics. MJ (10/15/26)"""
    timed = var in a.variables and a.variables[var].dimensions[:1] == ("time",)
    if var not in a.variables or var not in b.variables:
        if var == "zeta" and "zeta_max" in a.variables and "zeta_max" in b.variables:
            var, timed = "zeta_max", False
        else:
            raise KeyError(f"variable {var} not in both files")
    if timed != (b.variables[var].dimensions[:1] == ("time",)):
        raise ValueError(f"{var}: time-dimension layout differs between the files")
    nn = a.variables[var].shape[-1]
    if b.variables[var].shape[-1] != nn:
        raise ValueError(f"node counts differ: {nn} (this run) vs {b.variables[var].shape[-1]} (ops)")
    if timed:
        ta, tb = _epoch_seconds(a.variables["time"]), _epoch_seconds(b.variables["time"])
        common, ia, ib = np.intersect1d(ta, tb, return_indices=True)
        if not len(common):
            raise ValueError("no common times")
        steps = [(ia[k:k + chunk], ib[k:k + chunk]) for k in range(0, len(common), max(1, chunk))]
        ntimes = (len(common), len(ta), len(tb))
    else:
        steps = [(None, None)]
        ntimes = (1, 1, 1)
    maxd = np.full(nn, -1.0)
    sumabs = sumsq = 0.0
    npair = nmis = 0
    mism_nodes = np.zeros(nn, bool)
    for ca, cb in steps:
        if timed:
            za, zb = _rows(a.variables[var], ca), _rows(b.variables[var], cb)
        else:
            za, zb = np.asarray(a.variables[var][:], "f8")[None], np.asarray(b.variables[var][:], "f8")[None]
        wa, wb = _wet(za), _wet(zb)
        both = wa & wb
        mis = wa != wb
        nmis += int(mis.sum())
        mism_nodes |= mis.any(axis=0)
        d = np.where(both, np.abs(za - zb), -1.0)
        npair += int(both.sum())
        dv = d[both]
        sumabs += float(dv.sum())
        sumsq += float((dv * dv).sum())
        maxd = np.maximum(maxd, d.max(axis=0))
    ok = maxd >= 0
    nd = maxd[ok] * 1000.0
    return {"var": var, "ntimes": ntimes, "nnodes": nn, "ncompared": int(ok.sum()), "maxd": maxd, "ok": ok, "npair": npair,
            "mean": sumabs / npair if npair else 0.0, "rms": (sumsq / npair) ** 0.5 if npair else 0.0,
            "max": float(maxd[ok].max()) if ok.any() else 0.0, "pct": np.percentile(nd, [50, 99, 99.9]) if nd.size else None,
            "w1mm": int((nd <= 1).sum()), "w1cm": int((nd <= 10).sum()), "o10cm": int((nd > 100).sum()),
            "nmis": nmis, "mis_nodes": int(mism_nodes.sum())}


def _map(path, lon, lat, val_mm, title):
    """Scatter map of per-node max |d| (decimated to ~200k points); False when matplotlib is missing. MJ (10/15/26)"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    step = max(1, int(np.ceil(len(val_mm) / 200000.0)))
    lon, lat, v = lon[::step], lat[::step], val_mm[::step]
    fig, ax = plt.subplots(figsize=(12, 6.2))
    vmax = float(np.percentile(v, 99.9)) if v.size else 1.0
    sc = ax.scatter(lon, lat, c=v, s=1, cmap="viridis", vmin=0, vmax=max(vmax, 1e-6), linewidths=0, rasterized=True)
    fig.colorbar(sc, ax=ax, label="per-node max |d| (mm), colour limit at the 99.9th percentile")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.set_title(title)
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return True


def fields(args) -> int:
    ours, theirs = Path(args.ours), Path(args.ops)
    try:
        a, b = _open(ours), _open(theirs)
    except (OSError, RuntimeError) as exc:
        print(f"FAIL  {exc}")
        return 1
    try:
        st = field_stats(a, b, args.var, args.chunk)
        x = np.asarray(a.variables["x"][:], "f8")
        y = np.asarray(a.variables["y"][:], "f8")
    except (OSError, RuntimeError, KeyError, ValueError, IndexError) as exc:
        print(f"FAIL  {ours.name}: unreadable or incompatible ({exc})")
        return 1
    finally:
        a.close()
        b.close()
    n, na, nb = st["ntimes"]
    print(f"fields: {ours.name} ({st['var']}) vs {theirs}")
    print("  %d common times (%d this run, %d ops), %d nodes, %d nodes compared, %d node-time pairs"
          % (n, na, nb, st["nnodes"], st["ncompared"], st["npair"]))
    if st["pct"] is None:
        print("  WARN no node is wet in both files")
        return 0
    print("  |d| over wet pairs: max %.2f mm, mean %.3f mm, RMS %.3f mm" % (st["max"] * 1000, st["mean"] * 1000, st["rms"] * 1000))
    print("  per-node max |d| percentiles 50/99/99.9: %.2f / %.2f / %.2f mm" % tuple(st["pct"]))
    print("  per-node max |d|: within 1 mm %d, within 1 cm %d, over 10 cm %d" % (st["w1mm"], st["w1cm"], st["o10cm"]))
    print("  wet/dry mismatches: %d node-time pairs at %d nodes (wet in one file, dry or fill in the other)" % (st["nmis"], st["mis_nodes"]))
    idx = np.flatnonzero(st["ok"])
    sel = idx[np.argsort(st["maxd"][idx])[::-1][:10]]
    for i in sel:
        print("    worst: %9.2f mm  node %d  lon %.4f lat %.4f" % (st["maxd"][i] * 1000, i + 1, x[i], y[i]))
    if args.map:
        v = np.where(st["ok"], st["maxd"] * 1000.0, np.nan)
        keep = np.isfinite(v)
        if _map(args.map, x[keep], y[keep], v[keep], f"{ours.name}: per-node max |d| vs ops"):
            print(f"  map: {args.map}")
        else:
            print("  map skipped: matplotlib is not available")
    return 0


def _met_var(a, b, name):
    """(records this run, records ops, bitwise records, max, mean, fill mismatches) streamed per record. MJ (10/15/26)"""
    va, vb = a.variables[name], b.variables[name]
    na, nb = va.shape[0], vb.shape[0]
    bit = fillmis = npair = 0
    mx = tot = 0.0
    for r in range(min(na, nb)):
        ra, rb = np.asarray(va[r]), np.asarray(vb[r])
        if ra.shape != rb.shape:
            raise ValueError(f"{name}: record shape {ra.shape} vs {rb.shape}")
        if np.array_equal(ra, rb, equal_nan=True):
            bit += 1
            continue
        fa, fb = ra.astype("f8"), rb.astype("f8")
        with np.errstate(invalid="ignore"):
            ma = ~np.isfinite(fa) | (np.abs(fa) >= MET_FILL)
            mb = ~np.isfinite(fb) | (np.abs(fb) >= MET_FILL)
        fillmis += int((ma != mb).sum())
        both = ~ma & ~mb
        d = np.abs(fa[both] - fb[both])
        if d.size:
            mx = max(mx, float(d.max()))
            tot += float(d.sum())
            npair += d.size
    return na, nb, bit, mx, (tot / npair if npair else 0.0), fillmis


def met(args) -> int:
    fails = 0
    print(f"met: {args.ours_dir} vs {args.ops_dir}, cycle t{args.cyc}z (expect {args.records} records)")
    for prod, names in MET_VARS.items():
        fn = f"stofs_2d_glo.t{args.cyc}z.{prod}.nc"
        try:
            a, b = _open(Path(args.ours_dir) / fn), _open(Path(args.ops_dir) / fn)
        except (OSError, RuntimeError) as exc:
            print(f"FAIL  {fn}: {exc}")
            fails += 1
            continue
        print(fn)
        try:
            ta, tb = a.variables["time"], b.variables["time"]
            same_t = np.array_equal(np.asarray(ta[:]), np.asarray(tb[:])) and getattr(ta, "units", "") == getattr(tb, "units", "")
            print("  time: %s (%s vs %s)" % ("equal" if same_t else "DIFFERS", np.asarray(ta[:]).tolist(), np.asarray(tb[:]).tolist()))
            for name in names:
                na, nb, bit, mx, mean, fm = _met_var(a, b, name)
                flag = "" if na == nb == args.records else "  WARN record count is not %d" % args.records
                print("  %s: %d records this run, %d ops%s" % (name, na, nb, flag))
                if bit == min(na, nb) and fm == 0:
                    print("    bitwise identical in all %d compared records" % bit)
                else:
                    print("    %d of %d compared records bitwise; max |d| %.4g, mean |d| %.4g %s; fill mismatches %d"
                          % (bit, min(na, nb), mx, mean, getattr(a.variables[name], "units", ""), fm))
        except (OSError, RuntimeError, KeyError, ValueError, IndexError) as exc:
            print(f"FAIL  {fn}: unreadable or incompatible ({exc})")
            fails += 1
        finally:
            a.close()
            b.close()
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
    s = sub.add_parser("fields")
    s.add_argument("--ours", required=True)
    s.add_argument("--ops", required=True)
    s.add_argument("--var", default="zeta")
    s.add_argument("--chunk", type=int, default=8, help="time records per read")
    s.add_argument("--map", help="png of the per-node max |d| (needs matplotlib)")
    s = sub.add_parser("met")
    s.add_argument("--ours-dir", required=True)
    s.add_argument("--ops-dir", required=True)
    s.add_argument("--cyc", required=True)
    s.add_argument("--records", type=int, default=149)
    args = p.parse_args(argv)
    return {"regress": regress, "ops": ops, "fields": fields, "met": met}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
