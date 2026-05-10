"""Stage entry-point dispatch tests.

These tests intentionally avoid importing ``nos_utils`` at collection
time — the COMF prep test patches ``nos_utils.nco_bridge.run_prep`` via
``unittest.mock``.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from nos_workflow.errors import StageFailedError
from nos_workflow.registry import OFSDescriptor
from nos_workflow.stages import forecast as forecast_stage
from nos_workflow.stages import nowcast as nowcast_stage
from nos_workflow.stages import post as post_stage
from nos_workflow.stages import prep as prep_stage


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
    """A trivial stand-in for Agent A's ``NCOEnv`` — stages don't read it yet."""
    return object()


def test_nowcast_stub_raises_not_implemented(fake_env):
    with pytest.raises(NotImplementedError):
        nowcast_stage.run(_secofs_ufs_desc(), fake_env)


def test_forecast_stub_raises_not_implemented(fake_env):
    with pytest.raises(NotImplementedError):
        forecast_stage.run(_secofs_ufs_desc(), fake_env)


def test_post_stub_raises_not_implemented(fake_env):
    with pytest.raises(NotImplementedError):
        post_stage.run(_secofs_ufs_desc(), fake_env)


def test_prep_stofs_branch_mentions_task_33(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        prep_stage.run(_stofs_3d_desc(), fake_env)
    assert "#33" in str(exc_info.value)


def test_prep_adcirc_branch_mentions_task_34(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        prep_stage.run(_adcirc_desc(), fake_env)
    assert "#34" in str(exc_info.value)


def test_prep_unknown_framework_raises_stage_failed(fake_env):
    desc = OFSDescriptor(
        name="weird",
        framework="not-a-framework",
        canonical_stages=("prep",),
    )
    with pytest.raises(StageFailedError):
        prep_stage.run(desc, fake_env)


def _install_stub_nco_bridge(run_prep_callable):
    """Insert a stub ``nos_utils.nco_bridge`` into sys.modules.

    The stage module does ``from nos_utils.nco_bridge import run_prep``
    inside ``run()``. We need both a ``nos_utils`` package and a
    ``nos_utils.nco_bridge`` submodule for that to resolve without the
    real package on the import path.
    """
    pkg = types.ModuleType("nos_utils")
    pkg.__path__ = []  # mark as package
    sub = types.ModuleType("nos_utils.nco_bridge")
    sub.run_prep = run_prep_callable
    return {"nos_utils": pkg, "nos_utils.nco_bridge": sub}


def test_prep_comf_calls_run_prep_for_both_phases(fake_env):
    calls: list = []

    def fake_run_prep(phase: str = "nowcast"):
        calls.append(phase)
        return True  # nco_bridge.run_prep returns bool

    stubs = _install_stub_nco_bridge(fake_run_prep)
    with patch.dict(sys.modules, stubs):
        # Re-patch run_prep with a mock so we can inspect call_args too.
        with patch.object(stubs["nos_utils.nco_bridge"], "run_prep",
                          side_effect=fake_run_prep) as mock_rp:
            rc = prep_stage.run(_secofs_ufs_desc(), fake_env)

    assert rc == 0
    assert calls == ["nowcast", "forecast"]
    assert mock_rp.call_count == 2


def test_prep_comf_returns_nonzero_when_run_prep_fails(fake_env):
    def fake_run_prep(phase: str = "nowcast"):
        return False  # nowcast fails

    stubs = _install_stub_nco_bridge(fake_run_prep)
    with patch.dict(sys.modules, stubs):
        rc = prep_stage.run(_secofs_ufs_desc(), fake_env)

    assert rc != 0


def test_prep_comf_passes_through_int_rc(fake_env):
    """If a future ``run_prep`` returns an int, propagate it unchanged."""
    def fake_run_prep(phase: str = "nowcast"):
        return 0 if phase == "nowcast" else 7

    stubs = _install_stub_nco_bridge(fake_run_prep)
    with patch.dict(sys.modules, stubs):
        rc = prep_stage.run(_secofs_ufs_desc(), fake_env)

    assert rc == 7


def test_prep_comf_wraps_run_prep_exception_as_stage_failed(fake_env):
    def fake_run_prep(phase: str = "nowcast"):
        raise RuntimeError("boom")

    stubs = _install_stub_nco_bridge(fake_run_prep)
    with patch.dict(sys.modules, stubs):
        with pytest.raises(StageFailedError) as exc_info:
            prep_stage.run(_secofs_ufs_desc(), fake_env)

    assert exc_info.value.stage == "prep"
    assert exc_info.value.ofs == "secofs_ufs"
