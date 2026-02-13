"""
Unit tests for Model Run Orchestrator.

Tests ModelRunOrchestrator: 4-step workflow, nowcast/forecast phase
validation, ModelRunResult dataclass.
"""

import sys
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.orchestration.model_run import ModelRunOrchestrator, ModelRunResult
from nos_ofs.orchestration.handlers.base import StepResult


class TestModelRunResult:
    """Tests for ModelRunResult dataclass."""

    def test_success_result(self):
        """Test creating a successful ModelRunResult."""
        result = ModelRunResult(
            success=True,
            phase="nowcast",
            total_duration_seconds=120.0,
        )

        assert result.success
        assert result.phase == "nowcast"
        assert result.total_duration_seconds == 120.0
        assert result.step_results == {}
        assert result.errors == []
        assert result.warnings == []

    def test_failure_result(self):
        """Test creating a failed ModelRunResult."""
        result = ModelRunResult(
            success=False,
            phase="forecast",
            total_duration_seconds=60.0,
            errors=["Model crashed"],
        )

        assert not result.success
        assert result.phase == "forecast"
        assert len(result.errors) == 1

    def test_bool_context_success(self):
        """Test ModelRunResult evaluates to True when successful."""
        result = ModelRunResult(success=True, phase="nowcast", total_duration_seconds=1.0)
        assert bool(result) is True

    def test_bool_context_failure(self):
        """Test ModelRunResult evaluates to False when failed."""
        result = ModelRunResult(success=False, phase="nowcast", total_duration_seconds=1.0)
        assert bool(result) is False

    def test_summary_success_nowcast(self):
        """Test summary string for successful nowcast result."""
        step = StepResult(
            success=True,
            step_name="execute_model",
            duration_seconds=100.0,
        )
        result = ModelRunResult(
            success=True,
            phase="nowcast",
            total_duration_seconds=120.0,
            step_results={"execute_model": step},
        )

        summary = result.summary()

        assert "nowcast" in summary
        assert "SUCCESS" in summary
        assert "120.0s" in summary
        assert "execute_model" in summary
        assert "OK" in summary

    def test_summary_failure_forecast(self):
        """Test summary string for failed forecast result."""
        step = StepResult(
            success=False,
            step_name="execute_model",
            message="Segfault",
            duration_seconds=30.0,
        )
        result = ModelRunResult(
            success=False,
            phase="forecast",
            total_duration_seconds=35.0,
            step_results={"execute_model": step},
            errors=["execute_model: Segfault"],
        )

        summary = result.summary()

        assert "forecast" in summary
        assert "FAILED" in summary
        assert "FAIL" in summary
        assert "Errors: 1" in summary

    def test_summary_with_warnings(self):
        """Test summary includes warning count."""
        result = ModelRunResult(
            success=True,
            phase="nowcast",
            total_duration_seconds=100.0,
            warnings=["Low disk space"],
        )

        summary = result.summary()

        assert "Warnings: 1" in summary

    def test_summary_truncates_errors(self):
        """Test summary truncates to first 3 errors."""
        result = ModelRunResult(
            success=False,
            phase="forecast",
            total_duration_seconds=10.0,
            errors=[f"Error {i}" for i in range(5)],
        )

        summary = result.summary()

        assert "Error 0" in summary
        assert "Error 1" in summary
        assert "Error 2" in summary
        assert "Error 3" not in summary

    def test_summary_shows_step_count(self):
        """Test summary shows step count."""
        result = ModelRunResult(
            success=True,
            phase="nowcast",
            total_duration_seconds=100.0,
            step_results={
                "stage": StepResult(success=True, step_name="stage", duration_seconds=1.0),
                "run": StepResult(success=True, step_name="run", duration_seconds=2.0),
            },
        )

        summary = result.summary()

        assert "Steps: 2" in summary


class TestModelRunOrchestratorInit:
    """Tests for ModelRunOrchestrator initialization."""

    def test_init_stofs_framework(self, sample_stofs_config):
        """Test ModelRunOrchestrator detects STOFS framework."""
        orch = ModelRunOrchestrator(sample_stofs_config)

        assert orch.framework == "stofs"
        assert orch.config is sample_stofs_config

    def test_init_comf_framework(self, sample_comf_config):
        """Test ModelRunOrchestrator detects COMF framework."""
        orch = ModelRunOrchestrator(sample_comf_config)

        assert orch.framework == "comf"

    def test_init_framework_override(self, sample_stofs_config):
        """Test explicit framework parameter overrides config."""
        orch = ModelRunOrchestrator(sample_stofs_config, framework="comf")

        assert orch.framework == "comf"

    def test_init_framework_case_insensitive(self, sample_stofs_config):
        """Test framework name is case insensitive."""
        orch = ModelRunOrchestrator(sample_stofs_config, framework="STOFS")

        assert orch.framework == "stofs"

    def test_init_invalid_framework_raises(self, sample_stofs_config):
        """Test unknown framework raises ValueError."""
        with pytest.raises(ValueError, match="Unknown framework"):
            ModelRunOrchestrator(sample_stofs_config, framework="invalid")

    def test_repr(self, sample_stofs_config):
        """Test ModelRunOrchestrator string representation."""
        orch = ModelRunOrchestrator(sample_stofs_config)

        repr_str = repr(orch)
        assert "ModelRunOrchestrator" in repr_str
        assert "stofs" in repr_str


class TestModelRunOrchestratorHandlerCreation:
    """Tests for handler creation."""

    def test_creates_stofs_handler(self, sample_stofs_config):
        """Test STOFS framework creates STOFSModelRunHandler."""
        from nos_ofs.orchestration.handlers.stofs import STOFSModelRunHandler

        orch = ModelRunOrchestrator(sample_stofs_config)

        assert isinstance(orch.handler, STOFSModelRunHandler)

    def test_creates_comf_handler(self, sample_comf_config):
        """Test COMF framework creates COMFModelRunHandler."""
        from nos_ofs.orchestration.handlers.comf import COMFModelRunHandler

        orch = ModelRunOrchestrator(sample_comf_config)

        assert isinstance(orch.handler, COMFModelRunHandler)


class TestModelRunOrchestratorSteps:
    """Tests for individual model run steps."""

    def _make_orch(self, config):
        """Create orchestrator with mocked handler."""
        orch = ModelRunOrchestrator(config)
        orch.handler = Mock()
        return orch

    def test_stage_model_files_delegates(self, sample_stofs_config):
        """Test stage_model_files delegates to handler."""
        orch = self._make_orch(sample_stofs_config)
        expected = StepResult(success=True, step_name="stage_model_files")
        orch.handler.stage_model_files.return_value = expected

        result = orch.stage_model_files("nowcast")

        orch.handler.stage_model_files.assert_called_once_with("nowcast")
        assert result is expected

    def test_prepare_restart_delegates(self, sample_stofs_config):
        """Test prepare_restart delegates to handler."""
        orch = self._make_orch(sample_stofs_config)
        expected = StepResult(success=True, step_name="prepare_restart")
        orch.handler.prepare_restart.return_value = expected

        result = orch.prepare_restart("forecast")

        orch.handler.prepare_restart.assert_called_once_with("forecast")
        assert result is expected

    def test_execute_model_delegates(self, sample_stofs_config):
        """Test execute_model delegates to handler."""
        orch = self._make_orch(sample_stofs_config)
        expected = StepResult(success=True, step_name="execute_model")
        orch.handler.execute_model.return_value = expected

        result = orch.execute_model("nowcast")

        orch.handler.execute_model.assert_called_once_with("nowcast")
        assert result is expected

    def test_archive_outputs_delegates(self, sample_stofs_config):
        """Test archive_outputs delegates to handler."""
        orch = self._make_orch(sample_stofs_config)
        expected = StepResult(success=True, step_name="archive_outputs")
        orch.handler.archive_outputs.return_value = expected

        result = orch.archive_outputs("forecast")

        orch.handler.archive_outputs.assert_called_once_with("forecast")
        assert result is expected


class TestModelRunOrchestratorRunAll:
    """Tests for run_all method."""

    def _make_success_step(self, name):
        """Create a successful StepResult."""
        return StepResult(
            success=True,
            step_name=name,
            message="OK",
            duration_seconds=1.0,
        )

    def _make_failure_step(self, name):
        """Create a failed StepResult."""
        return StepResult(
            success=False,
            step_name=name,
            message="Failed",
            duration_seconds=1.0,
            errors=["Something went wrong"],
        )

    def test_run_all_nowcast_success(self, sample_stofs_config):
        """Test run_all nowcast returns success when all steps pass."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        orch.handler.stage_model_files.return_value = self._make_success_step("stage_model_files")
        orch.handler.prepare_restart.return_value = self._make_success_step("prepare_restart")
        orch.handler.execute_model.return_value = self._make_success_step("execute_model")
        orch.handler.archive_outputs.return_value = self._make_success_step("archive_outputs")

        result = orch.run_all("nowcast")

        assert result.success
        assert result.phase == "nowcast"
        assert len(result.step_results) == 4

    def test_run_all_forecast_success(self, sample_stofs_config):
        """Test run_all forecast returns success when all steps pass."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        orch.handler.stage_model_files.return_value = self._make_success_step("stage_model_files")
        orch.handler.prepare_restart.return_value = self._make_success_step("prepare_restart")
        orch.handler.execute_model.return_value = self._make_success_step("execute_model")
        orch.handler.archive_outputs.return_value = self._make_success_step("archive_outputs")

        result = orch.run_all("forecast")

        assert result.success
        assert result.phase == "forecast"
        assert len(result.step_results) == 4

    def test_run_all_invalid_phase_raises(self, sample_stofs_config):
        """Test run_all raises ValueError for invalid phase."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        with pytest.raises(ValueError, match="Invalid phase"):
            orch.run_all("prep")

    @pytest.mark.parametrize("invalid_phase", ["post", "analysis", "NOWCAST", ""])
    def test_run_all_rejects_invalid_phases(self, invalid_phase, sample_stofs_config):
        """Test run_all rejects various invalid phase names."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        with pytest.raises(ValueError):
            orch.run_all(invalid_phase)

    def test_run_all_fail_fast_stops_on_first_failure(self, sample_stofs_config):
        """Test run_all with fail_fast=True stops at first failure."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        orch.handler.stage_model_files.return_value = self._make_success_step("stage_model_files")
        orch.handler.prepare_restart.return_value = self._make_failure_step("prepare_restart")

        result = orch.run_all("nowcast", fail_fast=True)

        assert not result.success
        assert len(result.step_results) == 2
        # execute_model and archive_outputs should NOT be called
        orch.handler.execute_model.assert_not_called()
        orch.handler.archive_outputs.assert_not_called()

    def test_run_all_continue_on_error(self, sample_stofs_config):
        """Test run_all with fail_fast=False continues after failure."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        orch.handler.stage_model_files.return_value = self._make_success_step("stage_model_files")
        orch.handler.prepare_restart.return_value = self._make_failure_step("prepare_restart")
        orch.handler.execute_model.return_value = self._make_success_step("execute_model")
        orch.handler.archive_outputs.return_value = self._make_success_step("archive_outputs")

        result = orch.run_all("nowcast", fail_fast=False)

        assert not result.success
        assert len(result.step_results) == 4  # All steps ran
        assert len(result.errors) == 1

    def test_run_all_handles_exception(self, sample_stofs_config):
        """Test run_all handles exception raised by a step."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        orch.handler.stage_model_files.side_effect = RuntimeError("Disk full")

        result = orch.run_all("nowcast", fail_fast=True)

        assert not result.success
        assert "Disk full" in result.errors[0]
        # Exception-generated step result should be in step_results
        assert "stage_model_files" in result.step_results
        assert not result.step_results["stage_model_files"].success

    def test_run_all_collects_warnings(self, sample_stofs_config):
        """Test run_all collects warnings from steps."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        step_with_warnings = StepResult(
            success=True,
            step_name="execute_model",
            duration_seconds=1.0,
            warnings=["High memory usage"],
        )
        orch.handler.stage_model_files.return_value = self._make_success_step("stage_model_files")
        orch.handler.prepare_restart.return_value = self._make_success_step("prepare_restart")
        orch.handler.execute_model.return_value = step_with_warnings
        orch.handler.archive_outputs.return_value = self._make_success_step("archive_outputs")

        result = orch.run_all("nowcast")

        assert result.success
        assert len(result.warnings) == 1
        assert "High memory usage" in result.warnings[0]

    def test_run_all_measures_duration(self, sample_stofs_config):
        """Test run_all measures total duration."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        orch.handler.stage_model_files.return_value = self._make_success_step("stage_model_files")
        orch.handler.prepare_restart.return_value = self._make_success_step("prepare_restart")
        orch.handler.execute_model.return_value = self._make_success_step("execute_model")
        orch.handler.archive_outputs.return_value = self._make_success_step("archive_outputs")

        result = orch.run_all("nowcast")

        assert result.total_duration_seconds >= 0

    def test_run_all_passes_phase_to_all_steps(self, sample_stofs_config):
        """Test run_all passes the phase argument to all handler steps."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        orch.handler.stage_model_files.return_value = self._make_success_step("stage_model_files")
        orch.handler.prepare_restart.return_value = self._make_success_step("prepare_restart")
        orch.handler.execute_model.return_value = self._make_success_step("execute_model")
        orch.handler.archive_outputs.return_value = self._make_success_step("archive_outputs")

        orch.run_all("forecast")

        orch.handler.stage_model_files.assert_called_once_with("forecast")
        orch.handler.prepare_restart.assert_called_once_with("forecast")
        orch.handler.execute_model.assert_called_once_with("forecast")
        orch.handler.archive_outputs.assert_called_once_with("forecast")


class TestModelRunOrchestratorStepCount:
    """Tests that verify the model run workflow has exactly 4 steps."""

    def test_run_all_executes_4_steps(self, sample_stofs_config):
        """Test run_all executes exactly 4 steps."""
        orch = ModelRunOrchestrator(sample_stofs_config)
        orch.handler = Mock()

        success_step = StepResult(
            success=True,
            step_name="test",
            duration_seconds=0.0,
        )
        orch.handler.stage_model_files.return_value = success_step
        orch.handler.prepare_restart.return_value = success_step
        orch.handler.execute_model.return_value = success_step
        orch.handler.archive_outputs.return_value = success_step

        result = orch.run_all("nowcast")

        assert len(result.step_results) == 4


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
