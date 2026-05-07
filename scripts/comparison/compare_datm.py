#!/usr/bin/env python3
"""Compare two datm_forcing.nc files: shell-based vs nos-utils.

Usage:
    python3 compare_datm.py SHELL.nc NOSUTILS.nc [--rtol 1e-4 --atol 1e-3]

Reports per-variable shape/dtype/max-abs-diff/RMSE and PASS/FAIL.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


DATM_VARS = [
    "UGRD_10maboveground",
    "VGRD_10maboveground",
    "TMP_2maboveground",
    "SPFH_2maboveground",
    "MSLMA_meansealevel",
    "PRATE_surface",
    "DSWRF_surface",
    "DLWRF_surface",
]


def load(path: Path):
    ds = Dataset(str(path))
    info = {
        "dims": {d: len(ds.dimensions[d]) for d in ds.dimensions},
        "vars": {},
    }
    for v in ds.variables:
        info["vars"][v] = {
            "shape": ds.variables[v].shape,
            "dtype": str(ds.variables[v].dtype),
        }
    return ds, info


def diff_axis(a: np.ndarray, b: np.ndarray, name: str):
    if a.shape != b.shape:
        return f"{name}: SHAPE MISMATCH a={a.shape} b={b.shape}"
    d = np.abs(a - b)
    return f"{name}: shape={a.shape} max|d|={d.max():.6g} mean|d|={d.mean():.6g}"


def _align_times(ds_a, ds_b):
    """Find indices where ds_a.time matches ds_b.time (within 1 second).

    Returns (idx_a, idx_b) — arrays of matching indices into each dataset,
    or (None, None) if no time variable.
    """
    if "time" not in ds_a.variables or "time" not in ds_b.variables:
        return None, None
    ta = np.asarray(ds_a.variables["time"][:], dtype=np.float64)
    tb = np.asarray(ds_b.variables["time"][:], dtype=np.float64)
    idx_a, idx_b = [], []
    for ia, va in enumerate(ta):
        match = np.where(np.abs(tb - va) < 1.0)[0]
        if len(match) > 0:
            idx_a.append(ia)
            idx_b.append(int(match[0]))
    if not idx_a:
        return None, None
    return np.array(idx_a, dtype=int), np.array(idx_b, dtype=int)


def diff_var(ds_a, ds_b, name: str, rtol: float, atol: float,
             idx_a=None, idx_b=None):
    if name not in ds_a.variables or name not in ds_b.variables:
        return False, f"{name}: MISSING (a={name in ds_a.variables} b={name in ds_b.variables})"

    a = np.asarray(ds_a.variables[name][:], dtype=np.float64)
    b = np.asarray(ds_b.variables[name][:], dtype=np.float64)

    # If shapes differ on time axis but caller provided index alignment, slice.
    if idx_a is not None and idx_b is not None and a.shape != b.shape:
        if a.ndim >= 1 and b.ndim >= 1 and a.shape[0] != b.shape[0]:
            a = a[idx_a]
            b = b[idx_b]

    if a.shape != b.shape:
        return False, f"{name}: SHAPE MISMATCH a={a.shape} b={b.shape}"

    finite = np.isfinite(a) & np.isfinite(b)
    if not finite.any():
        return True, f"{name}: all-NaN both sides (ok)"

    d = np.abs(a[finite] - b[finite])
    scale = np.abs(b[finite])
    rel = np.where(scale > 0, d / np.maximum(scale, atol), d)

    max_abs = float(d.max())
    rmse = float(np.sqrt((d ** 2).mean()))
    p99 = float(np.percentile(d, 99))
    max_rel = float(rel.max())

    a_min, a_max = float(a[finite].min()), float(a[finite].max())
    b_min, b_max = float(b[finite].min()), float(b[finite].max())

    passed = max_abs <= atol or max_rel <= rtol

    line = (
        f"{name}: shape={a.shape} "
        f"a=[{a_min:+.4g},{a_max:+.4g}] b=[{b_min:+.4g},{b_max:+.4g}] "
        f"max|d|={max_abs:.4g} rmse={rmse:.4g} p99|d|={p99:.4g} "
        f"max_rel={max_rel:.4g} {'PASS' if passed else 'FAIL'}"
    )
    return passed, line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shell", type=Path, help="Shell-based datm_forcing.nc")
    ap.add_argument("nosutils", type=Path, help="nos-utils datm_forcing.nc")
    ap.add_argument("--rtol", type=float, default=1e-4)
    ap.add_argument("--atol", type=float, default=1e-3)
    args = ap.parse_args()

    if not args.shell.exists():
        print(f"ERROR: not found: {args.shell}", file=sys.stderr)
        sys.exit(2)
    if not args.nosutils.exists():
        print(f"ERROR: not found: {args.nosutils}", file=sys.stderr)
        sys.exit(2)

    ds_a, info_a = load(args.shell)
    ds_b, info_b = load(args.nosutils)

    print(f"shell:    {args.shell}  size={args.shell.stat().st_size / 1e6:.1f} MB")
    print(f"nosutils: {args.nosutils}  size={args.nosutils.stat().st_size / 1e6:.1f} MB")
    print()

    # Dimensions
    print("--- dimensions ---")
    all_dims = sorted(set(info_a["dims"]) | set(info_b["dims"]))
    dims_match = True
    for d in all_dims:
        sa = info_a["dims"].get(d, "MISSING")
        sb = info_b["dims"].get(d, "MISSING")
        flag = "OK" if sa == sb else "FAIL"
        if sa != sb:
            dims_match = False
        print(f"  {d}: shell={sa} nosutils={sb} [{flag}]")
    print()

    # Coordinate axes
    print("--- coordinate axes ---")
    for axis in ("time", "latitude", "longitude", "lat", "lon"):
        if axis in ds_a.variables and axis in ds_b.variables:
            a = np.asarray(ds_a.variables[axis][:], dtype=np.float64)
            b = np.asarray(ds_b.variables[axis][:], dtype=np.float64)
            print(f"  {diff_axis(a, b, axis)}")
    print()

    # Time alignment — when time counts differ, find the common subset
    # so we can still compare values at matching timesteps.
    idx_a, idx_b = _align_times(ds_a, ds_b)
    if idx_a is not None and len(idx_a) > 0:
        nt_a = len(ds_a.variables["time"][:]) if "time" in ds_a.variables else 0
        nt_b = len(ds_b.variables["time"][:]) if "time" in ds_b.variables else 0
        if nt_a != nt_b:
            print(f"--- time alignment ---")
            print(f"  shell n_times={nt_a}, nosutils n_times={nt_b}, "
                  f"common={len(idx_a)} (matched within 1s)")
            print()

    # Data variables
    print(f"--- variables (rtol={args.rtol}, atol={args.atol}) ---")
    all_pass = dims_match
    for name in DATM_VARS:
        ok, msg = diff_var(ds_a, ds_b, name, args.rtol, args.atol, idx_a, idx_b)
        print(f"  {msg}")
        if not ok:
            all_pass = False
    print()

    print(f"=== OVERALL: {'PASS' if all_pass else 'FAIL'} ===")
    ds_a.close()
    ds_b.close()
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
