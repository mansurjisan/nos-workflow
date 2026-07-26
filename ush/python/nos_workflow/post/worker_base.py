"""Shared plumbing for post products backed by ``nos_utils.post`` writers.

Every such product follows the same shape: locate this cycle's staged
model output, hand explicit paths to a compute function in nos-utils,
and publish the result to $COMOUT under a canonical name. The compute
runs in a subprocess -- netCDF4/scipy/geopandas stay out of the stage
process, matching the ``fields_nc`` and stations-combine precedent
(LD_PRELOAD scrubbed for the netCDF4/Fortran preload clash).

This module holds the parts that do not vary: staging discovery, the
subprocess call, and the ``{"created": [...]}`` result protocol every
worker writes. A concrete product supplies only its worker module name
and the product-specific arguments.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .base import PostProduct, ProductContext, ProductResult

logger = logging.getLogger(__name__)

# Staged model output lives in these per-phase COMOUT subdirectories,
# written by runners/schism_ufs/archive.py.
PHASE_DIRS = (("nowcast", "restart_outputs"), ("forecast", "forecast_outputs"))

# Canonical scribe-shaped stack families a staging dir may hold.
FIELD_GLOBS = (
    "out2d_[0-9]*.nc",
    "temperature_[0-9]*.nc",
    "salinity_[0-9]*.nc",
    "horizontalVelX_[0-9]*.nc",
    "horizontalVelY_[0-9]*.nc",
    "zCoordinates_[0-9]*.nc",
)


def staging_dir(ctx: ProductContext, phase: str) -> Path:
    """COMOUT staging directory for ``phase``."""
    suffix = dict(PHASE_DIRS)[phase]
    return ctx.comout / f"{ctx.run_name}.{ctx.cycle}.{suffix}"


def has_field_stacks(staging: Path) -> bool:
    """True when ``staging`` holds field data these products can use.

    Counts the canonical split stacks AND the coupled path's combined
    ``schout_<stack>.nc``: on that path the split files only appear once
    the fields worker has run, so gating on the split shape alone made
    every other product silently skip unless ``fields_nc`` happened to be
    ordered first -- an undeclared dependency that a
    ``NOS_POST_PRODUCTS=maxele`` rerun would trip over.
    """
    if not staging.is_dir():
        return False
    if any(any(staging.glob(g)) for g in FIELD_GLOBS):
        return True
    # Combined schout is schout_<stack>.nc; per-rank is schout_<rank>_<stack>.nc.
    return any(f.name.count("_") == 1 for f in staging.glob("schout_[0-9]*.nc"))


def has_staout(staging: Path) -> bool:
    """True when ``staging`` holds station timeseries files."""
    return staging.is_dir() and (staging / "staout_1").is_file()


def base_date_from_staging(staging: Path) -> Optional[str]:
    """The staged stacks' own time origin, as ops uses.

    Operational post copies the model's ``time:units`` / ``base_date``
    through rather than recomputing them (e.g. maxele reads them back
    from param.nml, slab2d off the input file). Inheriting the source
    string is both simpler and safer: it cannot drift from the data, it
    is automatically correct per phase and per engine (a coupled
    forecast resets its clock, a standalone one continues the nowcast
    clock), and it preserves the ops units format.

    Returns the text after "seconds since", or None when no stack is
    readable -- callers then fall back to a computed value.
    """
    try:
        from netCDF4 import Dataset
    except ImportError:
        return None
    for cand in sorted(staging.glob("out2d_[0-9]*.nc")):
        try:
            with Dataset(cand, "r") as ds:
                units = getattr(ds.variables["time"], "units", "")
        except Exception:  # noqa: BLE001
            continue
        low = units.lower()
        if "since" in low:
            return units[low.index("since") + len("since"):].strip()
    return None


def read_created(result_json: Path, product: str) -> List[str]:
    """Files a worker reports having created; [] when unreadable."""
    try:
        data = json.loads(result_json.read_text())
        return [str(p) for p in data.get("created", [])]
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: result json unreadable (%s)", product, exc)
        return []


class NosUtilsProduct(PostProduct):
    """A post product whose compute lives in ``nos_utils.post``.

    Subclasses set :attr:`name` and :attr:`worker` and implement
    :meth:`worker_args`, returning the product-specific CLI arguments
    for one phase (or ``None`` to skip that phase). Phase iteration,
    the subprocess call, failure isolation and result collection are
    handled here.

    Set :attr:`phases` to restrict which phases run (STOFS maxele, for
    instance, reduces forecast stacks only).
    """

    worker: str = ""
    phases: Sequence[str] = ("nowcast", "forecast")
    #: When the worker succeeds but writes nothing, report "skipped"
    #: rather than "ok". True for products whose inputs may legitimately
    #: yield no output (an optional geometry stack, a cycle with no
    #: complete stack), so an empty result never reads as success.
    empty_is_skipped: bool = False

    def worker_args(
        self, ctx: ProductContext, phase: str, staging: Path, work: Path
    ) -> Optional[List[str]]:
        raise NotImplementedError

    def produce(self, ctx: ProductContext) -> ProductResult:
        from ..stages.post import _run_subprocess_appending  # local: cycle

        outputs: List[str] = []
        ran_any = False
        failed: List[str] = []

        for phase in self.phases:
            staging = staging_dir(ctx, phase)
            work = ctx.data / f"post_{self.name}_{phase}"
            work.mkdir(parents=True, exist_ok=True)
            result_json = work / f"{self.name}_result.json"

            args = self.worker_args(ctx, phase, staging, work)
            if args is None:
                logger.info(
                    "%s: inputs not staged for %s, skipping", self.name, phase
                )
                continue
            ran_any = True

            rc = _run_subprocess_appending(
                ["python3", "-m", self.worker, *args,
                 "--result-json", str(result_json)],
                cwd=work,
                log_path=ctx.pgmout,
                scrub_ld_preload=True,
            )
            if rc != 0:
                logger.warning(
                    "WARNING: %s worker failed for %s (rc=%d)",
                    self.name, phase, rc,
                )
                failed.append(phase)
                continue
            outputs.extend(read_created(result_json, self.name))

        if not ran_any:
            return ProductResult(
                name=self.name, status="skipped",
                detail="required inputs not staged",
            )
        if failed:
            return ProductResult(
                name=self.name, status="failed", outputs=outputs,
                detail="worker failed for: " + ", ".join(failed),
            )
        if self.empty_is_skipped and not outputs:
            return ProductResult(
                name=self.name, status="skipped", outputs=outputs,
                detail="worker wrote nothing (inputs incomplete or "
                       "optional dependency unavailable)",
            )
        return ProductResult(name=self.name, status="ok", outputs=outputs)


def fix_file(ctx: ProductContext, *names: str) -> Optional[Path]:
    """First existing candidate under $FIXofs, trying each name in turn.

    Names are tried verbatim and with the system prefix, so a caller can
    ask for ``"staout_nc.json"`` and match
    ``stofs_3d_atl_staout_nc.json`` or ``{PREFIXNOS}.staout_nc.json``.
    """
    for name in names:
        for cand in (
            ctx.fixofs / name,
            ctx.fixofs / f"{ctx.prefix_nos}_{name}",
            ctx.fixofs / f"{ctx.prefix_nos}.{name}",
        ):
            if cand.is_file():
                return cand
    return None


__all__ = [
    "FIELD_GLOBS",
    "NosUtilsProduct",
    "PHASE_DIRS",
    "fix_file",
    "has_field_stacks",
    "has_staout",
    "read_created",
    "staging_dir",
]
