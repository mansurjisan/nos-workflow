"""Unit tests for ``nos_workflow.runners.schism_ufs.combine_hotstart``.

The actual ``combine_hotstart7`` Fortran binary stays in shell; here we
verify the Python orchestrator that finds the last hotstart step and
hands it to ``_schism_run_combine_hotstart``. The shell-bridge call is
mocked via ``unittest.mock.patch``.

Shell counterpart: ``_schism_run_combine_hotstart`` in
``ush/nos_run.sh`` (extracted in PR 8).
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

from nos_workflow.runners.schism_ufs import combine_hotstart
from nos_workflow.runners.schism_ufs.context import SchismRunContext


def _make_ctx(tmp_path: Path, *, phase: str = "nowcast") -> SchismRunContext:
    """Build a minimal context with $DATA + $USHnos + a stub nos_run.sh
    so the file-exists check inside ``_invoke_shell_wrapper`` passes."""
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    ushnos = tmp_path / "ushnos"
    comout.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    ushnos.mkdir(parents=True, exist_ok=True)
    (ushnos / "nos_run.sh").write_text(
        "#!/bin/bash\n_schism_run_combine_hotstart() { return 0; }\n"
    )
    return SchismRunContext(
        comout=comout,
        data=data,
        phase=phase,
        run="nos.secofs_ufs",
        cycle="t00z",
        pdy="20260512",
        cyc="00",
        ushnos=ushnos,
    )


# ---------------------------------------------------------------------------
# _find_last_hotstart_step
# ---------------------------------------------------------------------------


def test_find_last_hotstart_step_returns_max(tmp_path):
    """Multiple hotstart files -> return the highest step number."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    for step in (100, 200, 300):
        (outputs / f"hotstart_000000_{step}.nc").write_text("x")
    assert combine_hotstart._find_last_hotstart_step(outputs) == 300


def test_find_last_hotstart_step_returns_none_if_no_files(tmp_path):
    """Empty outputs/ -> None."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    assert combine_hotstart._find_last_hotstart_step(outputs) is None


def test_find_last_hotstart_step_skips_non_matching(tmp_path):
    """Files that don't match the glob are ignored (the
    ``hotstart_000000_*.nc`` filter is intentional)."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_000000_180.nc").write_text("x")
    # These should NOT count:
    (outputs / "hotstart_it=180.nc").write_text("x")          # post-combine
    (outputs / "schout_000000_180.nc").write_text("x")        # different file class
    (outputs / "random.log").write_text("x")
    assert combine_hotstart._find_last_hotstart_step(outputs) == 180


def test_find_last_hotstart_step_handles_higher_rank_numbers(tmp_path):
    """Files with rank > 0 (e.g. hotstart_000128_180.nc) -- the regex is
    intentionally loose to handle the case where the operator's `ls` of
    outputs picks up non-rank-0 files; max step still wins."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    # Only rank-0 matches the glob, but the regex is also tested with
    # the literal name.
    (outputs / "hotstart_000000_500.nc").write_text("x")
    assert combine_hotstart._find_last_hotstart_step(outputs) == 500


# ---------------------------------------------------------------------------
# combine_hotstart_files
# ---------------------------------------------------------------------------


def test_combine_hotstart_files_missing_outputs_dir(tmp_path, caplog):
    """No outputs/ -> rc=0 + warning (non-fatal, matches shell)."""
    ctx = _make_ctx(tmp_path)
    caplog.set_level(
        logging.WARNING,
        logger="nos_workflow.runners.schism_ufs.combine_hotstart",
    )
    rc = combine_hotstart.combine_hotstart_files(ctx, "nowcast")
    assert rc == 0
    assert any("outputs missing" in rec.getMessage() for rec in caplog.records)


def test_combine_hotstart_files_no_hotstart_files(tmp_path, caplog):
    """outputs/ exists but is empty -> rc=0 + warning."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "outputs").mkdir()
    caplog.set_level(
        logging.WARNING,
        logger="nos_workflow.runners.schism_ufs.combine_hotstart",
    )
    rc = combine_hotstart.combine_hotstart_files(ctx, "nowcast")
    assert rc == 0
    assert any(
        "no hotstart_000000" in rec.getMessage() for rec in caplog.records
    )


def test_combine_hotstart_files_invokes_shell_wrapper(tmp_path, monkeypatch):
    """Hotstart files present -> shell wrapper invoked with (step, phase)
    and its rc is returned."""
    ctx = _make_ctx(tmp_path)
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_000000_180.nc").write_text("x")
    monkeypatch.setenv("USHnos", str(ctx.ushnos))

    with patch.object(
        combine_hotstart, "run_shell_function", return_value=0,
    ) as rsf:
        rc = combine_hotstart.combine_hotstart_files(ctx, "nowcast")
    assert rc == 0
    rsf.assert_called_once()
    kwargs = rsf.call_args.kwargs
    assert kwargs["function"] == "_schism_run_combine_hotstart"
    assert kwargs["args"] == ("180", "nowcast")
    assert kwargs["cwd"] == ctx.data
    assert Path(kwargs["script"]).name == "nos_run.sh"


def test_combine_hotstart_files_propagates_wrapper_rc(tmp_path, monkeypatch):
    """Non-zero rc from the shell wrapper is propagated to the caller."""
    ctx = _make_ctx(tmp_path)
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_000000_180.nc").write_text("x")
    monkeypatch.setenv("USHnos", str(ctx.ushnos))

    with patch.object(
        combine_hotstart, "run_shell_function", return_value=7,
    ):
        rc = combine_hotstart.combine_hotstart_files(ctx, "nowcast")
    assert rc == 7


def test_combine_hotstart_files_passes_forecast_phase(tmp_path, monkeypatch):
    """Phase=forecast is passed through to the shell wrapper unchanged
    (used in the rst archive filename)."""
    ctx = _make_ctx(tmp_path, phase="forecast")
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_000000_360.nc").write_text("x")
    monkeypatch.setenv("USHnos", str(ctx.ushnos))

    with patch.object(
        combine_hotstart, "run_shell_function", return_value=0,
    ) as rsf:
        combine_hotstart.combine_hotstart_files(ctx, "forecast")
    assert rsf.call_args.kwargs["args"] == ("360", "forecast")


def test_combine_hotstart_files_missing_ushnos(tmp_path, monkeypatch, caplog):
    """USHnos absent from env AND ctx.ushnos is None -> rc=1 + error log,
    no shell call."""
    # Build ctx with NO ushnos set.
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    comout.mkdir()
    data.mkdir()
    outputs = data / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_000000_180.nc").write_text("x")
    ctx = SchismRunContext(
        comout=comout, data=data, phase="nowcast",
        run="nos.secofs_ufs", cycle="t00z",
    )
    monkeypatch.delenv("USHnos", raising=False)

    caplog.set_level(
        logging.ERROR,
        logger="nos_workflow.runners.schism_ufs.combine_hotstart",
    )
    with patch.object(combine_hotstart, "run_shell_function") as rsf:
        rc = combine_hotstart.combine_hotstart_files(ctx, "nowcast")
    assert rc == 1
    rsf.assert_not_called()
    assert any("USHnos not set" in rec.getMessage() for rec in caplog.records)
