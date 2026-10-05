"""Shared driver for the ADCIRC (STOFS-2D-GLO) model stages. MJ (10/05/26)"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from .._log import emit_stage_summary, stage_logger, timed_step
from ..errors import StageFailedError
from ..registry import OFSDescriptor


def load_context(descriptor: OFSDescriptor):
    from ..runners.adcirc.settings import AdcircSettings, CycleContext

    cfg = os.environ.get("OFS_CONFIG") or Path(os.environ.get("HOMEnos", ".")) / descriptor.yaml_path
    return CycleContext.from_env(AdcircSettings.from_yaml(cfg))


def run_model_stage(descriptor: OFSDescriptor, stage: str, step: Callable) -> int:
    """Run ``step(ctx)``; any failure becomes a StageFailedError with a FAIL summary."""
    sl = stage_logger(stage, descriptor.name)
    t0 = time.monotonic()
    try:
        ctx = load_context(descriptor)
        with timed_step(sl, f"run_{stage}"):
            argv = step(ctx)
    except Exception as exc:  # noqa: BLE001
        emit_stage_summary(sl, status="FAIL", runtime_s=time.monotonic() - t0,
                           extras={"reason": str(exc)[:200]})
        raise StageFailedError(stage=stage, ofs=descriptor.name, returncode=1,
                               msg=f"ADCIRC {stage} failed: {exc}") from exc
    emit_stage_summary(sl, status="PASS", runtime_s=time.monotonic() - t0,
                       extras={"launch": " ".join(argv)})
    return 0
