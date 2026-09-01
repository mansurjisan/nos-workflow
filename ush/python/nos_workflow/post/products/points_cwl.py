"""points.cwl worker: station timeseries from the staged staout files.

Runs as ``python3 -m nos_workflow.post.products.points_cwl`` from the
post stage and delegates the compute to
:func:`nos_utils.post.stations.write_station_timeseries` (the port of the
IT-STOFS ``generate_station_timeseries.py`` as driven by
``stofs_3d_atl_create_awips_shef.sh``). This module owns only
orchestration: which staout files to feed, the canonical COMOUT name,
and the ops datum shift.

Ops parity notes (from the nos-utils review ledger):
  * the staout files to read are named by the fix JSON itself, one per
    variable definition (ATL: staout_1 elev, 5 temp, 6 salt, 7 u, 8 v);
  * ops publishes one combined ``points.cwl.temp.salt.vel.nc`` per
    cycle, this runs per phase (see ``naming.points_cwl_name``);
  * ops then shifts ``zeta`` from xGEOID20B to its target vertical datum
    with ncap2, *subtracting* the per-station constants of the
    ``*_sta_cwl_xgeoid_to_<datum>.nco`` file (``_navd`` pre-v3.1,
    ``_msl`` from v3.1 on). ``--datum-offsets`` takes whichever .nco is
    staged verbatim and negates it, because the writer adds.

Exit codes: 2 staging dir missing, 3 staout files absent (the phase has
no station output -- skip), 4 nos-utils unavailable, 5 unusable
metadata.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..naming import points_cwl_name

# One ncap2 statement of the ops xGEOID20B -> target-datum shift
# (NAVD88 pre-v3.1, MSL from v3.1 on -- the .nco format is unchanged
# either way), e.g. ``zeta(:,17)=zeta(:,17)-float(-0.32794);``.
_NCO_RE = re.compile(
    r"zeta\(:,(\d+)\)\s*=\s*zeta\(:,\1\)\s*-\s*float\(\s*([-+0-9.eE]+)\s*\)"
)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    staging = Path(args.staging)
    comout = Path(args.comout)
    if not staging.is_dir():
        print(f"points_cwl: staging dir missing: {staging}")
        return 2

    try:
        var_defs = json.loads(Path(args.var_defs).read_text())
    except (OSError, ValueError) as exc:
        print(f"points_cwl: unusable var defs {args.var_defs}: {exc}")
        return 5
    if not isinstance(var_defs, dict) or not var_defs:
        print(f"points_cwl: no variable definitions in {args.var_defs}")
        return 5

    staout_files, missing = _staout_files(staging, var_defs)
    if missing:
        print(
            f"points_cwl: staout file(s) {missing} not staged in {staging}"
        )
        return 3

    offsets = None
    if args.datum_offsets:
        offsets = _nco_offsets(Path(args.datum_offsets))
        if offsets is None:
            print(
                f"points_cwl: no zeta statements in {args.datum_offsets}"
            )
            return 5

    try:
        from nos_utils.post.stations import write_station_timeseries
    except ImportError as exc:
        print(f"points_cwl: nos_utils.post unavailable: {exc}")
        return 4

    out_path = comout / points_cwl_name(
        args.prefix, args.cyc, args.pdy, args.phase
    )
    print(
        f"points_cwl: {len(staout_files)} staout file(s) -> {out_path.name}"
    )
    from ..worker_base import atomic_publish

    with atomic_publish(out_path) as tmp:
        write_station_timeseries(
            staout_files,
            var_defs,
            args.station_meta,
            tmp,
            base_date=args.base_date,
            datum_offsets=offsets,
        )
        _warn_transposed_coords(tmp, args.station_meta)

    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps({"created": [str(out_path)]}, indent=2)
        )
    print(f"points_cwl: wrote {out_path.name}")
    return 0


def _warn_transposed_coords(path: Path, meta_source: str) -> None:
    """Name stations whose x/y look swapped relative to the rest.

    The ops station CSV labels its coordinate columns ``lat``/``lon``
    while the data under them runs lon-first, and the writer reads by
    header name -- so ops' ``x`` ends up carrying latitudes. That
    mismatch is ops', and reproduced deliberately. What is not
    deliberate: a few rows in the ops fix file are keyed the other way
    round from the rest, so those stations come out transposed relative
    to their own file, with nothing in the output to say so. On the
    current ATL fix set that is 3 of 108.

    This only reports. Correcting the values would diverge from the ops
    product for the same input, which is a call for whoever owns the fix
    file, not for post.
    """
    try:
        import numpy as np
        from netCDF4 import Dataset

        with Dataset(path, "r") as ds:
            x = np.asarray(ds.variables["x"][:], dtype=float)
            y = np.asarray(ds.variables["y"][:], dtype=float)
            names = _station_names(ds)
    except Exception as exc:  # noqa: BLE001 -- advisory only
        print(f"points_cwl: coordinate check skipped ({exc})")
        return
    if x.size < 4:
        return

    # Calibrate on the bulk of the stations rather than on fixed bounds,
    # so this works for any domain (including one crossing the dateline).
    xlo, xhi = np.percentile(x, [10, 90])
    ylo, yhi = np.percentile(y, [10, 90])
    suspect = [
        i for i in range(x.size)
        if not (xlo <= x[i] <= xhi or ylo <= y[i] <= yhi)
        and (ylo <= x[i] <= yhi and xlo <= y[i] <= xhi)
    ]
    if not suspect:
        return
    print(
        f"points_cwl: WARNING: {len(suspect)} of {x.size} stations have x/y "
        f"that fit only when swapped -- their rows in {meta_source} look "
        "keyed the opposite way round to the rest. Values published as-is "
        "(ops parity); these stations will plot in the wrong place:"
    )
    for i in suspect:
        label = names[i] if i < len(names) else ""
        print(f"points_cwl:   station {i} x={x[i]:.4f} y={y[i]:.4f} {label}")


def _station_names(ds) -> List[str]:
    """Station names as text, or [] when the variable is absent/odd."""
    try:
        raw = ds.variables["station_name"][:]
    except Exception:  # noqa: BLE001
        return []
    out = []
    for row in raw:
        try:
            out.append(
                b"".join(
                    c for c in row.tobytes().split(b"\x00") if c
                ).decode("utf-8", "replace").strip()
            )
        except Exception:  # noqa: BLE001
            out.append("")
    return out


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--staging", required=True)
    p.add_argument("--comout", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--cyc", required=True)
    p.add_argument("--pdy", required=True)
    p.add_argument("--phase", required=True, help="nowcast | forecast")
    p.add_argument(
        "--base-date", required=True,
        help="time-units base, e.g. '2026-07-22 06:00'",
    )
    p.add_argument(
        "--var-defs", required=True,
        help="staout-nc JSON: variable name/attrs/staout_fname per variable",
    )
    p.add_argument(
        "--station-meta", required=True,
        help="staout-nc CSV: ';'-separated station_info/lon/lat",
    )
    p.add_argument(
        "--datum-offsets", default="",
        help="ops xGEOID20B->target-datum .nco (NAVD88 pre-v3.1, MSL "
             "from v3.1 on); its constants are negated and added to "
             "the elevation variable",
    )
    p.add_argument("--result-json", default="")
    return p.parse_args(argv)


def _staout_files(
    staging: Path, var_defs: dict
) -> Tuple[Dict[int, Path], List[str]]:
    """Staged path per staout index, plus the names that are not there.

    Each variable definition names its own file (``staout_fname``); the
    writer selects it by the trailing integer, so that is the key.
    """
    files: Dict[int, Path] = {}
    missing: List[str] = []
    for spec in var_defs.values():
        fname = str(spec.get("staout_fname", "")) if isinstance(
            spec, dict
        ) else ""
        try:
            idx = int(fname.rsplit("_", 1)[-1])
        except ValueError:
            missing.append(fname or "<unset>")
            continue
        path = staging / fname
        if path.is_file():
            files[idx] = path
        else:
            missing.append(fname)
    return files, sorted(set(missing))


def _nco_offsets(path: Path) -> Optional[List[float]]:
    """Per-station shifts from the ops .nco, negated (ops subtracts).

    Returns None when the file holds no ``zeta`` statement; a gap in the
    1..N station numbering raises, since a partial datum shift would
    silently mislabel the product's target-datum metadata (NAVD88
    pre-v3.1, MSL from v3.1 on).
    """
    consts = {
        int(m.group(1)): float(m.group(2))
        for m in _NCO_RE.finditer(path.read_text())
    }
    if not consts:
        return None
    expected = set(range(1, max(consts) + 1))
    if set(consts) != expected:
        raise ValueError(
            f"{path}: datum shift missing for station(s) "
            f"{sorted(expected - set(consts))}"
        )
    return [-consts[i] for i in sorted(consts)]


if __name__ == "__main__":
    sys.exit(main())
