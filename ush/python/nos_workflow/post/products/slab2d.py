"""slab2d worker: 2D slabs (surface/bottom/fixed-depth) per output stack.

Runs as ``python3 -m nos_workflow.post.products.slab2d`` from the post
stage and delegates the compute to
:func:`nos_utils.post.slab2d.write_slab2d` (the port of the operational
``extract_slab_fcst_netcdf4.py``, which ``stofs_3d_atl_create_2d_field_nc.sh``
runs once per output stack -- ops calls the results ``field2d_*``). This
module owns only orchestration: which stack indices are complete, the
canonical COMOUT name, and the ops knobs.

One slab consumes six co-indexed stacks (out2d, zCoordinates,
temperature, salinity, horizontalVelX, horizontalVelY). Indices missing
any of them are skipped with a warning naming what was missing, so a
2D-only or partially staged cycle publishes less rather than failing the
post stage.

Hour labels come from ``products.fields``: the same phase-relative
detection, so ``field2d`` and ``fields`` stacks of one cycle carry
matching ``{n|f}{HHH}_{HHH}`` ranges on every system (STOFS-3D-ATL
standalone continues the nowcast clock, SECOFS restarts it).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..naming import field2d_stack_name
from .fields import _hour_range, _phase_start_hours

# The six co-indexed stacks one slab needs, in write_slab2d() order.
SLAB_FAMILIES = (
    "out2d",
    "zCoordinates",
    "temperature",
    "salinity",
    "horizontalVelX",
    "horizontalVelY",
)

# Ops interpolates velocity at these depths below the free surface.
OPS_DEPTHS = "0.5,4.5"


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    staging = Path(args.staging)
    comout = Path(args.comout)
    if not staging.is_dir():
        print(f"slab2d: staging dir missing: {staging}")
        return 2

    stacks = _stacks_by_index(staging)
    if not stacks:
        print(f"slab2d: no field stacks in {staging}")
        return 3

    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        print(f"slab2d: netCDF4 unavailable: {exc}")
        return 4
    try:
        from nos_utils.post.slab2d import write_slab2d
    except ImportError as exc:
        print(f"slab2d: nos_utils.post unavailable: {exc}")
        return 4

    depths = _parse_depths(args.depths)
    phase_start = _phase_start_hours(
        Dataset, staging, args.phase, args.nowcast_hours
    )
    if phase_start:
        print(f"slab2d: labels are phase-relative (offset {phase_start:g} h)")

    from ..worker_base import base_date_from_staging
    base_date = base_date_from_staging(staging) or args.base_date

    created: List[str] = []
    for index in sorted(stacks):
        found = stacks[index]
        missing = [f for f in SLAB_FAMILIES if f not in found]
        if missing:
            print(
                f"slab2d: stack {index} incomplete, missing "
                f"{', '.join(missing)}; skipped"
            )
            continue
        hours = _hour_range(Dataset, found["out2d"], phase_start)
        if hours is None:
            print(f"slab2d: stack {index}: empty/no time axis, skipped")
            continue
        name = field2d_stack_name(
            args.prefix, args.cyc, args.pdy, args.phase, *hours
        )
        out_path = comout / name
        try:
            write_slab2d(
                *(found[family] for family in SLAB_FAMILIES),
                out_path,
                base_date,
                depths=depths,
                datum=args.datum,
            )
        except (OSError, ValueError) as exc:
            # Unreadable stack or an out2d without the mesh variables:
            # drop the partial file and keep the other stacks.
            print(f"slab2d: stack {index} skipped: {exc}")
            out_path.unlink(missing_ok=True)
            continue
        created.append(str(out_path))
        print(f"slab2d: stack {index} -> {name}")

    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps({"created": created}, indent=2)
        )

    print(f"slab2d: wrote {len(created)} slab(s) for {args.phase}")
    return 0


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--staging", required=True)
    p.add_argument("--comout", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--cyc", required=True)
    p.add_argument("--pdy", required=True)
    p.add_argument("--phase", required=True, choices=("nowcast", "forecast"))
    p.add_argument(
        "--base-date", required=True,
        help="time-units base, e.g. '2026-07-22 12:00'",
    )
    p.add_argument(
        "--nowcast-hours", type=float, default=0.0,
        help="length of the nowcast leg; see products.fields (phase-relative "
             "hour labels on systems whose forecast continues the nowcast "
             "clock)",
    )
    p.add_argument(
        "--depths", default=OPS_DEPTHS,
        help="comma-separated depths below the free surface for the "
             "interpolated velocity slabs (ops: 0.5,4.5)",
    )
    p.add_argument(
        "--datum", default="xgeoid20b",
        help="vertical datum branded on depth/zeta (ops: xgeoid20b)",
    )
    p.add_argument("--result-json", default="")
    return p.parse_args(argv)


def _parse_depths(raw: str) -> Tuple[float, ...]:
    """Depths below the free surface from the CLI list."""
    return tuple(float(tok) for tok in raw.split(",") if tok.strip())


def _stacks_by_index(staging: Path) -> Dict[int, Dict[str, Path]]:
    """``{stack index: {family: path}}`` over the six slab families."""
    found: Dict[int, Dict[str, Path]] = {}
    for family in SLAB_FAMILIES:
        rx = re.compile(rf"^{re.escape(family)}_(\d+)\.nc$")
        for f in staging.glob(f"{family}_*.nc"):
            m = rx.match(f.name)
            if m:
                found.setdefault(int(m.group(1)), {})[family] = f
    return found


if __name__ == "__main__":
    sys.exit(main())
