"""fields_nc worker: publish canonical per-variable field stacks.

Runs as ``python3 -m nos_workflow.post.products.fields`` from the post
stage (subprocess with LD_PRELOAD scrubbed, like the stations combine).
Consumes the global field stacks staged by the run stage in a
``{RUN}.{cycle}.{restart|forecast}_outputs`` directory:

- scribe-shaped per-variable files (``out2d_<k>.nc``, ``temperature_<k>.nc``,
  ...) are published directly;
- combined ``schout_<k>.nc`` (the coupled OLDIO path after the run-stage
  combine) are first split into the scribe shape by reusing
  ``convert_schout_to_split()`` from the deployed
  ``schism_combine_outputs.py``.

Each stack is published to $COMOUT under the canonical name
``{prefix}.t{cyc}z.{pdy}.fields.{var}.{n|f}{HHH}_{HHH}.nc`` (hour range
read from the stack's own time axis, relative to the phase start) via
hardlink when possible (COMOUT staging and products share a filesystem)
with a copy fallback, then stamped with identifying global attributes.
Note the hardlink means the staged split file shares the attribute
stamp -- staging files are internal, so that is acceptable.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from ..naming import fields_stack_name

_VAR_FILE_PREFIXES = (
    "out2d",
    "temperature",
    "salinity",
    "horizontalVelX",
    "horizontalVelY",
    "zCoordinates",
    "verticalVelocity",
    "diffusivity",
)

_STACK_RE_TEMPLATE = r"^{var}_(\d+)\.nc$"


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    staging = Path(args.staging)
    comout = Path(args.comout)
    if not staging.is_dir():
        print(f"fields: staging dir missing: {staging}")
        return 2

    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        print(f"fields: netCDF4 unavailable: {exc}")
        return 4

    os.chdir(staging)

    # Always re-split when combined schout is present: the converter
    # overwrites the split files, so a rerun after a re-forecast never
    # republishes stale splits left from a prior run.
    if _has_combined_schout(staging):
        rc = _split_combined_schout(args.combine_script)
        if rc != 0:
            return rc

    phase_start = _phase_start_hours(
        Dataset, staging, args.phase, args.nowcast_hours
    )
    if phase_start:
        print(f"fields: labels are phase-relative (offset {phase_start:g} h)")

    created: List[str] = []
    for var in _VAR_FILE_PREFIXES:
        for src, stack in _stack_files(staging, var):
            hours = _hour_range(Dataset, src, phase_start)
            if hours is None:
                print(f"fields: {src.name}: empty/no time axis, skipped")
                continue
            h0, h1 = hours
            name = fields_stack_name(
                args.prefix, args.cyc, args.pdy, var, args.phase, h0, h1,
            )
            dst = comout / name
            _link_or_copy(src, dst)
            _stamp_attrs(Dataset, dst, args)
            created.append(str(dst))
            print(f"fields: {src.name} -> {name}")

    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps({"created": created}, indent=2)
        )

    print(f"fields: published {len(created)} stack(s) for {args.phase}")
    return 0


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Publish canonical per-variable field stacks to COMOUT",
    )
    p.add_argument("--staging", required=True)
    p.add_argument("--comout", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--cyc", required=True)
    p.add_argument("--pdy", required=True)
    p.add_argument("--phase", required=True, choices=("nowcast", "forecast"))
    p.add_argument(
        "--nowcast-hours", type=float, default=0.0,
        help="length of the nowcast leg. Used only for the forecast phase, "
             "to detect whether this system's forecast continues the nowcast "
             "clock (STOFS-3D-ATL standalone) or restarts it (SECOFS), so "
             "hour labels come out phase-relative either way.",
    )
    p.add_argument("--combine-script", default="")
    p.add_argument("--result-json", default="")
    return p.parse_args(argv)


def _has_combined_schout(staging: Path) -> bool:
    return any(
        f.name.count("_") == 1 for f in staging.glob("schout_[0-9]*.nc")
    )


def _stack_files(staging: Path, var: str) -> List["tuple[Path, int]"]:
    """(file, stack index) for ``var``, sorted by stack index."""
    rx = re.compile(_STACK_RE_TEMPLATE.format(var=re.escape(var)))
    hits = []
    for f in staging.glob(f"{var}_*.nc"):
        m = rx.match(f.name)
        if m:
            hits.append((f, int(m.group(1))))
    return sorted(hits, key=lambda t: t[1])


def _split_combined_schout(combine_script: str) -> int:
    """Split ``schout_<k>.nc`` in CWD via the deployed combine script."""
    if not combine_script or not Path(combine_script).is_file():
        print(
            "fields: combined schout present but no combine script "
            f"available ({combine_script!r}); cannot split"
        )
        return 3
    spec = importlib.util.spec_from_file_location(
        "schism_combine_outputs", combine_script,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    print("fields: splitting combined schout stacks ...")
    mod.convert_schout_to_split()
    return 0


def _phase_start_hours(
    Dataset, staging: Path, phase: str, nowcast_hours: float
) -> float:
    """Hours to subtract so this phase's labels start near 1.

    Detected from the data rather than configured: a forecast leg whose
    earliest record already sits at/after the nowcast length is running
    on a continued nowcast clock (STOFS-3D-ATL standalone), so the
    nowcast length is subtracted; one that restarts near zero (SECOFS)
    needs no shift. Nowcast legs are always already phase-relative.
    """
    if phase != "forecast" or nowcast_hours <= 0:
        return 0.0
    earliest = None
    for var in _VAR_FILE_PREFIXES:
        for src, _stack in _stack_files(staging, var):
            with Dataset(src, "r") as ds:
                if "time" not in ds.variables:
                    continue
                t = ds.variables["time"][:]
                if t.size == 0:
                    continue
                h0 = float(t[0]) / 3600.0
            earliest = h0 if earliest is None else min(earliest, h0)
    if earliest is None:
        return 0.0
    # A continued clock places the first forecast record AFTER the nowcast
    # ends, so require the earliest record to reach the nowcast length.
    # A looser threshold (e.g. half) admits false positives that would push
    # labels negative -- the guard below is the backstop, this is the rule.
    return nowcast_hours if earliest >= nowcast_hours else 0.0


def _hour_range(
    Dataset, src: Path, phase_start_hours: float = 0.0
) -> Optional["tuple[int, int]"]:
    """(start, end) hours **relative to the phase start**; None when empty.

    A stack's ``time`` axis is anchored to the model clock, and systems
    differ in where that clock starts for the forecast leg: SECOFS
    restarts it near zero, while STOFS-3D-ATL standalone continues the
    nowcast clock (so its first forecast stack begins at hour 25, not 1).
    Labelling straight off the raw axis therefore made the same product
    name mean different things per system -- and diverge from ops, which
    numbers forecast stacks from f001. Subtracting the phase start makes
    the label phase-relative everywhere.
    """
    with Dataset(src, "r") as ds:
        if "time" not in ds.variables:
            return None
        t = ds.variables["time"][:]
        if t.size == 0:
            return None
        h0 = int(round(float(t[0]) / 3600.0 - phase_start_hours))
        h1 = int(round(float(t[-1]) / 3600.0 - phase_start_hours))
    if h0 < 0 or h1 < 0:
        # Subtracting the offset should never push a label negative; if it
        # does, the continued-clock detection was wrong for these inputs.
        # Fall back to the raw axis rather than emitting a name like
        # "f-02_000", which formats badly and reads as corruption.
        print(
            f"fields: {src.name}: offset {phase_start_hours:g} h would give a "
            f"negative label; using the raw time axis instead"
        )
        return _hour_range(Dataset, src, 0.0)
    return h0, h1


def _link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _stamp_attrs(Dataset, dst: Path, args: argparse.Namespace) -> None:
    with Dataset(dst, "a") as ds:
        ds.setncattr("ofs", args.prefix)
        ds.setncattr("cycle", f"t{args.cyc}z")
        ds.setncattr("pdy", args.pdy)
        ds.setncattr("phase", args.phase)
        ds.setncattr("product", "fields_nc")
        ds.setncattr("source", "nos_workflow post")


if __name__ == "__main__":
    sys.exit(main())
