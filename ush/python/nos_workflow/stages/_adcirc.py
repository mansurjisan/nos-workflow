"""Shared driver for the ADCIRC (STOFS-2D-GLO) model stages. MJ (10/05/26)"""
from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Tuple

from .._log import emit_stage_summary, stage_logger, timed_step
from ..errors import StageFailedError
from ..registry import OFSDescriptor


def load_context(descriptor: OFSDescriptor):
    from ..runners.adcirc.settings import AdcircSettings, CycleContext

    cfg = os.environ.get("OFS_CONFIG") or Path(os.environ.get("HOMEnos", ".")) / descriptor.yaml_path
    return CycleContext.from_env(AdcircSettings.from_yaml(cfg))


def _items(value: str) -> List[str]:
    """A list value is space separated (qsub -v and sbatch --export split at commas); commas are accepted too. MJ (10/14/26)"""
    return value.replace(",", " ").split()


def ops_steps(ctx, stage: str) -> List[Tuple[str, object]]:
    """The (label, ctx) steps of one ops job. ADCIRC_SEGMENT and ADCIRC_STREAM take one value or a space (or comma) separated list:
    the segments run in the order given, ncst and fcst once per stream, the tide-only spin-up once. A list must follow the
    canonical order of its job and have no duplicates, and it is checked whole before the first step starts, so a typo cannot
    cost a spin-up first. MJ (10/14/26)"""
    from ..runners.adcirc import ops
    from ..runners.adcirc.settings import AdcircConfigError

    segs, streams = _items(ctx.segment), _items(ctx.stream)
    allowed = ops.SEGMENTS[stage]
    for seg in segs:
        ops.check_retired(seg)
    if not segs or segs != [s for s in allowed if s in segs]:
        raise AdcircConfigError(f"ADCIRC_SEGMENT must be one or more of {allowed}, in that order and without repeats, got {ctx.segment!r}")
    per_stream = ops.PER_STREAM.get(stage, ())
    if any(s in per_stream for s in segs) and (not streams or streams != [s for s in ops.STREAMS if s in streams]):
        raise AdcircConfigError(f"ADCIRC_STREAM must be one or more of {tuple(ops.STREAMS)}, in that order and without repeats, got {ctx.stream!r}")
    steps = []
    for seg in segs:
        if seg in per_stream:
            steps += [(f"{st}_{seg}", replace(ctx, segment=seg, stream=st)) for st in streams]
        else:
            steps.append((f"gfs_{seg}" if stage == "prep" and seg != "adcprep" else seg, replace(ctx, segment=seg, stream="")))
    return steps


def run_model_stage(descriptor: OFSDescriptor, stage: str, step: Callable) -> int:
    """Run ``step(ctx)``; any failure becomes a StageFailedError with a FAIL summary. In ops mode the job runs ``step`` for each
    (segment, stream) of ops_steps, one after the other, and the first failure stops it. The PASS and FAIL summaries list the
    seconds each finished step took (steps=tide_ncst:671,surf_ncst:791) and a failure names its step. MJ (10/14/26)"""
    sl = stage_logger(stage, descriptor.name)
    t0 = time.monotonic()
    name, done, argv = None, [], None
    try:
        ctx = load_context(descriptor)
        is_ops = ctx.settings.mode == "ops"
        for name, c in (ops_steps(ctx, stage) if is_ops else [(None, ctx)]):
            t1 = time.monotonic()
            with timed_step(sl, name or f"run_{stage}"):
                argv = step(c)
            done.append(f"{name}:{round(time.monotonic() - t1)}")
    except Exception as exc:  # noqa: BLE001
        why = f"{name}: {exc}" if name else str(exc)
        emit_stage_summary(sl, status="FAIL", runtime_s=time.monotonic() - t0,
                           extras={**({"steps": ",".join(done)} if done else {}), "reason": why[:200]})
        raise StageFailedError(stage=stage, ofs=descriptor.name, returncode=1,
                               msg=f"ADCIRC {stage} failed: {why}") from exc
    extras = {"steps": ",".join(done)} if is_ops else {}
    if argv:
        extras["launch"] = " ".join(argv)
    emit_stage_summary(sl, status="PASS", runtime_s=time.monotonic() - t0, extras=extras)
    return 0
