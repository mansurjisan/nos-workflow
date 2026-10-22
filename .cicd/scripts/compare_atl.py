#!/usr/bin/env python3
"""STOFS-3D-Atlantic CI comparisons (called by stofs_3d_atl.sh). MJ (10/14/26)

files:   the relative paths (under a COMROOT) that a frozen ref/ holds and a run must reproduce, one per line.
regress: those files of this run against the frozen reference. Per file: bitwise identical, else max |diff| per time-dependent
  variable within its tolerance, every other variable (time, station coordinates and names, depth) identical. A missing or
  unreadable file, a shape change, a different mask or a NaN in only one file fails. Exit 1 if any file fails.
  --tol is the water-level tolerance in m (default 1e-3) and scales all the others by fixed ratios, so the tolerances are
  tol x ratio: water level / zCoordinates / u / v / wind 1x (m, m/s), temperature and salinity 10x (degC, psu), staout_2 pressure 100x (Pa).
ops:     station water level (zeta) of this run against the ops public-bucket products, the cmp_points comparison: per-station max |dWL|
  over the common times, stations with |WL| > 20 m on either side skipped (the 5 out-of-mesh stations). Stations are matched by
  row order (station.in, 166 in v3.1) when the counts agree, else by exact name. Report only by default: a median above --warn-mm
  prints WARN and still exits 0; only a missing output of this run fails. With --fail-median-mm and --fail-over-10cm (the standalone
  variant, same model and forcing as ops) a file also FAILs when its median exceeds the first or more than the second number of
  stations are over 100 mm, and PASSes otherwise; a file that cannot be compared (no common times, no matching
  stations, no station left, unreadable) also FAILs when the gate is on, and only WARNs without it. Exit 1 if any file fails. MJ (10/22/26)
ops-files: the ops product names to keep under ref/ops/.
"""
from __future__ import annotations

import argparse
import re
import sys
from calendar import timegm
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import netCDF4 as nc  # noqa: E402
import numpy as np  # noqa: E402

from compare_2dglo import _compare_var, compare_file  # noqa: E402

RUN = "stofs_3d_atl_ufs"
OPS_RUN = "stofs_3d_atl"
VARIANTS = ("standalone", "coupled")
LEVELS = ("smoke", "cycle")
# SCHISM staout indices: 1 elevation, 2 pressure, 3/4 wind u/v, 5 temperature, 6 salinity, 7/8 velocity u/v. mirror.out, flux.out,
# restart files and rerun/ are left out: run-dependent or multi-GB. MJ (10/14/26)
STAOUTS = tuple(range(1, 9))
STAOUT_RATIO = {1: 1, 2: 100, 3: 1, 4: 1, 5: 10, 6: 10, 7: 1, 8: 1}
NC_RATIO = {"zeta": 1, "zCoordinates": 1, "u": 1, "v": 1, "uwind_speed": 1, "vwind_speed": 1, "temperature": 10, "salinity": 10}
STAOUT_PREFIX = "staout_"
_FORTRAN_EXP = re.compile(r"(\d)([+-]\d{2,3})(?=\s|$)")


def _day(root: Path, pdy: str) -> Path:
    return root / "nos" / f"{RUN}.{pdy}"


def _rel(pdy: str, name: str) -> str:
    return f"nos/{RUN}.{pdy}/{name}"


def regress_files(variant: str, level: str, pdy: str, cyc: str = "12") -> list:
    """smoke (prep + nowcast): the nowcast staout files. cycle (+ forecast + post): also the forecast staout files and the post
    station products (points.cwl and station.profile, nowcast and forecast). Same list for both variants: both write the same
    names and the station products are the small deterministic ones. MJ (10/14/26)"""
    if variant not in VARIANTS or level not in LEVELS:
        raise ValueError(f"unknown variant {variant!r} or level {level!r}")
    stem = f"{RUN}.t{cyc}z"
    names = [f"{stem}.restart_outputs/{STAOUT_PREFIX}{i}" for i in STAOUTS]
    if level == "cycle":
        names += [f"{stem}.forecast_outputs/{STAOUT_PREFIX}{i}" for i in STAOUTS]
        for phase in ("nowcast", "forecast"):
            names.append(f"{stem}.{pdy}.points.cwl.{phase}.nc")
        for phase in ("nowcast", "forecast"):
            names.append(f"{stem}.{pdy}.station.profile.{phase}.nc")
    return [_rel(pdy, n) for n in names]


def ops_names(cyc: str = "12") -> dict:
    """nos-workflow product kind -> ops file name. MJ (10/14/26)"""
    s = f"{OPS_RUN}.t{cyc}z"
    return {"points": f"{s}.points.cwl.temp.salt.vel.nc", "nowcast": f"{s}.ncast.station.profile.nc",
            "forecast": f"{s}.fcast.station.profile.nc"}


def _load_staout(path: Path) -> np.ndarray:
    try:
        return np.loadtxt(path, ndmin=2)
    except ValueError:  # Fortran writes 0.427-100 without the E. MJ (10/14/26)
        import io
        return np.loadtxt(io.StringIO(_FORTRAN_EXP.sub(r"\1e\2", Path(path).read_text())), ndmin=2)


def compare_staout(ref_path: Path, out_path: Path, tol: float) -> tuple:
    """(ok, text) for one staout text file: time column identical, station columns within tol. MJ (10/14/26)"""
    if not out_path.is_file():
        return False, "missing in this run"
    try:
        a, b = _load_staout(ref_path), _load_staout(out_path)
    except (OSError, ValueError) as exc:
        return False, f"unreadable ({exc})"
    if a.shape != b.shape:
        return False, f"shape {a.shape} vs {b.shape}"
    if a.size == 0:
        return False, "empty"
    same, _, problem = _compare_var("time column", a[:, 0], b[:, 0], 0.0)
    if problem or not same:
        return False, problem or "time column differs"
    same, mx, problem = _compare_var("values", a[:, 1:], b[:, 1:], tol)
    if problem:
        return False, problem
    if same:
        return True, f"bitwise identical ({a.shape[0]} records x {a.shape[1] - 1} stations)"
    if mx > tol:
        return False, f"max |diff| {mx:.3g} > tol {tol:g}"
    return True, f"max |diff| {mx:.3g} <= tol {tol:g}"


def regress(args) -> int:
    ref, out = Path(args.ref), Path(args.out)
    files = regress_files(args.variant, args.level, args.pdy, args.cyc)
    print(f"regress: {args.variant} LEVEL={args.level} {args.pdy}t{args.cyc}z: bitwise first, else within tol x ratio "
          f"(water level {args.tol:g} m; temperature/salinity x10; pressure x100)")
    nc_tol = {k: v * args.tol for k, v in NC_RATIO.items()}
    fails = bit = near = 0
    for rel in files:
        r, o = ref / rel, out / rel
        if not r.is_file():
            print(f"FAIL  {rel}: not in the reference ({r})")
            fails += 1
            continue
        base = Path(rel).name
        if base.startswith(STAOUT_PREFIX):
            ok, text = compare_staout(r, o, STAOUT_RATIO[int(base[len(STAOUT_PREFIX):])] * args.tol)
        else:
            ok, text = compare_file(r, o, nc_tol)
        print(f"{'PASS' if ok else 'FAIL'}  {rel}: {text}")
        fails += not ok
        bit += ok and text.startswith("bitwise")
        near += ok and not text.startswith("bitwise")
    print(f"regress: {len(files)} files, {bit} bitwise, {near} within tolerance, {fails} failed")
    return 1 if fails else 0


def _epoch(var) -> np.ndarray:
    """Time variable as whole seconds since 1970 (units 'seconds|hours|days since YYYY-MM-DD HH:MM:SS[ UTC]'). MJ (10/14/26)"""
    m = re.match(r"\s*(second|minute|hour|day)s?\s+since\s+(\d{4})-(\d\d)-(\d\d)(?:[ T](\d\d):(\d\d):(\d\d))?", var.units)
    if not m:
        raise ValueError(f"unsupported time units {var.units!r}")
    scale = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[m.group(1)]
    y, mo, d, hh, mi, ss = (int(x or 0) for x in m.groups()[1:])
    base = timegm(datetime(y, mo, d, hh, mi, ss).timetuple())
    return np.round(base + np.asarray(var[:], dtype="f8") * scale).astype("i8")


def _names(d):
    if "station_name" not in d.variables:
        return None
    return [s.strip() for s in nc.chartostring(d.variables["station_name"][:])]


def _wl(path: Path):
    with nc.Dataset(path) as d:
        z = np.ma.masked_invalid(d.variables["zeta"][:])
        return _epoch(d.variables["time"]), np.ma.masked_outside(z, -900, 900), _names(d)


def match_stations(na, nb, ca: int, cb: int):
    """(index_a, index_b): row order when the counts agree, else exact name; None when nothing matches. MJ (10/14/26)"""
    if ca == cb:
        idx = np.arange(ca)
        return idx, idx
    if na and nb:
        common = [n for n in dict.fromkeys(na) if n in nb and na.count(n) == 1 and nb.count(n) == 1]
        if common:
            return np.array([na.index(n) for n in common]), np.array([nb.index(n) for n in common])
    return None


def cmp_points(ours: Path, ops: Path, warn_mm: float):
    """Station water level over the common times, printed; WARN beyond warn_mm. Returns (median mm, stations over 10 cm), or None
    when nothing could be compared. MJ (10/22/26)"""
    ta, za, names = _wl(ours)
    tb, zb, nb = _wl(ops)
    common, ia, ib = np.intersect1d(ta, tb, return_indices=True)
    if not len(common):
        print("  WARN no common times with the ops file")
        return None
    m = match_stations(names, nb, za.shape[1], zb.shape[1])
    if m is None:
        print(f"  WARN station counts differ ({za.shape[1]} vs {zb.shape[1]} ops) and no names match")
        return None
    sa, sb = m
    za, zb = za[ia][:, sa], zb[ib][:, sb]
    d = np.ma.abs(za - zb).max(axis=0) * 1000.0
    # a 1e7 or -99999 fill value is masked by _wl, so a masked value counts as skipped too. MJ (10/14/26)
    odd = (np.ma.getmaskarray(za).any(axis=0) | np.ma.getmaskarray(zb).any(axis=0)
           | np.ma.filled(np.ma.abs(za) > 20, False).any(axis=0) | np.ma.filled(np.ma.abs(zb) > 20, False).any(axis=0))
    d[odd] = np.ma.masked
    print("  %d common times (%d this run, %d ops), %d stations compared, %d skipped (|WL| > 20 m)"
          % (len(common), len(ta), len(tb), d.count(), odd.sum()))
    if not d.count():
        print("  WARN no station left to compare")
        return None
    med = float(np.ma.median(d))
    over = int((d > 100).sum())
    print("  per-station max |dWL|: median %.2f mm; within 1 mm %d, within 1 cm %d, over 10 cm %d"
          % (med, (d <= 1).sum(), (d <= 10).sum(), over))
    for i in [j for j in np.argsort(d.filled(-1))[::-1] if not np.ma.getmaskarray(d)[j]][:5]:
        k = sa[i]
        print("    worst: %8.1f mm  %s" % (d[i], names[k] if names else k))
    if med > warn_mm:
        print(f"  WARN median {med:.1f} mm is above the {warn_mm:g} mm report threshold (not a failure)")
    return med, over


def ops(args) -> int:
    day, ops_dir = _day(Path(args.out), args.pdy), Path(args.ops_dir)
    on = ops_names(args.cyc)
    stem = f"{RUN}.t{args.cyc}z.{args.pdy}"
    pairs = [(f"{stem}.points.cwl.{ph}.nc", on["points"]) for ph in ("nowcast", "forecast")]
    pairs += [(f"{stem}.station.profile.{ph}.nc", on[ph]) for ph in ("nowcast", "forecast")]
    fails = 0
    gate = args.fail_median_mm is not None and args.fail_over_10cm is not None
    print(f"ops: {args.variant} {args.pdy}t{args.cyc}z: "
          + (f"pass/fail, a file fails when the median per-station max |dWL| exceeds {args.fail_median_mm:g} mm or more than {args.fail_over_10cm} stations are over 10 cm"
             if gate else f"report only, a median per-station max |dWL| above {args.warn_mm:g} mm is flagged"))
    for mine_name, ops_name in pairs:
        mine, theirs = day / mine_name, ops_dir / ops_name
        if not mine.is_file() or mine.stat().st_size == 0:
            print(f"FAIL  {mine_name}: missing in this run")
            fails += 1
            continue
        if not theirs.is_file():
            print(f"SKIP  {mine_name}: no ops product {ops_name} in {ops_dir}")
            continue
        print(f"{mine_name} vs {ops_name}")
        try:
            res = cmp_points(mine, theirs, args.warn_mm)
        except (OSError, RuntimeError, KeyError, ValueError) as exc:
            print(f"  WARN comparison failed: {exc}")
            res = None
        if gate and res is None:
            print(f"FAIL  {mine_name}: nothing compared with {ops_name}")
            fails += 1
        elif gate:
            med, over = res
            bad = [f"median {med:.2f} mm > {args.fail_median_mm:g} mm"] if med > args.fail_median_mm else []
            bad += [f"{over} stations over 10 cm > {args.fail_over_10cm}"] if over > args.fail_over_10cm else []
            for b in bad:
                print(f"FAIL  {mine_name}: {b}")
            if not bad:
                print(f"PASS  {mine_name}")
            fails += bool(bad)
    return 1 if fails else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("files", "regress", "ops", "ops-files"):
        s = sub.add_parser(name)
        s.add_argument("--pdy", required=True)
        s.add_argument("--cyc", default="12")
        if name != "ops-files":
            s.add_argument("--variant", choices=VARIANTS, required=name != "ops-files")
    for name in ("files", "regress"):
        sub.choices[name].add_argument("--level", choices=LEVELS, required=True)
    s = sub.choices["regress"]
    s.add_argument("--ref", required=True, help="the dataset's ref/ directory (same layout as COMROOT)")
    s.add_argument("--out", required=True, help="COMROOT of this run")
    s.add_argument("--tol", type=float, default=1e-3)
    s = sub.choices["ops"]
    s.add_argument("--out", required=True, help="COMROOT of this run")
    s.add_argument("--ops-dir", required=True)
    s.add_argument("--warn-mm", type=float, default=500.0)
    s.add_argument("--fail-median-mm", type=float, default=None, help="fail a file whose median per-station max |dWL| exceeds this (needs --fail-over-10cm)")
    s.add_argument("--fail-over-10cm", type=int, default=None, help="fail a file with more stations than this over 100 mm (needs --fail-median-mm)")
    args = p.parse_args(argv)
    if args.cmd == "ops" and (args.fail_median_mm is None) != (args.fail_over_10cm is None):
        p.error("--fail-median-mm and --fail-over-10cm go together")
    if args.cmd == "files":
        print("\n".join(regress_files(args.variant, args.level, args.pdy, args.cyc)))
        return 0
    if args.cmd == "ops-files":
        print("\n".join(ops_names(args.cyc).values()))
        return 0
    return regress(args) if args.cmd == "regress" else ops(args)


if __name__ == "__main__":
    sys.exit(main())
