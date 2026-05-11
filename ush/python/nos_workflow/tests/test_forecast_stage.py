"""Forecast stage tests for nos_workflow.stages.forecast.

Mirrors ``test_nowcast_stage.py`` with phase-arg substitution. The COMF
body shells out to ``ush/nos_run.sh`` via
``bash_compat.run_shell_function``. We mock that callable so the body
can exercise its env-validation, step ordering, and error-propagation
logic without actually sourcing the shell library.

The forecast-specific operational delta (hotstart pickup from THIS
cycle's nowcast COMOUT, ``RNDAY_FORECAST`` / ``PDYHH_FCAST_BEGIN`` env
vars, ``forecast_outputs/`` archive dir) is all handled inside
``nos_run.sh`` by branching on the ``"forecast"`` phase arg — the Python
stage doesn't special-case any of it. So the unit-test surface is
structurally identical to ``test_nowcast_stage.py``: we just assert the
right phase arg flows through and the right log lines fire.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from nos_workflow.errors import StageFailedError
from nos_workflow.registry import OFSDescriptor
from nos_workflow.stages import forecast as forecast_stage


# ---------------------------------------------------------------------------
# Descriptor fixtures (kept shape-identical to test_nowcast_stage.py so they
# can be lifted into a shared module later without diffs).
# ---------------------------------------------------------------------------


def _secofs_ufs_desc() -> OFSDescriptor:
    return OFSDescriptor(
        name="secofs_ufs",
        framework="comf",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={},
        yaml_path=Path("parm/systems/secofs_ufs.yaml"),
        runner_module="nos_workflow.runners.ufs_coastal",
        notes="test fixture",
    )


def _stofs_3d_desc() -> OFSDescriptor:
    return OFSDescriptor(
        name="stofs_3d_atl",
        framework="stofs",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={"prep_nowcast": "prep", "now_forecast": "nowcast"},
        extra_stages=("post_1", "post_2", "temp_salt_restart"),
        yaml_path=Path("parm/systems/stofs_3d_atl.yaml"),
        runner_module="",
        notes="test fixture",
    )


def _adcirc_desc() -> OFSDescriptor:
    return OFSDescriptor(
        name="stofs_2d_glo",
        framework="adcirc",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={},
        yaml_path=Path("parm/systems/stofs_2d_glo.yaml"),
        runner_module="",
        notes="test fixture",
    )


@pytest.fixture
def fake_env() -> object:
    """Trivial stand-in for ``NCOEnv`` — the forecast stage reads
    ``os.environ`` directly, so this is unused but matches the
    dispatch-test signature."""
    return object()


# ---------------------------------------------------------------------------
# Framework-branch tests (mirror nowcast_stage tests).
# ---------------------------------------------------------------------------


def test_forecast_stofs_branch_mentions_task_33(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        forecast_stage.run(_stofs_3d_desc(), fake_env)
    assert "#33" in str(exc_info.value)


def test_forecast_adcirc_branch_mentions_task_34(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        forecast_stage.run(_adcirc_desc(), fake_env)
    assert "#34" in str(exc_info.value)


def test_forecast_unknown_framework_raises_stage_failed(fake_env):
    desc = OFSDescriptor(
        name="weird",
        framework="not-a-framework",
        canonical_stages=("forecast",),
    )
    with pytest.raises(StageFailedError) as exc_info:
        forecast_stage.run(desc, fake_env)
    assert exc_info.value.stage == "forecast"


def test_forecast_phase_header_logged(fake_env, caplog):
    """The shared phase-header log line ``[<UTC>] [forecast] [<ofs>] entered``
    must fire on every dispatch — even when the body later raises."""
    caplog.set_level("INFO", logger="nos_workflow.stages.forecast")
    with pytest.raises(NotImplementedError):
        forecast_stage.run(_stofs_3d_desc(), fake_env)
    assert any(
        "[forecast]" in rec.getMessage() and "stofs_3d_atl" in rec.getMessage()
        and "entered" in rec.getMessage()
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# COMF body — happy path
# ---------------------------------------------------------------------------


def _make_minimal_forecast_env(tmp_path: Path) -> dict:
    """Build the env vars the COMF forecast body requires, with stubs in
    tmp_path. The 4-step contract is mocked, so we only need USHnos/
    nos_run.sh to exist (it gets validated up-front)."""
    ushnos = tmp_path / "ush"
    data = tmp_path / "data"
    ushnos.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)

    # Drop a stub nos_run.sh (just has to exist for the path check;
    # run_shell_function is mocked so its body is never sourced).
    nos_run = ushnos / "nos_run.sh"
    nos_run.write_text("#!/bin/bash\n# stub\n")

    return {
        "USHnos": str(ushnos),
        "DATA": str(data),
        "OFS": "secofs_ufs",
        "RUN": "nos.secofs_ufs",
        "PDY": "20260507",
        "cyc": "00",
        "cycle": "t00z",
        "PREFIXNOS": "nos.secofs_ufs",
    }


def test_forecast_comf_happy_path_invokes_all_four_steps(tmp_path, fake_env):
    """End-to-end COMF happy path: every step in the 4-step contract is
    invoked with ``args=('forecast',)`` and the right script path, and
    the stage returns 0."""
    env = _make_minimal_forecast_env(tmp_path)
    nos_run = Path(env["USHnos"]) / "nos_run.sh"
    data = Path(env["DATA"])

    seen: list = []

    def fake_run_shell_function(*, script, function, args, env, cwd):
        seen.append({
            "script": Path(script),
            "function": function,
            "args": tuple(args),
            "cwd": Path(cwd) if cwd is not None else None,
            "env_keys": set(env.keys()) if env else set(),
        })
        return 0

    with patch.dict(os.environ, env, clear=False):
        with patch.object(
            forecast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            rc = forecast_stage.run(_secofs_ufs_desc(), fake_env)

    assert rc == 0
    # All 4 steps were called, in the contracted order.
    assert [c["function"] for c in seen] == [
        "stage_model_files",
        "prepare_restart",
        "execute_model",
        "archive_outputs",
    ]
    # Every call passed the same script path and the "forecast" phase arg.
    for call in seen:
        assert call["script"] == nos_run
        assert call["args"] == ("forecast",)
        assert call["cwd"] == data
        # The parent env was forwarded (otherwise the shell helpers
        # wouldn't see PDY/cyc/PREFIXNOS/etc).
        assert "PDY" in call["env_keys"]
        assert "PREFIXNOS" in call["env_keys"]


def test_forecast_comf_stops_on_first_failing_step(tmp_path, fake_env):
    """If ``stage_model_files`` returns non-zero, the body must raise
    ``StageFailedError`` with that rc and NOT call the remaining steps."""
    env = _make_minimal_forecast_env(tmp_path)

    seen: list = []

    def fake_run_shell_function(*, script, function, args, env, cwd):
        seen.append(function)
        # Fail on the first step.
        if function == "stage_model_files":
            return 7
        return 0

    with patch.dict(os.environ, env, clear=False):
        with patch.object(
            forecast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)

    # Only the first step ran; the rest were skipped.
    assert seen == ["stage_model_files"]
    assert exc_info.value.stage == "forecast"
    assert exc_info.value.ofs == "secofs_ufs"
    assert exc_info.value.returncode == 7
    assert "stage_model_files" in str(exc_info.value)


def test_forecast_comf_prepare_restart_failure_surfaces(tmp_path, fake_env):
    """``prepare_restart "forecast"`` failure is the most-likely operational
    error (e.g. nowcast didn't archive ``rst.nowcast.nc`` to COMOUT). The
    body must surface the exact rc on the FATAL line and NOT proceed to
    the MPI launch."""
    env = _make_minimal_forecast_env(tmp_path)

    seen: list = []

    def fake_run_shell_function(*, script, function, args, env, cwd):
        seen.append(function)
        if function == "prepare_restart":
            return 11  # arbitrary distinctive rc
        return 0

    with patch.dict(os.environ, env, clear=False):
        with patch.object(
            forecast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)

    # stage_model_files succeeded, prepare_restart failed; execute_model
    # and archive_outputs were skipped (no wasted MPI cycle).
    assert seen == ["stage_model_files", "prepare_restart"]
    assert exc_info.value.returncode == 11
    assert "prepare_restart" in str(exc_info.value)


def test_forecast_comf_propagates_execute_model_rc(tmp_path, fake_env):
    """If the MPI launch (``execute_model``) fails, the body must
    surface the exact rc — operators read this number off the FATAL
    line to figure out whether it was a SCHISM crash, a CDEPS error,
    or an mpiexec rank failure."""
    env = _make_minimal_forecast_env(tmp_path)

    def fake_run_shell_function(*, script, function, args, env, cwd):
        if function == "execute_model":
            return 137  # OOM-killed; classic MPI exit code
        return 0

    with patch.dict(os.environ, env, clear=False):
        with patch.object(
            forecast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)

    assert exc_info.value.returncode == 137
    assert "execute_model" in str(exc_info.value)


def test_forecast_comf_archive_failure_surfaces(tmp_path, fake_env):
    """``archive_outputs`` failures are still fatal: a successful MPI
    run that we couldn't archive is a wasted cycle that the operator
    must see."""
    env = _make_minimal_forecast_env(tmp_path)

    def fake_run_shell_function(*, script, function, args, env, cwd):
        if function == "archive_outputs":
            return 2
        return 0

    with patch.dict(os.environ, env, clear=False):
        with patch.object(
            forecast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)

    assert exc_info.value.returncode == 2
    assert "archive_outputs" in str(exc_info.value)


# ---------------------------------------------------------------------------
# COMF body — fatal env / fs paths
# ---------------------------------------------------------------------------


def test_forecast_comf_missing_ushnos_raises(tmp_path, fake_env):
    """Missing USHnos (or any required env var) must be a structured
    StageFailedError, not a KeyError."""
    env = _make_minimal_forecast_env(tmp_path)
    del env["USHnos"]

    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("USHnos", None)
        with pytest.raises(StageFailedError) as exc_info:
            forecast_stage.run(_secofs_ufs_desc(), fake_env)
    assert "USHnos" in str(exc_info.value)


def test_forecast_comf_missing_data_raises(tmp_path, fake_env):
    """Missing DATA must fail loudly — the 4-step contract uses $DATA
    as the working directory."""
    env = _make_minimal_forecast_env(tmp_path)
    del env["DATA"]

    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("DATA", None)
        with pytest.raises(StageFailedError) as exc_info:
            forecast_stage.run(_secofs_ufs_desc(), fake_env)
    assert "DATA" in str(exc_info.value)


def test_forecast_comf_missing_nos_run_sh_raises(tmp_path, fake_env):
    """If ``${USHnos}/nos_run.sh`` is absent, fail fast with a
    StageFailedError naming the missing path."""
    env = _make_minimal_forecast_env(tmp_path)
    # Yank the stub nos_run.sh.
    nos_run = Path(env["USHnos"]) / "nos_run.sh"
    nos_run.unlink()

    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(StageFailedError) as exc_info:
            forecast_stage.run(_secofs_ufs_desc(), fake_env)
    assert exc_info.value.stage == "forecast"
    assert "nos_run.sh" in str(exc_info.value)


def test_forecast_comf_unexpected_exception_wrapped(tmp_path, fake_env):
    """An unexpected RuntimeError from ``run_shell_function`` is wrapped
    into a StageFailedError so the CLI prints a clean FATAL line."""
    env = _make_minimal_forecast_env(tmp_path)

    def boom(*, script, function, args, env, cwd):
        raise RuntimeError("subprocess.run died unexpectedly")

    with patch.dict(os.environ, env, clear=False):
        with patch.object(
            forecast_stage,
            "run_shell_function",
            side_effect=boom,
        ):
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)

    assert exc_info.value.stage == "forecast"
    assert "unexpected exception" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Pure-function helper
# ---------------------------------------------------------------------------


def test_require_env_returns_value_when_set():
    """Sanity check: the helper returns the value verbatim when set."""
    env = {"OFS": "secofs_ufs", "FOO": "bar"}
    assert forecast_stage._require_env(env, "FOO") == "bar"


def test_require_env_raises_on_empty_string():
    """Empty string is treated the same as unset — both indicate the
    J-job didn't export the value."""
    env = {"OFS": "secofs_ufs", "FOO": ""}
    with pytest.raises(StageFailedError) as exc_info:
        forecast_stage._require_env(env, "FOO")
    assert "FOO" in str(exc_info.value)
