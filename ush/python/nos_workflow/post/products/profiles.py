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
  datum while its attributes keep the ops NAVD88 wording.

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
    with atomic_publish(out_path) as tmp:
        write_station_profiles(
            stacks,
            Path(args.hgrid),
            Path(args.vgrid),
            tmp,
            base_date=base_date,
            station_file=Path(args.station_in),
            outside=args.outside,
        )

    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps({"created": [str(out_path)]}, indent=2)
        )
    print(f"profiles: wrote {out_path.name} (zeta on the model datum)")
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
        "--outside", default="error", choices=("error", "nearest"),
        help="what to do with a station outside the mesh. 'error' (default) "
             "is ops parity: the operational driver sys.exit()s on one. "
             "'nearest' takes pylib's nearest-node fallback, which publishes "
             "another node's column under the misplaced station's name.",
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
