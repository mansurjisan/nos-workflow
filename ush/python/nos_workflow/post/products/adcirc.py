"""adcirc worker: ADCIRC-format water-level fields (the CERA product).

Runs as ``python3 -m nos_workflow.post.products.adcirc`` from the post
stage and delegates the compute to
:func:`nos_utils.post.adcirc.write_adcirc` (the port of the operational
``pysh/generate_adcirc.py``, driven by
``stofs_3d_atl_create_adcirc_nc.sh``). This module owns only
orchestration: which stacks go into which published file, the canonical
COMOUT name, the optional city mask, and the ops-parity time stamp.

Ops packaging, and what of it we keep: ops writes 12 h output stacks and
``ncrcat``s them in PAIRS before the python step, so each published file
covers 24 h -- one CERA "day" -- and carries THAT day's ``zeta_max`` /
``disturbance_max``. The pair merge is therefore part of the product (it
sets the reduction window and the per-file size), not shell bookkeeping,
so it is reproduced here generically: consecutive stacks are grouped
until the group spans ``--group-hours`` (24 by default = ops' day; 0
publishes one file per stack). Whole-run maxima remain the ``maxele``
product's job.

Downstream: the AWIPS grib2 step (``stofs_3d_atl_create_awips_grib2.sh``)
``cd``s into ops' working ``dir_adcirc_nc``, ``ncrcat``s the whole set
into one file and lets ``stofs_3d_atl_netcdf2grib`` walk forecast hours
over the merged record axis. It therefore needs the set complete,
chronologically ordered and on one mesh -- properties the canonical
hour-range name states outright (see
:func:`nos_workflow.post.naming.adcirc_name`), unlike ops' calendar-date
name, which needs a hand-maintained ``list_YMD`` array because an ops
"day" is not a calendar day at all: it is a 24 h window anchored at the
cycle hour and labelled with its START date.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from ..naming import adcirc_name
from ..worker_base import atomic_publish, base_date_from_staging
from .fields import _hour_range, _phase_start_hours
from .maxele import _out2d_stacks

# Ops merges two 12 h stacks per published file.
OPS_GROUP_HOURS = 24.0

# (path, (start hour, end hour)) for one staged stack.
Span = Tuple[Path, Tuple[int, int]]


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    staging = Path(args.staging)
    comout = Path(args.comout)
    if not staging.is_dir():
        print(f"adcirc: staging dir missing: {staging}")
        return 2

    stacks = _out2d_stacks(staging)
    if not stacks:
        print(f"adcirc: no out2d stacks in {staging}")
        return 3

    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        print(f"adcirc: netCDF4 unavailable: {exc}")
        return 4
    try:
        from nos_utils.post.adcirc import write_adcirc
    except ImportError as exc:
        print(f"adcirc: nos_utils.post unavailable: {exc}")
        return 4

    city_mask = _city_mask(args.city_nodes)

    phase_start = _phase_start_hours(
        Dataset, staging, args.phase, args.nowcast_hours
    )
    if phase_start:
        print(f"adcirc: labels are phase-relative (offset {phase_start:g} h)")

    # Ops copies the input file's own time:units / base_date through to the
    # product; inherit both so the stamp cannot drift from the data (the
    # --base-date argument is only the fallback for unreadable stacks).
    base_date = base_date_from_staging(staging) or args.base_date
    time_units = _time_units(Dataset, stacks)
    print(f"adcirc: time origin {base_date!r}, units {time_units!r}")

    spans: List[Span] = []
    for path in stacks:
        try:
            hours = _hour_range(Dataset, path, phase_start)
        except OSError as exc:
            print(f"adcirc: {path.name} unreadable ({exc}); skipped")
            continue
        if hours is None:
            print(f"adcirc: {path.name}: empty/no time axis, skipped")
            continue
        spans.append((path, hours))

    created: List[str] = []
    failed = 0
    for group in _group_stacks(spans, args.group_hours):
        paths = [p for p, _h in group]
        name = adcirc_name(
            args.prefix, args.cyc, args.pdy, args.phase,
            group[0][1][0], group[-1][1][1],
        )
        out_path = comout / name
        try:
            with atomic_publish(out_path) as tmp:
                write_adcirc(
                    paths,
                    tmp,
                    base_date=base_date,
                    datum=args.datum,
                    city_mask=city_mask,
                    min_disturbance=args.min_disturbance,
                    time_units=time_units,
                )
        except Exception as exc:  # noqa: BLE001
            # An unreadable stack, a mesh-less out2d, a city mask sized for
            # another grid -- keep the other days. atomic_publish has
            # already removed the partial, so COMOUT stays clean.
            print(f"adcirc: {name} skipped: {exc!r}")
            failed += 1
            continue
        created.append(str(out_path))
        print(f"adcirc: {' + '.join(p.name for p in paths)} -> {name}")

    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps({"created": created}, indent=2)
        )

    print(f"adcirc: wrote {len(created)} file(s) for {args.phase}")
    # Nothing published *because every write failed* is a failure, not the
    # empty-input skip the base class would otherwise report.
    return 5 if (failed and not created) else 0


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
        help="time-units base, e.g. '2026-07-22 12:00'. FALLBACK ONLY: the "
             "stamp is inherited from the stacks when they carry units, as "
             "ops does.",
    )
    p.add_argument(
        "--nowcast-hours", type=float, default=0.0,
        help="length of the nowcast leg; see products.fields (phase-relative "
             "hour labels on systems whose forecast continues the nowcast "
             "clock)",
    )
    p.add_argument(
        "--city-nodes", default="",
        help="ops node-id city file (one 0.0/1.0 per mesh node) marking "
             "urban nodes whose small disturbances are masked out. Optional: "
             "without it no urban masking is applied, as in ops when no city "
             "identifier is given.",
    )
    p.add_argument(
        "--group-hours", type=float, default=OPS_GROUP_HOURS,
        help="hours of model time per published file (ops: 24, its pair "
             "merge). 0 publishes one file per staged stack.",
    )
    p.add_argument(
        "--datum", default="xGEOID20B",
        help="vertical datum branded on depth/zeta (ops: xGEOID20B)",
    )
    p.add_argument(
        "--min-disturbance", type=float, default=0.3,
        help="disturbances below this (m) are masked on land/city nodes "
             "(ops: 0.3)",
    )
    p.add_argument("--result-json", default="")
    return p.parse_args(argv)


def _city_mask(path_str: str):
    """Ops' node-id city file as a boolean mask; None when unavailable.

    The fix file is the cached result of ops' point-in-polygon search over
    the urban shapefile: one float per line (0.0/1.0), one per mesh node.
    Absent or unreadable means "no urban masking" -- the writer's own
    no-city-mask behaviour -- never a failure, since only STOFS-3D-ATL
    ships the file.
    """
    if not path_str:
        print("adcirc: no city node-id file given; urban masking off")
        return None
    path = Path(path_str)
    if not path.is_file():
        print(f"adcirc: city node-id file missing: {path}; urban masking off")
        return None
    import numpy as np

    try:
        mask = np.loadtxt(path, encoding="utf-8").astype(bool)
    except Exception as exc:  # noqa: BLE001
        print(f"adcirc: city node-id file unreadable ({exc!r}); masking off")
        return None
    print(f"adcirc: city mask: {int(mask.sum())} of {mask.size} nodes")
    return mask


def _time_units(Dataset, stacks: Sequence[Path]) -> Optional[str]:
    """The stacks' own ``time:units``, copied verbatim as ops does.

    ``base_date_from_staging`` recovers the origin; this keeps the units
    string itself byte-identical to the model output rather than
    re-synthesising ``seconds since {base_date}``. None (no readable
    stack) leaves the writer to synthesise it.
    """
    for path in stacks:
        try:
            with Dataset(path, "r") as ds:
                units = getattr(ds.variables["time"], "units", "")
        except Exception:  # noqa: BLE001
            continue
        if units:
            return str(units)
    return None


def _group_stacks(
    spans: Sequence[Span], group_hours: float
) -> List[List[Span]]:
    """Batch consecutive stacks into ``group_hours``-wide output files.

    A stack joins the open group while the group would still span less
    than ``group_hours`` -- with ops' 12 h stacks and the 24 h default
    that reproduces the operational pair merge exactly, and it stays
    correct for any other output cadence (a stack longer than the window
    simply becomes its own group). ``group_hours <= 0`` publishes one file
    per stack.
    """
    if group_hours <= 0:
        return [[span] for span in spans]
    groups: List[List[Span]] = []
    for span in spans:
        if groups and (span[1][1] - groups[-1][0][1][0]) < group_hours:
            groups[-1].append(span)
        else:
            groups.append([span])
    return groups


if __name__ == "__main__":
    sys.exit(main())
