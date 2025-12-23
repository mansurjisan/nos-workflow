"""
Legacy Shell Script Runner for STOFS Workflow

This module provides a wrapper to execute the original STOFS shell scripts
from the /ush directory. This allows the Python workflow package to use YAML
configuration while delegating actual processing to the proven legacy scripts.

Usage in YAML config:
    legacy:
      enabled: true
      ush_dir: "/path/to/STOFS/ush/stofs_3d_atl"
      scripts:
        river: true
        gfs: true
        hrrr: true
        obc: true

The runner sets up the required environment variables and calls the shell
scripts, capturing their output for logging.
"""

import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schism_config import StofsConfig

log = logging.getLogger(__name__)


class LegacyScriptRunner:
    """
    Runner for executing STOFS legacy shell scripts.

    This class wraps the original shell scripts and provides:
    - Environment variable setup from YAML config
    - Script execution with proper working directory
    - Output capture and logging
    - Error handling and status reporting
    """

    def __init__(self, config: StofsConfig, exec_dir: Optional[str] = None):
        """
        Initialize the legacy script runner.

        Args:
            config: StofsConfig instance with legacy settings
            exec_dir: Optional path to compiled executables (defaults to STOFS/exec/stofs_3d_atl)
        """
        self.config = config
        self.ush_dir = Path(config.legacy_ush_dir) if config.legacy_ush_dir else None
        self.pysh_dir = Path(config.legacy_pysh_dir) if config.legacy_pysh_dir else None
        self.fix_dir = Path(config.legacy_fix_dir) if config.legacy_fix_dir else None

        # Executable directory - defaults to STOFS/exec/stofs_3d_atl
        if exec_dir:
            self.exec_dir = Path(exec_dir)
        elif self.ush_dir:
            # Derive from ush_dir: ush/stofs_3d_atl -> exec/stofs_3d_atl
            self.exec_dir = self.ush_dir.parent.parent / "exec" / "stofs_3d_atl"
        else:
            self.exec_dir = None

        # Validate paths
        if not self.ush_dir or not self.ush_dir.exists():
            log.warning(f"Legacy USH directory not found: {self.ush_dir}")
        if not self.pysh_dir or not self.pysh_dir.exists():
            log.warning(f"Legacy pysh directory not found: {self.pysh_dir}")
        if not self.exec_dir or not self.exec_dir.exists():
            log.warning(f"Legacy EXEC directory not found: {self.exec_dir}")
        else:
            log.info(f"Using executables from: {self.exec_dir}")

    def setup_environment(self, work_dir: Path) -> Dict[str, str]:
        """
        Setup environment variables required by legacy scripts.

        Args:
            work_dir: Working directory for script execution

        Returns:
            Dictionary of environment variables
        """
        env = os.environ.copy()

        # Basic NCO variables
        env["RUN"] = self.config.RUN
        env["NET"] = self.config.NET
        env["PDY"] = self.config.PDY
        env["cyc"] = f"{self.config.cyc:02d}"
        env["cycle"] = self.config.cycle

        # NCO tools - set full paths for tools used by shell scripts
        # The scripts use $WGRIB2, $NCKS, etc. instead of calling tools directly
        for tool in ["wgrib2", "ncks", "ncap2", "ncrcat", "ncatted", "ncrename", "ncdump"]:
            tool_path = shutil.which(tool)
            if tool_path:
                env[tool.upper()] = tool_path

        # Add our bin directory to PATH for shim scripts (cpreq, etc.)
        bin_dir = Path(self.config.HOMEstofs) / "ush" / "stofs_3d_atl" / "bin"
        if bin_dir.exists():
            current_path = env.get("PATH", "")
            env["PATH"] = f"{bin_dir}:{current_path}"

        # Directory paths
        env["DATA"] = str(work_dir)
        env["HOMEstofs"] = self.config.HOMEstofs or str(work_dir.parent.parent.parent.parent)
        env["FIXstofs3d"] = str(self.fix_dir) if self.fix_dir else ""
        env["USHstofs3d"] = str(self.ush_dir) if self.ush_dir else ""
        env["PYstofs3d"] = str(self.pysh_dir) if self.pysh_dir else ""

        # Use our compiled executables if available, otherwise fallback to config
        if self.exec_dir and self.exec_dir.exists():
            env["EXECstofs3d"] = str(self.exec_dir)
        else:
            env["EXECstofs3d"] = self.config.EXECstofs3d

        # COM directories
        env["COMOUT"] = self.config.COMOUT or str(work_dir / "com")
        env["COMOUTrerun"] = self.config.COMOUTrerun or str(work_dir / "rerun")
        env["COMIN"] = self.config.COMIN or ""
        env["COMOUT_PREV"] = ""  # Previous cycle output (not available in test)

        # Forcing data paths - handle nested directory structures
        # GFS: may be in lfs/h1/ops/prod/com/gfs/v16.3/ subdirectory
        gfs_path = Path(self.config.COMINgfs) if self.config.COMINgfs else None
        if gfs_path and gfs_path.exists():
            # Check for nested lfs structure
            nested_gfs = list(gfs_path.glob("**/gfs.*/*/atmos"))
            if nested_gfs:
                # Found nested structure - use parent of gfs.YYYYMMDD
                env["COMINgfs"] = str(nested_gfs[0].parent.parent.parent)
            else:
                env["COMINgfs"] = self.config.COMINgfs
        else:
            env["COMINgfs"] = self.config.COMINgfs

        # HRRR: may be in lfs/h1/ops/prod/com/hrrr/v4.1/ subdirectory
        hrrr_path = Path(self.config.COMINhrrr) if self.config.COMINhrrr else None
        if hrrr_path and hrrr_path.exists():
            # Check for nested lfs structure
            nested_hrrr = list(hrrr_path.glob("**/hrrr.*/conus"))
            if nested_hrrr:
                # Found nested structure - use parent of hrrr.YYYYMMDD
                env["COMINhrrr"] = str(nested_hrrr[0].parent.parent)
            else:
                env["COMINhrrr"] = self.config.COMINhrrr
        else:
            env["COMINhrrr"] = self.config.COMINhrrr

        env["COMINnwm"] = self.config.COMINnwm
        env["COMINrtofs"] = self.config.COMINrtofs

        # ADT data path (for SSH correction in OBC)
        # Structure: ${COMINadt}/${yyyymmdd}/validation_data/marine/cmems/ssh/nrt_global_allsat_phy_l4_*.nc
        env["COMINadt"] = getattr(self.config, 'COMINadt', self.config.COMINrtofs)

        # DCOMROOT for St. Lawrence River data
        # Structure: ${DCOMROOT}/${yyyymmdd}/canadian_water/QC_02OA016_hourly_hydrometric.csv
        env["DCOMROOT"] = getattr(self.config, 'DCOMROOT', '')

        # Date/time variables used by scripts
        # PDYHH: Current cycle time (PDY + cyc)
        # PDYHH_FCAST_BEGIN: Start of forecast = PDYHH
        # PDYHH_NCAST_BEGIN: Start of nowcast = PDYHH - 24 hours (from ndate -24 PDYHH)
        #
        # This matches the Docker/shell logic:
        #   PDYHH=2025050412
        #   PDYHH_FCAST_BEGIN=2025050412
        #   PDYHH_NCAST_BEGIN=$(ndate -24 2025050412) = 2025050312
        fcast_start = datetime.strptime(self.config.PDY, "%Y%m%d") + timedelta(
            hours=self.config.cyc
        )
        ncast_start = fcast_start - timedelta(hours=24)

        pdyhh = fcast_start.strftime("%Y%m%d%H")
        fcast_end = fcast_start + timedelta(hours=72)  # 3-day forecast

        env["PDYHH"] = pdyhh
        env["PDYHH_FCAST_BEGIN"] = pdyhh
        env["PDYHH_FCAST_END"] = fcast_end.strftime("%Y%m%d%H")
        env["PDYHH_NCAST_BEGIN"] = ncast_start.strftime("%Y%m%d%H")
        env["yyyymmdd_today"] = self.config.PDY
        env["yyyymmdd_prev"] = ncast_start.strftime("%Y%m%d")

        log.info(f"  Date variables: PDYHH={pdyhh}, NCAST_BEGIN={env['PDYHH_NCAST_BEGIN']}, prev={env['yyyymmdd_prev']}")

        # Work subdirectories used by scripts
        # Matches operational STOFS JSTOFS_3D_ATL_PREP structure
        env["DATA_prep_nwm"] = str(work_dir / "river")
        env["DATA_prep_river_st_lawrence"] = str(work_dir / "river_st_lawrence")
        env["DATA_prep_gfs"] = str(work_dir / "gfs")
        env["DATA_prep_hrrr"] = str(work_dir / "hrrr")
        env["DATA_prep_rtofs"] = str(work_dir / "rtofs")
        env["DATA_prep_obc"] = str(work_dir / "rtofs")

        return env

    def run_script(
        self,
        script_name: str,
        work_dir: Path,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 3600,
    ) -> Tuple[bool, str, str]:
        """
        Execute a legacy shell script.

        Args:
            script_name: Name of the script (e.g., 'stofs_3d_atl_create_river_forcing_nwm.sh')
            work_dir: Working directory for execution
            env: Environment variables (if None, setup_environment is called)
            timeout: Timeout in seconds

        Returns:
            Tuple of (success, stdout, stderr)
        """
        if not self.ush_dir:
            return False, "", "Legacy USH directory not configured"

        script_path = self.ush_dir / script_name
        if not script_path.exists():
            return False, "", f"Script not found: {script_path}"

        # Setup environment
        if env is None:
            env = self.setup_environment(work_dir)

        # Create work directory
        work_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"Running legacy script: {script_name}")
        log.info(f"  Working directory: {work_dir}")

        try:
            result = subprocess.run(
                ["bash", str(script_path)],
                cwd=str(work_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            success = result.returncode == 0

            if success:
                log.info(f"  Script completed successfully")
            else:
                log.error(f"  Script failed with return code {result.returncode}")

            return success, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            log.error(f"  Script timed out after {timeout} seconds")
            return False, "", f"Timeout after {timeout} seconds"
        except Exception as e:
            log.error(f"  Error running script: {e}")
            return False, "", str(e)

    def run_python_script(
        self,
        script_name: str,
        work_dir: Path,
        args: List[str] = None,
        timeout: int = 600,
    ) -> Tuple[bool, str, str]:
        """
        Execute a legacy Python script from pysh directory.

        Args:
            script_name: Name of the Python script (e.g., 'gen_sourcesink.py')
            work_dir: Working directory for execution
            args: Command line arguments for the script
            timeout: Timeout in seconds

        Returns:
            Tuple of (success, stdout, stderr)
        """
        if not self.pysh_dir:
            return False, "", "Legacy pysh directory not configured"

        script_path = self.pysh_dir / script_name
        if not script_path.exists():
            return False, "", f"Script not found: {script_path}"

        # Copy script to work directory (some scripts expect to run locally)
        work_script = work_dir / script_name
        shutil.copy2(script_path, work_script)

        # Copy helper modules if needed
        helper_modules = ["relocate_source_feeder_lean.py", "mylib.py", "pylib.py", "schism_file.py"]
        for helper in helper_modules:
            helper_path = self.pysh_dir / helper
            if helper_path.exists():
                shutil.copy2(helper_path, work_dir / helper)

        cmd = [sys.executable, str(work_script)]
        if args:
            cmd.extend(args)

        log.info(f"Running legacy Python script: {script_name}")
        log.info(f"  Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            success = result.returncode == 0

            if success:
                log.info(f"  Script completed successfully")
            else:
                log.error(f"  Script failed with return code {result.returncode}")

            return success, result.stdout, result.stderr

        except subprocess.TimeoutExpired:
            log.error(f"  Script timed out after {timeout} seconds")
            return False, "", f"Timeout after {timeout} seconds"
        except Exception as e:
            log.error(f"  Error running script: {e}")
            return False, "", str(e)

    # =========================================================================
    # Forcing Generation Methods
    # =========================================================================

    def create_river_forcing(self, work_dir: Path) -> bool:
        """
        Create river forcing using legacy scripts.

        This uses either:
        1. The shell script (stofs_3d_atl_create_river_forcing_nwm.sh)
        2. Or directly the Python script (gen_sourcesink.py)

        Args:
            work_dir: Working directory

        Returns:
            True if successful
        """
        log.info("=" * 60)
        log.info("Creating river forcing (legacy mode)")
        log.info("=" * 60)

        # Setup work directory (matches operational structure)
        nwm_work = work_dir / "river"
        nwm_work.mkdir(parents=True, exist_ok=True)

        # Copy required FIX files
        self._copy_river_fix_files(nwm_work)

        # Link NWM data files
        n_linked = self._link_nwm_files(nwm_work)
        if n_linked == 0:
            log.error("No NWM files found to link")
            return False

        # Calculate start date for gen_sourcesink.py
        ncast_start = datetime.strptime(self.config.PDY, "%Y%m%d") + timedelta(
            hours=self.config.cyc - 6
        )
        date_str = ncast_start.strftime("%Y-%m-%d-%H")

        # Run gen_sourcesink.py directly (more portable than shell script)
        success, stdout, stderr = self.run_python_script(
            "gen_sourcesink.py",
            nwm_work,
            args=[date_str],
            timeout=600,
        )

        if stdout:
            for line in stdout.split("\n"):
                if line.strip():
                    log.info(f"  {line}")

        if stderr:
            for line in stderr.split("\n"):
                if line.strip():
                    log.warning(f"  STDERR: {line}")

        # Copy output files to rerun directory
        if success:
            self._copy_river_outputs(nwm_work)

        return success

    def _copy_river_fix_files(self, work_dir: Path) -> None:
        """Copy FIX files needed for river forcing."""
        if not self.fix_dir:
            return

        fix_files = [
            ("stofs_3d_atl_river_source_sink.in.before_relocate", "source_sink.in.before_relocate"),
            ("stofs_3d_atl_river_sources_conus.json", "sources_conus.json"),
            ("stofs_3d_atl_river_sinks_conus.json", "sinks_conus.json"),
            ("stofs_3d_atl_river_relocate_map.txt", "relocate_map.txt"),
            ("stofs_3d_atl_river_source_scale.txt", "source_scale.txt"),
            ("stofs_3d_atl_river_source_sink.in", "source_sink.in"),
        ]

        for src_name, dst_name in fix_files:
            src = self.fix_dir / src_name
            if src.exists():
                shutil.copy2(src, work_dir / dst_name)
                log.debug(f"  Copied: {src_name}")

    def _link_nwm_files(self, work_dir: Path) -> int:
        """Link NWM files in STOFS naming format."""
        nwm_path = Path(self.config.COMINnwm)
        if not nwm_path.exists():
            log.warning(f"NWM path not found: {nwm_path}")
            return 0

        # Find NWM files
        nwm_files = sorted(nwm_path.glob("**/*.nc"))
        if not nwm_files:
            return 0

        log.info(f"  Found {len(nwm_files)} NWM files")

        # Link as nwm_XXX.conus.nc
        for i, nwm_file in enumerate(nwm_files, start=1):
            link_name = work_dir / f"nwm_{i:03d}.conus.nc"
            if link_name.exists() or link_name.is_symlink():
                link_name.unlink()
            link_name.symlink_to(nwm_file)

        return len(nwm_files)

    def _copy_river_outputs(self, work_dir: Path) -> None:
        """Copy river forcing outputs to rerun directory."""
        rerun_dir = Path(self.config.COMOUTrerun or work_dir.parent / "rerun")
        rerun_dir.mkdir(parents=True, exist_ok=True)

        outputs = ["vsource.th", "vsink.th", "msource.th"]
        for fname in outputs:
            src = work_dir / fname
            if src.exists():
                # Use standard naming
                std_name = f"{self.config.RUN}.{self.config.cycle}.{fname}"
                shutil.copy2(src, rerun_dir / std_name)
                log.info(f"  Copied: {fname} -> {std_name}")

        # Copy static files from FIX if not generated
        if self.fix_dir:
            static_files = [
                ("stofs_3d_atl_river_msource.th", "msource.th"),
                ("stofs_3d_atl_river_vsink.th", "vsink.th"),
            ]
            for src_name, dst_name in static_files:
                dst = rerun_dir / f"{self.config.RUN}.{self.config.cycle}.{dst_name}"
                if not dst.exists():
                    src = self.fix_dir / src_name
                    if src.exists():
                        shutil.copy2(src, dst)
                        log.info(f"  Copied static: {src_name}")

    def create_gfs_forcing(self, work_dir: Path) -> bool:
        """
        Create GFS atmospheric forcing using legacy scripts.

        Note: This requires NCO tools (wgrib2, ncap2, ncrcat) which
        may not be available in all environments.

        Args:
            work_dir: Working directory

        Returns:
            True if successful
        """
        log.info("=" * 60)
        log.info("Creating GFS forcing (legacy mode)")
        log.info("=" * 60)

        # Check for required tools
        if not shutil.which("wgrib2"):
            log.warning("wgrib2 not found - GFS processing requires NCO tools")
            log.warning("Skipping GFS forcing generation")
            return False

        env = self.setup_environment(work_dir)

        # Debug: Log critical environment variables for forcing scripts
        log.info(f"  COMINgfs: {env.get('COMINgfs', 'NOT SET')}")
        log.info(f"  PDYHH_NCAST_BEGIN: {env.get('PDYHH_NCAST_BEGIN', 'NOT SET')}")
        log.info(f"  yyyymmdd_prev: {env.get('yyyymmdd_prev', 'NOT SET')}")

        success, stdout, stderr = self.run_script(
            self.config.legacy_script_gfs,
            work_dir / "gfs",  # Matches operational structure
            env=env,
            timeout=3600,
        )

        # Log script output for debugging
        if stdout:
            for line in stdout.split("\n")[:50]:  # First 50 lines
                if line.strip():
                    log.debug(f"  {line}")
        if stderr:
            for line in stderr.split("\n")[:20]:
                if line.strip():
                    log.warning(f"  STDERR: {line}")

        return success

    def create_hrrr_forcing(self, work_dir: Path) -> bool:
        """
        Create HRRR atmospheric forcing using legacy scripts.

        Note: This requires NCO tools (wgrib2, ncap2) which may not
        be available in all environments.

        Args:
            work_dir: Working directory

        Returns:
            True if successful
        """
        log.info("=" * 60)
        log.info("Creating HRRR forcing (legacy mode)")
        log.info("=" * 60)

        if not shutil.which("wgrib2"):
            log.warning("wgrib2 not found - HRRR processing requires NCO tools")
            log.warning("Skipping HRRR forcing generation")
            return False

        env = self.setup_environment(work_dir)

        # Debug: Log critical environment variables for forcing scripts
        log.info(f"  COMINhrrr: {env.get('COMINhrrr', 'NOT SET')}")
        log.info(f"  PDYHH_NCAST_BEGIN: {env.get('PDYHH_NCAST_BEGIN', 'NOT SET')}")
        log.info(f"  yyyymmdd_prev: {env.get('yyyymmdd_prev', 'NOT SET')}")

        success, stdout, stderr = self.run_script(
            self.config.legacy_script_hrrr,
            work_dir / "hrrr",  # Matches operational structure
            env=env,
            timeout=7200,  # 2 hours - HRRR processing takes a long time
        )

        # Log script output for debugging
        if stdout:
            for line in stdout.split("\n")[:50]:  # First 50 lines
                if line.strip():
                    log.debug(f"  {line}")
        if stderr:
            for line in stderr.split("\n")[:20]:
                if line.strip():
                    log.warning(f"  STDERR: {line}")

        return success

    def create_obc_forcing(self, work_dir: Path) -> bool:
        """
        Create ocean boundary forcing using legacy scripts.

        This runs the stofs_3d_atl_create_obc_3d_th.sh script which:
        1. Reads RTOFS 2D (ssh) and 3D (temperature, salinity, u, v) data
        2. Uses NCO tools to extract and process data
        3. Runs the gen_3Dth_from_hycom Fortran executable
        4. Produces elev2dth.nc, tem3dth.nc, sal3dth.nc, uv3dth.nc

        Requires:
        - Compiled Fortran executables (gen_3Dth_from_hycom, gen_nudge_from_hycom)
        - NCO tools (ncks, ncap2, ncrcat, ncatted, ncrename)
        - RTOFS data files

        Args:
            work_dir: Working directory

        Returns:
            True if successful
        """
        log.info("=" * 60)
        log.info("Creating OBC forcing (legacy mode)")
        log.info("=" * 60)

        # Check for required executables
        if not self.exec_dir or not self.exec_dir.exists():
            log.error("Executable directory not found")
            return False

        gen_3dth_exe = self.exec_dir / "stofs_3d_atl_gen_3Dth_from_hycom"
        if not gen_3dth_exe.exists():
            log.error(f"Required executable not found: {gen_3dth_exe}")
            return False

        log.info(f"Using executable: {gen_3dth_exe}")

        # Check for NCO tools
        required_tools = ["ncks", "ncap2", "ncrcat", "ncatted", "ncrename"]
        for tool in required_tools:
            if not shutil.which(tool):
                log.error(f"Required NCO tool not found: {tool}")
                return False
        log.info("NCO tools available")

        # Setup work directory (matches operational structure)
        obc_work = work_dir / "rtofs" / "dir_3d_th"
        obc_work.mkdir(parents=True, exist_ok=True)

        # Setup environment
        env = self.setup_environment(work_dir)

        # Create symlink to RTOFS data in expected location
        # The script expects: ${COMINrtofs}/rtofs.${yyyymmdd_today}/rtofs_glo_*.nc
        rtofs_base = Path(self.config.COMINrtofs)
        expected_rtofs_dir = obc_work / f"rtofs.{self.config.PDY}"

        # Find actual RTOFS data location (may be in subdirectory)
        actual_rtofs = None
        for pattern in [
            rtofs_base / f"rtofs.{self.config.PDY}",
            rtofs_base / "rtofs" / "*" / f"rtofs.{self.config.PDY}",
        ]:
            matches = list(pattern.parent.glob(pattern.name)) if "*" in str(pattern) else ([pattern] if pattern.exists() else [])
            for match in matches:
                if match.exists():
                    actual_rtofs = match
                    break
            if actual_rtofs:
                break

        if not actual_rtofs:
            # Try to find any rtofs directory with date
            for rtofs_dir in rtofs_base.glob("**/rtofs.*"):
                if rtofs_dir.is_dir():
                    actual_rtofs = rtofs_dir
                    break

        if actual_rtofs:
            log.info(f"Found RTOFS data: {actual_rtofs}")
            # Update COMINrtofs to parent of rtofs.YYYYMMDD
            env["COMINrtofs"] = str(actual_rtofs.parent)
        else:
            log.warning(f"RTOFS data directory not found under {rtofs_base}")
            return False

        # Run the OBC shell script
        success, stdout, stderr = self.run_script(
            self.config.legacy_script_obc,
            obc_work,
            env=env,
            timeout=7200,  # 2 hours - OBC processing can be slow
        )

        if stdout:
            # Log important output lines
            for line in stdout.split("\n"):
                if any(x in line.lower() for x in ["error", "warning", "success", "completed", "created"]):
                    log.info(f"  {line}")

        if stderr:
            for line in stderr.split("\n"):
                if line.strip():
                    log.warning(f"  STDERR: {line}")

        # Copy outputs to rerun directory
        if success:
            self._copy_obc_outputs(obc_work)

        return success

    def _copy_obc_outputs(self, work_dir: Path) -> None:
        """Copy OBC forcing outputs to rerun directory."""
        rerun_dir = Path(self.config.COMOUTrerun or work_dir.parent.parent / "rerun")
        rerun_dir.mkdir(parents=True, exist_ok=True)

        # OBC output files
        obc_files = [
            ("elev2D.th.nc", "elev2dth.nc"),
            ("TEM_3D.th.nc", "tem3dth.nc"),
            ("SAL_3D.th.nc", "sal3dth.nc"),
            ("uv3D.th.nc", "uv3dth.nc"),
            ("TEM_nu.nc", "temnu.nc"),
            ("SAL_nu.nc", "salnu.nc"),
        ]

        for src_name, dst_suffix in obc_files:
            src = work_dir / src_name
            if src.exists():
                std_name = f"{self.config.RUN}.{self.config.cycle}.{dst_suffix}"
                shutil.copy2(src, rerun_dir / std_name)
                log.info(f"  Copied: {src_name} -> {std_name}")

    def create_tidal_forcing(self, work_dir: Path) -> bool:
        """
        Create tidal forcing using legacy scripts.

        Args:
            work_dir: Working directory

        Returns:
            True if successful
        """
        log.info("=" * 60)
        log.info("Creating tidal forcing (legacy mode)")
        log.info("=" * 60)

        env = self.setup_environment(work_dir)
        success, stdout, stderr = self.run_script(
            self.config.legacy_script_tides,
            work_dir / "prep_tides",
            env=env,
            timeout=600,
        )

        return success

    def create_param_nml(self, work_dir: Path) -> bool:
        """
        Create param.nml model control file using legacy script.

        The script uses a template and substitutes date/time values:
        - rnday: Number of days to run
        - start_year, start_month, start_day, start_hour

        Args:
            work_dir: Working directory

        Returns:
            True if successful
        """
        log.info("=" * 60)
        log.info("Creating param.nml (legacy mode)")
        log.info("=" * 60)

        # Setup environment
        env = self.setup_environment(work_dir)

        # Add N_DAYS_MODEL_RUN_PERIOD (default 5.5 days for nowcast+forecast)
        env["N_DAYS_MODEL_RUN_PERIOD"] = str(getattr(self.config, 'model_run_days', 5.5))

        # Create symlink for param.nml_template
        # The prep script expects: ln -sf $FIXstofs3d/${RUN}_param.nml_6globaloutput param.nml_template
        template_link = work_dir / "param.nml_template"
        template_src_6global = self.fix_dir / f"{self.config.RUN}_param.nml_6globaloutput" if self.fix_dir else None

        if template_src_6global and template_src_6global.exists():
            if template_link.exists() or template_link.is_symlink():
                template_link.unlink()
            template_link.symlink_to(template_src_6global)
            log.info(f"  Linked template: {template_src_6global.name} -> param.nml_template")
        else:
            # Try without RUN prefix
            alt_template = self.fix_dir / "stofs_3d_atl_param.nml_6globaloutput" if self.fix_dir else None
            if alt_template and alt_template.exists():
                if template_link.exists() or template_link.is_symlink():
                    template_link.unlink()
                template_link.symlink_to(alt_template)
                log.info(f"  Linked template: {alt_template.name} -> param.nml_template")
            else:
                log.warning(f"  Template not found: {template_src_6global}")

        success, stdout, stderr = self.run_script(
            "stofs_3d_atl_create_param_nml.sh",
            work_dir,
            env=env,
            timeout=120,
        )

        if stdout:
            for line in stdout.split("\n"):
                if "param.nml" in line.lower() or "created" in line.lower():
                    log.info(f"  {line}")

        return success

    def create_bctides_in(self, work_dir: Path) -> bool:
        """
        Create bctides.in tidal forcing file using legacy script.

        Uses the tide_fac executable to generate tidal constituents
        based on the model run period and start date.

        The tide_fac executable reads bctides.in and generates bctides.in.out
        with updated nodal factors.

        Args:
            work_dir: Working directory

        Returns:
            True if successful
        """
        log.info("=" * 60)
        log.info("Creating bctides.in (legacy mode)")
        log.info("=" * 60)

        # Check for tide_fac executable
        if self.exec_dir:
            tide_fac_exe = self.exec_dir / "stofs_3d_atl_tide_fac"
            if not tide_fac_exe.exists():
                log.error(f"tide_fac executable not found: {tide_fac_exe}")
                return False
            log.info(f"  Using executable: {tide_fac_exe}")

        # Setup environment
        env = self.setup_environment(work_dir)
        env["N_DAYS_MODEL_RUN_PERIOD"] = str(getattr(self.config, 'model_run_days', 5.5))

        # PDYHH is needed by the script
        env["PDYHH"] = env["PDYHH_FCAST_BEGIN"]

        # Copy bctides template - the script copies to bctides.in_template
        # but tide_fac executable reads from bctides.in
        template_name = "stofs_3d_atl_bctides.in_template"
        template_src = self.fix_dir / template_name if self.fix_dir else None
        if template_src and template_src.exists():
            # Copy as bctides.in_template (for script) and also as bctides.in (for tide_fac)
            shutil.copy2(template_src, work_dir / "bctides.in_template")
            shutil.copy2(template_src, work_dir / "bctides.in")
            log.info(f"  Copied template: {template_name}")
        else:
            log.warning(f"  Template not found: {template_src}")

        success, stdout, stderr = self.run_script(
            "stofs_3d_atl_create_bctides_in.sh",
            work_dir,
            env=env,
            timeout=300,
        )

        if stdout:
            for line in stdout.split("\n"):
                if "bctides" in line.lower() or "completed" in line.lower():
                    log.info(f"  {line}")

        return success

    def create_st_lawrence_forcing(self, work_dir: Path) -> bool:
        """
        Create St. Lawrence River forcing using legacy script.

        Uses observed river data and GFS sflux data to create:
        - flux.th: River discharge time series
        - TEM_1.th: River temperature time series

        Args:
            work_dir: Working directory

        Returns:
            True if successful
        """
        log.info("=" * 60)
        log.info("Creating St. Lawrence River forcing (legacy mode)")
        log.info("=" * 60)

        # Setup work directory
        stlaw_work = work_dir / "prep_river_st_lawrence"
        stlaw_work.mkdir(parents=True, exist_ok=True)

        # Setup environment
        env = self.setup_environment(work_dir)
        env["DATA_prep_river_st_lawrence"] = str(stlaw_work)

        # DCOMROOT should point to the root of St. Lawrence River data
        # Structure: ${DCOMROOT}/${yyyymmdd}/canadian_water/QC_02OA016_hourly_hydrometric.csv
        dcomroot = getattr(self.config, 'DCOMROOT', '')
        if dcomroot:
            env["DCOMROOT"] = dcomroot
            log.info(f"  Using DCOMROOT: {dcomroot}")

        success, stdout, stderr = self.run_script(
            "stofs_3d_atl_create_river_st_lawrence.sh",
            stlaw_work,
            env=env,
            timeout=600,
        )

        if stdout:
            for line in stdout.split("\n"):
                if any(x in line.lower() for x in ["success", "completed", "flux", "tem_1"]):
                    log.info(f"  {line}")

        return success

    # =========================================================================
    # Main Entry Points
    # =========================================================================

    def run_full_preprocessing(self, work_dir: Path) -> Dict[str, bool]:
        """
        Run complete preprocessing for STOFS 3D Atlantic.

        This runs all preprocessing steps in order:
        1. Create param.nml (model control file)
        2. Create bctides.in (tidal forcing)
        3. Create NWM river forcing (vsource.th, vsink.th, msource.th)
        4. Create GFS surface forcing (sflux_air, sflux_prc, sflux_rad)
        5. Create HRRR surface forcing (high-resolution atmospheric)
        6. Create St. Lawrence River forcing (flux.th, TEM_1.th)

        Args:
            work_dir: Working directory

        Returns:
            Dictionary of {step_name: success}
        """
        log.info("")
        log.info("=" * 70)
        log.info("STOFS 3D ATLANTIC FULL PREPROCESSING (Legacy Mode)")
        log.info("=" * 70)
        log.info(f"Work directory: {work_dir}")
        log.info(f"PDY: {self.config.PDY}, cyc: {self.config.cyc}")
        log.info("")

        results = {}

        # Step 1: Create param.nml
        log.info("Step 1/6: Creating param.nml")
        results["param_nml"] = self.create_param_nml(work_dir)

        # Step 2: Create bctides.in
        log.info("")
        log.info("Step 2/6: Creating bctides.in")
        results["bctides"] = self.create_bctides_in(work_dir)

        # Step 3: NWM River forcing
        log.info("")
        log.info("Step 3/6: Creating NWM river forcing")
        if self.config.nwm_enabled:
            results["river_nwm"] = self.create_river_forcing(work_dir)
        else:
            log.info("  Skipped (NWM disabled)")
            results["river_nwm"] = None

        # Step 4: GFS surface forcing
        log.info("")
        log.info("Step 4/6: Creating GFS surface forcing")
        if self.config.gfs_enabled:
            results["gfs"] = self.create_gfs_forcing(work_dir)
        else:
            log.info("  Skipped (GFS disabled)")
            results["gfs"] = None

        # Step 5: HRRR surface forcing
        log.info("")
        log.info("Step 5/6: Creating HRRR surface forcing")
        if self.config.hrrr_enabled:
            results["hrrr"] = self.create_hrrr_forcing(work_dir)
        else:
            log.info("  Skipped (HRRR disabled)")
            results["hrrr"] = None

        # Step 6: St. Lawrence River forcing
        log.info("")
        log.info("Step 6/6: Creating St. Lawrence River forcing")
        results["st_lawrence"] = self.create_st_lawrence_forcing(work_dir)

        # Summary
        log.info("")
        log.info("=" * 70)
        log.info("PREPROCESSING SUMMARY")
        log.info("=" * 70)

        for step, success in results.items():
            if success is None:
                status = "SKIPPED"
            elif success:
                status = "SUCCESS"
            else:
                status = "FAILED"
            log.info(f"  {step}: {status}")

        # Count results
        completed = sum(1 for s in results.values() if s is True)
        failed = sum(1 for s in results.values() if s is False)
        skipped = sum(1 for s in results.values() if s is None)

        log.info("-" * 40)
        log.info(f"  Completed: {completed}, Failed: {failed}, Skipped: {skipped}")
        log.info("=" * 70)

        return results

    def run_prep_forcing(self, work_dir: Path) -> Dict[str, bool]:
        """
        Run forcing preparation using legacy scripts.

        Args:
            work_dir: Working directory

        Returns:
            Dictionary of {forcing_type: success}
        """
        results = {}

        # River forcing
        if self.config.legacy_river_enabled and self.config.nwm_enabled:
            results["river"] = self.create_river_forcing(work_dir)

        # GFS atmospheric forcing
        if self.config.legacy_gfs_enabled and self.config.gfs_enabled:
            results["gfs"] = self.create_gfs_forcing(work_dir)

        # HRRR atmospheric forcing
        if self.config.legacy_hrrr_enabled and self.config.hrrr_enabled:
            results["hrrr"] = self.create_hrrr_forcing(work_dir)

        # Ocean boundary conditions
        if self.config.legacy_obc_enabled and self.config.rtofs_enabled:
            results["obc"] = self.create_obc_forcing(work_dir)

        # Tidal forcing
        if self.config.legacy_tides_enabled and self.config.tides_enabled:
            results["tides"] = self.create_tidal_forcing(work_dir)

        # Summary
        log.info("")
        log.info("=" * 60)
        log.info("Legacy forcing preparation summary")
        log.info("=" * 60)
        for forcing_type, success in results.items():
            status = "SUCCESS" if success else "FAILED"
            log.info(f"  {forcing_type}: {status}")

        return results
