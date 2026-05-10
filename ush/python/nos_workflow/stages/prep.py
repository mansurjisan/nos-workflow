"""Prep stage entry point.

Right now only ``framework="comf"`` (SECOFS-UFS) has a real
implementation — it dispatches to ``nos_utils.nco_bridge.run_prep`` for
both the nowcast and forecast phases, mirroring the two-phase split in
the legacy ``exnos_prep.sh``. The STOFS and ADCIRC branches raise
``NotImplementedError`` until tasks #33 / #34 land.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..errors import StageFailedError
from ..registry import OFSDescriptor

if TYPE_CHECKING:
    # Forward-reference NCOEnv so the stage modules don't import Agent A's
    # env.py at collection time. The runtime parameter type is structural.
    from ..env import NCOEnv  # noqa: F401


logger = logging.getLogger(__name__)


_STAGE = "prep"


def _phase_header(ofs: str) -> None:
    """Emit the one-line phase header used by the J-job ``OUTPUT.$$`` log."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info("[%s] [%s] [%s] entered", ts, _STAGE, ofs)


def run(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """Execute the prep stage for ``descriptor``.

    Args:
        descriptor: The OFS descriptor returned by ``registry.lookup``.
        env: NCO environment bundle (PDY, cyc, COM paths, etc.).

    Returns:
        0 on success; a non-zero return code is surfaced unchanged from
        ``run_prep`` if it returns rc-style instead of raising.

    Raises:
        StageFailedError: any wrapped exception from ``run_prep`` or a
            non-bool return that we can't map cleanly to rc.
        NotImplementedError: framework other than ``"comf"``; STOFS and
            ADCIRC branches are stubbed for tasks #33 / #34.
    """
    _phase_header(descriptor.name)

    if descriptor.framework == "comf":
        return _run_comf_prep(descriptor, env)
    if descriptor.framework == "stofs":
        raise NotImplementedError(
            "STOFS-3D-ATL prep not yet ported — task #33 on the roadmap"
        )
    if descriptor.framework == "adcirc":
        raise NotImplementedError(
            "STOFS-2D-GLO prep not yet ported — task #34"
        )

    raise StageFailedError(
        stage=_STAGE,
        ofs=descriptor.name,
        returncode=2,
        msg=f"unknown framework {descriptor.framework!r}",
    )


def _run_comf_prep(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """COMF (SECOFS-UFS) prep: run nowcast then forecast phases.

    Lazy-imports ``nos_utils.nco_bridge`` so ``nos_uw list`` and the
    descriptor tests don't pay the netCDF/numpy import cost.
    """
    try:
        # Lazy import — never hoisted to module top.
        from nos_utils.nco_bridge import run_prep  # type: ignore[import-not-found]
    except ImportError as exc:
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=127,
            msg=f"nos_utils.nco_bridge import failed: {exc}",
        ) from exc

    # The nos-unified-workflow branch is FULL_PYTHON_PREP-only — NWM /
    # RTOFS / nudging are produced by the Python orchestrator, not the
    # legacy Fortran scripts. The default `skip_legacy=True` in
    # nco_bridge.run_prep dates from the older HYBRID mode and would
    # skip those steps; pass False explicitly so the new shim's COMOUT
    # matches the legacy preY-mig shell's COMOUT (which sets
    # FULL_PYTHON_PREP=YES → skip_legacy=False).
    for phase in ("nowcast", "forecast"):
        try:
            result: Any = run_prep(phase=phase, skip_legacy=False)
        except Exception as exc:  # noqa: BLE001 — wrap to StageFailedError
            raise StageFailedError(
                stage=_STAGE,
                ofs=descriptor.name,
                returncode=1,
                msg=f"nos_utils.run_prep({phase!r}) raised: {exc}",
            ) from exc

        rc = _coerce_rc(result)
        if rc != 0:
            return rc

    return 0


def _coerce_rc(result: Any) -> int:
    """Normalize ``run_prep`` return values into an integer rc.

    ``nos_utils.nco_bridge.run_prep`` currently returns a bool
    (True=success). If a future version starts returning an int we
    pass it through unchanged.
    """
    if isinstance(result, bool):
        return 0 if result else 1
    if isinstance(result, int):
        return result
    if result is None:
        # Treat ``None`` as success — convention for procedural shims.
        return 0
    raise StageFailedError(
        stage=_STAGE,
        ofs="<unknown>",
        returncode=2,
        msg=f"run_prep returned unexpected type {type(result).__name__}: {result!r}",
    )


__all__ = ["run"]
