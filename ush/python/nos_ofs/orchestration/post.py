"""
Post-Processing Orchestrator

Provides a unified Python interface for NOS OFS post-processing workflow,
dispatching to framework-specific handlers (STOFS or COMF).

For STOFS: Coordinates two-phase post-processing (post_1 and post_2).
For COMF: Coordinates single-phase post-processing with model-type-specific
handlers (SCHISM, ROMS, FVCOM).

Usage:
    from nos_ofs.orchestration import PostOrchestrator
    from nos_ofs.config import OFSConfig

    config = OFSConfig.load("stofs_3d_atl")
    orchestrator = PostOrchestrator(config)
    result = orchestrator.run_all()

    # Or for STOFS, run individual phases:
    result_1 = orchestrator.run_phase("post_1")
    result_2 = orchestrator.run_phase("post_2")
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .handlers import (
    BasePostHandler,
    STOFSPostHandler,
    COMFPostHandler,
    StepResult,
)

log = logging.getLogger(__name__)


@dataclass
class PostResult:
    """Overall result of post-processing workflow execution."""

    success: bool
    phase: str = "post"
    total_duration_seconds: float = 0.0
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Allow using result in boolean context."""
        return self.success

    def summary(self) -> str:
        """Return a summary string."""
        lines = [
            f"Post-Processing ({self.phase}): {'SUCCESS' if self.success else 'FAILED'}",
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


class PostOrchestrator:
    """
    Orchestrates NOS OFS post-processing workflow.

    Provides a unified API that dispatches to framework-specific handlers
    (STOFS or COMF) based on configuration.

    Steps (COMF single-phase):
        1. extract_fields() - Extract 2D/3D fields from raw output
        2. extract_stations() - Extract station timeseries
        3. create_standard_netcdf() - Convert to CO-OPS standard NetCDF
        4. create_grib2() - Create GRIB2 output (if applicable)
        5. create_awips() - Create AWIPS-format output (if applicable)
        6. archive_outputs() - Copy products to COMOUT

    Steps (STOFS two-phase):
        Phase 1: attribute addition, SHEF, ADCIRC, GRIB2, station profiles
        Phase 2: hotstart merge, 2D fields, GeoPackage

    Example:
        config = OFSConfig.load("cbofs")
        post = PostOrchestrator(config)
        result = post.run_all()
        if result.success:
            print("Post-processing completed successfully")

        # STOFS-specific phase execution:
        config = OFSConfig.load("stofs_3d_atl")
        post = PostOrchestrator(config)
        result_1 = post.run_phase("post_1")
        result_2 = post.run_phase("post_2")
    """

    def __init__(self, config: Any, framework: Optional[str] = None):
        """
        Initialize post-processing orchestrator.

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
            f"PostOrchestrator initialized for {self.framework.upper()} framework"
        )

    def _create_handler(self) -> BasePostHandler:
        """Create framework-specific post-processing handler."""
        if self.framework == "stofs":
            return STOFSPostHandler(self.config)
        elif self.framework == "comf":
            return COMFPostHandler(self.config)
        else:
            raise ValueError(
                f"Unknown framework: {self.framework}. Must be 'stofs' or 'comf'."
            )

    def extract_fields(self) -> StepResult:
        """
        Step 1: Extract 2D/3D fields from raw model output.

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 1/6: Extracting fields")
        return self.handler.extract_fields()

    def extract_stations(self) -> StepResult:
        """
        Step 2: Extract station timeseries.

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 2/6: Extracting station timeseries")
        return self.handler.extract_stations()

    def create_standard_netcdf(self) -> StepResult:
        """
        Step 3: Convert to CO-OPS standard NetCDF format.

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 3/6: Creating standard NetCDF")
        return self.handler.create_standard_netcdf()

    def create_grib2(self) -> StepResult:
        """
        Step 4: Create GRIB2 output (if applicable).

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 4/6: Creating GRIB2 output")
        return self.handler.create_grib2()

    def create_awips(self) -> StepResult:
        """
        Step 5: Create AWIPS-format output (if applicable).

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 5/6: Creating AWIPS output")
        return self.handler.create_awips()

    def archive_outputs(self) -> StepResult:
        """
        Step 6: Archive products to COMOUT.

        Returns:
            StepResult with execution status
        """
        self.logger.info("Step 6/6: Archiving outputs")
        return self.handler.archive_outputs()

    def run_phase(self, phase: str) -> PostResult:
        """
        Run a specific post-processing phase (STOFS only).

        Args:
            phase: "post_1" or "post_2" for STOFS; "post" for COMF

        Returns:
            PostResult with phase execution status
        """
        if self.framework != "stofs" and phase in ("post_1", "post_2"):
            self.logger.warning(
                f"Phase {phase} is STOFS-specific; running full COMF post instead"
            )
            return self.run_all()

        self.logger.info(f"Running post-processing phase: {phase}")
        start_time = time.time()

        try:
            result = self.handler.run_phase(phase)
            duration = time.time() - start_time

            return PostResult(
                success=result.success,
                phase=phase,
                total_duration_seconds=duration,
                step_results={phase: result},
                errors=result.errors if not result.success else [],
                warnings=result.warnings,
            )

        except Exception as e:
            duration = time.time() - start_time
            self.logger.exception(f"Phase {phase} raised exception: {e}")
            return PostResult(
                success=False,
                phase=phase,
                total_duration_seconds=duration,
                errors=[str(e)],
            )

    def run_all(self, fail_fast: bool = True) -> PostResult:
        """
        Run all post-processing steps.

        For STOFS: Runs post_1 then post_2.
        For COMF: Runs the 6-step pipeline.

        Args:
            fail_fast: If True, stop on first failure. If False, continue
                      and collect all errors.

        Returns:
            PostResult with overall workflow status
        """
        self.logger.info(
            f"Starting post-processing workflow for {self.framework.upper()} framework"
        )

        start_time = time.time()

        if self.framework == "stofs":
            return self._run_stofs_pipeline(fail_fast)

        return self._run_comf_pipeline(fail_fast)

    def _run_stofs_pipeline(self, fail_fast: bool) -> PostResult:
        """Run STOFS two-phase post-processing pipeline."""
        start_time = time.time()

        step_results = {}
        errors = []
        warnings = []
        overall_success = True

        for phase in ["post_1", "post_2"]:
            self.logger.info(f"--- STOFS {phase} ---")
            try:
                result = self.handler.run_phase(phase)
                step_results[phase] = result

                if result.warnings:
                    warnings.extend(result.warnings)

                if not result.success:
                    overall_success = False
                    errors.append(f"{phase}: {result.message}")

                    if fail_fast:
                        self.logger.error(f"Phase {phase} failed, stopping")
                        break
                    else:
                        self.logger.warning(f"Phase {phase} failed, continuing...")

            except Exception as e:
                self.logger.exception(f"Phase {phase} raised exception: {e}")
                step_results[phase] = StepResult(
                    success=False,
                    step_name=phase,
                    message=str(e),
                    errors=[str(e)],
                )
                errors.append(f"{phase}: {e}")
                overall_success = False

                if fail_fast:
                    break

        total_duration = time.time() - start_time

        result = PostResult(
            success=overall_success,
            phase="stofs_pipeline",
            total_duration_seconds=total_duration,
            step_results=step_results,
            errors=errors,
            warnings=warnings,
        )

        if overall_success:
            self.logger.info(
                f"STOFS post-processing completed successfully in {total_duration:.1f}s"
            )
        else:
            self.logger.error(
                f"STOFS post-processing failed after {total_duration:.1f}s "
                f"with {len(errors)} errors"
            )

        return result

    def _run_comf_pipeline(self, fail_fast: bool) -> PostResult:
        """Run COMF 6-step post-processing pipeline."""
        start_time = time.time()

        steps = [
            ("extract_fields", self.extract_fields),
            ("extract_stations", self.extract_stations),
            ("create_standard_netcdf", self.create_standard_netcdf),
            ("create_grib2", self.create_grib2),
            ("create_awips", self.create_awips),
            ("archive_outputs", self.archive_outputs),
        ]

        step_results = {}
        errors = []
        warnings = []
        overall_success = True

        for step_name, step_func in steps:
            try:
                result = step_func()
                step_results[step_name] = result

                if result.warnings:
                    warnings.extend(result.warnings)

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

        result = PostResult(
            success=overall_success,
            phase="post",
            total_duration_seconds=total_duration,
            step_results=step_results,
            errors=errors,
            warnings=warnings,
        )

        if overall_success:
            self.logger.info(
                f"Post-processing completed successfully in {total_duration:.1f}s"
            )
        else:
            self.logger.error(
                f"Post-processing failed after {total_duration:.1f}s "
                f"with {len(errors)} errors"
            )

        return result

    def __repr__(self) -> str:
        return f"PostOrchestrator(framework={self.framework})"
