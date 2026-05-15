"""Unit tests for ``nos_workflow.runners.schism_ufs.prepare_restart.run_python``.

Mirrors the behavior of ``_schism_prepare_restart`` in ``ush/nos_run.sh``
(lines 770-781). The shell function is a no-op — actual restart staging
happens inside ``_schism_stage_files`` step 6 — so the Python port is
also a no-op. We just verify the contract: rc=0 and an info log entry
naming the phase so operators can grep ``OUTPUT.$$`` for the dispatch.
"""
from __future__ import annotations

import logging
from pathlib import Path

from nos_workflow.runners.schism_ufs.context import SchismRunContext
from nos_workflow.runners.schism_ufs.prepare_restart import run_python


def _make_ctx(tmp_path: Path, *, phase: str = "nowcast") -> SchismRunContext:
    """Minimal context (only the 5 required PR-2 fields)."""
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    comout.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    return SchismRunContext(
        comout=comout, data=data, phase=phase,
        run="nos.secofs_ufs", cycle="t00z",
    )


def test_prepare_restart_returns_zero(tmp_path):
    """No-op port always returns 0 (matches shell, which always returns 0)."""
    ctx = _make_ctx(tmp_path)
    assert run_python(ctx, "nowcast") == 0


def test_prepare_restart_returns_zero_forecast_phase(tmp_path):
    """Forecast phase is identical to nowcast in shell — same here."""
    ctx = _make_ctx(tmp_path, phase="forecast")
    assert run_python(ctx, "forecast") == 0


def test_prepare_restart_logs_phase(tmp_path, caplog):
    """An info log record must fire with the phase so operators can
    grep ``OUTPUT.$$`` for restart-prep dispatch on the Python path."""
    ctx = _make_ctx(tmp_path)
    caplog.set_level(
        logging.INFO,
        logger="nos_workflow.runners.schism_ufs.prepare_restart",
    )
    run_python(ctx, "nowcast")
    assert any(
        "nowcast" in rec.getMessage()
        for rec in caplog.records
        if rec.levelno >= logging.INFO
    ), "expected an INFO log mentioning the phase"
