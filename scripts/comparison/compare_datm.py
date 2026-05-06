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


def diff_var(ds_a, ds_b, name: str, rtol: float, atol: float):
    if name not in ds_a.variables or name not in ds_b.variables:
        return False, f"{name}: MISSING (a={name in ds_a.variables} b={name in ds_b.variables})"

    a = np.asarray(ds_a.variables[name][:], dtype=np.float64)
    b = np.asarray(ds_b.variables[name][:], dtype=np.float64)

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

    # Data variables
    print(f"--- variables (rtol={args.rtol}, atol={args.atol}) ---")
    all_pass = dims_match
    for name in DATM_VARS:
        ok, msg = diff_var(ds_a, ds_b, name, args.rtol, args.atol)
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
