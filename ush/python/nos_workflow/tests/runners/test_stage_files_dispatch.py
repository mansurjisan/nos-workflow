"""End-to-end dispatch tests for ``stage_model_files`` -> Python (PR 7c).

These tests verify that the dispatcher in ``stages/nowcast.py`` and
``stages/forecast.py`` routes ``stage_model_files`` to the
:func:`nos_workflow.runners.schism_ufs.stage_files.run_python`
orchestrator when ``NOS_WORKFLOW_PYTHON_STAGE_FILES=1`` (or the global
``NOS_WORKFLOW_PYTHON_RUNNER=1``) is set in the environment.

The integration is mocked at two boundaries:

  - :func:`nos_workflow.env.NCOEnv.from_env` -> returns a fake NCOEnv
    (lets us avoid setting up the full COM tree the real NCOEnv requires).
  - :func:`nos_workflow.runners.schism_ufs.setup_paths.compute_paths`
    and :func:`...stage_files.run_python` -> mocked at the module
    where the dispatcher imports them, so the real fs-touching logic
    never runs.

What we verify:

  1. Flag set -> ``stage_files.run_python`` is called for
     ``stage_model_files`` (and ``run_shell_function`` is NOT called for
     that step).
  2. Flag unset -> dispatcher falls back to ``run_shell_function``
     (shell path), with no call to ``stage_files.run_python``.
  3. The phase string ("nowcast"/"forecast") propagates correctly into
     both ``compute_paths`` and ``run_python``.
  4. If ``stage_files.run_python`` raises, the stage surfaces it as
     :class:`StageFailedError` -- the standard wrap in ``_run_comf_*``.
  5. If ``stage_files.run_python`` returns a non-zero rc, the stage
     surfaces it via the same ``StageFailedError`` path.
  6. The dispatcher uses ``OFS`` from ``shell_env`` (not from a
     hard-coded default) when building the NCOEnv.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nos_workflow.errors import StageFailedError
from nos_workflow.registry import OFSDescriptor
from nos_workflow.stages import forecast as forecast_stage
from nos_workflow.stages import nowcast as nowcast_stage


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _secofs_ufs_desc() -> OFSDescriptor:
    """SECOFS-UFS descriptor (framework=comf)."""
    return OFSDescriptor(
        name="secofs_ufs",
        framework="comf",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={},
        yaml_path=Path("parm/systems/secofs_ufs.yaml"),
        runner_module="nos_workflow.runners.ufs_coastal",
        notes="test fixture",
    )


def _make_minimal_env(tmp_path: Path) -> dict:
    """Build the env vars the COMF body requires, with stubs in tmp_path.

    Mirrors ``_make_minimal_nowcast_env`` in test_nowcast_stage.py so
    the dispatch tests have the same surface area.
    """
    ushnos = tmp_path / "ush"
    data = tmp_path / "data"
    ushnos.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    nos_run = ushnos / "nos_run.sh"
    nos_run.write_text("#!/bin/bash\n# stub\n")
    return {
        "USHnos": str(ushnos),
        "DATA": str(data),
        "OFS": "secofs_ufs",
        "RUN": "nos.secofs_ufs",
        "PDY": "20260510",
        "cyc": "00",
        "cycle": "t00z",
        "PREFIXNOS": "nos.secofs_ufs",
    }


@pytest.fixture
def fake_env_object() -> object:
    """The stage's ``env`` parameter is unused once we're in the COMF
    body -- shell_env is read from ``os.environ`` instead. Keep this
    as a trivial sentinel to match the dispatcher signature."""
    return object()


# ---------------------------------------------------------------------------
# Happy path: flag set -> Python dispatched
# ---------------------------------------------------------------------------


def test_nowcast_stage_files_dispatch_calls_python_when_flag_set(
    tmp_path, fake_env_object
):
    """When ``NOS_WORKFLOW_PYTHON_STAGE_FILES=1``, the nowcast dispatcher
    routes ``stage_model_files`` to ``stage_files.run_python`` instead
    of ``run_shell_function``."""
    env = _make_minimal_env(tmp_path)
    env["NOS_WORKFLOW_PYTHON_STAGE_FILES"] = "1"

    fake_ctx = MagicMock(name="SchismRunContext")
    fake_run_python = MagicMock(return_value=0, name="stage_files.run_python")
    fake_compute_paths = MagicMock(return_value=fake_ctx, name="compute_paths")
    fake_nco_env = MagicMock(name="NCOEnv")
    fake_from_env = MagicMock(return_value=fake_nco_env, name="NCOEnv.from_env")

    seen_shell_calls: list = []

    def fake_run_shell_function(*, script, function, args, env, cwd):
        # All other steps (prepare_restart, execute_model,
        # archive_outputs) still fall through to shell -- record them
        # so we can verify stage_model_files in particular did NOT.
        seen_shell_calls.append(function)
        return 0

    with patch.dict(os.environ, env, clear=False):
        with patch(
            "nos_workflow.runners.schism_ufs.stage_files.run_python",
            fake_run_python,
        ), patch(
            "nos_workflow.runners.schism_ufs.setup_paths.compute_paths",
            fake_compute_paths,
        ), patch(
            "nos_workflow.env.NCOEnv.from_env",
            fake_from_env,
        ), patch.object(
            nowcast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            rc = nowcast_stage.run(_secofs_ufs_desc(), fake_env_object)

    assert rc == 0
    # Python path was taken for stage_model_files.
    assert fake_run_python.called
    fake_run_python.assert_called_once_with(fake_ctx, "nowcast")
    # NCOEnv built from os.environ with OFS=secofs_ufs (matches shell_env).
    fake_from_env.assert_called_once_with(ofs="secofs_ufs")
    # compute_paths called with phase=nowcast, runtype=nowcast.
    fake_compute_paths.assert_called_once_with(
        fake_nco_env, phase="nowcast", runtype="nowcast"
    )
    # Other 3 steps still go through shell.
    assert seen_shell_calls == [
        "prepare_restart",
        "execute_model",
        "archive_outputs",
    ]


def test_forecast_stage_files_dispatch_calls_python_when_flag_set(
    tmp_path, fake_env_object
):
    """Same as the nowcast test but for the forecast stage -- phase +
    runtype must propagate as ``"forecast"`` everywhere."""
    env = _make_minimal_env(tmp_path)
    env["NOS_WORKFLOW_PYTHON_STAGE_FILES"] = "1"

    fake_ctx = MagicMock(name="SchismRunContext")
    fake_run_python = MagicMock(return_value=0)
    fake_compute_paths = MagicMock(return_value=fake_ctx)
    fake_nco_env = MagicMock(name="NCOEnv")
    fake_from_env = MagicMock(return_value=fake_nco_env)

    def fake_run_shell_function(*, script, function, args, env, cwd):
        return 0

    with patch.dict(os.environ, env, clear=False):
        with patch(
            "nos_workflow.runners.schism_ufs.stage_files.run_python",
            fake_run_python,
        ), patch(
            "nos_workflow.runners.schism_ufs.setup_paths.compute_paths",
            fake_compute_paths,
        ), patch(
            "nos_workflow.env.NCOEnv.from_env",
            fake_from_env,
        ), patch.object(
            forecast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            rc = forecast_stage.run(_secofs_ufs_desc(), fake_env_object)

    assert rc == 0
    fake_run_python.assert_called_once_with(fake_ctx, "forecast")
    fake_compute_paths.assert_called_once_with(
        fake_nco_env, phase="forecast", runtype="forecast"
    )


# ---------------------------------------------------------------------------
# Global flag also flips stage_model_files
# ---------------------------------------------------------------------------


def test_global_runner_flag_also_dispatches_stage_files_to_python(
    tmp_path, fake_env_object
):
    """``NOS_WORKFLOW_PYTHON_RUNNER=1`` flips every step at once,
    including stage_model_files. The dispatcher's ``if step ==
    "stage_model_files"`` branch must therefore fire when the global
    flag is set even if the per-step ``STAGE_FILES`` var is absent."""
    env = _make_minimal_env(tmp_path)
    env["NOS_WORKFLOW_PYTHON_RUNNER"] = "1"
    # The global flag also turns on archive + prepare_restart, which
    # build a SchismRunContext via from_env_and_phase -- that requires
    # COMOUT in the env even though the actual archive helper is
    # mocked below.  Add a COMOUT stub so context construction works.
    env["COMOUT"] = str(tmp_path / "comout")
    (tmp_path / "comout").mkdir(parents=True, exist_ok=True)

    fake_run_python = MagicMock(return_value=0)
    fake_compute_paths = MagicMock(return_value=MagicMock())
    fake_from_env = MagicMock(return_value=MagicMock())

    # When the global flag is on, ALL four steps route to Python.
    # archive_outputs and prepare_restart have their own Python paths
    # (PR 2/3), so we mock those too to keep this test focused on
    # stage_model_files dispatch.
    fake_archive_python = MagicMock(return_value=0)
    fake_prepare_python = MagicMock(return_value=0)

    def fake_run_shell_function(*, script, function, args, env, cwd):
        # execute_model still falls through (PR 8 territory). With the
        # global flag on, the WARNING fallback path is taken.
        return 0

    with patch.dict(os.environ, env, clear=False):
        with patch(
            "nos_workflow.runners.schism_ufs.stage_files.run_python",
            fake_run_python,
        ), patch(
            "nos_workflow.runners.schism_ufs.setup_paths.compute_paths",
            fake_compute_paths,
        ), patch(
            "nos_workflow.env.NCOEnv.from_env",
            fake_from_env,
        ), patch(
            "nos_workflow.runners.schism_ufs.archive.run_python",
            fake_archive_python,
        ), patch(
            "nos_workflow.runners.schism_ufs.prepare_restart.run_python",
            fake_prepare_python,
        ), patch.object(
            nowcast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            rc = nowcast_stage.run(_secofs_ufs_desc(), fake_env_object)

    assert rc == 0
    assert fake_run_python.called
    fake_run_python.assert_called_once_with(fake_compute_paths.return_value, "nowcast")


# ---------------------------------------------------------------------------
# Flag unset: shell fallback
# ---------------------------------------------------------------------------


def test_stage_files_dispatch_falls_back_to_shell_when_flag_unset(
    tmp_path, fake_env_object
):
    """When ``NOS_WORKFLOW_PYTHON_STAGE_FILES`` is unset, the dispatcher
    must NOT call ``stage_files.run_python`` and must call
    ``run_shell_function(function="stage_model_files", ...)`` instead.

    This is the default operator state -- the WARNING-fallback path
    from PR 1 is replaced with real shell dispatch via PR 7c, BUT only
    when the flag is on. Without it, shell stays the default."""
    env = _make_minimal_env(tmp_path)
    # Explicitly unset to be sure no inherited value affects us.
    env.pop("NOS_WORKFLOW_PYTHON_STAGE_FILES", None)
    env.pop("NOS_WORKFLOW_PYTHON_RUNNER", None)

    fake_run_python = MagicMock(return_value=0)

    seen_functions: list = []

    def fake_run_shell_function(*, script, function, args, env, cwd):
        seen_functions.append(function)
        return 0

    with patch.dict(os.environ, env, clear=True):
        # Re-export essentials after clear=True.
        for k, v in env.items():
            os.environ[k] = v
        os.environ.pop("NOS_WORKFLOW_PYTHON_STAGE_FILES", None)
        os.environ.pop("NOS_WORKFLOW_PYTHON_RUNNER", None)

        with patch(
            "nos_workflow.runners.schism_ufs.stage_files.run_python",
            fake_run_python,
        ), patch.object(
            nowcast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            rc = nowcast_stage.run(_secofs_ufs_desc(), fake_env_object)

    assert rc == 0
    # Python orchestrator was NOT called.
    assert not fake_run_python.called
    # All 4 steps went through shell.
    assert seen_functions == [
        "stage_model_files",
        "prepare_restart",
        "execute_model",
        "archive_outputs",
    ]


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


def test_stage_files_python_raises_surfaces_as_stage_failed(
    tmp_path, fake_env_object
):
    """If ``stage_files.run_python`` raises (e.g.,
    :class:`FileNotFoundError` from a missing hotstart source), the
    nowcast body's outer ``try/except`` wraps it as
    :class:`StageFailedError` so the CLI gets a clean FATAL line."""
    env = _make_minimal_env(tmp_path)
    env["NOS_WORKFLOW_PYTHON_STAGE_FILES"] = "1"

    fake_run_python = MagicMock(
        side_effect=FileNotFoundError("hotstart.nc missing"),
    )
    fake_compute_paths = MagicMock(return_value=MagicMock())
    fake_from_env = MagicMock(return_value=MagicMock())

    with patch.dict(os.environ, env, clear=False):
        with patch(
            "nos_workflow.runners.schism_ufs.stage_files.run_python",
            fake_run_python,
        ), patch(
            "nos_workflow.runners.schism_ufs.setup_paths.compute_paths",
            fake_compute_paths,
        ), patch(
            "nos_workflow.env.NCOEnv.from_env",
            fake_from_env,
        ):
            with pytest.raises(StageFailedError) as exc_info:
                nowcast_stage.run(_secofs_ufs_desc(), fake_env_object)

    # Wrapped -- not the raw FileNotFoundError.
    assert exc_info.value.stage == "nowcast"
    assert exc_info.value.ofs == "secofs_ufs"
    # The original exception is chained via __cause__ for debugging.
    assert isinstance(exc_info.value.__cause__, FileNotFoundError)


def test_stage_files_python_nonzero_rc_surfaces_as_stage_failed(
    tmp_path, fake_env_object
):
    """If ``stage_files.run_python`` returns non-zero, the dispatcher
    must treat it the same as a shell-side non-zero rc -- raise
    :class:`StageFailedError` with that rc and skip the remaining
    steps in the 4-step contract."""
    env = _make_minimal_env(tmp_path)
    env["NOS_WORKFLOW_PYTHON_STAGE_FILES"] = "1"

    fake_run_python = MagicMock(return_value=11)
    fake_compute_paths = MagicMock(return_value=MagicMock())
    fake_from_env = MagicMock(return_value=MagicMock())

    seen_shell_calls: list = []

    def fake_run_shell_function(*, script, function, args, env, cwd):
        seen_shell_calls.append(function)
        return 0

    with patch.dict(os.environ, env, clear=False):
        with patch(
            "nos_workflow.runners.schism_ufs.stage_files.run_python",
            fake_run_python,
        ), patch(
            "nos_workflow.runners.schism_ufs.setup_paths.compute_paths",
            fake_compute_paths,
        ), patch(
            "nos_workflow.env.NCOEnv.from_env",
            fake_from_env,
        ), patch.object(
            nowcast_stage,
            "run_shell_function",
            side_effect=fake_run_shell_function,
        ):
            with pytest.raises(StageFailedError) as exc_info:
                nowcast_stage.run(_secofs_ufs_desc(), fake_env_object)

    assert exc_info.value.stage == "nowcast"
    assert exc_info.value.returncode == 11
    assert "stage_model_files" in str(exc_info.value)
    # No subsequent steps ran.
    assert seen_shell_calls == []


# ---------------------------------------------------------------------------
# OFS pass-through
# ---------------------------------------------------------------------------


def test_stage_files_dispatch_passes_ofs_from_shell_env_to_nco_env(
    tmp_path, fake_env_object
):
    """The dispatcher must read ``$OFS`` from ``shell_env`` and pass it
    to ``NCOEnv.from_env(ofs=...)``. This matters because the OFS
    value drives directory resolution in NCOEnv.from_env."""
    env = _make_minimal_env(tmp_path)
    env["NOS_WORKFLOW_PYTHON_STAGE_FILES"] = "1"
    env["OFS"] = "stofs_3d_atl_ufs"  # override the default

    fake_run_python = MagicMock(return_value=0)
    fake_compute_paths = MagicMock(return_value=MagicMock())
    fake_from_env = MagicMock(return_value=MagicMock())

    with patch.dict(os.environ, env, clear=False):
        with patch(
            "nos_workflow.runners.schism_ufs.stage_files.run_python",
            fake_run_python,
        ), patch(
            "nos_workflow.runners.schism_ufs.setup_paths.compute_paths",
            fake_compute_paths,
        ), patch(
            "nos_workflow.env.NCOEnv.from_env",
            fake_from_env,
        ), patch.object(
            nowcast_stage,
            "run_shell_function",
            return_value=0,
        ):
            nowcast_stage.run(_secofs_ufs_desc(), fake_env_object)

    fake_from_env.assert_called_once_with(ofs="stofs_3d_atl_ufs")
