"""
Fortran Executable Wrappers for NOS-OFS

This module provides Python wrappers around the production Fortran executables
used in nosofs.v3.7.0. This approach:
- Maintains compatibility with validated production code
- Allows gradual migration to pure Python implementations
- Enables side-by-side comparison of outputs

Wrapped executables:
- nos_ofs_met_file_search: Search for available met files in time window
- nos_ofs_create_forcing_met: Create meteorological forcing files
- nos_ofs_create_forcing_river: Create river forcing files
- nos_ofs_create_forcing_obc: Create ocean boundary conditions
- nos_ofs_create_forcing_obc_tides: Create tidal forcing
- nos_ofs_create_tide_fac_schism: Calculate tidal nodal factors
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)


@dataclass
class FortranResult:
    """Result from a Fortran executable call."""
    success: bool
    return_code: int
    stdout: str
    stderr: str
    output_files: List[Path]
    control_file: Optional[Path] = None
    log_file: Optional[Path] = None


class FortranExecutableNotFoundError(Exception):
    """Raised when a required Fortran executable is not found."""
    pass


class FortranWrapper:
    """
    Base wrapper class for NOS-OFS Fortran executables.

    Provides common functionality for:
    - Finding executables in EXECnos directory
    - Creating control files
    - Running executables with proper environment
    - Parsing output and logs
    """

    def __init__(
        self,
        exec_dir: Optional[Path] = None,
        work_dir: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize Fortran wrapper.

        Args:
            exec_dir: Path to executables directory (EXECnos)
            work_dir: Working directory for control files and output
            env: Additional environment variables
        """
        # Find executable directory
        self.exec_dir = self._find_exec_dir(exec_dir)
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        self.env = os.environ.copy()
        if env:
            self.env.update(env)

    def _find_exec_dir(self, exec_dir: Optional[Path]) -> Path:
        """Find the EXECnos directory."""
        if exec_dir and Path(exec_dir).exists():
            return Path(exec_dir)

        # Try environment variable
        if os.environ.get('EXECnos'):
            return Path(os.environ['EXECnos'])

        # Try common locations
        search_paths = [
            Path(os.environ.get('HOMEnos', '')) / 'exec',
            Path('/lfs/h1/nos/nosofs/noscrub/packages/nosofs.v3.7.0/exec'),
            Path.cwd() / 'exec',
        ]

        for path in search_paths:
            if path.exists():
                return path

        log.warning("EXECnos directory not found, using current directory")
        return Path.cwd()

    def _check_executable(self, name: str) -> Path:
        """Check if executable exists and is runnable."""
        exe_path = self.exec_dir / name
        if not exe_path.exists():
            raise FortranExecutableNotFoundError(
                f"Executable not found: {exe_path}\n"
                f"Set EXECnos environment variable or pass exec_dir parameter"
            )
        if not os.access(exe_path, os.X_OK):
            raise FortranExecutableNotFoundError(
                f"Executable not runnable: {exe_path}"
            )
        return exe_path

    def _write_control_file(self, ctl_path: Path, lines: List[str]) -> None:
        """Write a Fortran control file."""
        with open(ctl_path, 'w') as f:
            for line in lines:
                f.write(f"{line}\n")
        log.debug(f"Created control file: {ctl_path}")

    def _run_executable(
        self,
        exe_name: str,
        ctl_file: Path,
        log_file: Optional[Path] = None,
        timeout: int = 1800,
    ) -> FortranResult:
        """
        Run a Fortran executable with control file input.

        Args:
            exe_name: Name of executable (without path)
            ctl_file: Path to control file
            log_file: Path for stdout/log output
            timeout: Timeout in seconds (default 30 min)

        Returns:
            FortranResult with execution details
        """
        exe_path = self._check_executable(exe_name)

        log.info(f"Running {exe_name}")
        log.debug(f"  Executable: {exe_path}")
        log.debug(f"  Control file: {ctl_file}")

        try:
            with open(ctl_file, 'r') as ctl_input:
                result = subprocess.run(
                    [str(exe_path)],
                    stdin=ctl_input,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(self.work_dir),
                    env=self.env,
                )

            # Write log file if specified
            if log_file:
                with open(log_file, 'w') as f:
                    f.write(result.stdout)
                    if result.stderr:
                        f.write("\n--- STDERR ---\n")
                        f.write(result.stderr)

            # Check for success
            success = result.returncode == 0
            if "COMPLETED SUCCESSFULLY" in result.stdout:
                success = True

            if success:
                log.info(f"{exe_name} completed successfully")
            else:
                log.warning(f"{exe_name} failed with return code {result.returncode}")
                if result.stderr:
                    log.warning(f"STDERR: {result.stderr[:500]}")

            return FortranResult(
                success=success,
                return_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                output_files=[],
                control_file=ctl_file,
                log_file=log_file,
            )

        except subprocess.TimeoutExpired:
            log.error(f"{exe_name} timed out after {timeout} seconds")
            return FortranResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=f"Timeout after {timeout} seconds",
                output_files=[],
                control_file=ctl_file,
            )
        except Exception as e:
            log.error(f"{exe_name} failed: {e}")
            return FortranResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=str(e),
                output_files=[],
                control_file=ctl_file,
            )


class MetFileSearchWrapper(FortranWrapper):
    """
    Wrapper for nos_ofs_met_file_search executable.

    This executable searches for available meteorological files
    within a specified time window.

    Control file format (Fortran_file_search.ctl):
        TIME_START      # Start time (YYYYMMDDHH)
        TIME_NOWCAST_END  # Nowcast end time
        TIME_END        # Forecast end time
        INPUT_FILE      # File with list of available files
        OUTPUT_FILE     # Output file with filtered list
    """

    EXECUTABLE = "nos_ofs_met_file_search"

    def search(
        self,
        time_start: str,
        time_nowcast_end: str,
        time_end: str,
        available_files: List[str],
        output_file: str = "met_files.dat",
    ) -> FortranResult:
        """
        Search for available met files in time window.

        Args:
            time_start: Start time (YYYYMMDDHH format)
            time_nowcast_end: Nowcast end time (YYYYMMDDHH)
            time_end: Forecast end time (YYYYMMDDHH)
            available_files: List of available file paths
            output_file: Name of output file

        Returns:
            FortranResult with filtered file list
        """
        # Write input file list
        input_file = self.work_dir / "met_files_available.dat"
        with open(input_file, 'w') as f:
            for fpath in available_files:
                f.write(f"{fpath}\n")

        # Create control file
        ctl_file = self.work_dir / "Fortran_file_search.ctl"
        ctl_lines = [
            time_start,
            time_nowcast_end,
            time_end,
            str(input_file),
            output_file,
        ]
        self._write_control_file(ctl_file, ctl_lines)

        # Run executable
        log_file = self.work_dir / "Fortran_file_search.log"
        result = self._run_executable(self.EXECUTABLE, ctl_file, log_file)

        # Check for output file
        output_path = self.work_dir / output_file
        if output_path.exists():
            result.output_files.append(output_path)

        return result

    def get_filtered_files(self, result: FortranResult) -> List[str]:
        """Parse the output file to get filtered file list."""
        if not result.success or not result.output_files:
            return []

        files = []
        output_file = result.output_files[0]
        if output_file.exists():
            with open(output_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        files.append(line)
        return files


class MetForcingWrapper(FortranWrapper):
    """
    Wrapper for nos_ofs_create_forcing_met executable.

    Creates meteorological forcing files for ocean models by:
    - Reading GRIB2 data (via wgrib2 pre-processing)
    - Interpolating to model grid
    - Writing model-specific NetCDF output

    Control file format (Fortran_met.ctl):
        Multiple parameters depending on model type
    """

    EXECUTABLE = "nos_ofs_create_forcing_met"
    EXECUTABLE_FVCOM = "nos_ofs_create_forcing_met_fvcom"

    def __init__(self, model_type: str = "SCHISM", **kwargs):
        """
        Initialize met forcing wrapper.

        Args:
            model_type: Ocean model type (SCHISM, ROMS, FVCOM)
            **kwargs: Additional arguments for FortranWrapper
        """
        super().__init__(**kwargs)
        self.model_type = model_type.upper()

    def create_forcing(
        self,
        dbase: str,
        runtype: str,
        time_start: str,
        time_end: str,
        met_files: List[str],
        grid_file: str,
        output_prefix: str,
        **params,
    ) -> FortranResult:
        """
        Create meteorological forcing files.

        Args:
            dbase: Data source (GFS, HRRR, NAM, etc.)
            runtype: Run type (nowcast, forecast)
            time_start: Start time (YYYYMMDDHH)
            time_end: End time (YYYYMMDDHH)
            met_files: List of input met file paths
            grid_file: Model grid file path
            output_prefix: Prefix for output files
            **params: Additional model-specific parameters

        Returns:
            FortranResult with created forcing files
        """
        # Build control file based on model type
        if self.model_type == "FVCOM":
            exe_name = self.EXECUTABLE_FVCOM
            ctl_lines = self._build_fvcom_ctl(
                dbase, runtype, time_start, time_end,
                met_files, grid_file, output_prefix, **params
            )
        else:
            exe_name = self.EXECUTABLE
            ctl_lines = self._build_schism_ctl(
                dbase, runtype, time_start, time_end,
                met_files, grid_file, output_prefix, **params
            )

        # Write control file
        ctl_file = self.work_dir / "Fortran_met.ctl"
        self._write_control_file(ctl_file, ctl_lines)

        # Run executable
        log_file = self.work_dir / f"{dbase}_Fortran.log"
        result = self._run_executable(exe_name, ctl_file, log_file)

        # Find output files
        output_pattern = f"{output_prefix}*.nc"
        for f in self.work_dir.glob(output_pattern):
            result.output_files.append(f)

        return result

    def _build_schism_ctl(
        self,
        dbase: str,
        runtype: str,
        time_start: str,
        time_end: str,
        met_files: List[str],
        grid_file: str,
        output_prefix: str,
        **params,
    ) -> List[str]:
        """Build control file for SCHISM/ROMS."""
        lines = [
            dbase,
            runtype,
            time_start,
            time_end,
            grid_file,
            output_prefix,
            str(len(met_files)),
        ]
        lines.extend(met_files)

        # Add optional parameters
        for key, value in params.items():
            lines.append(f"{key}={value}")

        return lines

    def _build_fvcom_ctl(
        self,
        dbase: str,
        runtype: str,
        time_start: str,
        time_end: str,
        met_files: List[str],
        grid_file: str,
        output_prefix: str,
        **params,
    ) -> List[str]:
        """Build control file for FVCOM."""
        # FVCOM has different control file format
        lines = [
            dbase,
            runtype,
            time_start,
            time_end,
            grid_file,
            output_prefix,
            str(len(met_files)),
        ]
        lines.extend(met_files)

        return lines


class RiverForcingWrapper(FortranWrapper):
    """
    Wrapper for nos_ofs_create_forcing_river executable.

    Creates river forcing files from:
    - National Water Model (NWM) data
    - USGS gauge data (fallback)
    - Climatology (fallback)
    """

    EXECUTABLE = "nos_ofs_create_forcing_river"

    def create_forcing(
        self,
        river_ctl_file: str,
        time_start: str,
        time_end: str,
        river_source: str = "NWM",
        **params,
    ) -> FortranResult:
        """
        Create river forcing files.

        Args:
            river_ctl_file: River control file path
            time_start: Start time (YYYYMMDDHH)
            time_end: End time (YYYYMMDDHH)
            river_source: Data source (NWM, USGS, CLIM)
            **params: Additional parameters

        Returns:
            FortranResult with river forcing files
        """
        ctl_file = self.work_dir / "Fortran_river.ctl"
        ctl_lines = [
            river_ctl_file,
            time_start,
            time_end,
            river_source,
        ]
        for key, value in params.items():
            ctl_lines.append(f"{value}")

        self._write_control_file(ctl_file, ctl_lines)

        log_file = self.work_dir / "river_Fortran.log"
        result = self._run_executable(self.EXECUTABLE, ctl_file, log_file)

        return result


class OBCForcingWrapper(FortranWrapper):
    """
    Wrapper for nos_ofs_create_forcing_obc executables.

    Creates ocean boundary condition files from:
    - RTOFS (Real-Time Ocean Forecast System)
    - HYCOM
    - Climatology
    """

    EXECUTABLES = {
        "SCHISM": "nos_ofs_create_forcing_obc_schism",
        "SELFE": "nos_ofs_create_forcing_obc_selfe",
        "ROMS": "nos_ofs_create_forcing_obc",
        "FVCOM": "nos_ofs_create_forcing_obc_fvcom",
    }

    def __init__(self, model_type: str = "SCHISM", **kwargs):
        super().__init__(**kwargs)
        self.model_type = model_type.upper()

    def create_forcing(
        self,
        obc_ctl_file: str,
        time_start: str,
        time_end: str,
        obc_source: str = "RTOFS",
        **params,
    ) -> FortranResult:
        """
        Create ocean boundary condition files.

        Args:
            obc_ctl_file: OBC control file path
            time_start: Start time (YYYYMMDDHH)
            time_end: End time (YYYYMMDDHH)
            obc_source: Data source (RTOFS, HYCOM, CLIM)
            **params: Additional parameters

        Returns:
            FortranResult with OBC files
        """
        exe_name = self.EXECUTABLES.get(self.model_type, self.EXECUTABLES["SCHISM"])

        ctl_file = self.work_dir / "Fortran_obc.ctl"
        ctl_lines = [
            obc_ctl_file,
            time_start,
            time_end,
            obc_source,
        ]
        for key, value in params.items():
            ctl_lines.append(f"{value}")

        self._write_control_file(ctl_file, ctl_lines)

        log_file = self.work_dir / "obc_Fortran.log"
        result = self._run_executable(exe_name, ctl_file, log_file)

        return result


class TidalForcingWrapper(FortranWrapper):
    """
    Wrapper for tidal forcing executables.

    - nos_ofs_create_forcing_obc_tides: Create tidal boundary forcing
    - nos_ofs_create_tide_fac_schism: Calculate nodal factors
    - nos_ofs_adjust_tides: Adjust tidal constituents
    """

    def create_tidal_forcing(
        self,
        bctides_template: str,
        time_ref: str,
        constituents: List[str],
        **params,
    ) -> FortranResult:
        """
        Create tidal boundary forcing files.

        Args:
            bctides_template: Template bctides.in file
            time_ref: Reference time for nodal factors
            constituents: List of tidal constituents
            **params: Additional parameters

        Returns:
            FortranResult with tidal forcing files
        """
        ctl_file = self.work_dir / "Fortran_tides.ctl"
        ctl_lines = [
            bctides_template,
            time_ref,
            str(len(constituents)),
        ]
        ctl_lines.extend(constituents)

        self._write_control_file(ctl_file, ctl_lines)

        log_file = self.work_dir / "tides_Fortran.log"
        result = self._run_executable(
            "nos_ofs_create_forcing_obc_tides", ctl_file, log_file
        )

        return result

    def calculate_nodal_factors(
        self,
        year: int,
        month: int = 1,
        day: int = 1,
    ) -> FortranResult:
        """
        Calculate tidal nodal factors for a given date.

        Args:
            year: Year
            month: Month (default 1)
            day: Day (default 1)

        Returns:
            FortranResult with nodal factor output
        """
        ctl_file = self.work_dir / "Fortran_tide_fac.ctl"
        ctl_lines = [
            str(year),
            str(month),
            str(day),
        ]

        self._write_control_file(ctl_file, ctl_lines)

        log_file = self.work_dir / "tide_fac_Fortran.log"
        result = self._run_executable(
            "nos_ofs_create_tide_fac_schism", ctl_file, log_file
        )

        return result

    def adjust_tides(
        self,
        hc_file: str,
        output_file: str,
        year: int,
        apply_nodal: int = 1,
    ) -> FortranResult:
        """
        Adjust tidal harmonic constants with nodal factors.

        Args:
            hc_file: Input harmonic constants file
            output_file: Output adjusted file
            year: Year for nodal factor calculation
            apply_nodal: Flag to apply nodal factors (1=yes, 0=no)

        Returns:
            FortranResult with adjusted tidal file
        """
        ctl_file = self.work_dir / "Fortran_Modeltide.ctl"
        ctl_lines = [
            hc_file,
            output_file,
            str(year),
            str(apply_nodal),
        ]

        self._write_control_file(ctl_file, ctl_lines)

        log_file = self.work_dir / "Fortran_Modeltide.log"
        result = self._run_executable("nos_ofs_adjust_tides", ctl_file, log_file)

        if Path(output_file).exists():
            result.output_files.append(Path(output_file))

        return result


# Convenience function to get all wrappers for an OFS
def get_fortran_wrappers(
    model_type: str = "SCHISM",
    exec_dir: Optional[Path] = None,
    work_dir: Optional[Path] = None,
) -> Dict[str, FortranWrapper]:
    """
    Get all Fortran wrappers for an OFS system.

    Args:
        model_type: Ocean model type (SCHISM, ROMS, FVCOM)
        exec_dir: Path to executables directory
        work_dir: Working directory

    Returns:
        Dictionary of wrapper instances
    """
    kwargs = {"exec_dir": exec_dir, "work_dir": work_dir}

    return {
        "met_search": MetFileSearchWrapper(**kwargs),
        "met_forcing": MetForcingWrapper(model_type=model_type, **kwargs),
        "river": RiverForcingWrapper(**kwargs),
        "obc": OBCForcingWrapper(model_type=model_type, **kwargs),
        "tidal": TidalForcingWrapper(**kwargs),
    }
