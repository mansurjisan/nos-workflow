"""
Fortran Executable Wrappers for NOS-OFS  (LEGACY / DEPRECATED)

.. deprecated:: 1.0
    This module is retained **only** as a legacy fallback for environments
    where the native Python forcing processors cannot be used (e.g., a
    missing scipy or netCDF4 installation on a production HPC node).

    **All new code should use the native Python processors instead:**

    - ``RTOFSProcessor``   (``forcing/rtofs.py``)  -- replaces
      gen_3Dth_from_hycom, gen_nudge_from_hycom, and all NCO calls
    - ``TidalProcessor``   (``forcing/tidal.py``)  -- replaces
      stofs_3d_atl_tide_fac
    - ``NWMProcessor``     (``forcing/nwm.py``)    -- replaces
      gen_sourcesink.py subprocess call
    - ``ADTProcessor``     (``forcing/adt.py``)    -- replaces NCO-based
      ADT blending

    If you find yourself needing this module, please open a GitHub issue
    so the native Python path can be extended to cover your use case.

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
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)

# Issue a deprecation warning at import time so users are aware.
warnings.warn(
    "nos_ofs.forcing.fortran_wrapper is DEPRECATED.  "
    "Use the native Python forcing processors (rtofs, tidal, nwm, adt) "
    "instead.  This module will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)


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

    .. deprecated:: 1.0
        Use the native Python forcing processors instead.

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
        warnings.warn(
            "FortranWrapper is deprecated.  Use native Python processors.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.exec_dir = self._find_exec_dir(exec_dir)
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        self.env = os.environ.copy()
        if env:
            self.env.update(env)

    def _find_exec_dir(self, exec_dir: Optional[Path]) -> Path:
        if exec_dir and Path(exec_dir).exists():
            return Path(exec_dir)
        if os.environ.get("EXECnos"):
            return Path(os.environ["EXECnos"])
        search_paths = [
            Path(os.environ.get("HOMEnos", "")) / "exec",
            Path("/lfs/h1/nos/nosofs/noscrub/packages/nosofs.v3.7.0/exec"),
            Path.cwd() / "exec",
        ]
        for path in search_paths:
            if path.exists():
                return path
        log.warning("EXECnos directory not found, using current directory")
        return Path.cwd()

    def _check_executable(self, name: str) -> Path:
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
        with open(ctl_path, "w") as f:
            for line in lines:
                f.write(f"{line}\n")
        log.debug("Created control file: %s", ctl_path)

    def _run_executable(
        self,
        exe_name: str,
        ctl_file: Path,
        log_file: Optional[Path] = None,
        timeout: int = 1800,
    ) -> FortranResult:
        exe_path = self._check_executable(exe_name)

        log.info("[LEGACY] Running %s", exe_name)
        log.debug("  Executable: %s", exe_path)
        log.debug("  Control file: %s", ctl_file)

        try:
            with open(ctl_file, "r") as ctl_input:
                result = subprocess.run(
                    [str(exe_path)],
                    stdin=ctl_input,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(self.work_dir),
                    env=self.env,
                )

            if log_file:
                with open(log_file, "w") as f:
                    f.write(result.stdout)
                    if result.stderr:
                        f.write("\n--- STDERR ---\n")
                        f.write(result.stderr)

            success = result.returncode == 0
            if "COMPLETED SUCCESSFULLY" in result.stdout:
                success = True

            if success:
                log.info("[LEGACY] %s completed successfully", exe_name)
            else:
                log.warning(
                    "[LEGACY] %s failed with return code %d",
                    exe_name,
                    result.returncode,
                )
                if result.stderr:
                    log.warning("STDERR: %s", result.stderr[:500])

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
            log.error("[LEGACY] %s timed out after %d seconds", exe_name, timeout)
            return FortranResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=f"Timeout after {timeout} seconds",
                output_files=[],
                control_file=ctl_file,
            )
        except Exception as e:
            log.error("[LEGACY] %s failed: %s", exe_name, e)
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
    DEPRECATED -- Wrapper for nos_ofs_met_file_search executable.
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
        input_file = self.work_dir / "met_files_available.dat"
        with open(input_file, "w") as f:
            for fpath in available_files:
                f.write(f"{fpath}\n")

        ctl_file = self.work_dir / "Fortran_file_search.ctl"
        self._write_control_file(
            ctl_file,
            [time_start, time_nowcast_end, time_end, str(input_file), output_file],
        )

        log_file = self.work_dir / "Fortran_file_search.log"
        result = self._run_executable(self.EXECUTABLE, ctl_file, log_file)

        output_path = self.work_dir / output_file
        if output_path.exists():
            result.output_files.append(output_path)

        return result

    def get_filtered_files(self, result: FortranResult) -> List[str]:
        if not result.success or not result.output_files:
            return []
        files = []
        output_file = result.output_files[0]
        if output_file.exists():
            with open(output_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        files.append(line)
        return files


class MetForcingWrapper(FortranWrapper):
    """DEPRECATED -- Wrapper for nos_ofs_create_forcing_met executable."""

    EXECUTABLE = "nos_ofs_create_forcing_met"
    EXECUTABLE_FVCOM = "nos_ofs_create_forcing_met_fvcom"

    def __init__(self, model_type: str = "SCHISM", **kwargs):
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
        if self.model_type == "FVCOM":
            exe_name = self.EXECUTABLE_FVCOM
        else:
            exe_name = self.EXECUTABLE

        lines = [dbase, runtype, time_start, time_end, grid_file, output_prefix, str(len(met_files))]
        lines.extend(met_files)
        for key, value in params.items():
            lines.append(f"{key}={value}")

        ctl_file = self.work_dir / "Fortran_met.ctl"
        self._write_control_file(ctl_file, lines)

        log_file = self.work_dir / f"{dbase}_Fortran.log"
        result = self._run_executable(exe_name, ctl_file, log_file)

        for f in self.work_dir.glob(f"{output_prefix}*.nc"):
            result.output_files.append(f)

        return result


class RiverForcingWrapper(FortranWrapper):
    """DEPRECATED -- Wrapper for nos_ofs_create_forcing_river executable."""

    EXECUTABLE = "nos_ofs_create_forcing_river"

    def create_forcing(
        self,
        river_ctl_file: str,
        time_start: str,
        time_end: str,
        river_source: str = "NWM",
        **params,
    ) -> FortranResult:
        ctl_file = self.work_dir / "Fortran_river.ctl"
        ctl_lines = [river_ctl_file, time_start, time_end, river_source]
        for key, value in params.items():
            ctl_lines.append(f"{value}")
        self._write_control_file(ctl_file, ctl_lines)

        log_file = self.work_dir / "river_Fortran.log"
        return self._run_executable(self.EXECUTABLE, ctl_file, log_file)


class OBCForcingWrapper(FortranWrapper):
    """DEPRECATED -- Wrapper for nos_ofs_create_forcing_obc executables."""

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
        exe_name = self.EXECUTABLES.get(self.model_type, self.EXECUTABLES["SCHISM"])
        ctl_file = self.work_dir / "Fortran_obc.ctl"
        ctl_lines = [obc_ctl_file, time_start, time_end, obc_source]
        for key, value in params.items():
            ctl_lines.append(f"{value}")
        self._write_control_file(ctl_file, ctl_lines)

        log_file = self.work_dir / "obc_Fortran.log"
        return self._run_executable(exe_name, ctl_file, log_file)


class TidalForcingWrapper(FortranWrapper):
    """
    DEPRECATED -- Wrapper for tidal forcing executables.

    Use ``TidalProcessor`` (``forcing/tidal.py``) which implements native
    Python nodal factor computation instead.
    """

    def create_tidal_forcing(
        self,
        bctides_template: str,
        time_ref: str,
        constituents: List[str],
        **params,
    ) -> FortranResult:
        ctl_file = self.work_dir / "Fortran_tides.ctl"
        ctl_lines = [bctides_template, time_ref, str(len(constituents))]
        ctl_lines.extend(constituents)
        self._write_control_file(ctl_file, ctl_lines)

        log_file = self.work_dir / "tides_Fortran.log"
        return self._run_executable(
            "nos_ofs_create_forcing_obc_tides", ctl_file, log_file
        )

    def calculate_nodal_factors(
        self,
        year: int,
        month: int = 1,
        day: int = 1,
    ) -> FortranResult:
        ctl_file = self.work_dir / "Fortran_tide_fac.ctl"
        self._write_control_file(ctl_file, [str(year), str(month), str(day)])

        log_file = self.work_dir / "tide_fac_Fortran.log"
        return self._run_executable(
            "nos_ofs_create_tide_fac_schism", ctl_file, log_file
        )

    def adjust_tides(
        self,
        hc_file: str,
        output_file: str,
        year: int,
        apply_nodal: int = 1,
    ) -> FortranResult:
        ctl_file = self.work_dir / "Fortran_Modeltide.ctl"
        self._write_control_file(
            ctl_file, [hc_file, output_file, str(year), str(apply_nodal)]
        )

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
    DEPRECATED -- Get all Fortran wrappers for an OFS system.

    Use the native Python forcing processors instead.
    """
    warnings.warn(
        "get_fortran_wrappers() is deprecated.  "
        "Use native Python processors (RTOFSProcessor, TidalProcessor, etc.)",
        DeprecationWarning,
        stacklevel=2,
    )
    kwargs: Dict[str, Any] = {"exec_dir": exec_dir, "work_dir": work_dir}

    return {
        "met_search": MetFileSearchWrapper(**kwargs),
        "met_forcing": MetForcingWrapper(model_type=model_type, **kwargs),
        "river": RiverForcingWrapper(**kwargs),
        "obc": OBCForcingWrapper(model_type=model_type, **kwargs),
        "tidal": TidalForcingWrapper(**kwargs),
    }
