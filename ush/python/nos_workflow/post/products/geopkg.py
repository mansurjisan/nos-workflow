"""geopkg worker: per-timestep disturbance GeoPackages (nowCOAST feed).

Runs as ``python3 -m nos_workflow.post.products.geopkg`` from the post
stage and delegates the compute to
:func:`nos_utils.post.geopkg.write_disturbance_series` (the port of the
operational ``gen_geojson.py`` driven by
``stofs_3d_atl_create_geopackage.sh``). Only the out2d stacks are
needed: elevation plus the mesh read from the first stack.

Naming keeps the ops timestep convention -- nowcast records count down
to ``n000`` at the cycle time, forecast records count up from ``f001``
-- under our canonical stem, so nos-utils' ``nowcast_forecast_namer``
is replaced by the local :func:`_namer`.

The contour/geometry stack (matplotlib, shapely, geopandas) is optional
at runtime. When it is missing the worker warns and reports nothing
created, which the product turns into "skipped" rather than a failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from ..naming import disturbance_gpkg_name

_STACK_RE = re.compile(r"^out2d_(\d+)\.nc$")


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    staging = Path(args.staging)
    comout = Path(args.comout)
    if not staging.is_dir():
        print(f"geopkg: staging dir missing: {staging}")
        return 2

    stacks, dropped = _usable_out2d_stacks(_out2d_stacks(staging))
    for note in dropped:
        print(f"geopkg: {note}")
    if not stacks:
        print(f"geopkg: no out2d stacks in {staging}")
        return 3

    try:
        from nos_utils.post.geopkg import write_disturbance_series
    except ImportError as exc:
        print(f"geopkg: nos_utils.post unavailable: {exc}")
        return 4

    print(f"geopkg: contouring {len(stacks)} out2d stack(s) for {args.phase}")
    try:
        # Nowcast numbering counts down to the cycle time, so it needs
        # the phase's record count up front.
        # Ops hardcodes a 24-record nowcast countdown and err_exits on a
        # missing stack. We derive the expected count from LEN_NOWCAST and
        # cross-check the staged records: anchoring the countdown to whatever
        # happened to stage would silently relabel every frame if a stack were
        # missing (n011..n000 for records that are really n023..n012).
        n_records = 0
        if args.phase == "nowcast":
            staged = _record_count(stacks)
            expected = int(round(args.nowcast_hours)) if args.nowcast_hours else 0
            if expected and staged != expected:
                print(
                    f"geopkg: staged {staged} nowcast records but LEN_NOWCAST "
                    f"implies {expected}; refusing to guess the countdown "
                    "anchor (frames would be mislabelled)"
                )
                return 5
            n_records = expected or staged
        written = write_disturbance_series(
            stacks,
            comout,
            _namer(args, n_records),
            max_workers=args.max_workers,
        )
    except ImportError as exc:
        # matplotlib/shapely/geopandas (or netCDF4) not deployed here.
        print(
            f"geopkg: geometry stack unavailable ({exc}); "
            "no GeoPackages written"
        )
        written = []
    except KeyError as exc:
        # The stacks lack a mesh variable the contouring needs (element
        # table / coordinates). Warn and skip rather than failing the
        # product -- slab2d treats the same condition the same way.
        print(
            f"geopkg: out2d stacks missing variable {exc}; "
            "no GeoPackages written"
        )
        written = []

    created = [str(p) for p in written]
    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps({"created": created}, indent=2)
        )

    print(f"geopkg: wrote {len(created)} GeoPackage(s) for {args.phase}")
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
        "--max-workers", type=int, default=1,
        help="fan the timesteps out to this many processes (ops used a "
             "fork pool over the merged field)",
    )
    p.add_argument(
        "--nowcast-hours", type=float, default=0.0,
        help="expected hourly nowcast records; anchors the n### countdown "
             "and guards against a partially staged nowcast.",
    )
    p.add_argument("--result-json", default="")
    return p.parse_args(argv)


def _out2d_stacks(staging: Path) -> List[Path]:
    """out2d stacks in stack order (chronological)."""
    hits = []
    for f in staging.glob("out2d_*.nc"):
        m = _STACK_RE.match(f.name)
        if m:
            hits.append((int(m.group(1)), f))
    return [f for _i, f in sorted(hits)]


def _usable_out2d_stacks(
    stacks: Sequence[Path],
) -> Tuple[List[Path], List[str]]:
    """Split ``stacks`` into ones the writer can read, and why the rest went.

    A leg's trailing stack is routinely empty -- the model closes the
    window before writing any record into it -- and such a file carries
    no ``elevation`` at all. The writer reads elevation from every stack
    it is handed, so a single empty one raised KeyError and cost the
    WHOLE phase its GeoPackages, not just that stack. Every sibling
    product already filters these (fields, slab2d, adcirc, profiles);
    this one did not.
    """
    try:
        from netCDF4 import Dataset
    except ImportError:
        return list(stacks), []

    usable: List[Path] = []
    dropped: List[str] = []
    for path in stacks:
        try:
            with Dataset(path, "r") as ds:
                has_elev = "elevation" in ds.variables
                nrec = (
                    int(ds.variables["time"].shape[0])
                    if "time" in ds.variables else 0
                )
        except Exception as exc:  # noqa: BLE001
            dropped.append(f"{path.name}: unreadable ({exc}); skipped")
            continue
        if not has_elev or nrec == 0:
            why = "no elevation" if not has_elev else "no records"
            dropped.append(f"{path.name}: {why}; skipped")
            continue
        usable.append(path)
    return usable, dropped


def _record_count(stacks: Sequence[Path]) -> int:
    """Total timesteps across ``stacks``."""
    from netCDF4 import Dataset

    total = 0
    for path in stacks:
        with Dataset(path, "r") as ds:
            if "time" in ds.variables:
                total += int(ds.variables["time"].shape[0])
    return total


def _namer(
    args: argparse.Namespace, n_records: int
) -> Callable[[int], str]:
    """Ops timestep numbering under our canonical stem.

    The worker runs one phase at a time, so ``n_records`` is that
    phase's record count: nowcast record ``k`` becomes
    ``n{n_records-1-k}`` (the last one, at the cycle time, is ``n000``)
    and forecast record ``k`` becomes ``f{k+1}``.
    """

    def name_fn(istep: int) -> str:
        hour = n_records - 1 - istep if args.phase == "nowcast" else istep + 1
        return disturbance_gpkg_name(
            args.prefix, args.cyc, args.pdy, args.phase, max(hour, 0)
        )

    return name_fn


if __name__ == "__main__":
    sys.exit(main())
