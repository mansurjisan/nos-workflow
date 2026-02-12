"""
Prep Orchestrator

Provides a unified Python interface for NOS OFS preparation workflow,
dispatching to framework-specific handlers (STOFS or COMF).

Usage:
    from nos_ofs.orchestration import PrepOrchestrator
    from nos_ofs.config import OFSConfig

    config = OFSConfig.load("stofs_3d_atl")
    orchestrator = PrepOrchestrator(config)
    results = orchestrator.run_all()
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .handlers import (
    BasePrepHandler,
    STOFSPrepHandler,
    COMFPrepHandler,
    StepResult,
)

log = logging.getLogger(__name__)


@dataclass
class PrepResult:
    """Overall result of prep workflow execution."""

    success: bool
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
            f"Prep Workflow: {'SUCCESS' if self.success else 'FAILED'}",
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


class PrepOrchestrator:
    """
    Orchestrates NOS OFS preparation workflow.

    Provides a unified 7-step API that dispatches to framework-specific
    handlers (STOFS or COMF) based on configuration.

    Steps:
        1. stage_static_files() - Link/copy grid, control files
        2. create_model_config() - Generate param.nml, run_control.nml, etc.
        3. create_forcing_atmospheric() - GFS/HRRR or NAM/GFS/RTMA
        4. create_forcing_river() - NWM + St. Lawrence or NWM/USGS
        5. create_forcing_obc() - RTOFS/HYCOM open boundaries
        6. create_forcing_nudging() - T/S interior nudging (optional)
        7. prepare_initial_condition() - Restart/hotstart search

    Example:
        config = OFSConfig.load("stofs_3d_atl")
        prep = PrepOrchestrator(config)

        # Run individual steps
        prep.stage_static_files()
        prep.create_model_config()
        # ...

        # Or run all steps
        result = prep.run_all()
        if result.success:
            print("Prep completed successfully")
    """

    def __init__(self, config: Any, framework: Optional[str] = None):
        """
        Initialize prep orchestrator.

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
            f"PrepOrchestrator initialized for {self.framework.upper()} framework"
        )

    def _create_handler(self) -> BasePrepHandler:
        """Create framework-specific prep handler."""
        if self.framework == "stofs":
            return STOFSPrepHandler(self.config)
        elif self.framework == "comf":
            return COMFPrepHandler(self.config)
        else:
            raise ValueError(
                f"Unknown framework: {self.framework}. Must be 'stofs' or 'comf'."
            )

    def stage_static_files(self) -> StepResult:
        """
        Step 1: Stage static files (grids, control files).

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 1/7: Staging static files")
        return self.handler.stage_static_files()

    def create_model_config(self) -> StepResult:
        """
        Step 2: Create model configuration files.

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 2/7: Creating model configuration")
        return self.handler.create_model_config()

    def create_forcing_atmospheric(self) -> StepResult:
        """
        Step 3: Create atmospheric forcing.

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 3/7: Creating atmospheric forcing")
        return self.handler.create_forcing_atmospheric()

    def create_forcing_river(self) -> StepResult:
        """
        Step 4: Create river forcing.

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 4/7: Creating river forcing")
        return self.handler.create_forcing_river()

    def create_forcing_obc(self) -> StepResult:
        """
        Step 5: Create open boundary conditions.

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 5/7: Creating OBC forcing")
        return self.handler.create_forcing_obc()

    def create_forcing_nudging(self) -> StepResult:
        """
        Step 6: Create interior nudging fields (optional).

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 6/7: Creating nudging forcing")
        return self.handler.create_forcing_nudging()

    def prepare_initial_condition(self) -> StepResult:
        """
        Step 7: Prepare restart/hotstart file.

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 7/7: Preparing initial condition")
        return self.handler.prepare_initial_condition()

    def run_all(self, fail_fast: bool = True) -> PrepResult:
        """
        Run all 7 prep steps in sequence.

        Args:
            fail_fast: If True, stop on first failure. If False, continue
                      and collect all errors.

        Returns:
            PrepResult with overall workflow status
        """
        self.logger.info(
            f"Starting prep workflow for {self.framework.upper()} framework"
        )

        start_time = time.time()

        steps = [
            ("stage_static_files", self.stage_static_files),
            ("create_model_config", self.create_model_config),
            ("create_forcing_atmospheric", self.create_forcing_atmospheric),
            ("create_forcing_river", self.create_forcing_river),
            ("create_forcing_obc", self.create_forcing_obc),
            ("create_forcing_nudging", self.create_forcing_nudging),
            ("prepare_initial_condition", self.prepare_initial_condition),
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

        result = PrepResult(
            success=overall_success,
            total_duration_seconds=total_duration,
            step_results=step_results,
            errors=errors,
            warnings=warnings,
        )

        if overall_success:
            self.logger.info(
                f"Prep workflow completed successfully in {total_duration:.1f}s"
            )
        else:
            self.logger.error(
                f"Prep workflow failed after {total_duration:.1f}s with {len(errors)} errors"
            )

        return result

    def __repr__(self) -> str:
        return f"PrepOrchestrator(framework={self.framework})"
