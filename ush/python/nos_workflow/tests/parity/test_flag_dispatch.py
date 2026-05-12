"""Verify the per-step + global feature flag dispatch in nos_workflow.

Default state (no env vars) must keep every step on the shell path; each
per-step var flips that step to Python while leaving the others alone;
the global var flips everything. Unknown step names raise ValueError
(typo guard for the dispatcher in stages/nowcast.py and forecast.py).

These tests do NOT exercise the actual shell-vs-Python wiring in the
stages — that's covered in test_nowcast_stage.py / test_forecast_stage.py.
They isolate the flag logic so it can be reasoned about independently.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from nos_workflow.runners.schism_ufs import _flags


@pytest.mark.parametrize("step", sorted(_flags.STEPS))
def test_default_is_shell_for_every_step(step):
    """No env vars set → every step routes to shell."""
    with patch.dict(os.environ, {}, clear=True):
        assert _flags.is_python_enabled(step) is False


@pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", "on", "Yes"])
@pytest.mark.parametrize("step,var", sorted(_flags._PER_STEP_VARS.items()))
def test_per_step_var_flips_only_that_step(step, var, truthy):
    """Each per-step var flips its own step but leaves the others alone."""
    with patch.dict(os.environ, {var: truthy}, clear=True):
        assert _flags.is_python_enabled(step) is True
        for other in _flags.STEPS - {step}:
            assert _flags.is_python_enabled(other) is False


@pytest.mark.parametrize("falsy", ["", "0", "false", "no", "off", "FALSE"])
@pytest.mark.parametrize("step,var", sorted(_flags._PER_STEP_VARS.items()))
def test_per_step_var_falsy_stays_shell(step, var, falsy):
    """Empty / 0 / false / no / off — all keep shell."""
    with patch.dict(os.environ, {var: falsy}, clear=True):
        assert _flags.is_python_enabled(step) is False


@pytest.mark.parametrize("truthy", ["1", "true", "yes", "on"])
def test_global_var_flips_every_step(truthy):
    """Global var → every step on Python."""
    with patch.dict(os.environ, {"NOS_WORKFLOW_PYTHON_RUNNER": truthy}, clear=True):
        for step in _flags.STEPS:
            assert _flags.is_python_enabled(step) is True


def test_global_var_takes_precedence_over_per_step_falsy():
    """Global on + per-step explicitly off → per-step still Python (global wins).

    Documented behavior: to revert one step to shell while keeping
    everything else on Python, operators unset the global, not toggle
    one per-step var. This avoids the surprise of a per-step "off"
    silently overriding a global "on"."""
    env = {
        "NOS_WORKFLOW_PYTHON_RUNNER": "1",
        "NOS_WORKFLOW_PYTHON_STAGE_FILES": "0",
    }
    with patch.dict(os.environ, env, clear=True):
        assert _flags.is_python_enabled("stage_model_files") is True


def test_unknown_step_raises_value_error_listing_valid_names():
    """Typos in dispatcher caller surface as ValueError with the valid
    step names in the message — saves operators from grep at 3 AM."""
    with pytest.raises(ValueError) as exc_info:
        _flags.is_python_enabled("not_a_real_step")
    msg = str(exc_info.value)
    assert "not_a_real_step" in msg
    for valid in _flags.STEPS:
        assert valid in msg
