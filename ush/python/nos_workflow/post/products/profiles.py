"""station-profile worker: vertical profiles at the station list.

Runs as ``python3 -m nos_workflow.post.products.profiles`` from the post
stage and delegates the compute to
:func:`nos_utils.post.profiles.write_station_profiles` (the port of the
operational ``pysh/get_stations_profile.py``, driven by
``stofs_3d_atl_create_station_profile_nc.sh``). This module owns only
orchestration: which stack indices are complete, the canonical COMOUT
name, and the ops-parity arguments.

Ops parity notes:

* ops runs the extractor once per stack and ``ncrcat``s the pieces into
  one ``{ncast,fcast}.station.profile.nc``; our writer takes the whole
  per-phase stack list and concatenates the times in-code, so this is
  one call per phase (see :func:`..naming.station_profile_name`).

* **Out-of-mesh stations abort.** ``get_stations_profile.py`` ends in
  ``sys.exit('points outside of domain: ...')`` as soon as one station
  misses the mesh, so this worker passes ``outside="error"``. The
  writer's own default is ``"nearest"`` -- pylib's fallback, which
  substitutes the nearest node's column (weights 1, 0, 0) for a
  misplaced station and publishes a full-looking profile that is
  indistinguishable downstream from a real one. Ops-parity is the
  default here for exactly that reason; ``--outside nearest`` (env
  ``NOS_PROFILES_OUTSIDE``) opts back into the fallback deliberately,
  e.g. to keep publishing the rest of a station list while one bad entry
  is corrected.

* Ops shifts ``zeta`` off xGEOID20B with ``ncap2 -S
  *_sta_cwl_xgeoid_to_msl.nco`` AFTER the extractor. The nos-utils
  writer has no hook for that (unlike ``points_cwl``'s
  ``--datum-offsets``), so the published ``zeta`` carries the model's own
  datum while its attributes keep the ops wording -- MSL as of v3.1
  (nos-utils commit ``d9d324f`` updated the hardcoded ``long_name``/
  ``standard_name`` from the retired NAVD88 wording to
  "water surface elevation above msl" / "sea_surface_height_above_msl").

Exit codes: 2 staging dir missing, 3 no complete stack in the staging
dir (the phase has no 3D output -- skip), 4 nos-utils unavailable,
5 a required fix input (hgrid / vgrid / station.in) is not readable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..naming import station_profile_name
from ..worker_base import atomic_publish, base_date_from_staging

_STACK_RE = re.compile(r"^out2d_(\d+)\.nc$")

# Time origins write_station_profiles can parse (``YYYY-MM-DD-HH`` plus
# the ISO-ish variants); see _base_date.
_BASE_DATE_RE = re.compile(r"\s*\d{4}-\d{1,2}-\d{1,2}[-T ]\d{1,2}")


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    staging = Path(args.staging)
    comout = Path(args.comout)
    if not staging.is_dir():
        print(f"profiles: staging dir missing: {staging}")
        return 2

    missing_fix = [
        f"{flag} {value}"
        for flag, value in (
            ("--hgrid", args.hgrid),
            ("--vgrid", args.vgrid),
            ("--station-in", args.station_in),
        )
        if not Path(value).is_file()
    ]
    if missing_fix:
        print(f"profiles: fix input(s) not readable: {'; '.join(missing_fix)}")
        return 5

    # Name the resolved inputs. fix_file() accepts several spellings and
    # tries the bare name first, so "which mesh did it actually use" is
    # not answerable from the arguments -- and it is the first question
    # asked when a station comes out of the domain.
    print(f"profiles: hgrid      {args.hgrid}")
    print(f"profiles: vgrid      {args.vgrid}")
    print(f"profiles: station.in {args.station_in}")

    try:
        from nos_utils.post.profiles import (
            stack_inputs,
            write_station_profiles,
        )
    except ImportError as exc:
        print(f"profiles: nos_utils.post unavailable: {exc}")
        return 4

    stacks, skipped = _complete_stacks(staging, stack_inputs)
    if skipped:
        # A gap in the middle leaves a hole in the concatenated time
        # axis, so name the indices rather than dropping them silently.
        print(f"profiles: incomplete stack(s) skipped: {'; '.join(skipped)}")
    if not stacks:
        print(f"profiles: no complete stacks in {staging}")
        return 3

    base_date = _base_date(staging, args.base_date)
    out_path = comout / station_profile_name(
        args.prefix, args.cyc, args.pdy, args.phase
    )
    print(
        f"profiles: {len(stacks)} stack(s), outside={args.outside} "
        f"-> {out_path.name}"
    )
    station_kwargs = {"station_file": Path(args.station_in)}
    outside = args.outside
    if outside == "drop":
        kept = _keep_in_mesh_stations(args)
        if kept is None:
            return 6
        lons, lats, names = kept
        if not len(lons):
            print("profiles: no stations left inside the mesh")
            return 6
        # Filtered already, so anything still outside is a genuine
        # surprise and should stop us rather than pass silently.
        station_kwargs = {"lons": lons, "lats": lats, "names": names}
        outside = "error"

    try:
        with atomic_publish(out_path) as tmp:
            write_station_profiles(
                stacks,
                Path(args.hgrid),
                Path(args.vgrid),
                tmp,
                base_date=base_date,
                outside=outside,
                **station_kwargs,
            )
    except ValueError as exc:
        if "outside of domain" not in str(exc):
            raise
        # Aborting here is the ops behaviour and is kept. What ops does
        # not do is say WHICH station or how far out, and without that a
        # bad coordinate and a mismatched mesh look identical in the log.
        print(f"profiles: {exc}")
        _diagnose_outside(args)
        return 6

    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps({"created": [str(out_path)]}, indent=2)
        )
    print(f"profiles: wrote {out_path.name} (zeta on the model datum)")
    return 0


def _locate_stations(args: argparse.Namespace):
    """``(lons, lats, names, ie)`` for the station list against the mesh."""
    from nos_utils.post.profiles import (
        compute_area_coords, read_station_in, _read_elements,
    )
    from nos_utils.io.schism_grid import SchismGrid

    lons, lats, names = read_station_in(Path(args.station_in))
    grid = SchismGrid.read(Path(args.hgrid), read_boundaries=False)
    elnode = _read_elements(Path(args.hgrid), grid.n_nodes, grid.n_elements)
    ie, _ip, _acor = compute_area_coords(
        grid.node_lons, grid.node_lats, elnode, lons, lats
    )
    return lons, lats, names, ie, grid


def _keep_in_mesh_stations(args: argparse.Namespace):
    """Stations inside the mesh, naming every one dropped.

    ``--outside drop`` exists because the two ops-inherited choices both
    fail this case badly on a 430-station list: ``error`` loses the other
    429 to one bad entry, and ``nearest`` publishes some other node's
    water column under the bad station's name. Dropping is the only
    option that neither discards good data nor invents any -- the
    station is simply absent, and the log says which and why.

    Returns None when the station list or mesh cannot be read.
    """
    try:
        import numpy as np

        lons, lats, names, ie, grid = _locate_stations(args)
    except Exception as exc:  # noqa: BLE001
        print(f"profiles: cannot locate stations against the mesh ({exc})")
        return None

    bad = np.nonzero(ie == -1)[0]
    if not bad.size:
        return lons, lats, names
    print(
        f"profiles: dropping {bad.size} of {lons.size} station(s) outside "
        f"{Path(args.hgrid).name}:"
    )
    for k in bad:
        d = np.hypot(grid.node_lons - lons[k], grid.node_lats - lats[k])
        print(
            f"profiles:   [{k}] {str(names[k])[:32]:32s} "
            f"({lons[k]:.6f}, {lats[k]:.6f})  "
            f"nearest node at {d.min() * 111000:.2f} m"
        )
    keep = ie != -1
    return lons[keep], lats[keep], np.asarray(names)[keep]


def _diagnose_outside(args: argparse.Namespace) -> None:
    """Name the out-of-domain stations and their distance to the mesh.

    The distance is the discriminator an operator needs: metres out
    means a coordinate that wants nudging onto the mesh, kilometres out
    means the station list and the hgrid are from different domains.
    Best effort only -- this runs on a path that has already failed, so
    nothing here may raise.
    """
    try:
        import numpy as np

        lons, lats, names, ie, grid = _locate_stations(args)
        bad = np.nonzero(ie == -1)[0]
        print(
            f"profiles: {bad.size} of {lons.size} station(s) outside "
            f"{Path(args.hgrid).name} ({grid.n_nodes} nodes):"
        )
        for k in bad[:20]:
            d = np.hypot(grid.node_lons - lons[k], grid.node_lats - lats[k])
            j = int(d.argmin())
            print(
                f"profiles:   [{k}] {str(names[k])[:32]:32s} "
                f"({lons[k]:.6f}, {lats[k]:.6f})  "
                f"nearest node {j} at {d[j] * 111000:.2f} m"
            )
        if bad.size > 20:
            print(f"profiles:   ... and {bad.size - 20} more")
    except Exception as exc:  # noqa: BLE001
        print(f"profiles: could not diagnose the out-of-domain stations ({exc})")


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
        help="fallback time-units base, e.g. '2026-07-22 12:00'; the staged "
             "stacks' own origin wins when they carry one",
    )
    p.add_argument("--hgrid", required=True, help="SCHISM hgrid.gr3")
    p.add_argument(
        "--vgrid", required=True,
        help="SCHISM vgrid.in; only its nvrt is read (the siglay dimension)",
    )
    p.add_argument(
        "--station-in", required=True,
        help="SCHISM station.in -- the ops station list",
    )
    p.add_argument(
        "--outside", default="error", choices=("error", "nearest", "drop"),
        help="what to do with a station outside the mesh. 'error' (default) "
             "is ops parity: the operational driver sys.exit()s on one. "
             "'nearest' takes pylib's nearest-node fallback, which publishes "
             "another node's column under the misplaced station's name. "
             "'drop' excludes it and publishes the rest, naming what went -- "
             "the only choice that neither loses good stations to one bad "
             "entry nor invents data for it.",
    )
    p.add_argument("--result-json", default="")
    return p.parse_args(argv)


def _stack_indices(staging: Path) -> List[int]:
    """out2d stack indices present in ``staging``, in stack order."""
    hits = []
    for f in staging.glob("out2d_*.nc"):
        m = _STACK_RE.match(f.name)
        if m:
            hits.append(int(m.group(1)))
    return sorted(hits)


def _complete_stacks(
    staging: Path, stack_inputs
) -> Tuple[List[Dict[str, Path]], List[str]]:
    """``(file maps in stack order, human-readable skips)``.

    A stack is usable only with all six co-indexed families present
    (ops' ``list_fn_base``): the writer indexes every family of every
    stack it is handed, so a partial index would raise mid-write rather
    than produce a shorter product.
    """
    stacks: List[Dict[str, Path]] = []
    skipped: List[str] = []
    for index in _stack_indices(staging):
        files = stack_inputs(staging, index)
        missing = sorted(k for k, p in files.items() if not p.is_file())
        if missing:
            skipped.append(f"{index} (missing {', '.join(missing)})")
            continue
        stacks.append(files)
    return stacks, skipped


def _base_date(staging: Path, fallback: str) -> str:
    """The stacks' own time origin when the writer can parse it.

    Ops copies the model clock through (see ``worker_base``), but this
    writer *parses* the base date instead of passing it verbatim, so an
    origin in an unexpected shape would raise mid-write. Fall back to the
    stage-computed ``--base-date`` in that case rather than losing the
    product.
    """
    inherited = base_date_from_staging(staging)
    if inherited and _BASE_DATE_RE.match(inherited):
        return inherited
    if inherited:
        print(
            f"profiles: stack time origin {inherited!r} not parseable; "
            "using --base-date"
        )
    return fallback


if __name__ == "__main__":
    sys.exit(main())
