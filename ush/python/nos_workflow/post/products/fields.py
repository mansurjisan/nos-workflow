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

``--deflate`` opts into repacking the stack with zlib on the way out
instead of linking it. It is off by default because that matches ops,
which publishes these stacks uncompressed (STOFS ``cpreq -pf`` in
``stofs_3d_atl_add_attr_2d_3d_nc.sh``; SECOFS writes plain
NETCDF4_CLASSIC in ``schism_fields_station_redo.py``). Measured on a
real 1.69M-node SECOFS cycle, the win is far smaller than raw volume
suggests, because SCHISM already deflates the 3D stacks itself at
level 4 -- only out2d arrives uncompressed:

    out2d 3.0 GB + 3D 11.3 GB = 14.3 GB published per cycle
    out2d alone repacks 155 MB -> 103 MB (1.5x), ~1.6 s at level 1

so roughly 7% off the cycle for ~26 s of post CPU. Levels above 1 are
not worth it here (level 4 buys another 1% for 5x the time), and
already-compressed variables are passed through untouched.
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
from ..worker_base import atomic_publish

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
            if args.deflate > 0 and _worth_deflating(Dataset, src):
                _repack_deflated(Dataset, src, dst, args.deflate)
            else:
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
    p.add_argument(
        "--deflate", type=int, default=0,
        help="zlib level for stacks that arrive uncompressed (0 = off, "
             "the ops-parity default: publish by hardlink). Level 1 gets "
             "essentially all of the available compression; see the module "
             "docstring for measured ratios.",
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
    if (h0 < 0 or h1 < 0) and phase_start_hours:
        # Subtracting the offset should never push a label negative; if it
        # does, the continued-clock detection was wrong for these inputs.
        # Retry once on the raw axis -- guarded by `phase_start_hours` so a
        # genuinely negative time axis cannot recurse forever.
        print(
            f"fields: {src.name}: offset {phase_start_hours:g} h would give a "
            f"negative label; using the raw time axis instead"
        )
        return _hour_range(Dataset, src, 0.0)
    if h0 < 0 or h1 < 0:
        # Raw axis itself is negative (records before the model origin):
        # nothing sensible to label, so let the caller skip the stack.
        print(f"fields: {src.name}: time axis is negative ({h0}..{h1}); skipped")
        return None
    return h0, h1


def _link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


#: Repack only when this share of a stack's payload arrives uncompressed.
#: A repack decompresses and recompresses everything, so a stack that is
#: already compressed costs a full read/write cycle to save nothing --
#: measured at 60 s per 3D stack to shave 3 KB off 303 MB.
_DEFLATE_WORTH_FRACTION = 0.05


def _worth_deflating(Dataset, src: Path) -> bool:
    """True when enough of ``src`` is uncompressed to justify a repack."""
    try:
        raw = 0
        with Dataset(src, "r") as ds:
            for var in ds.variables.values():
                if (var.filters() or {}).get("zlib"):
                    continue
                count = 1
                for dim in var.dimensions:
                    count *= len(ds.dimensions[dim])
                raw += count * var.dtype.itemsize
        on_disk = src.stat().st_size
    except Exception as exc:  # noqa: BLE001
        print(f"fields: {src.name}: cannot size for deflate ({exc}); linking")
        return False
    if on_disk and raw < on_disk * _DEFLATE_WORTH_FRACTION:
        print(
            f"fields: {src.name}: already compressed "
            f"({raw / 1e6:.1f} MB of {on_disk / 1e6:.1f} MB raw); linking"
        )
        return False
    return True


def _repack_deflated(Dataset, src: Path, dst: Path, level: int) -> None:
    """Copy ``src`` to ``dst``, deflating variables that arrive raw.

    Variables SCHISM already wrote compressed (the 3D stacks come out at
    level 4) keep their own filters: re-deflating them costs the whole
    read/write cycle for no measurable gain. Chunking is carried over so
    the published stack reads back the way the model wrote it.
    """
    with atomic_publish(dst) as tmp:
        with Dataset(src, "r") as s, Dataset(
            tmp, "w", format=_repack_format(s)
        ) as d:
            for dim_name, dim in s.dimensions.items():
                d.createDimension(
                    dim_name, None if dim.isunlimited() else len(dim)
                )
            d.setncatts({k: s.getncattr(k) for k in s.ncattrs()})
            for var_name, var in s.variables.items():
                kwargs = _repack_kwargs(s, var, level)
                fill = kwargs.pop("_fill_value", None)
                if fill is not None:
                    kwargs["fill_value"] = fill
                new = d.createVariable(
                    var_name, var.dtype, var.dimensions, **kwargs
                )
                new.setncatts({
                    a: var.getncattr(a)
                    for a in var.ncattrs() if a != "_FillValue"
                })
                new[...] = var[...]


def _repack_format(src_ds) -> str:
    """Keep the source's data model; deflation needs at least netCDF-4.

    Writing everything as NETCDF4 would silently promote a
    NETCDF4_CLASSIC stack (what ops' own SECOFS writer produces) to the
    full model, which is a format change dressed up as a storage change.
    A classic-3D source has no compression at all, so that one is
    promoted to NETCDF4_CLASSIC -- the smallest model that can hold the
    result.
    """
    model = getattr(src_ds, "data_model", "NETCDF4")
    if model in ("NETCDF4", "NETCDF4_CLASSIC"):
        return model
    return "NETCDF4_CLASSIC"


def _repack_kwargs(ds, var, level: int) -> dict:
    """createVariable kwargs preserving ``var``'s storage, deflating if raw."""
    kwargs: dict = {}
    if "_FillValue" in var.ncattrs():
        kwargs["_fill_value"] = var.getncattr("_FillValue")
    if not var.dimensions:
        return kwargs

    filters = var.filters() or {}
    if filters.get("zlib"):
        # Already compressed by the model -- pass its settings through.
        kwargs["zlib"] = True
        kwargs["complevel"] = filters.get("complevel", level)
        kwargs["shuffle"] = bool(filters.get("shuffle", False))
    else:
        kwargs["zlib"] = True
        kwargs["complevel"] = level

    chunking = var.chunking()
    if isinstance(chunking, (list, tuple)):
        # A chunk may exceed a dimension only when that dimension is
        # unlimited; passing an oversized chunk on a fixed dimension is an
        # error, so fall back to library-chosen chunking in that case.
        ok = all(
            ds.dimensions[dim].isunlimited() or size <= len(ds.dimensions[dim])
            for dim, size in zip(var.dimensions, chunking)
        )
        if ok:
            kwargs["chunksizes"] = list(chunking)
    return kwargs


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
