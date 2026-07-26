#!/usr/bin/env python3
"""Value-parity comparator: canonical fields stacks vs ops fields files.

Compares one canonical per-variable stack
(``{prefix}.t{cyc}z.{pdy}.fields.{var}.{n|f}HHH_HHH.nc``) against one or
more operational per-timestep files (``secofs.t{cyc}z.{pdy}.fields.{n|f}KKK.nc``
or any file holding the same variable). Records are aligned by absolute
valid time (decoded from each file's ``time`` units), so differing run
starts and stack layouts don't matter.

Per matched record it reports RMSE, max |diff|, correlation, and
fill-mask agreement over the node dimension. Node counts must match
(same mesh); node *ordering* differences will show up as large diffs --
interpret accordingly.

Usage:
  python3 tools/compare_fields_products.py \
      --ours $COMOUT/secofs_ufs.t12z.20260721.fields.temperature.f001_006.nc \
      --var temperature \
      --ops /path/ops/secofs.t12z.20260721.fields.f001.nc [more ops files...]
  # different variable name on the ops side:
  #   --ops-var temperature
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
from netCDF4 import Dataset, num2date

FILL = -99999.0


def _times(ds):
    tv = ds.variables["time"]
    return [
        d.strftime("%Y-%m-%d %H:%M")
        for d in num2date(tv[:], tv.units)
    ]


def _flat_record(var, idx):
    """Record ``idx`` flattened to 1-D per node (3D vars flatten levels)."""
    arr = np.ma.filled(var[idx], FILL).astype("f8")
    return arr.reshape(-1)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ours", required=True, help="canonical stack file")
    p.add_argument("--var", required=True, help="variable name in --ours")
    p.add_argument("--ops", required=True, nargs="+",
                   help="ops file(s) holding the same variable")
    p.add_argument("--ops-var", default=None,
                   help="variable name on the ops side (default: --var)")
    p.add_argument("--rmse-tol", type=float, default=None,
                   help="exit 1 if any matched record's RMSE exceeds this")
    args = p.parse_args(argv)
    ops_var = args.ops_var or args.var

    ours = Dataset(args.ours)
    if args.var not in ours.variables:
        print(f"ERROR: {args.var!r} not in {args.ours}")
        return 2
    our_times = _times(ours)
    print(f"ours: {args.ours}")
    print(f"  records: {len(our_times)}  ({our_times[0]} .. {our_times[-1]})")

    worst = 0.0
    matched = 0
    print(f"\n{'valid time':17s} {'RMSE':>12s} {'max|diff|':>12s} "
          f"{'corr':>8s} {'fill=':>7s} {'n':>9s}")
    for ops_path in args.ops:
        with Dataset(ops_path) as ops:
            if ops_var not in ops.variables:
                print(f"{ops_path}: no {ops_var!r}, skipped")
                continue
            for k, when in enumerate(_times(ops)):
                if when not in our_times:
                    print(f"{when:17s}  -- not in ours ({ops_path}), skipped")
                    continue
                a = _flat_record(ops.variables[ops_var], k)
                b = _flat_record(
                    ours.variables[args.var], our_times.index(when)
                )
                if a.size != b.size:
                    print(f"{when:17s}  -- size mismatch ops={a.size} "
                          f"ours={b.size}; different mesh/levels?")
                    continue
                fill_a = a == FILL
                fill_b = b == FILL
                both = ~fill_a & ~fill_b
                if not both.any():
                    print(f"{when:17s}  -- all-fill on one side")
                    continue
                d = a[both] - b[both]
                rmse = float(np.sqrt(np.mean(d * d)))
                mx = float(np.abs(d).max())
                corr = float(np.corrcoef(a[both], b[both])[0, 1])
                fill_agree = float((fill_a == fill_b).mean())
                print(f"{when:17s} {rmse:12.6f} {mx:12.6f} "
                      f"{corr:8.5f} {fill_agree:7.1%} {both.sum():9d}")
                worst = max(worst, rmse)
                matched += 1

    print(f"\nmatched records: {matched}   worst RMSE: {worst:.6f}")
    if args.rmse_tol is not None and (matched == 0 or worst > args.rmse_tol):
        print(f"FAIL: worst RMSE {worst} exceeds tolerance {args.rmse_tol}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
