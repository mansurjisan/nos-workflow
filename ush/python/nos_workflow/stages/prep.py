"""Prep stage entry point."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .._log import emit_stage_summary, stage_logger, timed_step
from ..errors import StageFailedError
from ..registry import OFSDescriptor
from ..tools import build_staout_1

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
        return _run_adcirc_prep(descriptor, env)
    if descriptor.framework == "comf_standalone":
        raise NotImplementedError(
            "comf_standalone prep (ROMS/FVCOM standalone) not yet wired; "
            "model execution shells out to the legacy COMF scripts (WCOSS2-gated)"
        )

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

    _export_prev_cycle_dirs(descriptor)

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


def _run_adcirc_prep(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """STOFS-2D-GLO prep: nowcast then forecast inputs (forcing, fort.15, adcprep). MJ (10/05/26)"""
    sl = stage_logger(_STAGE, descriptor.name)
    t_stage = time.monotonic()
    from ..runners.adcirc import ops as adcirc_ops, prep as adcirc_prep
    from ..runners.adcirc.settings import AdcircSettings, CycleContext

    try:
        cfg = os.environ.get("OFS_CONFIG") or Path(os.environ.get("HOMEnos", ".")) / descriptor.yaml_path
        settings = AdcircSettings.from_yaml(cfg)
        ctx = CycleContext.from_env(settings)
        phases = ([("ops", adcirc_ops.run_prep)] if settings.mode == "ops"
                  else [("nowcast", adcirc_prep.prep_nowcast), ("forecast", adcirc_prep.prep_forecast)])
        for phase, fn in phases:
            with timed_step(sl, f"prep_{phase}"):
                fn(ctx)
    except Exception as exc:  # noqa: BLE001
        emit_stage_summary(sl, status="FAIL", runtime_s=time.monotonic() - t_stage,
                           extras={"reason": str(exc)[:200]})
        raise StageFailedError(
            stage=_STAGE, ofs=descriptor.name, returncode=1,
            msg=f"ADCIRC prep failed: {exc}",
        ) from exc
    emit_stage_summary(sl, status="PASS", runtime_s=time.monotonic() - t_stage,
                       extras={"phases_completed": 2})
    return 0


def _export_prev_cycle_dirs(descriptor: OFSDescriptor) -> None:
    """STOFS-3D-ATL: set COMOUT_PREV and COMOUTrerun as ops JSTOFS_3D_ATL_PREP does, unless already set.

    The dynamic SSH adjust reads $COMOUT_PREV/staout_1 and $COMOUT_PREV/rerun/<run>.<cycle>.avg_bias
    and writes today's bias to $COMOUTrerun. COMOUT_PREV is the PDY-1 sibling of $COMOUT, as for the
    hotstart search. MJ (10/03/26)
    """
    if not build_staout_1.is_atl_run(descriptor.name):
        return
    sl = stage_logger(_STAGE, descriptor.name)
    comout, pdy = os.environ.get("COMOUT"), os.environ.get("PDY")
    if not (comout and pdy):
        sl.warning("COMOUT_PREV / COMOUTrerun not derived: PDY or COMOUT unset")
        return
    if not os.environ.get("COMOUTrerun"):
        os.environ["COMOUTrerun"] = str(Path(comout) / "rerun")
    if not os.environ.get("COMOUT_PREV"):
        run = os.environ.get("RUN") or descriptor.name
        os.environ["COMOUT_PREV"] = str(build_staout_1.previous_comout(comout, run, pdy))
    _anchor_restart_search_on_comout(comout, pdy, descriptor)
    prev = Path(os.environ["COMOUT_PREV"])
    if prev.is_dir():
        sl.info("COMOUT_PREV=%s COMOUTrerun=%s", prev, os.environ["COMOUTrerun"])
    else:
        sl.warning("COMOUT_PREV=%s not found; dynamic adjust runs without a previous-cycle bias", prev)
    if os.environ.get("COMINrerun"):
        sl.info("COMINrerun=%s overrides the COMOUT_PREV layout", os.environ["COMINrerun"])


def _anchor_restart_search_on_comout(comout: str, pdy: str, descriptor: OFSDescriptor) -> None:
    """Make the restart search follow an overridden COMOUT.

    JNOS_PREP derives COMIN from COMROOT/NET/RUN.PDY, so a COMOUT override alone left the
    search in the shared com tree. COMIN is moved to COMOUT only when it still equals that
    default; an explicit COMIN or RESTART_DIR is kept. MJ (10/05/26)
    """
    if os.environ.get("RESTART_DIR"):
        return
    run = os.environ.get("RUN") or descriptor.name
    default = Path(os.environ.get("COMROOT", "")) / os.environ.get("NET", "") / f"{run}.{pdy}"
    comin = os.environ.get("COMIN")
    if (not comin or Path(comin) == default) and Path(comout) != default:
        os.environ["COMIN"] = comout
        stage_logger(_STAGE, descriptor.name).info("COMIN=%s (follows COMOUT override)", comout)


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
