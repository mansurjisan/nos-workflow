"""Logging helpers for stage modules.

The CLI's ``_UTCFormatter`` prints ``[ts] [stage] [ofs] message`` and
expects ``stage`` and ``ofs`` attributes on the log record. Two
complementary mechanisms keep those attributes populated:

1. ``stage_logger(stage, ofs)`` returns a ``LoggerAdapter`` that auto-
   injects ``stage`` and ``ofs`` via ``extra=`` on every log call from
   the stage module. Adapter-emitted lines are guaranteed to carry the
   correct context.

2. ``StageContextFilter`` (attached to the handler by the CLI's
   ``setup_logging``) injects the same ``stage`` and ``ofs`` onto
   records that come from bare ``logging.getLogger(__name__).info(...)``
   calls — e.g. the loggers used inside ``nos_utils.forcing.*``
   processors. Without it those records showed up as
   ``[2026-05-11T16:08:11Z] [-] [-] ...`` in prep logs because the
   formatter found no stage/ofs to format.

The filter reads from two ``contextvars.ContextVar``s that
``stage_logger`` sets when the stage starts. Adapter-emitted records
already carry stage/ofs as record attributes (via the ``extra`` dict),
so the filter is a no-op for those — adapter overrides always win.

``timed_step`` is a context manager for the 4-step contract. It logs a
header on entry, an ``ok``/``fail`` footer with elapsed seconds on exit,
and re-raises the original exception unchanged.

``emit_stage_summary`` writes the canonical machine-grep-able stage
summary line (``STAGE_SUMMARY stage=... status=PASS|FAIL runtime_s=...``)
that operators / CI / monitoring tooling can rely on.
"""
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
    """Inject stage/ofs from contextvars onto records that lack them.

    Adapter-emitted records already have ``stage`` and ``ofs`` set as
    record attributes (via the LoggerAdapter's ``extra`` dict), so the
    filter is a no-op for them. Records from bare logger calls inside
    libraries (e.g. ``nos_utils.forcing.*``) lack those attributes and
    get them populated from the contextvars that ``stage_logger`` set
    at stage entry.

    Always returns True — this is a record-mutator, not a record-
    rejecter.

    Attach to the CLI's stream handler in ``setup_logging`` so every
    record flowing to console/file picks up the context, regardless of
    which logger it originated from.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "stage"):
            record.stage = _stage_var.get()
        if not hasattr(record, "ofs"):
            record.ofs = _ofs_var.get()
        return True


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

    Also publishes ``stage`` / ``ofs`` into process-wide context vars so
    that bare ``logging.getLogger(__name__)`` calls inside libraries
    (e.g. ``nos_utils.forcing.*`` processors) pick up the same context
    through ``StageContextFilter`` once it has been attached to the
    handler (CLI's ``setup_logging`` does this automatically).

    Use at the top of ``run()`` in each stage module. Pass ``name`` if
    you want a non-default logger hierarchy (defaults to
    ``nos_workflow.stages.<stage>``).
    """
    _stage_var.set(stage)
    _ofs_var.set(ofs)
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


__all__ = [
    "stage_logger",
    "timed_step",
    "emit_stage_summary",
    "StageContextFilter",
]
