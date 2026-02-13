"""
Base Handler Classes for Orchestration

Defines abstract base classes for prep, model run, and post-processing
handlers that framework-specific implementations must inherit from.
"""

import logging
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of a workflow step execution."""

    success: bool
    step_name: str
    message: str = ""
    command: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    duration_seconds: float = 0.0
    output_files: List[Path] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Allow using result in boolean context."""
        return self.success


class BasePrepHandler(ABC):
    """
    Abstract base class for prep handlers.

    Framework-specific implementations (STOFS, COMF) must implement
    all abstract methods to handle their specific workflow patterns.
    """

    def __init__(self, config: Any):
        """
        Initialize prep handler.

        Args:
            config: OFSConfig instance
        """
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def stage_static_files(self) -> StepResult:
        """
        Stage static files (grids, control files) to working directory.

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def create_model_config(self) -> StepResult:
        """
        Generate model control files (param.nml, run_control.nml, ROMS.in).

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def create_forcing_atmospheric(self) -> StepResult:
        """
        Create atmospheric forcing (GFS, HRRR, NAM).

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def create_forcing_river(self) -> StepResult:
        """
        Create river forcing (NWM, USGS).

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def create_forcing_obc(self) -> StepResult:
        """
        Create open boundary conditions (RTOFS, HYCOM).

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def create_forcing_nudging(self) -> StepResult:
        """
        Create interior nudging fields (optional).

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def prepare_initial_condition(self) -> StepResult:
        """
        Prepare restart/hotstart files.

        Returns:
            StepResult with execution status
        """
        pass

    def _run_subprocess(
        self,
        command: str,
        step_name: str,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        fatal: bool = True,
        timeout: int = 3600,
    ) -> StepResult:
        """
        Execute a shell command via subprocess.

        Args:
            command: Shell command to execute
            step_name: Name of the step (for logging)
            env: Environment variables (merged with os.environ)
            cwd: Working directory (defaults to config.DATA)
            fatal: Whether failure should be treated as fatal
            timeout: Command timeout in seconds (default: 1 hour)

        Returns:
            StepResult with execution status
        """
        import time

        start_time = time.time()

        # Prepare environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        # Default working directory
        if cwd is None:
            cwd = Path(getattr(self.config, "DATA", "/tmp"))

        self.logger.info(f"Running {step_name}: {command}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                env=run_env,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )

            duration = time.time() - start_time

            stdout = result.stdout or ""
            stderr = result.stderr or ""

            success = result.returncode == 0

            if success:
                self.logger.info(f"{step_name} completed successfully in {duration:.1f}s")
            else:
                level = logging.ERROR if fatal else logging.WARNING
                self.logger.log(
                    level,
                    f"{step_name} failed with return code {result.returncode} "
                    f"after {duration:.1f}s",
                )
                if stderr:
                    self.logger.log(level, f"stderr: {stderr[:500]}")

            return StepResult(
                success=success,
                step_name=step_name,
                command=command,
                stdout=stdout,
                stderr=stderr,
                returncode=result.returncode,
                duration_seconds=duration,
                message=f"Completed in {duration:.1f}s" if success else "Failed",
                errors=[stderr] if not success and stderr else [],
            )

        except subprocess.TimeoutExpired as e:
            duration = time.time() - start_time
            self.logger.error(f"{step_name} timed out after {duration:.1f}s")
            return StepResult(
                success=False,
                step_name=step_name,
                command=command,
                message="Timeout",
                duration_seconds=duration,
                errors=[f"Command timed out after {duration:.1f}s"],
            )

        except Exception as e:
            duration = time.time() - start_time
            self.logger.exception(f"{step_name} raised exception: {e}")
            return StepResult(
                success=False,
                step_name=step_name,
                command=command,
                message=str(e),
                duration_seconds=duration,
                errors=[str(e)],
            )

    def _source_and_capture_env(
        self,
        script: str,
        args: str = "",
        step_name: str = "source_script",
        fatal: bool = True,
        timeout: int = 3600,
    ) -> StepResult:
        """
        Source a shell script and capture environment variable changes.

        This is critical for COMF workflows where nos_ofs_launch.sh must be
        sourced (not subprocess'd) to export ~200 configuration variables.

        Args:
            script: Path to shell script to source
            args: Arguments to pass to the script
            step_name: Name of the step (for logging)
            fatal: Whether failure should be treated as fatal
            timeout: Command timeout in seconds (default: 1 hour)

        Returns:
            StepResult with execution status
        """
        import time

        start_time = time.time()

        # Default working directory
        cwd = Path(getattr(self.config, "DATA", "/tmp"))

        self.logger.info(f"Sourcing {step_name}: {script} {args}")

        # Build command to source script and dump environment
        command = f"source {script} {args} >/dev/null 2>&1 && env"

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                env=os.environ.copy(),
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )

            duration = time.time() - start_time

            success = result.returncode == 0

            if success:
                # Parse env output and apply to os.environ
                for line in result.stdout.splitlines():
                    if "=" in line:
                        key, _, value = line.partition("=")
                        os.environ[key] = value

                self.logger.info(
                    f"{step_name} sourced successfully in {duration:.1f}s, "
                    f"environment updated"
                )
            else:
                level = logging.ERROR if fatal else logging.WARNING
                stderr = result.stderr or ""
                self.logger.log(
                    level,
                    f"{step_name} failed with return code {result.returncode} "
                    f"after {duration:.1f}s",
                )
                if stderr:
                    self.logger.log(level, f"stderr: {stderr[:500]}")

            return StepResult(
                success=success,
                step_name=step_name,
                command=command,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                returncode=result.returncode,
                duration_seconds=duration,
                message=f"Sourced in {duration:.1f}s" if success else "Failed to source",
                errors=[result.stderr] if not success and result.stderr else [],
            )

        except subprocess.TimeoutExpired as e:
            duration = time.time() - start_time
            self.logger.error(f"{step_name} timed out after {duration:.1f}s")
            return StepResult(
                success=False,
                step_name=step_name,
                command=command,
                message="Timeout",
                duration_seconds=duration,
                errors=[f"Command timed out after {duration:.1f}s"],
            )

        except Exception as e:
            duration = time.time() - start_time
            self.logger.exception(f"{step_name} raised exception: {e}")
            return StepResult(
                success=False,
                step_name=step_name,
                command=command,
                message=str(e),
                duration_seconds=duration,
                errors=[str(e)],
            )


class BaseModelRunHandler(ABC):
    """
    Abstract base class for model run handlers.

    Framework-specific implementations (STOFS, COMF) must implement
    all abstract methods to handle their specific model execution patterns.
    """

    def __init__(self, config: Any):
        """
        Initialize model run handler.

        Args:
            config: OFSConfig instance
        """
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def stage_model_files(self, phase: str) -> StepResult:
        """
        Stage forcing and static files for model run.

        Args:
            phase: "nowcast" or "forecast"

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def prepare_restart(self, phase: str) -> StepResult:
        """
        Prepare restart/hotstart file for model run.

        Args:
            phase: "nowcast" or "forecast"

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def execute_model(self, phase: str) -> StepResult:
        """
        Execute the model.

        Args:
            phase: "nowcast" or "forecast"

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def archive_outputs(self, phase: str) -> StepResult:
        """
        Archive model outputs to COMOUT.

        Args:
            phase: "nowcast" or "forecast"

        Returns:
            StepResult with execution status
        """
        pass

    def _run_subprocess(
        self,
        command: str,
        step_name: str,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        fatal: bool = True,
        timeout: int = 7200,
    ) -> StepResult:
        """
        Execute a shell command via subprocess.

        Args:
            command: Shell command to execute
            step_name: Name of the step (for logging)
            env: Environment variables (merged with os.environ)
            cwd: Working directory (defaults to config.DATA)
            fatal: Whether failure should be treated as fatal
            timeout: Command timeout in seconds (default: 2 hours)

        Returns:
            StepResult with execution status
        """
        import time

        start_time = time.time()

        # Prepare environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        # Default working directory
        if cwd is None:
            cwd = Path(getattr(self.config, "DATA", "/tmp"))

        self.logger.info(f"Running {step_name}: {command}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                env=run_env,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )

            duration = time.time() - start_time

            stdout = result.stdout or ""
            stderr = result.stderr or ""

            success = result.returncode == 0

            if success:
                self.logger.info(f"{step_name} completed successfully in {duration:.1f}s")
            else:
                level = logging.ERROR if fatal else logging.WARNING
                self.logger.log(
                    level,
                    f"{step_name} failed with return code {result.returncode} "
                    f"after {duration:.1f}s",
                )
                if stderr:
                    self.logger.log(level, f"stderr: {stderr[:500]}")

            return StepResult(
                success=success,
                step_name=step_name,
                command=command,
                stdout=stdout,
                stderr=stderr,
                returncode=result.returncode,
                duration_seconds=duration,
                message=f"Completed in {duration:.1f}s" if success else "Failed",
                errors=[stderr] if not success and stderr else [],
            )

        except subprocess.TimeoutExpired as e:
            duration = time.time() - start_time
            self.logger.error(f"{step_name} timed out after {duration:.1f}s")
            return StepResult(
                success=False,
                step_name=step_name,
                command=command,
                message="Timeout",
                duration_seconds=duration,
                errors=[f"Command timed out after {duration:.1f}s"],
            )

        except Exception as e:
            duration = time.time() - start_time
            self.logger.exception(f"{step_name} raised exception: {e}")
            return StepResult(
                success=False,
                step_name=step_name,
                command=command,
                message=str(e),
                duration_seconds=duration,
                errors=[str(e)],
            )


class BasePostHandler(ABC):
    """
    Abstract base class for post-processing handlers.

    Framework-specific implementations (STOFS, COMF) must implement
    all abstract methods to handle their specific post-processing patterns.

    STOFS uses two-phase post-processing (post_1, post_2) dispatched via
    run_phase(). COMF uses a 6-step pipeline dispatched through individual
    step methods.
    """

    def __init__(self, config: Any):
        """
        Initialize post-processing handler.

        Args:
            config: OFSConfig instance
        """
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def extract_fields(self) -> StepResult:
        """
        Extract 2D and 3D fields from raw model output.

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def extract_stations(self) -> StepResult:
        """
        Extract station timeseries from model output.

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def create_standard_netcdf(self) -> StepResult:
        """
        Convert extracted fields to CO-OPS standard NetCDF format.

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def create_grib2(self) -> StepResult:
        """
        Create GRIB2 output for AWIPS dissemination.

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def create_awips(self) -> StepResult:
        """
        Create AWIPS-format output (SHEF bulletins, etc.).

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def archive_outputs(self) -> StepResult:
        """
        Copy final post-processed products to COMOUT.

        Returns:
            StepResult with execution status
        """
        pass

    @abstractmethod
    def run_phase(self, phase: str) -> StepResult:
        """
        Run a specific post-processing phase.

        For STOFS: phase is "post_1" or "post_2".
        For COMF: phase is "post" (runs all steps).

        Args:
            phase: Post-processing phase identifier

        Returns:
            StepResult with execution status
        """
        pass

    def _run_subprocess(
        self,
        command: str,
        step_name: str,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        fatal: bool = True,
        timeout: int = 3600,
    ) -> StepResult:
        """
        Execute a shell command via subprocess.

        Args:
            command: Shell command to execute
            step_name: Name of the step (for logging)
            env: Environment variables (merged with os.environ)
            cwd: Working directory (defaults to config.DATA)
            fatal: Whether failure should be treated as fatal
            timeout: Command timeout in seconds (default: 1 hour)

        Returns:
            StepResult with execution status
        """
        import time

        start_time = time.time()

        # Prepare environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        # Default working directory
        if cwd is None:
            cwd = Path(getattr(self.config, "DATA", "/tmp"))

        self.logger.info(f"Running {step_name}: {command}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                env=run_env,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )

            duration = time.time() - start_time

            stdout = result.stdout or ""
            stderr = result.stderr or ""

            success = result.returncode == 0

            if success:
                self.logger.info(
                    f"{step_name} completed successfully in {duration:.1f}s"
                )
            else:
                level = logging.ERROR if fatal else logging.WARNING
                self.logger.log(
                    level,
                    f"{step_name} failed with return code {result.returncode} "
                    f"after {duration:.1f}s",
                )
                if stderr:
                    self.logger.log(level, f"stderr: {stderr[:500]}")

            return StepResult(
                success=success,
                step_name=step_name,
                command=command,
                stdout=stdout,
                stderr=stderr,
                returncode=result.returncode,
                duration_seconds=duration,
                message=f"Completed in {duration:.1f}s" if success else "Failed",
                errors=[stderr] if not success and stderr else [],
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            self.logger.error(f"{step_name} timed out after {duration:.1f}s")
            return StepResult(
                success=False,
                step_name=step_name,
                command=command,
                message="Timeout",
                duration_seconds=duration,
                errors=[f"Command timed out after {duration:.1f}s"],
            )

        except Exception as e:
            duration = time.time() - start_time
            self.logger.exception(f"{step_name} raised exception: {e}")
            return StepResult(
                success=False,
                step_name=step_name,
                command=command,
                message=str(e),
                duration_seconds=duration,
                errors=[str(e)],
            )
