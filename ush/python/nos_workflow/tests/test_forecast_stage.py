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


def _stofs_3d_atl_ufs_desc() -> OFSDescriptor:
    """STOFS-3D-ATL on UFS-Coastal — routes through the same UFS-Coastal
    body as ``comf``; the distinct framework label keeps it free for
    future divergence."""
    return OFSDescriptor(
        name="stofs_3d_atl_ufs",
        framework="stofs_ufs",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={},
        yaml_path=Path("parm/systems/stofs_3d_atl_ufs.yaml"),
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


def test_forecast_stofs_branch_raises_not_implemented(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        forecast_stage.run(_stofs_3d_desc(), fake_env)
    assert "STOFS-3D-ATL" in str(exc_info.value)


def test_forecast_adcirc_branch_raises_not_implemented(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        forecast_stage.run(_adcirc_desc(), fake_env)
    assert "STOFS-2D-GLO" in str(exc_info.value)


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
    """The stage-start log record must fire on every dispatch. Stage + ofs
    live in record.extra under the LoggerAdapter pattern."""
    caplog.set_level("INFO", logger="nos_workflow.stages.forecast")
    with pytest.raises(NotImplementedError):
        forecast_stage.run(_stofs_3d_desc(), fake_env)
    assert any(
        rec.getMessage() == "stage start"
        and getattr(rec, "stage", None) == "forecast"
        and getattr(rec, "ofs", None) == "stofs_3d_atl"
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# COMF body — happy path
#
# The COMF body drives the 4-step contract via direct Python runner calls
# (``runners.schism_ufs.{stage_files,prepare_restart,execute,archive}.run_python``).
# We patch those functions at their source modules so the body can exercise
# its env-validation, step ordering, and error-propagation logic without
# touching the filesystem or building real SchismRunContexts.
# ---------------------------------------------------------------------------


def _make_minimal_forecast_env(tmp_path: Path) -> dict:
    """Build the env vars the COMF forecast body requires, with stubs in
    tmp_path. The 4-step contract is mocked at the Python runner level,
    so we only need USHnos/DATA on disk to satisfy the up-front env
    validation."""
    ushnos = tmp_path / "ush"
    data = tmp_path / "data"
    ushnos.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)

    return {
        "USHnos": str(ushnos),
        "DATA": str(data),
        "OFS": "secofs_ufs",
        "RUN": "nos.secofs_ufs",
        "PDY": "20260507",
        "cyc": "00",
        "cycle": "t00z",
        "PREFIXNOS": "nos.secofs_ufs",
        "COMOUT": str(tmp_path / "com"),
    }


def _patch_all_runner_steps(stage_module, *, returns):
    """Patch all four Python runners + context builders the stage uses.

    ``returns`` is a dict mapping step name -> rc (or callable / exception).
    A missing step defaults to rc=0.

    Returns the dict of MagicMock objects keyed by step name so callers
    can inspect call_args / call_count, plus the list of patch objects.
    """
    from unittest.mock import MagicMock, patch

    mocks = {}
    patches = []

    for step in ("stage_model_files", "prepare_restart", "execute_model", "archive_outputs"):
        spec = returns.get(step, 0)
        if isinstance(spec, BaseException) or (
            isinstance(spec, type) and issubclass(spec, BaseException)
        ):
            m = MagicMock(side_effect=spec)
        elif callable(spec):
            m = MagicMock(side_effect=spec)
        else:
            m = MagicMock(return_value=spec)
        mocks[step] = m

    patches.append(patch(
        "nos_workflow.runners.schism_ufs.stage_files.run_python",
        mocks["stage_model_files"],
    ))
    patches.append(patch(
        "nos_workflow.runners.schism_ufs.prepare_restart.run_python",
        mocks["prepare_restart"],
    ))
    patches.append(patch(
        "nos_workflow.runners.schism_ufs.execute.run_python",
        mocks["execute_model"],
    ))
    patches.append(patch(
        "nos_workflow.runners.schism_ufs.archive.run_python",
        mocks["archive_outputs"],
    ))

    patches.append(patch(
        "nos_workflow.runners.schism_ufs.setup_paths.compute_paths",
        MagicMock(return_value=MagicMock(name="SchismRunContext")),
    ))
    patches.append(patch(
        "nos_workflow.env.NCOEnv.from_env",
        MagicMock(return_value=MagicMock(name="NCOEnv")),
    ))
    patches.append(patch(
        "nos_workflow.runners.schism_ufs.context.SchismRunContext.from_env_and_phase",
        MagicMock(return_value=MagicMock(name="SchismRunContext")),
    ))

    return mocks, patches


def _enter_all(patches):
    """Enter every patch in ``patches`` and return them so the caller can stop()."""
    started = [p.start() for p in patches]
    return started


def _stop_all(patches):
    for p in patches:
        p.stop()


@pytest.mark.parametrize(
    "desc_factory",
    [_secofs_ufs_desc, _stofs_3d_atl_ufs_desc],
    ids=["comf", "stofs_ufs"],
)
def test_forecast_comf_happy_path_invokes_all_four_steps(
    tmp_path, fake_env, desc_factory
):
    """End-to-end UFS-Coastal happy path: every step in the 4-step
    contract is invoked with ``phase='forecast'`` and the stage returns 0.

    Parametrized across both ``framework="comf"`` (SECOFS-UFS) and
    ``framework="stofs_ufs"`` (STOFS-3D-ATL-UFS) since both must route
    through ``_run_comf_forecast`` identically.
    """
    env = _make_minimal_forecast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(forecast_stage, returns={})

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            rc = forecast_stage.run(desc_factory(), fake_env)
        finally:
            _stop_all(patches)

    assert rc == 0
    for step, m in mocks.items():
        assert m.call_count == 1, f"{step} should have been called once, got {m.call_count}"
        call_args = m.call_args
        assert call_args.args[1] == "forecast", f"{step} should receive phase='forecast'"


def test_forecast_comf_stops_on_first_failing_step(tmp_path, fake_env):
    """If ``stage_model_files`` returns non-zero, the body must raise
    ``StageFailedError`` with that rc and NOT call the remaining steps."""
    env = _make_minimal_forecast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(
        forecast_stage,
        returns={"stage_model_files": 7},
    )

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)
        finally:
            _stop_all(patches)

    assert mocks["stage_model_files"].call_count == 1
    assert mocks["prepare_restart"].call_count == 0
    assert mocks["execute_model"].call_count == 0
    assert mocks["archive_outputs"].call_count == 0
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

    mocks, patches = _patch_all_runner_steps(
        forecast_stage,
        returns={"prepare_restart": 11},
    )

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)
        finally:
            _stop_all(patches)

    # stage_model_files succeeded, prepare_restart failed; execute_model
    # and archive_outputs were skipped (no wasted MPI cycle).
    assert mocks["stage_model_files"].call_count == 1
    assert mocks["prepare_restart"].call_count == 1
    assert mocks["execute_model"].call_count == 0
    assert mocks["archive_outputs"].call_count == 0
    assert exc_info.value.returncode == 11
    assert "prepare_restart" in str(exc_info.value)


def test_forecast_comf_propagates_execute_model_rc(tmp_path, fake_env):
    """If the MPI launch (``execute_model``) fails, the body must
    surface the exact rc — operators read this number off the FATAL
    line to figure out whether it was a SCHISM crash, a CDEPS error,
    or an mpiexec rank failure."""
    env = _make_minimal_forecast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(
        forecast_stage,
        returns={"execute_model": 137},  # OOM-killed; classic MPI exit code
    )

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)
        finally:
            _stop_all(patches)

    assert exc_info.value.returncode == 137
    assert "execute_model" in str(exc_info.value)
    assert mocks["archive_outputs"].call_count == 0


def test_forecast_comf_archive_failure_surfaces(tmp_path, fake_env):
    """``archive_outputs`` failures are still fatal: a successful MPI
    run that we couldn't archive is a wasted cycle that the operator
    must see."""
    env = _make_minimal_forecast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(
        forecast_stage,
        returns={"archive_outputs": 2},
    )

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)
        finally:
            _stop_all(patches)

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


def test_forecast_comf_unexpected_exception_wrapped(tmp_path, fake_env):
    """An unexpected RuntimeError from a runner is wrapped into a
    StageFailedError so the CLI prints a clean FATAL line."""
    env = _make_minimal_forecast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(
        forecast_stage,
        returns={"stage_model_files": RuntimeError("runner died unexpectedly")},
    )

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            with pytest.raises(StageFailedError) as exc_info:
                forecast_stage.run(_secofs_ufs_desc(), fake_env)
        finally:
            _stop_all(patches)

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
