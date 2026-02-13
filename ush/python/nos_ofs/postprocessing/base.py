"""
Base Post-Processing Classes

Defines the abstract base class and result dataclass for all post-processing
implementations (SCHISM, ROMS, FVCOM). Follows the same patterns as
BaseForcingProcessor and BaseModel.

Post-processing converts raw model output into standard operational products:
- CO-OPS standard NetCDF (CF-1.6 conventions)
- Station timeseries (6-minute interval)
- GRIB2 fields for AWIPS dissemination
- SHEF bulletins for NWS river forecast centers
- GeoPackage for nowCOAST web mapping
"""

import logging
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


@dataclass
class PostResult:
    """
    Result of post-processing execution.

    Attributes:
        success: Whether post-processing completed successfully
        phase: Post-processing phase ("post_1", "post_2", or "post")
        total_duration_seconds: Wall clock time for post-processing
        output_files: List of generated output files
        archived_files: List of files copied to COMOUT
        errors: List of error messages
        warnings: List of warning messages (non-fatal issues)
        metadata: Additional processing metadata (variable counts, etc.)
        step_results: Results for individual sub-steps
    """

    success: bool
    phase: str = "post"
    total_duration_seconds: float = 0.0
    output_files: List[Path] = field(default_factory=list)
    archived_files: List[Path] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    step_results: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Allow using result in boolean context."""
        return self.success

    def summary(self) -> str:
        """Return a human-readable summary of post-processing results."""
        lines = [
            f"Post-Processing ({self.phase}): {'SUCCESS' if self.success else 'FAILED'}",
            f"Duration: {self.total_duration_seconds:.1f}s",
            f"Output files: {len(self.output_files)}",
            f"Archived files: {len(self.archived_files)}",
        ]

        if self.step_results:
            lines.append("Steps:")
            for step_name, step_ok in self.step_results.items():
                status = "OK" if step_ok else "FAIL"
                lines.append(f"  {step_name}: {status}")

        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
            for err in self.errors[:5]:
                lines.append(f"  - {err}")

        if self.warnings:
            lines.append(f"Warnings: {len(self.warnings)}")
            for warn in self.warnings[:5]:
                lines.append(f"  - {warn}")

        return "\n".join(lines)


class BasePostProcessor(ABC):
    """
    Abstract base class for model post-processors.

    All model-specific post-processors (SCHISM, ROMS, FVCOM) inherit from
    this class and implement the required abstract methods. The run_all()
    method executes the full post-processing pipeline.

    Post-processing pipeline:
        1. validate_model_output() - Check raw model output exists/is valid
        2. extract_fields() - Extract 2D/3D fields from raw output
        3. extract_stations() - Extract station timeseries
        4. create_standard_netcdf() - Convert to CO-OPS standard NetCDF
        5. create_grib2() - Create GRIB2 output (if applicable)
        6. create_awips() - Create AWIPS-format output
        7. archive_outputs() - Copy products to COMOUT

    Attributes:
        config: OFS configuration object
        data_dir: Working directory (DATA)
        comout: Output archive directory (COMOUT)
        fix_dir: Static input files directory (FIXofs)
        exec_dir: Compiled executables directory (EXECnos/EXECstofs3d)
        ush_dir: Utility scripts directory (USHnos/USHstofs3d)
        ofs_name: OFS system name (e.g., "cbofs", "stofs_3d_atl")
        cycle: Cycle identifier (e.g., "t00z")
        pdy: Production date (YYYYMMDD)
    """

    def __init__(self, config: Any):
        """
        Initialize post-processor.

        Args:
            config: OFSConfig instance with model configuration
        """
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Resolve directory paths from config or environment
        self.data_dir = Path(
            os.environ.get("DATA", getattr(config, "DATA", "/tmp"))
        )
        self.comout = Path(
            os.environ.get("COMOUT", getattr(config, "COMOUT", "/tmp"))
        )
        self.fix_dir = Path(
            os.environ.get(
                "FIXofs",
                os.environ.get(
                    "FIXstofs3d",
                    getattr(getattr(config, "runtime", config), "fix_ofs", "/tmp"),
                ),
            )
        )
        self.exec_dir = Path(
            os.environ.get(
                "EXECnos",
                os.environ.get(
                    "EXECstofs3d",
                    getattr(getattr(config, "runtime", config), "exec_ofs", "/tmp"),
                ),
            )
        )
        self.ush_dir = Path(
            os.environ.get(
                "USHnos",
                os.environ.get(
                    "USHstofs3d",
                    getattr(getattr(config, "runtime", config), "ush_ofs", "/tmp"),
                ),
            )
        )

        # Job metadata
        self.ofs_name = os.environ.get(
            "RUN", os.environ.get("OFS", getattr(config, "RUN", "unknown"))
        )
        self.cycle = os.environ.get("cycle", getattr(config, "cycle", "t00z"))
        self.pdy = os.environ.get(
            "PDY", getattr(config, "PDY", datetime.now().strftime("%Y%m%d"))
        )
        self.prefixnos = os.environ.get("PREFIXNOS", self.ofs_name)

    @abstractmethod
    def validate_model_output(self) -> Tuple[bool, List[str]]:
        """
        Validate that required model output files exist and are readable.

        Returns:
            Tuple of (is_valid, list_of_missing_or_invalid_files)
        """
        pass

    @abstractmethod
    def extract_fields(self) -> PostResult:
        """
        Extract 2D and 3D fields from raw model output.

        Extracts variables such as water level, velocity, temperature,
        salinity from native model output format. Adds CF-compliant
        variable attributes.

        Returns:
            PostResult with list of extracted field files
        """
        pass

    @abstractmethod
    def extract_stations(self) -> PostResult:
        """
        Extract station timeseries from model output.

        Reads station output (staout for SCHISM, station files for ROMS/FVCOM)
        and creates timeseries NetCDF or ASCII files at standard 6-minute
        intervals for CO-OPS reporting.

        Returns:
            PostResult with list of station timeseries files
        """
        pass

    @abstractmethod
    def create_standard_netcdf(self) -> PostResult:
        """
        Convert extracted fields to CO-OPS standard NetCDF format.

        Applies CF-1.6 conventions, standard variable names, coordinate
        reference system metadata, and quality flags. This is the primary
        dissemination format for NOS OFS products.

        Returns:
            PostResult with list of standard NetCDF files
        """
        pass

    def create_grib2(self) -> PostResult:
        """
        Create GRIB2 output for AWIPS dissemination.

        Default implementation returns success with a warning that GRIB2
        is not implemented for this model type. Model-specific subclasses
        can override this method.

        Returns:
            PostResult indicating GRIB2 creation status
        """
        self.logger.info("GRIB2 creation not implemented for this model type")
        return PostResult(
            success=True,
            phase="create_grib2",
            warnings=["GRIB2 creation not implemented; skipping"],
        )

    def create_awips(self) -> PostResult:
        """
        Create AWIPS-format output (SHEF bulletins, etc.).

        Default implementation returns success with a warning that AWIPS
        format is not implemented for this model type. Model-specific
        subclasses can override this method.

        Returns:
            PostResult indicating AWIPS creation status
        """
        self.logger.info("AWIPS format creation not implemented for this model type")
        return PostResult(
            success=True,
            phase="create_awips",
            warnings=["AWIPS format creation not implemented; skipping"],
        )

    @abstractmethod
    def archive_outputs(self) -> PostResult:
        """
        Copy final post-processed products to COMOUT for dissemination.

        This includes all standard NetCDF files, GRIB2 files, SHEF bulletins,
        GeoPackage files, and any other products required by downstream
        consumers (AWIPS, CO-OPS dashboard, nowCOAST).

        Returns:
            PostResult with list of archived files
        """
        pass

    def run_all(self, fail_fast: bool = True) -> PostResult:
        """
        Execute the full post-processing pipeline.

        Runs all post-processing steps in sequence:
        1. validate_model_output
        2. extract_fields
        3. extract_stations
        4. create_standard_netcdf
        5. create_grib2
        6. create_awips
        7. archive_outputs

        Args:
            fail_fast: If True, stop on first failure. If False, continue
                      and collect all errors.

        Returns:
            PostResult with overall post-processing status
        """
        self.logger.info(
            f"Starting post-processing pipeline for {self.ofs_name} "
            f"({self.__class__.__name__})"
        )

        start_time = time.time()

        all_output_files = []
        all_archived_files = []
        all_errors = []
        all_warnings = []
        step_results = {}
        overall_success = True

        # Step 0: Validate model output
        self.logger.info("Step 0/6: Validating model output")
        try:
            is_valid, missing = self.validate_model_output()
            step_results["validate_model_output"] = is_valid
            if not is_valid:
                msg = f"Model output validation failed: {', '.join(missing[:5])}"
                all_errors.append(msg)
                self.logger.error(msg)
                if fail_fast:
                    return PostResult(
                        success=False,
                        phase="post",
                        total_duration_seconds=time.time() - start_time,
                        errors=all_errors,
                        step_results=step_results,
                    )
                overall_success = False
        except Exception as e:
            step_results["validate_model_output"] = False
            all_errors.append(f"validate_model_output: {e}")
            self.logger.exception(f"Validation raised exception: {e}")
            if fail_fast:
                return PostResult(
                    success=False,
                    phase="post",
                    total_duration_seconds=time.time() - start_time,
                    errors=all_errors,
                    step_results=step_results,
                )
            overall_success = False

        # Processing steps
        steps = [
            ("extract_fields", self.extract_fields),
            ("extract_stations", self.extract_stations),
            ("create_standard_netcdf", self.create_standard_netcdf),
            ("create_grib2", self.create_grib2),
            ("create_awips", self.create_awips),
            ("archive_outputs", self.archive_outputs),
        ]

        for step_name, step_func in steps:
            self.logger.info(
                f"Step {list(dict(steps).keys()).index(step_name) + 1}/6: {step_name}"
            )
            try:
                result = step_func()
                step_results[step_name] = result.success

                if result.output_files:
                    all_output_files.extend(result.output_files)
                if result.archived_files:
                    all_archived_files.extend(result.archived_files)
                if result.warnings:
                    all_warnings.extend(result.warnings)

                if not result.success:
                    overall_success = False
                    all_errors.extend(result.errors)
                    self.logger.error(f"Step {step_name} failed")
                    if fail_fast:
                        break
                else:
                    self.logger.info(f"Step {step_name} completed successfully")

            except Exception as e:
                step_results[step_name] = False
                all_errors.append(f"{step_name}: {e}")
                self.logger.exception(f"Step {step_name} raised exception: {e}")
                overall_success = False
                if fail_fast:
                    break

        total_duration = time.time() - start_time

        result = PostResult(
            success=overall_success,
            phase="post",
            total_duration_seconds=total_duration,
            output_files=all_output_files,
            archived_files=all_archived_files,
            errors=all_errors,
            warnings=all_warnings,
            step_results=step_results,
        )

        if overall_success:
            self.logger.info(
                f"Post-processing completed successfully in {total_duration:.1f}s "
                f"({len(all_output_files)} output files, "
                f"{len(all_archived_files)} archived)"
            )
        else:
            self.logger.error(
                f"Post-processing failed after {total_duration:.1f}s "
                f"with {len(all_errors)} errors"
            )

        return result

    # ---------------------------------------------------------------
    # Helper methods shared across model types
    # ---------------------------------------------------------------

    def _run_subprocess(
        self,
        command: str,
        step_name: str,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        fatal: bool = True,
        timeout: int = 3600,
    ) -> Tuple[bool, str, str]:
        """
        Execute a shell command via subprocess.

        Args:
            command: Shell command to execute
            step_name: Name of the step (for logging)
            env: Additional environment variables (merged with os.environ)
            cwd: Working directory (defaults to self.data_dir)
            fatal: Whether failure should be logged at ERROR vs WARNING level
            timeout: Command timeout in seconds

        Returns:
            Tuple of (success, stdout, stderr)
        """
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        if cwd is None:
            cwd = self.data_dir

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

            success = result.returncode == 0
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            if success:
                self.logger.info(f"{step_name} completed successfully")
            else:
                level = logging.ERROR if fatal else logging.WARNING
                self.logger.log(
                    level,
                    f"{step_name} failed with return code {result.returncode}",
                )
                if stderr:
                    self.logger.log(level, f"stderr: {stderr[:500]}")

            return success, stdout, stderr

        except subprocess.TimeoutExpired:
            self.logger.error(f"{step_name} timed out after {timeout}s")
            return False, "", f"Timed out after {timeout}s"

        except Exception as e:
            self.logger.exception(f"{step_name} raised exception: {e}")
            return False, "", str(e)

    def _copy_to_comout(
        self,
        src: Path,
        dst_name: Optional[str] = None,
        permissions: int = 0o644,
    ) -> Optional[Path]:
        """
        Copy a file to the COMOUT directory.

        Args:
            src: Source file path
            dst_name: Destination filename (defaults to src.name)
            permissions: File permissions for the destination

        Returns:
            Path to archived file, or None if copy failed
        """
        if not src.exists():
            self.logger.warning(f"Source file does not exist: {src}")
            return None

        dst = self.comout / (dst_name or src.name)
        try:
            self.comout.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            os.chmod(str(dst), permissions)
            self.logger.debug(f"Archived: {src.name} -> {dst}")
            return dst
        except Exception as e:
            self.logger.error(f"Failed to copy {src} to {dst}: {e}")
            return None

    def _standard_output_name(
        self,
        variable: str,
        file_type: str = "fields",
        extension: str = ".nc",
    ) -> str:
        """
        Generate standard NOS OFS output filename.

        Format: {ofs_name}.{cycle}.{variable}.{file_type}{extension}
        Example: cbofs.t00z.water_level.fields.nc

        Args:
            variable: Variable name (e.g., "water_level", "temperature")
            file_type: File type descriptor (e.g., "fields", "stations")
            extension: File extension

        Returns:
            Standardized filename string
        """
        return f"{self.ofs_name}.{self.cycle}.{variable}.{file_type}{extension}"

    def _check_file_exists(
        self, filepath: Path, min_size_bytes: int = 0
    ) -> bool:
        """
        Check if a file exists and meets minimum size requirement.

        Args:
            filepath: Path to check
            min_size_bytes: Minimum file size in bytes (0 = just check exists)

        Returns:
            True if file exists and meets size requirement
        """
        if not filepath.exists():
            return False
        if min_size_bytes > 0 and filepath.stat().st_size < min_size_bytes:
            return False
        return True

    def _add_cf_global_attributes(
        self, ds: Any, title: str, summary: str
    ) -> Any:
        """
        Add CF-1.6 compliant global attributes to an xarray Dataset.

        Args:
            ds: xarray Dataset to update
            title: Dataset title
            summary: Dataset summary/abstract

        Returns:
            Updated xarray Dataset
        """
        ds.attrs.update(
            {
                "Conventions": "CF-1.6",
                "title": title,
                "summary": summary,
                "institution": "NOAA/NOS/CO-OPS",
                "source": f"NOS OFS {self.ofs_name.upper()}",
                "history": f"Created {datetime.utcnow().isoformat()}Z by nos_ofs postprocessing",
                "references": "https://tidesandcurrents.noaa.gov/ofs/",
                "model_type": self._get_model_type(),
                "ofs_name": self.ofs_name,
                "cycle": self.cycle,
                "production_date": self.pdy,
            }
        )
        return ds

    def _get_model_type(self) -> str:
        """Return the model type string for this processor."""
        return "unknown"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"ofs={self.ofs_name}, cycle={self.cycle}, pdy={self.pdy})"
        )
