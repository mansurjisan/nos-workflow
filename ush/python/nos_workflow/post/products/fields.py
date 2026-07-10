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

    if not _has_split_stacks(staging) and _has_combined_schout(staging):
        rc = _split_combined_schout(args.combine_script)
        if rc != 0:
            return rc

    created: List[str] = []
    for var in _VAR_FILE_PREFIXES:
        for src, stack in _stack_files(staging, var):
            hours = _hour_range(Dataset, src)
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
    p.add_argument("--combine-script", default="")
    p.add_argument("--result-json", default="")
    return p.parse_args(argv)


def _has_split_stacks(staging: Path) -> bool:
    return any(
        _stack_files(staging, var) for var in _VAR_FILE_PREFIXES
    )


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


def _hour_range(Dataset, src: Path) -> Optional["tuple[int, int]"]:
    """(start, end) hours from the stack's time axis; None when empty."""
    with Dataset(src, "r") as ds:
        if "time" not in ds.variables:
            return None
        t = ds.variables["time"][:]
        if t.size == 0:
            return None
        h0 = int(round(float(t[0]) / 3600.0))
        h1 = int(round(float(t[-1]) / 3600.0))
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
