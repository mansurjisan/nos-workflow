"""Logging helpers for stage modules.

The CLI's ``_UTCFormatter`` prints ``[ts] [stage] [ofs] message`` and
expects ``stage`` and ``ofs`` in the log record's ``extra`` dict. Plain
``logging.getLogger(__name__)`` calls inside stage modules don't inject
those, so the formatter falls through to ``-`` placeholders — which is
what produced the ``[2026-05-11T02:46:34Z] [-] [-] ...`` lines all over
the WCOSS2 prep/nowcast logs.

``stage_logger`` returns a ``LoggerAdapter`` that auto-injects the
context on every log call, so each stage module just does::

    logger = stage_logger(_STAGE, descriptor.name)
    logger.info("staging complete")        # -> [ts] [nowcast] [secofs_ufs] staging complete

``timed_step`` is a context manager for the 4-step contract. It logs a
header on entry, an ``ok``/``fail`` footer with elapsed seconds on exit,
and re-raises the original exception unchanged.

``emit_stage_summary`` writes the canonical machine-grep-able stage
summary line (``STAGE_SUMMARY stage=... status=PASS|FAIL runtime_s=...``)
that operators / CI / monitoring tooling can rely on.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator, Optional


class _StageAdapter(logging.LoggerAdapter):
    """LoggerAdapter that pins stage + ofs into every record's extra dict.

    A caller-supplied ``extra`` on an individual log call still wins,
    so per-message overrides remain possible.
    """

    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("stage", self.extra["stage"])
        extra.setdefault("ofs", self.extra["ofs"])
        return msg, kwargs


def stage_logger(stage: str, ofs: str, name: Optional[str] = None) -> _StageAdapter:
    """Return a LoggerAdapter pre-bound to ``stage`` and ``ofs``.

    Use at the top of ``run()`` in each stage module. Pass ``name`` if
    you want a non-default logger hierarchy (defaults to
    ``nos_workflow.stages.<stage>``).
    """
    base = logging.getLogger(name or f"nos_workflow.stages.{stage}")
    return _StageAdapter(base, {"stage": stage, "ofs": ofs})


@contextmanager
def timed_step(logger: _StageAdapter, step: str) -> Iterator[None]:
    """Time a stage step. Logs header on entry and ok/fail footer on exit.

    Re-raises any exception unchanged so callers can map to
    ``StageFailedError`` as they already do.
    """
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
    """Emit the canonical end-of-stage summary line.

    Format::

        STAGE_SUMMARY stage=nowcast ofs=secofs_ufs status=PASS runtime_s=1890.3 [k=v ...]

    ``status`` should be one of ``PASS`` / ``FAIL`` / ``SKIP``. ``extras``
    is a flat dict of additional ``key=value`` pairs to append; values
    are stringified without quoting.
    """
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


__all__ = ["stage_logger", "timed_step", "emit_stage_summary"]
