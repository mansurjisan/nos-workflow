"""Prep stage entry point."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from .._log import emit_stage_summary, stage_logger, timed_step
from ..errors import StageFailedError
from ..registry import OFSDescriptor

if TYPE_CHECKING:
    from ..env import NCOEnv  # noqa: F401


logger = logging.getLogger(__name__)


_STAGE = "prep"


def run(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """Execute the prep stage for ``descriptor``."""
    sl = stage_logger(_STAGE, descriptor.name)
    sl.info("stage start")

    if descriptor.framework in ("comf", "stofs_ufs"):
        return _run_comf_prep(descriptor, env)
    if descriptor.framework == "stofs":
        raise NotImplementedError("STOFS-3D-ATL prep not yet ported")
    if descriptor.framework == "adcirc":
        raise NotImplementedError("STOFS-2D-GLO prep not yet ported")

    raise StageFailedError(
        stage=_STAGE,
        ofs=descriptor.name,
        returncode=2,
        msg=f"unknown framework {descriptor.framework!r}",
    )


def _run_comf_prep(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """SCHISM-UFS (framework=comf|stofs_ufs) prep: run nowcast then forecast phases."""
    sl = stage_logger(_STAGE, descriptor.name)
    t_stage = time.monotonic()

    try:
        from nos_utils.nco_bridge import run_prep  # type: ignore[import-not-found]
    except ImportError as exc:
        emit_stage_summary(sl, status="FAIL",
                           runtime_s=time.monotonic() - t_stage,
                           extras={"reason": "nos_utils_import_failed"})
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=127,
            msg=f"nos_utils.nco_bridge import failed: {exc}",
        ) from exc

    for phase in ("nowcast", "forecast"):
        step_name = f"prep_{phase}"
        with timed_step(sl, step_name):
            try:
                result: Any = run_prep(phase=phase, skip_legacy=False)
            except Exception as exc:  # noqa: BLE001
                emit_stage_summary(sl, status="FAIL",
                                   runtime_s=time.monotonic() - t_stage,
                                   extras={"failed_phase": phase})
                raise StageFailedError(
                    stage=_STAGE,
                    ofs=descriptor.name,
                    returncode=1,
                    msg=f"nos_utils.run_prep({phase!r}) raised: {exc}",
                ) from exc

            rc = _coerce_rc(result)
            if rc != 0:
                emit_stage_summary(sl, status="FAIL",
                                   runtime_s=time.monotonic() - t_stage,
                                   extras={"failed_phase": phase, "rc": rc})
                return rc

    emit_stage_summary(sl, status="PASS",
                       runtime_s=time.monotonic() - t_stage,
                       extras={"phases_completed": 2})
    return 0


def _coerce_rc(result: Any) -> int:
    """Normalize ``run_prep`` return values into an integer rc."""
    if isinstance(result, bool):
        return 0 if result else 1
    if isinstance(result, int):
        return result
    if result is None:
        return 0
    raise StageFailedError(
        stage=_STAGE,
        ofs="<unknown>",
        returncode=2,
        msg=f"run_prep returned unexpected type {type(result).__name__}: {result!r}",
    )


__all__ = ["run"]
