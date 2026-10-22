"""Logging helpers for stage modules."""
from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from typing import Iterator, Optional


_stage_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "nos_workflow_stage", default="-"
)
_ofs_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "nos_workflow_ofs", default="-"
)


class StageContextFilter(logging.Filter):
    """Inject stage/ofs from contextvars onto records that lack them."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "stage"):
            record.stage = _stage_var.get()
        if not hasattr(record, "ofs"):
            record.ofs = _ofs_var.get()
        return True


class _StageAdapter(logging.LoggerAdapter):
    """LoggerAdapter that pins stage + ofs into every record's extra dict."""

    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("stage", self.extra["stage"])
        extra.setdefault("ofs", self.extra["ofs"])
        return msg, kwargs


def stage_logger(stage: str, ofs: str, name: Optional[str] = None) -> _StageAdapter:
    """Return a LoggerAdapter pre-bound to ``stage`` and ``ofs``."""
    _stage_var.set(stage)
    _ofs_var.set(ofs)
    base = logging.getLogger(name or f"nos_workflow.stages.{stage}")
    return _StageAdapter(base, {"stage": stage, "ofs": ofs})


@contextmanager
def timed_step(logger: _StageAdapter, step: str) -> Iterator[None]:
    """Time a stage step. Logs header on entry and ok/fail footer on exit."""
    logger.info("--- step: %s ---", step)
    t0 = time.monotonic()
    status = "ok"
    try:
        yield
    except BaseException:
        status = "fail"
        raise
    finally:
        dt = time.monotonic() - t0
        logger.info("--- step: %s done (status=%s, elapsed=%.1fs) ---", step, status, dt)


def emit_stage_summary(
    logger: _StageAdapter,
    *,
    status: str,
    runtime_s: float,
    extras: Optional[dict] = None,
) -> None:
    """Emit the canonical end-of-stage summary line."""
    parts = [
        f"STAGE_SUMMARY",
        f"stage={logger.extra['stage']}",
        f"ofs={logger.extra['ofs']}",
        f"status={status}",
        f"runtime_s={runtime_s:.1f}",
    ]
    if extras:
        for k, v in extras.items():
            parts.append(f"{k}={v}")
    logger.info(" ".join(parts))


__all__ = [
    "stage_logger",
    "timed_step",
    "emit_stage_summary",
    "StageContextFilter",
]
