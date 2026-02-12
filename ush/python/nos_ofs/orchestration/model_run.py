"""
Model Run Orchestrator

Provides a unified Python interface for NOS OFS model execution workflow,
dispatching to framework-specific handlers (STOFS or COMF).

Usage:
    from nos_ofs.orchestration import ModelRunOrchestrator
    from nos_ofs.config import OFSConfig

    config = OFSConfig.load("stofs_3d_atl")
    orchestrator = ModelRunOrchestrator(config)

    # Run nowcast
    result = orchestrator.run_all("nowcast")

    # Run forecast
    result = orchestrator.run_all("forecast")
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .handlers import (
    BaseModelRunHandler,
    STOFSModelRunHandler,
    COMFModelRunHandler,
    StepResult,
)

log = logging.getLogger(__name__)


@dataclass
class ModelRunResult:
    """Overall result of model run workflow execution."""

    success: bool
    phase: str
    total_duration_seconds: float
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Allow using result in boolean context."""
        return self.success

    def summary(self) -> str:
        """Return a summary string."""
        lines = [
            f"Model Run ({self.phase}): {'SUCCESS' if self.success else 'FAILED'}",
            f"Duration: {self.total_duration_seconds:.1f}s",
            f"Steps: {len(self.step_results)}",
        ]

        for step_name, result in self.step_results.items():
            status = "OK" if result.success else "FAIL"
            lines.append(f"  {step_name}: {status} ({result.duration_seconds:.1f}s)")

        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
            for err in self.errors[:3]:
                lines.append(f"  - {err}")

        if self.warnings:
            lines.append(f"Warnings: {len(self.warnings)}")

        return "\n".join(lines)


class ModelRunOrchestrator:
    """
    Orchestrates NOS OFS model execution workflow.

    Provides a unified 4-step API that dispatches to framework-specific
    handlers (STOFS or COMF) based on configuration.

    Steps (per phase):
        1. stage_model_files(phase) - Copy forcing/static files to $DATA
        2. prepare_restart(phase) - Find and stage hotstart/initial condition
        3. execute_model(phase) - Configure runtime and run model
        4. archive_outputs(phase) - Copy outputs to $COMOUT

    Example:
        config = OFSConfig.load("stofs_3d_atl")
        runner = ModelRunOrchestrator(config)

        # Run nowcast phase
        result = runner.run_all("nowcast")
        if result.success:
            print("Nowcast completed successfully")

        # Run forecast phase
        result = runner.run_all("forecast")
        if result.success:
            print("Forecast completed successfully")
    """

    def __init__(self, config: Any, framework: Optional[str] = None):
        """
        Initialize model run orchestrator.

        Args:
            config: OFSConfig instance
            framework: Force framework ("stofs" or "comf"). If None, auto-detect
                      from config.OFS_FRAMEWORK or config.framework.
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Determine framework
        if framework is None:
            framework = getattr(config, "OFS_FRAMEWORK", None)
            if framework is None:
                framework = getattr(config, "framework", "comf").lower()

        self.framework = framework.lower()

        # Create framework-specific handler
        self.handler = self._create_handler()

        self.logger.info(
            f"ModelRunOrchestrator initialized for {self.framework.upper()} framework"
        )

    def _create_handler(self) -> BaseModelRunHandler:
        """Create framework-specific model run handler."""
        if self.framework == "stofs":
            return STOFSModelRunHandler(self.config)
        elif self.framework == "comf":
            return COMFModelRunHandler(self.config)
        else:
            raise ValueError(
                f"Unknown framework: {self.framework}. Must be 'stofs' or 'comf'."
            )

    def stage_model_files(self, phase: str) -> StepResult:
        """
        Step 1: Stage forcing and static files for model run.

        Args:
            phase: "nowcast" or "forecast"

        Returns:
            StepResult with execution status
        """
        self.logger.info(f"Step 1/4: Staging model files for {phase}")
        return self.handler.stage_model_files(phase)

    def prepare_restart(self, phase: str) -> StepResult:
        """
        Step 2: Prepare restart/hotstart file.

        Args:
            phase: "nowcast" or "forecast"

        Returns:
            StepResult with execution status
        """
        self.logger.info(f"Step 2/4: Preparing restart for {phase}")
        return self.handler.prepare_restart(phase)

    def execute_model(self, phase: str) -> StepResult:
        """
        Step 3: Execute the model.

        Args:
            phase: "nowcast" or "forecast"

        Returns:
            StepResult with execution status
        """
        self.logger.info(f"Step 3/4: Executing model for {phase}")
        return self.handler.execute_model(phase)

    def archive_outputs(self, phase: str) -> StepResult:
        """
        Step 4: Archive model outputs to COMOUT.

        Args:
            phase: "nowcast" or "forecast"

        Returns:
            StepResult with execution status
        """
        self.logger.info(f"Step 4/4: Archiving outputs for {phase}")
        return self.handler.archive_outputs(phase)

    def run_all(self, phase: str, fail_fast: bool = True) -> ModelRunResult:
        """
        Run all 4 model run steps for the specified phase.

        Args:
            phase: "nowcast" or "forecast"
            fail_fast: If True, stop on first failure. If False, continue
                      and collect all errors.

        Returns:
            ModelRunResult with overall workflow status
        """
        if phase not in ["nowcast", "forecast"]:
            raise ValueError(f"Invalid phase: {phase}. Must be 'nowcast' or 'forecast'.")

        self.logger.info(
            f"Starting {phase} workflow for {self.framework.upper()} framework"
        )

        start_time = time.time()

        steps = [
            ("stage_model_files", lambda: self.stage_model_files(phase)),
            ("prepare_restart", lambda: self.prepare_restart(phase)),
            ("execute_model", lambda: self.execute_model(phase)),
            ("archive_outputs", lambda: self.archive_outputs(phase)),
        ]

        step_results = {}
        errors = []
        warnings = []
        overall_success = True

        for step_name, step_func in steps:
            try:
                result = step_func()
                step_results[step_name] = result

                # Collect warnings
                if result.warnings:
                    warnings.extend(result.warnings)

                # Check for failure
                if not result.success:
                    overall_success = False
                    errors.append(f"{step_name}: {result.message}")

                    if fail_fast:
                        self.logger.error(f"Step {step_name} failed, stopping workflow")
                        break
                    else:
                        self.logger.warning(f"Step {step_name} failed, continuing...")

            except Exception as e:
                self.logger.exception(f"Step {step_name} raised exception: {e}")
                step_results[step_name] = StepResult(
                    success=False,
                    step_name=step_name,
                    message=str(e),
                    errors=[str(e)],
                )
                errors.append(f"{step_name}: {e}")
                overall_success = False

                if fail_fast:
                    break

        total_duration = time.time() - start_time

        result = ModelRunResult(
            success=overall_success,
            phase=phase,
            total_duration_seconds=total_duration,
            step_results=step_results,
            errors=errors,
            warnings=warnings,
        )

        if overall_success:
            self.logger.info(
                f"{phase.capitalize()} workflow completed successfully in {total_duration:.1f}s"
            )
        else:
            self.logger.error(
                f"{phase.capitalize()} workflow failed after {total_duration:.1f}s "
                f"with {len(errors)} errors"
            )

        return result

    def __repr__(self) -> str:
        return f"ModelRunOrchestrator(framework={self.framework})"
