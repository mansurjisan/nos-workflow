"""
Unit tests for orchestration module.

These tests verify the structure and basic functionality of the
orchestration layer without actually executing workflows.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

from nos_ofs.orchestration import (
    PrepOrchestrator,
    ModelRunOrchestrator,
    PrepResult,
    ModelRunResult,
    StepResult,
)
from nos_ofs.orchestration.handlers import (
    STOFSPrepHandler,
    STOFSModelRunHandler,
    COMFPrepHandler,
    COMFModelRunHandler,
)


class TestPrepOrchestrator:
    """Test PrepOrchestrator class."""

    def test_stofs_framework_creates_stofs_handler(self):
        """Test that STOFS framework creates STOFSPrepHandler."""
        config = Mock()
        config.OFS_FRAMEWORK = "stofs"
        config.USHnos = "/tmp/ush"
        config.FIXnos = "/tmp/fix"
        config.DATA = "/tmp/data"
        config.USHstofs3d = "/tmp/ush/stofs"
        config.FIXstofs3d = "/tmp/fix/stofs"

        orchestrator = PrepOrchestrator(config, framework="stofs")

        assert orchestrator.framework == "stofs"
        assert isinstance(orchestrator.handler, STOFSPrepHandler)

    def test_comf_framework_creates_comf_handler(self):
        """Test that COMF framework creates COMFPrepHandler."""
        config = Mock()
        config.OFS_FRAMEWORK = "comf"
        config.USHnos = "/tmp/ush"
        config.FIXnos = "/tmp/fix"
        config.DATA = "/tmp/data"

        orchestrator = PrepOrchestrator(config, framework="comf")

        assert orchestrator.framework == "comf"
        assert isinstance(orchestrator.handler, COMFPrepHandler)

    def test_auto_detect_framework_from_config(self):
        """Test auto-detection of framework from config."""
        config = Mock()
        config.OFS_FRAMEWORK = "stofs"
        config.USHnos = "/tmp/ush"
        config.FIXnos = "/tmp/fix"
        config.DATA = "/tmp/data"
        config.USHstofs3d = "/tmp/ush/stofs"
        config.FIXstofs3d = "/tmp/fix/stofs"

        orchestrator = PrepOrchestrator(config)

        assert orchestrator.framework == "stofs"

    def test_invalid_framework_raises_error(self):
        """Test that invalid framework raises ValueError."""
        config = Mock()

        with pytest.raises(ValueError, match="Unknown framework"):
            PrepOrchestrator(config, framework="invalid")

    def test_prep_result_boolean_context(self):
        """Test PrepResult can be used in boolean context."""
        success_result = PrepResult(success=True, total_duration_seconds=10.0)
        assert success_result

        failure_result = PrepResult(success=False, total_duration_seconds=5.0)
        assert not failure_result

    def test_prep_result_summary(self):
        """Test PrepResult summary method."""
        step_results = {
            "step1": StepResult(
                success=True,
                step_name="step1",
                duration_seconds=2.0,
            ),
            "step2": StepResult(
                success=False,
                step_name="step2",
                message="Failed",
                duration_seconds=3.0,
            ),
        }

        result = PrepResult(
            success=False,
            total_duration_seconds=5.0,
            step_results=step_results,
            errors=["step2: Failed"],
        )

        summary = result.summary()
        assert "FAILED" in summary
        assert "5.0s" in summary
        assert "step1: OK" in summary
        assert "step2: FAIL" in summary


class TestModelRunOrchestrator:
    """Test ModelRunOrchestrator class."""

    def test_stofs_framework_creates_stofs_handler(self):
        """Test that STOFS framework creates STOFSModelRunHandler."""
        config = Mock()
        config.OFS_FRAMEWORK = "stofs"
        config.USHnos = "/tmp/ush"
        config.FIXnos = "/tmp/fix"
        config.DATA = "/tmp/data"
        config.COMOUT = "/tmp/comout"
        config.USHstofs3d = "/tmp/ush/stofs"
        config.FIXstofs3d = "/tmp/fix/stofs"
        config.EXECstofs3d = "/tmp/exec"

        orchestrator = ModelRunOrchestrator(config, framework="stofs")

        assert orchestrator.framework == "stofs"
        assert isinstance(orchestrator.handler, STOFSModelRunHandler)

    def test_comf_framework_creates_comf_handler(self):
        """Test that COMF framework creates COMFModelRunHandler."""
        config = Mock()
        config.OFS_FRAMEWORK = "comf"
        config.USHnos = "/tmp/ush"
        config.DATA = "/tmp/data"

        orchestrator = ModelRunOrchestrator(config, framework="comf")

        assert orchestrator.framework == "comf"
        assert isinstance(orchestrator.handler, COMFModelRunHandler)

    def test_invalid_phase_raises_error(self):
        """Test that invalid phase raises ValueError."""
        config = Mock()
        config.OFS_FRAMEWORK = "stofs"
        config.USHnos = "/tmp/ush"
        config.FIXnos = "/tmp/fix"
        config.DATA = "/tmp/data"
        config.COMOUT = "/tmp/comout"
        config.USHstofs3d = "/tmp/ush/stofs"
        config.FIXstofs3d = "/tmp/fix/stofs"
        config.EXECstofs3d = "/tmp/exec"

        orchestrator = ModelRunOrchestrator(config)

        with pytest.raises(ValueError, match="Invalid phase"):
            orchestrator.run_all("invalid_phase")

    def test_model_run_result_boolean_context(self):
        """Test ModelRunResult can be used in boolean context."""
        success_result = ModelRunResult(
            success=True,
            phase="nowcast",
            total_duration_seconds=100.0,
        )
        assert success_result

        failure_result = ModelRunResult(
            success=False,
            phase="forecast",
            total_duration_seconds=50.0,
        )
        assert not failure_result


class TestStepResult:
    """Test StepResult class."""

    def test_step_result_boolean_context(self):
        """Test StepResult can be used in boolean context."""
        success_result = StepResult(
            success=True,
            step_name="test_step",
        )
        assert success_result

        failure_result = StepResult(
            success=False,
            step_name="test_step",
        )
        assert not failure_result


class TestHandlerImports:
    """Test that all handlers can be imported."""

    def test_import_base_handlers(self):
        """Test importing base handler classes."""
        from nos_ofs.orchestration.handlers.base import (
            BasePrepHandler,
            BaseModelRunHandler,
        )

        assert BasePrepHandler is not None
        assert BaseModelRunHandler is not None

    def test_import_stofs_handlers(self):
        """Test importing STOFS handlers."""
        from nos_ofs.orchestration.handlers.stofs import (
            STOFSPrepHandler,
            STOFSModelRunHandler,
        )

        assert STOFSPrepHandler is not None
        assert STOFSModelRunHandler is not None

    def test_import_comf_handlers(self):
        """Test importing COMF handlers."""
        from nos_ofs.orchestration.handlers.comf import (
            COMFPrepHandler,
            COMFModelRunHandler,
        )

        assert COMFPrepHandler is not None
        assert COMFModelRunHandler is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
