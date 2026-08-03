"""Unit tests for ``nos_workflow.runners.schism_ufs.execute.run_python``.

Covers the orchestration without actually running mpiexec (we mock the
shell-bridge helpers + the mesh module). The actual ``module load`` /
mpiexec / ``combine_hotstart7`` invocations are exercised in shell-side
integration tests on WCOSS2; this file pins the Python contract.

Shell counterpart: ``_schism_execute_ufs_coastal`` in
``ush/nos_run.sh`` (PR 8 refactored body).
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from nos_workflow.runners.schism_ufs import execute
from nos_workflow.runners.schism_ufs.context import SchismRunContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    tmp_path: Path,
    *,
    phase: str = "nowcast",
    rst_out_nowcast: str | None = None,
    rst_out_forecast: str | None = None,
) -> SchismRunContext:
    """Build a context with $COMOUT / $DATA / $USHnos under tmp_path.

    The USHnos directory contains a stub nos_run.sh so the shell-bridge
    path checks pass even when we mock run_shell_function. Tests can
    override rst_out_* to exercise the archive branch.
    """
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    ushnos = tmp_path / "ushnos"
    comout.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    ushnos.mkdir(parents=True, exist_ok=True)
    # Stub nos_run.sh so the file-exists check inside _run_mpi_shell /
    # combine_hotstart._invoke_shell_wrapper passes. Content doesn't
    # matter -- run_shell_function is mocked in every test.
    (ushnos / "nos_run.sh").write_text(
        "#!/bin/bash\n_schism_run_mpi() { return 0; }\n"
        "_schism_run_combine_hotstart() { return 0; }\n"
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
        rst_out_nowcast=rst_out_nowcast,
        rst_out_forecast=rst_out_forecast,
    )


def _seed_configs(data: Path, *, missing: tuple = ()) -> None:
    """Drop a minimal set of UFS config files into $DATA. ``missing``
    names files to skip so a test can exercise the validation branch."""
    for name in ("model_configure", "datm_in", "datm.streams", "ufs.configure"):
        if name in missing:
            continue
        (data / name).write_text(f"# stub {name}\n")


# ---------------------------------------------------------------------------
# _validate_configs
# ---------------------------------------------------------------------------


def test_validate_configs_pass(tmp_path):
    """All four required UFS configs present -> rc=0."""
    ctx = _make_ctx(tmp_path)
    _seed_configs(ctx.data)
    assert execute._validate_configs(ctx, "nowcast") == 0


def test_validate_configs_fails_on_missing_model_configure(tmp_path, caplog):
    """A missing required config -> rc=1 + error log."""
    ctx = _make_ctx(tmp_path)
    _seed_configs(ctx.data, missing=("model_configure",))
    caplog.set_level(
        logging.ERROR,
        logger="nos_workflow.runners.schism_ufs.execute",
    )
    rc = execute._validate_configs(ctx, "nowcast")
    assert rc == 1
    assert any("model_configure" in rec.getMessage() for rec in caplog.records)


def test_validate_configs_fails_on_empty_config(tmp_path):
    """An empty config file is treated as missing (matches shell's
    ``[ ! -s ... ]`` test)."""
    ctx = _make_ctx(tmp_path)
    _seed_configs(ctx.data)
    # Truncate one of them.
    (ctx.data / "datm_in").write_text("")
    rc = execute._validate_configs(ctx, "nowcast")
    assert rc == 1


# ---------------------------------------------------------------------------
# _maybe_regenerate_mesh
# ---------------------------------------------------------------------------


def test_maybe_regenerate_mesh_skips_when_no_forcing(tmp_path):
    """Missing datm_forcing.nc -> rc=0, no mesh call (non-fatal)."""
    ctx = _make_ctx(tmp_path)
    # No INPUT/ directory at all.
    with patch.object(execute.mesh, "generate_esmf_mesh") as gen:
        rc = execute._maybe_regenerate_mesh(ctx, "nowcast")
        assert rc == 0
        gen.assert_not_called()


def test_maybe_regenerate_mesh_calls_mesh_module(tmp_path):
    """Forcing file present -> mesh.generate_esmf_mesh is invoked with
    the right paths and its rc is propagated."""
    ctx = _make_ctx(tmp_path)
    input_dir = ctx.data / "INPUT"
    input_dir.mkdir()
    forcing = input_dir / "datm_forcing.nc"
    forcing.write_bytes(b"\x89HDF\r\n\x1a\n" + b"x" * 64)

    with patch.object(execute.mesh, "generate_esmf_mesh", return_value=0) as gen:
        rc = execute._maybe_regenerate_mesh(ctx, "nowcast")
        assert rc == 0
        gen.assert_called_once()
        # First positional arg must be the forcing path.
        args, _ = gen.call_args
        assert Path(args[0]) == forcing
        # Second is the output mesh path under the same INPUT/ dir.
        assert Path(args[1]) == input_dir / "datm_esmf_mesh.nc"


def test_maybe_regenerate_mesh_propagates_failure_rc(tmp_path):
    """Mesh generator non-zero rc is returned but treated as non-fatal
    upstream in ``run_python``."""
    ctx = _make_ctx(tmp_path)
    input_dir = ctx.data / "INPUT"
    input_dir.mkdir()
    (input_dir / "datm_forcing.nc").write_bytes(b"x" * 64)
    with patch.object(execute.mesh, "generate_esmf_mesh", return_value=2):
        rc = execute._maybe_regenerate_mesh(ctx, "nowcast")
        assert rc == 2


# ---------------------------------------------------------------------------
# _run_mpi_shell
# ---------------------------------------------------------------------------


def test_run_mpi_shell_calls_shell_function(tmp_path, monkeypatch):
    """The Python wrapper invokes ``run_shell_function`` with the right
    script + function + args."""
    ctx = _make_ctx(tmp_path)
    monkeypatch.setenv("USHnos", str(ctx.ushnos))
    with patch.object(execute, "run_shell_function", return_value=0) as rsf:
        rc = execute._run_mpi_shell(ctx, "nowcast")
        assert rc == 0
        rsf.assert_called_once()
        kwargs = rsf.call_args.kwargs
        assert kwargs["function"] == "_schism_run_mpi"
        assert kwargs["args"] == ("nowcast",)
        assert kwargs["cwd"] == ctx.data
        assert Path(kwargs["script"]).name == "nos_run.sh"


def test_run_mpi_shell_returns_subprocess_rc(tmp_path, monkeypatch):
    """Non-zero rc from the shell function propagates."""
    ctx = _make_ctx(tmp_path)
    monkeypatch.setenv("USHnos", str(ctx.ushnos))
    with patch.object(execute, "run_shell_function", return_value=42):
        assert execute._run_mpi_shell(ctx, "nowcast") == 42


def test_run_mpi_shell_fails_when_nos_run_missing(tmp_path, monkeypatch, caplog):
    """USHnos points to a directory that doesn't contain nos_run.sh ->
    rc=1, no shell function call."""
    ctx = _make_ctx(tmp_path)
    bad = tmp_path / "no-such-dir"
    bad.mkdir()
    monkeypatch.setenv("USHnos", str(bad))
    caplog.set_level(logging.ERROR, logger="nos_workflow.runners.schism_ufs.execute")
    with patch.object(execute, "run_shell_function") as rsf:
        rc = execute._run_mpi_shell(ctx, "nowcast")
        assert rc == 1
        rsf.assert_not_called()
    assert any("nos_run.sh not found" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# _archive_restart
# ---------------------------------------------------------------------------


def test_archive_restart_copies_nowcast_to_rst_out(tmp_path):
    """Nowcast phase: source hotstart_it=*.nc -> ctx.rst_out_nowcast."""
    ctx = _make_ctx(tmp_path, rst_out_nowcast="nos.secofs_ufs.t00z.rst.nowcast.nc")
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    src = outputs / "hotstart_it=180.nc"
    src.write_text("hotstart data")

    rc = execute._archive_restart(ctx, "nowcast")
    assert rc == 0
    dst = ctx.comout / "nos.secofs_ufs.t00z.rst.nowcast.nc"
    assert dst.is_file()
    assert dst.read_text() == "hotstart data"


def test_archive_restart_copies_forecast_to_rst_out_forecast(tmp_path):
    """Forecast phase: source hotstart_it=*.nc -> ctx.rst_out_forecast."""
    ctx = _make_ctx(
        tmp_path,
        rst_out_forecast="nos.secofs_ufs.t00z.rst.forecast.nc",
    )
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_it=360.nc").write_text("fcst hotstart")

    rc = execute._archive_restart(ctx, "forecast")
    assert rc == 0
    dst = ctx.comout / "nos.secofs_ufs.t00z.rst.forecast.nc"
    assert dst.is_file()
    assert dst.read_text() == "fcst hotstart"


def test_archive_restart_picks_latest_when_multiple_steps(tmp_path):
    """If there are multiple ``hotstart_it=*.nc`` files, pick the one with
    the highest step number -- matches the canonical operator expectation
    (single combine output per run, but defensive against re-runs)."""
    ctx = _make_ctx(tmp_path, rst_out_nowcast="x.rst.nowcast.nc")
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_it=100.nc").write_text("older")
    (outputs / "hotstart_it=180.nc").write_text("newer")

    execute._archive_restart(ctx, "nowcast")
    assert (ctx.comout / "x.rst.nowcast.nc").read_text() == "newer"


def test_archive_restart_picks_numerically_highest_step(tmp_path):
    """Regression: step numbers must be compared numerically, not
    lexicographically. AK's daily 12z cadence (nhot_write=1920) writes
    hotstarts at steps 480/960/1440/1920 -- as strings "960" sorts after
    "1920", so a lexical pick would silently archive the 12h state instead
    of the final one."""
    ctx = _make_ctx(tmp_path, rst_out_nowcast="x.rst.nowcast.nc")
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_it=480.nc").write_text("stack1")
    (outputs / "hotstart_it=960.nc").write_text("stack2")
    (outputs / "hotstart_it=1440.nc").write_text("stack3")
    (outputs / "hotstart_it=1920.nc").write_text("final")

    execute._archive_restart(ctx, "nowcast")
    assert (ctx.comout / "x.rst.nowcast.nc").read_text() == "final"


def test_archive_restart_no_source_is_nonfatal(tmp_path, caplog):
    """No outputs/ directory -> rc=0, info log (non-fatal)."""
    ctx = _make_ctx(tmp_path, rst_out_nowcast="x.rst.nowcast.nc")
    caplog.set_level(logging.INFO, logger="nos_workflow.runners.schism_ufs.execute")
    rc = execute._archive_restart(ctx, "nowcast")
    assert rc == 0


def test_archive_restart_unknown_phase_is_nonfatal(tmp_path, caplog):
    """Unknown phase -> rc=0 + warning (defensive against dispatcher
    typos; matches the shell's silent skip)."""
    ctx = _make_ctx(tmp_path)
    caplog.set_level(logging.WARNING, logger="nos_workflow.runners.schism_ufs.execute")
    rc = execute._archive_restart(ctx, "bogus")
    assert rc == 0
    assert any("unknown phase" in rec.getMessage().lower() for rec in caplog.records)


def test_archive_restart_skips_when_rst_out_is_none(tmp_path):
    """ctx.rst_out_{phase} is None -> no-op, rc=0 (combine_hotstart shell
    helper already wrote the canonical filename)."""
    ctx = _make_ctx(tmp_path, rst_out_nowcast=None)
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_it=180.nc").write_text("data")

    rc = execute._archive_restart(ctx, "nowcast")
    assert rc == 0
    # Nothing should have been copied (no destination set).
    assert list(ctx.comout.iterdir()) == []


# ---------------------------------------------------------------------------
# run_python full orchestration
# ---------------------------------------------------------------------------


def test_run_python_full_orchestration_happy_path(tmp_path, monkeypatch):
    """All shell + mesh calls succeed -> rc=0 and each helper is called
    exactly once in the right order."""
    ctx = _make_ctx(
        tmp_path,
        rst_out_nowcast="nos.secofs_ufs.t00z.rst.nowcast.nc",
    )
    monkeypatch.setenv("USHnos", str(ctx.ushnos))
    _seed_configs(ctx.data)
    # Stage a hotstart for the archive step.
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "hotstart_it=180.nc").write_text("combined hotstart data")

    with patch.object(execute, "run_shell_function", return_value=0) as rsf, \
         patch.object(execute.mesh, "generate_esmf_mesh", return_value=0) as gen, \
         patch.object(
             execute.combine_hotstart,
             "combine_hotstart_files",
             return_value=0,
         ) as ch:
        rc = execute.run_python(ctx, "nowcast")

    assert rc == 0
    # MPI launcher was invoked (via run_shell_function for _schism_run_mpi).
    rsf.assert_called_once()
    assert rsf.call_args.kwargs["function"] == "_schism_run_mpi"
    # No DATM forcing was staged so mesh.generate_esmf_mesh is NOT called.
    gen.assert_not_called()
    # Combine helper is invoked.
    ch.assert_called_once_with(ctx, "nowcast")
    # Restart archive landed at the rst_out filename.
    assert (ctx.comout / "nos.secofs_ufs.t00z.rst.nowcast.nc").is_file()


def test_run_python_returns_validation_error_without_invoking_mpi(tmp_path, monkeypatch):
    """If validation fails, run_python returns non-zero and does NOT
    call mpiexec."""
    ctx = _make_ctx(tmp_path)
    monkeypatch.setenv("USHnos", str(ctx.ushnos))
    # No configs seeded -> validation fails.
    with patch.object(execute, "run_shell_function") as rsf, \
         patch.object(execute.combine_hotstart, "combine_hotstart_files") as ch:
        rc = execute.run_python(ctx, "nowcast")
    assert rc != 0
    rsf.assert_not_called()
    ch.assert_not_called()


def test_run_python_returns_mpi_error_and_skips_combine(tmp_path, monkeypatch):
    """mpiexec failure short-circuits before combine_hotstart -- a failed
    run has nothing to combine."""
    ctx = _make_ctx(tmp_path)
    monkeypatch.setenv("USHnos", str(ctx.ushnos))
    _seed_configs(ctx.data)
    with patch.object(execute, "run_shell_function", return_value=137) as rsf, \
         patch.object(execute.combine_hotstart, "combine_hotstart_files") as ch:
        rc = execute.run_python(ctx, "nowcast")
    assert rc == 137
    rsf.assert_called_once()
    ch.assert_not_called()


def test_run_python_combine_failure_is_nonfatal(tmp_path, monkeypatch, caplog):
    """combine_hotstart non-zero rc is logged at WARNING but does NOT
    fail the stage (matches the shell which only emits a WARNING)."""
    ctx = _make_ctx(tmp_path)
    monkeypatch.setenv("USHnos", str(ctx.ushnos))
    _seed_configs(ctx.data)
    caplog.set_level(logging.WARNING, logger="nos_workflow.runners.schism_ufs.execute")
    with patch.object(execute, "run_shell_function", return_value=0), \
         patch.object(
             execute.combine_hotstart,
             "combine_hotstart_files",
             return_value=3,
         ):
        rc = execute.run_python(ctx, "nowcast")
    assert rc == 0
    assert any(
        "combine_hotstart returned rc=3" in rec.getMessage()
        for rec in caplog.records
    )
