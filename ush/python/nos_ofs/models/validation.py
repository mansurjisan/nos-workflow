"""
Validation Utilities for STOFS 3D Atlantic

Provides validation functions to check:
- Input file existence and formats
- Output file correctness
- Configuration completeness
- Runtime environment requirements
"""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a validation check."""

    valid: bool
    name: str
    message: str
    details: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Complete validation report."""

    timestamp: str
    system: str
    results: List[ValidationResult] = field(default_factory=list)

    @property
    def all_valid(self) -> bool:
        """Check if all validations passed."""
        return all(r.valid for r in self.results)

    @property
    def error_count(self) -> int:
        """Count of failed validations."""
        return sum(1 for r in self.results if not r.valid)

    @property
    def warning_count(self) -> int:
        """Count of warnings."""
        return sum(len(r.warnings) for r in self.results)

    def summary(self) -> str:
        """Generate summary string."""
        status = "PASSED" if self.all_valid else "FAILED"
        return (
            f"Validation Report: {status}\n"
            f"System: {self.system}\n"
            f"Time: {self.timestamp}\n"
            f"Checks: {len(self.results)} total, {self.error_count} failed\n"
            f"Warnings: {self.warning_count}"
        )

    def detailed_report(self) -> str:
        """Generate detailed report string."""
        lines = [self.summary(), "", "=" * 60, ""]

        for result in self.results:
            status = "PASS" if result.valid else "FAIL"
            lines.append(f"[{status}] {result.name}")
            lines.append(f"       {result.message}")

            for detail in result.details:
                lines.append(f"       - {detail}")

            for warning in result.warnings:
                lines.append(f"       WARNING: {warning}")

            lines.append("")

        return "\n".join(lines)


class InputValidator:
    """Validates input files and directories for STOFS workflow."""

    def __init__(self, config):
        """
        Initialize validator with configuration.

        Args:
            config: StofsConfig instance
        """
        self.config = config

    def validate_all(self) -> ValidationReport:
        """
        Run all input validations.

        Returns:
            ValidationReport with all results
        """
        report = ValidationReport(
            timestamp=datetime.now().isoformat(),
            system=self.config.RUN,
        )

        # Directory validations
        report.results.append(self.validate_directories())

        # Grid file validations
        report.results.append(self.validate_grid_files())

        # Forcing input validations
        if self.config.gfs_enabled:
            report.results.append(self.validate_gfs_input())

        if self.config.hrrr_enabled:
            report.results.append(self.validate_hrrr_input())

        if self.config.nwm_enabled:
            report.results.append(self.validate_nwm_input())

        if self.config.rtofs_enabled:
            report.results.append(self.validate_rtofs_input())

        # Environment validations
        report.results.append(self.validate_environment())

        # Tool validations
        report.results.append(self.validate_tools())

        return report

    def validate_directories(self) -> ValidationResult:
        """Validate required directories exist."""
        required_dirs = {
            "FIXstofs3d": self.config.FIXstofs3d,
            "EXECstofs3d": self.config.EXECstofs3d,
            "DATA": self.config.DATA or self.config.get_data_dir(),
        }

        missing = []
        details = []

        for name, path in required_dirs.items():
            if not path:
                missing.append(f"{name}: not set")
            elif not Path(path).exists():
                missing.append(f"{name}: {path}")
            else:
                details.append(f"{name}: {path} OK")

        if missing:
            return ValidationResult(
                valid=False,
                name="Directory Check",
                message=f"Missing {len(missing)} directories",
                details=missing,
            )

        return ValidationResult(
            valid=True,
            name="Directory Check",
            message="All required directories exist",
            details=details,
        )

    def validate_grid_files(self) -> ValidationResult:
        """Validate SCHISM grid files exist."""
        grid_files = {
            "hgrid.gr3": self.config.grid_horizontal,
            "vgrid.in": self.config.grid_vertical,
        }

        missing = []
        details = []
        warnings = []

        for name, filename in grid_files.items():
            path = self.config.get_fix_file(filename)
            if path.exists():
                size_mb = path.stat().st_size / (1024 * 1024)
                details.append(f"{name}: {path.name} ({size_mb:.1f} MB)")

                # Warn if hgrid seems too small
                if name == "hgrid.gr3" and size_mb < 10:
                    warnings.append(f"{name} is small ({size_mb:.1f} MB) - verify correct file")
            else:
                missing.append(f"{name}: {path}")

        if missing:
            return ValidationResult(
                valid=False,
                name="Grid File Check",
                message=f"Missing {len(missing)} grid files",
                details=missing,
                warnings=warnings,
            )

        return ValidationResult(
            valid=True,
            name="Grid File Check",
            message="All grid files found",
            details=details,
            warnings=warnings,
        )

    def validate_gfs_input(self) -> ValidationResult:
        """Validate GFS input files."""
        gfs_path = self.config.get_forcing_path("gfs")

        if not gfs_path or not gfs_path.exists():
            return ValidationResult(
                valid=False,
                name="GFS Input Check",
                message=f"GFS input path not found: {gfs_path}",
            )

        # Look for GFS files
        patterns = [
            f"gfs.t{self.config.cyc:02d}z.pgrb2.0p25.f*.grib2",
            f"gfs.t{self.config.cyc:02d}z.pgrb2.0p25.f*",
            "*.grib2",
        ]

        found_files = []
        for pattern in patterns:
            found = list(gfs_path.glob(pattern))
            if found:
                found_files = found
                break

        if not found_files:
            return ValidationResult(
                valid=False,
                name="GFS Input Check",
                message="No GFS files found",
                details=[f"Searched: {gfs_path}"],
            )

        # Check forecast hour coverage
        fhrs = self._extract_forecast_hours(found_files, "gfs")
        details = [
            f"Found {len(found_files)} GFS files",
            f"Forecast hours: {min(fhrs) if fhrs else 0} - {max(fhrs) if fhrs else 0}",
        ]

        warnings = []
        if fhrs and max(fhrs) < 48:
            warnings.append(f"Limited forecast coverage: max fhr={max(fhrs)}")

        return ValidationResult(
            valid=True,
            name="GFS Input Check",
            message=f"GFS data available ({len(found_files)} files)",
            details=details,
            warnings=warnings,
        )

    def validate_hrrr_input(self) -> ValidationResult:
        """Validate HRRR input files."""
        hrrr_path = self.config.get_forcing_path("hrrr")

        if not hrrr_path or not hrrr_path.exists():
            # HRRR is optional
            return ValidationResult(
                valid=True,
                name="HRRR Input Check",
                message="HRRR input path not found (optional)",
                warnings=["HRRR not available - will use GFS only"],
            )

        # Look for HRRR files
        pattern = f"hrrr.t{self.config.cyc:02d}z.wrfsfcf*.grib2"
        found_files = list(hrrr_path.glob(pattern))

        if not found_files:
            return ValidationResult(
                valid=True,
                name="HRRR Input Check",
                message="No HRRR files found (optional)",
                warnings=["HRRR not available - will use GFS only"],
            )

        return ValidationResult(
            valid=True,
            name="HRRR Input Check",
            message=f"HRRR data available ({len(found_files)} files)",
        )

    def validate_nwm_input(self) -> ValidationResult:
        """Validate NWM input files."""
        nwm_path = self.config.get_forcing_path("nwm")

        if not nwm_path or not nwm_path.exists():
            return ValidationResult(
                valid=False,
                name="NWM Input Check",
                message=f"NWM input path not found: {nwm_path}",
            )

        # Look for NWM files
        patterns = [
            f"nwm.t{self.config.cyc:02d}z.*.channel_rt*.nc",
            "*channel_rt*.nc",
        ]

        found_files = []
        for pattern in patterns:
            found = list(nwm_path.glob(pattern))
            if found:
                found_files = found
                break

        if not found_files:
            return ValidationResult(
                valid=False,
                name="NWM Input Check",
                message="No NWM files found",
                details=[f"Searched: {nwm_path}"],
            )

        return ValidationResult(
            valid=True,
            name="NWM Input Check",
            message=f"NWM data available ({len(found_files)} files)",
        )

    def validate_rtofs_input(self) -> ValidationResult:
        """Validate RTOFS input files."""
        rtofs_path = self.config.get_forcing_path("rtofs")

        if not rtofs_path or not rtofs_path.exists():
            return ValidationResult(
                valid=False,
                name="RTOFS Input Check",
                message=f"RTOFS input path not found: {rtofs_path}",
            )

        # Look for RTOFS files
        patterns = [
            "rtofs_glo_2ds_*.nc",
            "rtofs_glo_3dz_*.nc",
            "*.nc",
        ]

        found_2d = []
        found_3d = []

        for f in rtofs_path.glob("*.nc"):
            if "2ds" in f.name:
                found_2d.append(f)
            elif "3dz" in f.name:
                found_3d.append(f)

        if not found_2d and not found_3d:
            return ValidationResult(
                valid=False,
                name="RTOFS Input Check",
                message="No RTOFS files found",
                details=[f"Searched: {rtofs_path}"],
            )

        details = [
            f"2D files: {len(found_2d)}",
            f"3D files: {len(found_3d)}",
        ]

        warnings = []
        if not found_3d:
            warnings.append("No 3D files - T/S nudging may not work")

        return ValidationResult(
            valid=True,
            name="RTOFS Input Check",
            message=f"RTOFS data available",
            details=details,
            warnings=warnings,
        )

    def validate_environment(self) -> ValidationResult:
        """Validate environment variables."""
        required_vars = ["PDY", "cyc", "RUN"]
        recommended_vars = ["COMOUT", "COMIN", "DATA"]

        missing_required = []
        missing_recommended = []
        details = []

        for var in required_vars:
            value = os.environ.get(var)
            if not value:
                missing_required.append(var)
            else:
                details.append(f"{var}={value}")

        for var in recommended_vars:
            if not os.environ.get(var):
                missing_recommended.append(var)

        warnings = []
        if missing_recommended:
            warnings.append(f"Recommended vars not set: {', '.join(missing_recommended)}")

        if missing_required:
            return ValidationResult(
                valid=False,
                name="Environment Check",
                message=f"Missing required variables: {', '.join(missing_required)}",
                details=details,
            )

        return ValidationResult(
            valid=True,
            name="Environment Check",
            message="Required environment variables set",
            details=details,
            warnings=warnings,
        )

    def validate_tools(self) -> ValidationResult:
        """Validate required tools are available."""
        required_tools = ["mpiexec"]
        optional_tools = ["wgrib2", "cnvgrib", "ncks"]

        missing_required = []
        missing_optional = []
        details = []

        for tool in required_tools:
            if self._check_tool(tool):
                details.append(f"{tool}: available")
            else:
                missing_required.append(tool)

        for tool in optional_tools:
            if not self._check_tool(tool):
                missing_optional.append(tool)

        warnings = []
        if missing_optional:
            warnings.append(f"Optional tools not found: {', '.join(missing_optional)}")

        if missing_required:
            return ValidationResult(
                valid=False,
                name="Tools Check",
                message=f"Missing required tools: {', '.join(missing_required)}",
                details=details,
            )

        return ValidationResult(
            valid=True,
            name="Tools Check",
            message="Required tools available",
            details=details,
            warnings=warnings,
        )

    def _check_tool(self, tool_name: str) -> bool:
        """Check if a tool is available in PATH."""
        try:
            result = subprocess.run(
                ["which", tool_name],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _extract_forecast_hours(self, files: List[Path], source: str) -> List[int]:
        """Extract forecast hours from filenames."""
        fhrs = []
        for f in files:
            try:
                if source == "gfs":
                    # gfs.t12z.pgrb2.0p25.f048
                    if ".f" in f.name:
                        fhr = int(f.name.split(".f")[-1].split(".")[0])
                        fhrs.append(fhr)
            except (ValueError, IndexError):
                continue
        return sorted(set(fhrs))


class OutputValidator:
    """Validates output files from STOFS workflow."""

    def __init__(self, config):
        """
        Initialize validator with configuration.

        Args:
            config: StofsConfig instance
        """
        self.config = config

    def validate_prep_outputs(self, data_dir: Path) -> ValidationReport:
        """Validate preprocessing stage outputs."""
        report = ValidationReport(
            timestamp=datetime.now().isoformat(),
            system=f"{self.config.RUN}_prep",
        )

        # Check sflux files
        report.results.append(self._validate_sflux_files(data_dir))

        # Check river forcing files
        report.results.append(self._validate_river_files(data_dir))

        # Check boundary files
        report.results.append(self._validate_boundary_files(data_dir))

        # Check bctides.in
        report.results.append(self._validate_bctides(data_dir))

        return report

    def validate_model_outputs(self, data_dir: Path) -> ValidationReport:
        """Validate model run outputs."""
        report = ValidationReport(
            timestamp=datetime.now().isoformat(),
            system=f"{self.config.RUN}_model",
        )

        outputs_dir = data_dir / "outputs"

        # Check for completion
        report.results.append(self._validate_completion(outputs_dir))

        # Check output files
        report.results.append(self._validate_output_files(outputs_dir))

        # Check restart
        report.results.append(self._validate_restart(outputs_dir))

        return report

    def _validate_sflux_files(self, data_dir: Path) -> ValidationResult:
        """Validate sflux NetCDF files."""
        sflux_dir = data_dir / "sflux"

        if not sflux_dir.exists():
            return ValidationResult(
                valid=False,
                name="Sflux Files",
                message="Sflux directory not found",
            )

        required_patterns = ["sflux_air_1*.nc"]
        optional_patterns = ["sflux_air_2*.nc", "sflux_rad_1*.nc", "sflux_prc_1*.nc"]

        missing_required = []
        found = []

        for pattern in required_patterns:
            files = list(sflux_dir.glob(pattern))
            if files:
                found.extend(files)
            else:
                missing_required.append(pattern)

        for pattern in optional_patterns:
            files = list(sflux_dir.glob(pattern))
            found.extend(files)

        if missing_required:
            return ValidationResult(
                valid=False,
                name="Sflux Files",
                message=f"Missing required sflux files",
                details=[f"Missing: {p}" for p in missing_required],
            )

        details = [f"Found {len(found)} sflux files"]
        details.extend([f.name for f in found[:5]])
        if len(found) > 5:
            details.append(f"... and {len(found) - 5} more")

        return ValidationResult(
            valid=True,
            name="Sflux Files",
            message=f"Sflux files present ({len(found)} files)",
            details=details,
        )

    def _validate_river_files(self, data_dir: Path) -> ValidationResult:
        """Validate river forcing files."""
        required_files = ["vsource.th", "msource.th", "source_sink.in"]

        missing = []
        details = []

        for filename in required_files:
            path = data_dir / filename
            if path.exists():
                size = path.stat().st_size
                details.append(f"{filename}: {size} bytes")
            else:
                missing.append(filename)

        if missing:
            return ValidationResult(
                valid=False,
                name="River Files",
                message=f"Missing river forcing files",
                details=[f"Missing: {f}" for f in missing],
            )

        return ValidationResult(
            valid=True,
            name="River Files",
            message="River forcing files present",
            details=details,
        )

    def _validate_boundary_files(self, data_dir: Path) -> ValidationResult:
        """Validate ocean boundary condition files."""
        boundary_files = ["elev2D.th.nc", "TEM_3D.th.nc", "SAL_3D.th.nc", "uv3D.th.nc"]

        found = []
        missing = []

        for filename in boundary_files:
            path = data_dir / filename
            if path.exists():
                found.append(filename)
            else:
                missing.append(filename)

        if not found:
            return ValidationResult(
                valid=False,
                name="Boundary Files",
                message="No boundary condition files found",
                details=[f"Expected: {f}" for f in boundary_files],
            )

        warnings = []
        if missing:
            warnings.append(f"Some boundary files missing: {', '.join(missing)}")

        return ValidationResult(
            valid=True,
            name="Boundary Files",
            message=f"Found {len(found)}/{len(boundary_files)} boundary files",
            details=[f"Present: {f}" for f in found],
            warnings=warnings,
        )

    def _validate_bctides(self, data_dir: Path) -> ValidationResult:
        """Validate bctides.in file."""
        bctides_path = data_dir / "bctides.in"

        if not bctides_path.exists():
            return ValidationResult(
                valid=False,
                name="Bctides File",
                message="bctides.in not found",
            )

        # Check file has content
        content = bctides_path.read_text()
        lines = [l for l in content.split('\n') if l.strip() and not l.strip().startswith('!')]

        if len(lines) < 5:
            return ValidationResult(
                valid=False,
                name="Bctides File",
                message="bctides.in appears incomplete",
                details=[f"Only {len(lines)} non-comment lines"],
            )

        # Check for constituent names
        constituents_found = []
        for const in ["M2", "S2", "N2", "K1", "O1"]:
            if const in content:
                constituents_found.append(const)

        return ValidationResult(
            valid=True,
            name="Bctides File",
            message=f"bctides.in present with {len(constituents_found)} constituents",
            details=[f"Constituents: {', '.join(constituents_found)}"],
        )

    def _validate_completion(self, outputs_dir: Path) -> ValidationResult:
        """Validate model completed successfully."""
        mirror_file = outputs_dir / "mirror.out"

        if not mirror_file.exists():
            return ValidationResult(
                valid=False,
                name="Model Completion",
                message="mirror.out not found",
            )

        content = mirror_file.read_text()

        if "Run completed successfully" in content:
            return ValidationResult(
                valid=True,
                name="Model Completion",
                message="Model completed successfully",
            )

        return ValidationResult(
            valid=False,
            name="Model Completion",
            message="Model did not complete successfully",
            details=["Check mirror.out for errors"],
        )

    def _validate_output_files(self, outputs_dir: Path) -> ValidationResult:
        """Validate model output files exist."""
        if not outputs_dir.exists():
            return ValidationResult(
                valid=False,
                name="Output Files",
                message="Outputs directory not found",
            )

        # Check for 2D outputs
        out2d_files = list(outputs_dir.glob("out2d_*.nc"))

        # Check for 3D outputs
        temp_files = list(outputs_dir.glob("temperature_*.nc"))
        salt_files = list(outputs_dir.glob("salinity_*.nc"))

        total = len(out2d_files) + len(temp_files) + len(salt_files)

        if total == 0:
            return ValidationResult(
                valid=False,
                name="Output Files",
                message="No output NetCDF files found",
            )

        return ValidationResult(
            valid=True,
            name="Output Files",
            message=f"Found {total} output files",
            details=[
                f"2D files: {len(out2d_files)}",
                f"Temperature: {len(temp_files)}",
                f"Salinity: {len(salt_files)}",
            ],
        )

    def _validate_restart(self, outputs_dir: Path) -> ValidationResult:
        """Validate restart file was created."""
        hotstart_files = list(outputs_dir.glob("hotstart_it*.nc"))

        if not hotstart_files:
            return ValidationResult(
                valid=False,
                name="Restart File",
                message="No hotstart files found",
                warnings=["Next cycle may need cold start"],
            )

        latest = max(hotstart_files, key=lambda f: f.stat().st_mtime)
        size_gb = latest.stat().st_size / (1024**3)

        warnings = []
        if size_gb < 1:
            warnings.append(f"Restart file small ({size_gb:.2f} GB)")

        return ValidationResult(
            valid=True,
            name="Restart File",
            message=f"Restart file present ({size_gb:.2f} GB)",
            details=[f"Latest: {latest.name}"],
            warnings=warnings,
        )


def validate_inputs(config) -> ValidationReport:
    """
    Convenience function to validate all inputs.

    Args:
        config: StofsConfig instance

    Returns:
        ValidationReport
    """
    validator = InputValidator(config)
    return validator.validate_all()


def validate_outputs(config, data_dir: Path, stage: str = "prep") -> ValidationReport:
    """
    Convenience function to validate outputs.

    Args:
        config: StofsConfig instance
        data_dir: Data directory path
        stage: Stage name ('prep' or 'model')

    Returns:
        ValidationReport
    """
    validator = OutputValidator(config)

    if stage == "prep":
        return validator.validate_prep_outputs(data_dir)
    elif stage == "model":
        return validator.validate_model_outputs(data_dir)
    else:
        raise ValueError(f"Unknown stage: {stage}")
