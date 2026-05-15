"""Nowcast stage tests for nos_workflow.stages.nowcast.

Mirrors the contract laid out by ``test_post_stage.py`` but with the
4-step ``nos_run.sh`` invocation isolated here so the dispatch suite
stays lightweight.

The COMF body shells out to ``ush/nos_run.sh`` via
``bash_compat.run_shell_function``. We mock that callable so the body
can exercise its env-validation, step ordering, and error-propagation
logic without actually sourcing the shell library.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from nos_workflow.errors import StageFailedError
from nos_workflow.registry import OFSDescriptor
from nos_workflow.stages import nowcast as nowcast_stage


# ---------------------------------------------------------------------------
# Descriptor fixtures (kept shape-identical to test_post_stage.py so they
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
    """Trivial stand-in for ``NCOEnv`` — the nowcast stage reads
    ``os.environ`` directly, so this is unused but matches the
    dispatch-test signature."""
    return object()


# ---------------------------------------------------------------------------
# Framework-branch tests (mirror post_stage tests).
# ---------------------------------------------------------------------------


def test_nowcast_stofs_branch_raises_not_implemented(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        nowcast_stage.run(_stofs_3d_desc(), fake_env)
    assert "STOFS-3D-ATL" in str(exc_info.value)


def test_nowcast_adcirc_branch_raises_not_implemented(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        nowcast_stage.run(_adcirc_desc(), fake_env)
    assert "STOFS-2D-GLO" in str(exc_info.value)


def test_nowcast_unknown_framework_raises_stage_failed(fake_env):
    desc = OFSDescriptor(
        name="weird",
        framework="not-a-framework",
        canonical_stages=("nowcast",),
    )
    with pytest.raises(StageFailedError) as exc_info:
        nowcast_stage.run(desc, fake_env)
    assert exc_info.value.stage == "nowcast"


def test_nowcast_phase_header_logged(fake_env, caplog):
    """The stage-start log record must fire on every dispatch — even when
    the body later raises. Stage + ofs live in record.extra (not in the
    message text) under the LoggerAdapter pattern; the CLI's UTC formatter
    renders them as ``[ts] [nowcast] [stofs_3d_atl] stage start`` at
    output time."""
    caplog.set_level("INFO", logger="nos_workflow.stages.nowcast")
    with pytest.raises(NotImplementedError):
        nowcast_stage.run(_stofs_3d_desc(), fake_env)
    assert any(
        rec.getMessage() == "stage start"
        and getattr(rec, "stage", None) == "nowcast"
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


def _make_minimal_nowcast_env(tmp_path: Path) -> dict:
    """Build the env vars the COMF nowcast body requires, with stubs in
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
    can inspect call_args / call_count.
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

    # Patch the runners' run_python at their source modules.
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

    # Patch the supporting builders so ``_run_step`` can build a fake
    # context cheaply without needing a real COM tree.
    patches.append(patch(
        "nos_workflow.runners.schism_ufs.setup_paths.compute_paths",
        MagicMock(return_value=MagicMock(name="SchismRunContext")),
    ))
    patches.append(patch(
        "nos_workflow.env.NCOEnv.from_env",
        MagicMock(return_value=MagicMock(name="NCOEnv")),
    ))
    # prepare_restart / archive_outputs build context via
    # SchismRunContext.from_env_and_phase, so patch that too.
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
def test_nowcast_comf_happy_path_invokes_all_four_steps(
    tmp_path, fake_env, desc_factory
):
    """End-to-end UFS-Coastal happy path: every step in the 4-step
    contract is invoked with ``phase='nowcast'`` and the stage returns 0.

    Parametrized across both ``framework="comf"`` (SECOFS-UFS) and
    ``framework="stofs_ufs"`` (STOFS-3D-ATL-UFS) since both must route
    through ``_run_comf_nowcast`` identically.
    """
    env = _make_minimal_nowcast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(nowcast_stage, returns={})

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            rc = nowcast_stage.run(desc_factory(), fake_env)
        finally:
            _stop_all(patches)

    assert rc == 0
    # All 4 runners were called exactly once.
    for step, m in mocks.items():
        assert m.call_count == 1, f"{step} should have been called once, got {m.call_count}"
        # phase argument is always "nowcast"
        call_args = m.call_args
        # call_args.args is (ctx, phase)
        assert call_args.args[1] == "nowcast", f"{step} should receive phase='nowcast'"


def test_nowcast_comf_stops_on_first_failing_step(tmp_path, fake_env):
    """If ``stage_model_files`` returns non-zero, the body must raise
    ``StageFailedError`` with that rc and NOT call the remaining steps."""
    env = _make_minimal_nowcast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(
        nowcast_stage,
        returns={"stage_model_files": 7},
    )

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            with pytest.raises(StageFailedError) as exc_info:
                nowcast_stage.run(_secofs_ufs_desc(), fake_env)
        finally:
            _stop_all(patches)

    # Only stage_model_files was called; the other 3 were skipped.
    assert mocks["stage_model_files"].call_count == 1
    assert mocks["prepare_restart"].call_count == 0
    assert mocks["execute_model"].call_count == 0
    assert mocks["archive_outputs"].call_count == 0
    assert exc_info.value.stage == "nowcast"
    assert exc_info.value.ofs == "secofs_ufs"
    assert exc_info.value.returncode == 7
    assert "stage_model_files" in str(exc_info.value)


def test_nowcast_comf_propagates_execute_model_rc(tmp_path, fake_env):
    """If the MPI launch (``execute_model``) fails, the body must
    surface the exact rc — operators read this number off the FATAL
    line to figure out whether it was a SCHISM crash, a CDEPS error,
    or an mpiexec rank failure."""
    env = _make_minimal_nowcast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(
        nowcast_stage,
        returns={"execute_model": 137},  # OOM-killed; classic MPI exit code
    )

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            with pytest.raises(StageFailedError) as exc_info:
                nowcast_stage.run(_secofs_ufs_desc(), fake_env)
        finally:
            _stop_all(patches)

    assert exc_info.value.returncode == 137
    assert "execute_model" in str(exc_info.value)
    # archive_outputs not reached after execute_model failure.
    assert mocks["archive_outputs"].call_count == 0


def test_nowcast_comf_archive_failure_surfaces(tmp_path, fake_env):
    """``archive_outputs`` failures are still fatal: a successful MPI
    run that we couldn't archive is a wasted cycle that the operator
    must see."""
    env = _make_minimal_nowcast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(
        nowcast_stage,
        returns={"archive_outputs": 2},
    )

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            with pytest.raises(StageFailedError) as exc_info:
                nowcast_stage.run(_secofs_ufs_desc(), fake_env)
        finally:
            _stop_all(patches)

    assert exc_info.value.returncode == 2
    assert "archive_outputs" in str(exc_info.value)


# ---------------------------------------------------------------------------
# COMF body — fatal env / fs paths
# ---------------------------------------------------------------------------


def test_nowcast_comf_missing_ushnos_raises(tmp_path, fake_env):
    """Missing USHnos (or any required env var) must be a structured
    StageFailedError, not a KeyError."""
    env = _make_minimal_nowcast_env(tmp_path)
    del env["USHnos"]

    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("USHnos", None)
        with pytest.raises(StageFailedError) as exc_info:
            nowcast_stage.run(_secofs_ufs_desc(), fake_env)
    assert "USHnos" in str(exc_info.value)


def test_nowcast_comf_missing_data_raises(tmp_path, fake_env):
    """Missing DATA must fail loudly — the 4-step contract uses $DATA
    as the working directory."""
    env = _make_minimal_nowcast_env(tmp_path)
    del env["DATA"]

    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("DATA", None)
        with pytest.raises(StageFailedError) as exc_info:
            nowcast_stage.run(_secofs_ufs_desc(), fake_env)
    assert "DATA" in str(exc_info.value)


def test_nowcast_comf_unexpected_exception_wrapped(tmp_path, fake_env):
    """An unexpected RuntimeError from a runner is wrapped into a
    StageFailedError so the CLI prints a clean FATAL line."""
    env = _make_minimal_nowcast_env(tmp_path)

    mocks, patches = _patch_all_runner_steps(
        nowcast_stage,
        returns={"stage_model_files": RuntimeError("runner died unexpectedly")},
    )

    with patch.dict(os.environ, env, clear=False):
        _enter_all(patches)
        try:
            with pytest.raises(StageFailedError) as exc_info:
                nowcast_stage.run(_secofs_ufs_desc(), fake_env)
        finally:
            _stop_all(patches)

    assert exc_info.value.stage == "nowcast"
    assert "unexpected exception" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Pure-function helper
# ---------------------------------------------------------------------------


def test_require_env_returns_value_when_set():
    """Sanity check: the helper returns the value verbatim when set."""
    env = {"OFS": "secofs_ufs", "FOO": "bar"}
    assert nowcast_stage._require_env(env, "FOO") == "bar"


def test_require_env_raises_on_empty_string():
    """Empty string is treated the same as unset — both indicate the
    J-job didn't export the value."""
    env = {"OFS": "secofs_ufs", "FOO": ""}
    with pytest.raises(StageFailedError) as exc_info:
        nowcast_stage._require_env(env, "FOO")
    assert "FOO" in str(exc_info.value)
