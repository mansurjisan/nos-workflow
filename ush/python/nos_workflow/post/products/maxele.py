"""maxele worker: maximum water level over the forecast window.

Runs as ``python3 -m nos_workflow.post.products.maxele`` from the post
stage and delegates the compute to :func:`nos_utils.post.maxele.write_maxele`
(the port of the operational ``stofs_3d_atl_create_AWS_autoval_nc.sh``
NCO chain). This module owns only orchestration: which stacks to feed,
the canonical COMOUT name, and the ops-parity arguments.

Ops parity notes (from the nos-utils review ledger):
  * ops reduces the FORECAST stacks only, so the caller stages those;
  * ops hardcodes the 2-point time coordinate to (90000, 432000) s, so
    ``--window-seconds`` is passed rather than derived, unless the
    caller opts out with ``--window-from-data``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional

from ..naming import product_stem

# Ops autoval window: 25 h .. 120 h from the run origin -- correct only
# for a 24 h nowcast + 96 h forecast, which is ops' configuration.
OPS_WINDOW_SECONDS = (90000.0, 432000.0)

_STACK_RE = re.compile(r"^out2d_(\d+)\.nc$")


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    staging = Path(args.staging)
    comout = Path(args.comout)
    if not staging.is_dir():
        print(f"maxele: staging dir missing: {staging}")
        return 2

    stacks = _out2d_stacks(staging)
    if not stacks:
        print(f"maxele: no out2d stacks in {staging}")
        return 3

    try:
        from nos_utils.post.maxele import write_maxele
    except ImportError as exc:
        print(f"maxele: nos_utils.post unavailable: {exc}")
        return 4

    out_path = comout / (
        f"{product_stem(args.prefix, args.cyc, args.pdy)}.fields.cwl.maxele.nc"
    )
    # Ops copies the model's own time origin through; inherit it when the
    # stacks carry it so the stamp cannot drift from the data.
    from ..worker_base import atomic_publish, base_date_from_staging
    base_date = base_date_from_staging(staging) or args.base_date
    window = OPS_WINDOW_SECONDS if args.ops_window else None

    print(f"maxele: reducing {len(stacks)} stack(s) -> {out_path.name}")
    with atomic_publish(out_path) as tmp:
        write_maxele(
            stacks, tmp, base_date=base_date, window_seconds=window,
        )

    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps({"created": [str(out_path)]}, indent=2)
        )
    print(f"maxele: wrote {out_path.name}")
    return 0


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--staging", required=True)
    p.add_argument("--comout", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--cyc", required=True)
    p.add_argument("--pdy", required=True)
    p.add_argument(
        "--base-date", required=True,
        help="time-units base, e.g. '2026-07-22 12:00'",
    )
    p.add_argument(
        "--ops-window", action="store_true",
        help="stamp the ops-hardcoded (90000, 432000) s time coordinate. "
             "OFF by default: that constant is simply the data-derived "
             "window of ops' own 5-day run, so on a run of a different "
             "length (this branch forecasts 108 h, not 96) it would "
             "advertise a window the data does not cover.",
    )
    p.add_argument("--result-json", default="")
    return p.parse_args(argv)


def _out2d_stacks(staging: Path) -> List[Path]:
    """out2d stacks in stack order."""
    hits = []
    for f in staging.glob("out2d_*.nc"):
        m = _STACK_RE.match(f.name)
        if m:
            hits.append((int(m.group(1)), f))
    return [f for _i, f in sorted(hits)]


if __name__ == "__main__":
    sys.exit(main())
