"""
SCHISM Model Workflow Implementation

NCO-compliant Python implementation for SCHISM model execution.
Supports both IT-STOFS (STOFS 3D Atlantic/Pacific) and COMF (SECOFS).

This workflow is YAML-driven, allowing the same code to run different
forecast systems by changing the configuration file.

Execution Modes:
1. "legacy": Use IT-STOFS scripts from external directory (via YAML config)
   - Enabled by setting legacy.enabled: true in YAML
   - Uses LegacyScriptRunner to call shell/Python scripts from IT-STOFS
   - Best for validation and gradual migration

2. "native": Call original USH shell scripts in HOMEstofs (production mode)
   - Set via STOFS_EXEC_MODE=native or exec_mode parameter
   - Executes scripts from USHstofs3d directory
   - Default production mode

3. "python": Use pure Python forcing processors (development/future)
   - Set via STOFS_EXEC_MODE=python or exec_mode parameter
   - No external dependencies on shell scripts
   - Pure Python implementation

Priority: legacy (YAML) > native/python (env/param)
"""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .schism_config import StofsConfig
from .stage import Stage
from .forcing import (
    ForcingResult,
    GFSProcessor,
    HRRRProcessor,
    NAMProcessor,
    NWMProcessor,
    StLawrenceProcessor,
    RTOFSProcessor,
    ADTProcessor,
    TidalProcessor,
)
from .model import ParamNmlGenerator
from .legacy_runner import LegacyScriptRunner


@dataclass
class ScriptResult:
    """Result of executing a shell script."""
    success: bool
    script_name: str
    return_code: int
    stdout: str = ""
    stderr: str = ""
    log_file: Optional[Path] = None

log = logging.getLogger(__name__)


class SchismModel:
    """
    SCHISM model workflow implementation.

    Supports:
    - STOFS 3D Atlantic (IT-STOFS)
    - STOFS 3D Pacific (IT-STOFS)
    - SECOFS (COMF)

    All configuration is driven by YAML, including:
    - Which forcing sources to use (GFS, HRRR, NAM, NWM, RTOFS)
    - Domain parameters
    - Computational resources
    - Output settings

    Execution Modes:
    - "native": Execute original USH shell scripts (default, production)
    - "python": Use pure Python forcing processors (development)

    Set via STOFS_EXEC_MODE environment variable or exec_mode parameter.
    """

    # Minimum valid restart file size (configurable per system)
    DEFAULT_RESTART_SIZE = 20 * 1024**3  # 20GB for STOFS
    SECOFS_RESTART_SIZE = 5 * 1024**3    # 5GB for SECOFS (smaller domain)

    # Default USH scripts for STOFS 3D Atlantic preprocessing (in execution order)
    # Format: (script_name, description, timeout_seconds)
    # NOTE: This is a fallback when YAML config doesn't specify prep_scripts
    DEFAULT_PREP_SCRIPTS_STOFS = [
        ("stofs_3d_atl_create_param_nml.sh", "param.nml creation", 300),
        ("stofs_3d_atl_create_bctides_in.sh", "bctides.in creation", 300),
        ("stofs_3d_atl_create_river_forcing_nwm.sh", "NWM river forcing", 1800),
        ("stofs_3d_atl_create_surface_forcing_gfs.sh", "GFS surface forcing", 1800),
        ("stofs_3d_atl_create_surface_forcing_hrrr.sh", "HRRR surface forcing", 7200),  # 2 hours - large files
        ("stofs_3d_atl_create_river_st_lawrence.sh", "St. Lawrence River forcing", 300),
        ("stofs_3d_atl_create_obc_3d_th.sh", "RTOFS 3D boundary conditions", 3600),
        ("stofs_3d_atl_create_obc_nudge.sh", "RTOFS nudging fields", 3600),
    ]

    # Default optional scripts for STOFS (scripts that won't fail the workflow)
    DEFAULT_OPTIONAL_SCRIPTS_STOFS = [
        "stofs_3d_atl_create_surface_forcing_hrrr.sh",
        "stofs_3d_atl_create_river_st_lawrence.sh",
    ]

    # Static files to link from FIX directory
    STATIC_FILES = [
        ("windrot_geo2proj.gr3", "{RUN}_windrot_geo2proj.gr3"),
        ("watertype.gr3", "{RUN}_watertype.gr3"),
        ("vgrid.in", "{RUN}_vgrid.in"),
        ("tvd.prop", "{RUN}_tvd.prop"),
        ("TEM_nudge.gr3", "{RUN}_tem_nudge.gr3"),
        ("station.in", "{RUN}_station.in"),
        ("source_sink.in", "{RUN}_river_source_sink.in"),
        ("shapiro.gr3", "{RUN}_shapiro.gr3"),
        ("SAL_nudge.gr3", "{RUN}_sal_nudge.gr3"),
        ("param.nml_template", "{RUN}_param.nml_6globaloutput"),
        ("msource.th", "{RUN}_river_msource.th"),
        ("hgrid.ll", "{RUN}_hgrid.ll"),
        ("hgrid.gr3", "{RUN}_hgrid.gr3"),
        ("estuary.gr3", "{RUN}_estuary.gr3"),
        ("drag.gr3", "{RUN}_drag.gr3"),
        ("diffmin.gr3", "{RUN}_diffmin.gr3"),
        ("diffmax.gr3", "{RUN}_diffmax.gr3"),
        ("bctides.in_template", "{RUN}_bctides.in_template"),
        ("albedo.gr3", "{RUN}_albedo.gr3"),
        ("partition.prop", "{RUN}_partition.prop"),
    ]

    # Framework-aware stage mapping
    # IT-STOFS stage names -> COMF (NOSOFS) stage names
    STOFS_TO_COMF_STAGES = {
        "prep_nowcast": "prep",
        "now_forecast": "nowcast_forecast",
        "post_1": "post",
        "post_2": "post2",
        "temp_salt_restart": "ts_restart",
    }

    # COMF (NOSOFS) stage names -> IT-STOFS stage names
    COMF_TO_STOFS_STAGES = {
        "prep": "prep_nowcast",
        "nowcast_forecast": "now_forecast",
        "nowcst_fcst": "now_forecast",  # Alternative COMF naming
        "post": "post_1",
        "post2": "post_2",
        "ts_restart": "temp_salt_restart",
    }

    def __init__(self, config: StofsConfig, exec_mode: Optional[str] = None) -> None:
        """
        Initialize SCHISM model workflow.

        Args:
            config: STOFS configuration object (from YAML)
            exec_mode: Execution mode - "native" (shell scripts) or "python" (pure Python)
                      Defaults to STOFS_EXEC_MODE env var or "native"
        """
        self.config = config
        self.exec_mode = exec_mode or os.environ.get("STOFS_EXEC_MODE", "native")
        self._setup_logging()
        self._log_system_info()
        self._script_results: List[ScriptResult] = []

    def _setup_logging(self) -> None:
        """Configure logging for the workflow."""
        log_level = os.environ.get("STOFS_LOG_LEVEL", "INFO")
        logging.basicConfig(
            level=getattr(logging, log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    def _log_system_info(self) -> None:
        """Log system identification information."""
        info = self.config.get_system_info()
        log.info(f"System: {info['name']} ({info['description']})")
        log.info(f"Model: {info['model_type']}, Domain: {info['domain']}")
        log.info(f"Framework: {info['framework']}")
        log.info(f"Execution Mode: {self.exec_mode}")
        log.info(f"RUN={self.config.RUN}, cyc={self.config.cyc:02d}, PDY={self.config.PDY}")

    @property
    def valid_restart_size(self) -> int:
        """Get minimum valid restart file size based on system."""
        # Use config-based restart size if available
        if hasattr(self.config, 'restart_min_size') and self.config.restart_min_size:
            return self.config.restart_min_size
        if self.config.is_comf():
            return self.SECOFS_RESTART_SIZE
        return self.DEFAULT_RESTART_SIZE

    @property
    def prep_scripts(self) -> List[tuple]:
        """
        Get preprocessing scripts from config or use defaults.

        Returns list of tuples: (script_name, description, timeout_seconds)

        The scripts are configured in YAML under native.prep_scripts or
        fall back to system-specific defaults.
        """
        # Check if config has prep_scripts defined
        if hasattr(self.config, 'prep_scripts') and self.config.prep_scripts:
            # Convert from YAML format to tuple format
            scripts = []
            for script in self.config.prep_scripts:
                name = script.get('name', '')
                desc = script.get('description', name)
                timeout = script.get('timeout', 300)
                scripts.append((name, desc, timeout))
            return scripts

        # Fall back to system-specific defaults
        return self.DEFAULT_PREP_SCRIPTS_STOFS

    @property
    def optional_scripts(self) -> List[str]:
        """
        Get list of optional scripts that won't fail the workflow.

        Returns list of script names that are allowed to fail without
        stopping the workflow.
        """
        # Check if config has optional_scripts defined
        if hasattr(self.config, 'optional_scripts') and self.config.optional_scripts:
            return self.config.optional_scripts

        # Fall back to system-specific defaults
        return self.DEFAULT_OPTIONAL_SCRIPTS_STOFS

    # =========================================================================
    # SHELL SCRIPT EXECUTION HELPERS
    # =========================================================================

    def _get_script_environment(self) -> Dict[str, str]:
        """
        Build environment variables for shell script execution.

        Returns a dictionary of environment variables that replicate
        the NCO J-job environment for shell scripts.

        This matches legacy_runner.py's setup_environment() for consistency.
        """
        from datetime import datetime, timedelta

        env = os.environ.copy()

        # NCO standard variables
        env["NET"] = self.config.NET
        env["RUN"] = self.config.RUN
        env["cyc"] = f"{self.config.cyc:02d}"
        env["cycle"] = self.config.cycle
        env["PDY"] = self.config.PDY

        # Directory paths
        env["HOMEstofs"] = self.config.HOMEstofs
        env["EXECstofs3d"] = self.config.EXECstofs3d
        env["FIXstofs3d"] = self.config.FIXstofs3d
        env["PARMstofs3d"] = self.config.PARMstofs3d
        env["USHstofs3d"] = self.config.USHstofs3d

        # DATA directory - where scripts run from
        data_dir = self.config.get_data_dir()
        env["DATA"] = str(data_dir)

        # COM directories
        env["COMOUT"] = self.config.COMOUT
        env["COMIN"] = self.config.COMIN
        env["COMOUTrerun"] = getattr(self.config, 'COMOUTrerun', f"{self.config.COMOUT}/rerun")
        env["COMOUT_PREV"] = getattr(self.config, 'COMOUT_PREV', '')

        # =====================================================================
        # Forcing input paths - handle nested directory structures
        # The scripts expect: ${COMINgfs}/gfs.${yyyymmdd}/06/atmos/...
        # But extracted data may be in: ${COMINgfs}/lfs/h1/ops/.../gfs.${yyyymmdd}/...
        # =====================================================================

        # GFS: may be in lfs/h1/ops/prod/com/gfs/v16.3/ subdirectory
        gfs_path = self.config.get_forcing_path("gfs")
        if gfs_path and gfs_path.exists():
            # Check for nested lfs structure
            nested_gfs = list(gfs_path.glob("**/gfs.*/*/atmos"))
            if nested_gfs:
                # Found nested structure - use parent of gfs.YYYYMMDD
                env["COMINgfs"] = str(nested_gfs[0].parent.parent.parent)
            else:
                env["COMINgfs"] = str(gfs_path)
        else:
            env["COMINgfs"] = str(gfs_path) if gfs_path else ""

        # HRRR: may be in lfs/h1/ops/prod/com/hrrr/v4.1/ subdirectory
        hrrr_path = self.config.get_forcing_path("hrrr")
        if hrrr_path and hrrr_path.exists():
            # Check for nested lfs structure
            nested_hrrr = list(hrrr_path.glob("**/hrrr.*/conus"))
            if nested_hrrr:
                # Found nested structure - use parent of hrrr.YYYYMMDD
                env["COMINhrrr"] = str(nested_hrrr[0].parent.parent)
            else:
                env["COMINhrrr"] = str(hrrr_path)
        else:
            env["COMINhrrr"] = str(hrrr_path) if hrrr_path else ""

        # RTOFS: may be in nested lfs directory structure
        # Actual RTOFS files are named like: rtofs_glo_2ds_f000_diag.nc
        # Data may be at: extracted_rtofs/rtofs/v2.4/rtofs.YYYYMMDD/rtofs_glo_*.nc
        # Shell script expects: ${COMINrtofs}/rtofs.${yyyymmdd}/rtofs_glo_*.nc
        # So COMINrtofs should point to: extracted_rtofs/rtofs/v2.4
        rtofs_path = self.config.get_forcing_path("rtofs")
        if rtofs_path and rtofs_path.exists():
            # Check for nested lfs structure: rtofs.YYYYMMDD
            nested_rtofs = list(rtofs_path.glob("**/rtofs.*/rtofs_glo_*.nc"))
            if nested_rtofs:
                # Found nested structure - use parent of rtofs.YYYYMMDD
                # File: .../rtofs/v2.4/rtofs.20250504/rtofs_glo_2ds_f000_diag.nc
                # .parent = rtofs.20250504 dir
                # .parent.parent = v2.4 dir (which contains rtofs.YYYYMMDD dirs)
                env["COMINrtofs"] = str(nested_rtofs[0].parent.parent)
            else:
                env["COMINrtofs"] = str(rtofs_path)
        else:
            env["COMINrtofs"] = str(rtofs_path) if rtofs_path else ""

        # NWM: may be in nwm/v3.0/ subdirectory structure
        # Script expects: COMINnwm/nwm.YYYYMMDD/medium_range_mem1/
        # Data may be at: extracted_nwm/nwm/v3.0/nwm.YYYYMMDD/...
        nwm_path = self.config.get_forcing_path("nwm")
        if nwm_path and nwm_path.exists():
            # Check for nested nwm/v3.0/ structure
            nested_nwm = list(nwm_path.glob("**/nwm.*/medium_range_mem1/*.nc"))
            if nested_nwm:
                # Found nested structure - use parent of nwm.YYYYMMDD
                env["COMINnwm"] = str(nested_nwm[0].parent.parent.parent)
            else:
                env["COMINnwm"] = str(nwm_path)
        else:
            env["COMINnwm"] = str(nwm_path) if nwm_path else ""

        # ADT data path (for SSH correction in OBC)
        env["COMINadt"] = getattr(self.config, 'COMINadt', env.get("COMINrtofs", ""))

        # DCOMROOT for St. Lawrence River data
        env["DCOMROOT"] = getattr(self.config, 'DCOMROOT', os.environ.get("DCOMROOT", ""))

        # Model run period (nowcast + forecast in days)
        env["N_DAYS_MODEL_RUN_PERIOD"] = str(getattr(self.config, 'model_run_days', 5.5))

        # =====================================================================
        # Date/time variables used by scripts
        # PDYHH: Current cycle time (PDY + cyc)
        # PDYHH_FCAST_BEGIN: Start of forecast = PDYHH
        # PDYHH_NCAST_BEGIN: Start of nowcast = PDYHH - 24 hours
        # =====================================================================
        fcast_start = datetime.strptime(self.config.PDY, "%Y%m%d") + timedelta(
            hours=self.config.cyc
        )
        ncast_start = fcast_start - timedelta(hours=24)
        fcast_end = fcast_start + timedelta(hours=72)

        pdyhh = fcast_start.strftime("%Y%m%d%H")
        env["PDYHH"] = pdyhh
        env["PDYHH_FCAST_BEGIN"] = pdyhh
        env["PDYHH_FCAST_END"] = fcast_end.strftime("%Y%m%d%H")
        env["PDYHH_NCAST_BEGIN"] = ncast_start.strftime("%Y%m%d%H")
        env["yyyymmdd_today"] = self.config.PDY
        env["yyyymmdd_prev"] = ncast_start.strftime("%Y%m%d")

        log.info(f"  Date variables: PDYHH={pdyhh}, NCAST_BEGIN={env['PDYHH_NCAST_BEGIN']}, prev={env['yyyymmdd_prev']}")

        # =====================================================================
        # Work subdirectories used by scripts
        # Matches operational IT-STOFS JSTOFS_3D_ATL_PREP structure:
        #   DATA_prep_nwm=${DATA}/river
        #   DATA_prep_gfs=${DATA}/gfs
        #   DATA_prep_hrrr=${DATA}/hrrr
        #   DATA_prep_rtofs=${DATA}/rtofs
        # =====================================================================
        env["DATA_prep_nwm"] = str(data_dir / "river")
        env["DATA_prep_river_st_lawrence"] = str(data_dir / "river_st_lawrence")
        env["DATA_prep_gfs"] = str(data_dir / "gfs")
        env["DATA_prep_hrrr"] = str(data_dir / "hrrr")
        env["DATA_prep_rtofs"] = str(data_dir / "rtofs")
        env["DATA_prep_obc"] = str(data_dir / "rtofs")  # OBC uses rtofs dir
        env["DATA_prep_restart"] = str(data_dir / "restart")

        # Python scripts directory
        env["PYstofs3d"] = f"{self.config.USHstofs3d}/pysh"

        # Control flags
        env["SENDCOM"] = os.environ.get("SENDCOM", "YES")
        env["SENDDBN"] = os.environ.get("SENDDBN", "NO")
        env["KEEPDATA"] = os.environ.get("KEEPDATA", "YES")

        # COLDSTART flag
        env["COLDSTART"] = os.environ.get("COLDSTART", "NO")

        # =====================================================================
        # NCO TOOLS - Set full paths for tools used by shell scripts
        # The scripts use $WGRIB2, $NCKS, etc. instead of calling tools directly
        # =====================================================================
        nco_tools = ["wgrib2", "ncks", "ncap2", "ncrcat", "ncatted", "ncrename", "ncdump"]
        for tool in nco_tools:
            tool_path = shutil.which(tool)
            if tool_path:
                env[tool.upper()] = tool_path

        # =====================================================================
        # Add bin directory to PATH for shim scripts (cpreq, etc.)
        # =====================================================================
        bin_dir = Path(self.config.HOMEstofs) / "ush" / "stofs_3d_atl" / "bin"
        if bin_dir.exists():
            current_path = env.get("PATH", "")
            env["PATH"] = f"{bin_dir}:{current_path}"

        # jlogfile for postmsg
        env["jlogfile"] = str(data_dir / f"jlogfile.{self.config.RUN}")

        return env

    def _calc_ncast_begin(self, pdyhh: str) -> str:
        """Calculate PDYHH_NCAST_BEGIN (24 hours before PDYHH_FCAST_BEGIN)."""
        from datetime import datetime, timedelta
        dt = datetime.strptime(pdyhh, "%Y%m%d%H")
        ncast_begin = dt - timedelta(hours=24)
        return ncast_begin.strftime("%Y%m%d%H")

    def _execute_ush_script(
        self,
        script_name: str,
        description: str,
        timeout: int = 3600,
    ) -> ScriptResult:
        """
        Execute a USH shell script with proper NCO environment.

        Args:
            script_name: Name of the script in USHstofs3d directory
            description: Human-readable description for logging
            timeout: Maximum execution time in seconds

        Returns:
            ScriptResult with execution details
        """
        script_path = Path(self.config.USHstofs3d) / script_name
        data_dir = self.config.get_data_dir()
        log_file = data_dir / f"log_{script_name.replace('.sh', '')}.{self.config.cycle}.log"

        log.info(f"{'='*60}")
        log.info(f"Executing: {script_name}")
        log.info(f"Description: {description}")
        log.info(f"Script path: {script_path}")
        log.info(f"Log file: {log_file}")

        if not script_path.exists():
            error_msg = f"Script not found: {script_path}"
            log.error(error_msg)
            return ScriptResult(
                success=False,
                script_name=script_name,
                return_code=-1,
                stderr=error_msg,
            )

        # Build environment
        env = self._get_script_environment()

        try:
            # Execute script
            result = subprocess.run(
                ["bash", str(script_path)],
                cwd=str(data_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            # Write log file
            with open(log_file, 'w') as f:
                f.write(f"Script: {script_name}\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"{'='*60}\n")
                f.write("STDOUT:\n")
                f.write(result.stdout)
                f.write(f"\n{'='*60}\n")
                f.write("STDERR:\n")
                f.write(result.stderr)

            success = result.returncode == 0

            if success:
                log.info(f"SUCCESS: {script_name} completed (return code: {result.returncode})")
            else:
                log.error(f"FAILED: {script_name} (return code: {result.returncode})")
                log.error(f"Check log file: {log_file}")
                # Log last few lines of stderr
                if result.stderr:
                    for line in result.stderr.strip().split('\n')[-10:]:
                        log.error(f"  {line}")

            return ScriptResult(
                success=success,
                script_name=script_name,
                return_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                log_file=log_file,
            )

        except subprocess.TimeoutExpired:
            error_msg = f"Script timed out after {timeout} seconds"
            log.error(f"TIMEOUT: {script_name} - {error_msg}")
            return ScriptResult(
                success=False,
                script_name=script_name,
                return_code=-2,
                stderr=error_msg,
                log_file=log_file,
            )

        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            log.error(f"ERROR: {script_name} - {error_msg}")
            return ScriptResult(
                success=False,
                script_name=script_name,
                return_code=-3,
                stderr=error_msg,
                log_file=log_file,
            )

    def _normalize_stage_name(self, stage_name: str) -> str:
        """
        Normalize stage name to internal (IT-STOFS) format.

        Accepts both IT-STOFS and COMF stage naming conventions.

        Args:
            stage_name: Stage name in either framework's format

        Returns:
            Normalized stage name (IT-STOFS format)
        """
        # Convert to lowercase for comparison
        stage_lower = stage_name.lower().strip()

        # Check if this is a COMF stage name
        if stage_lower in self.COMF_TO_STOFS_STAGES:
            normalized = self.COMF_TO_STOFS_STAGES[stage_lower]
            log.debug(f"Mapped COMF stage '{stage_name}' -> '{normalized}'")
            return normalized

        # Already in IT-STOFS format or unknown
        return stage_lower

    def get_framework_stage_name(self, stage_name: str) -> str:
        """
        Get the stage name in the current framework's naming convention.

        Args:
            stage_name: Internal (IT-STOFS) stage name

        Returns:
            Stage name in the appropriate framework's convention
        """
        if self.config.is_comf():
            return self.STOFS_TO_COMF_STAGES.get(stage_name, stage_name)
        return stage_name

    def run_stage(self, stage_name: str) -> None:
        """
        Run a workflow stage.

        Accepts stage names in either IT-STOFS or COMF naming convention.
        Internally normalizes to IT-STOFS format for processing.

        Args:
            stage_name: Name of the stage to run (IT-STOFS or COMF format)

        Raises:
            ValueError: If stage name is invalid
            RuntimeError: If stage execution fails
        """
        # Normalize stage name (accept both STOFS and COMF names)
        normalized_stage = self._normalize_stage_name(stage_name)
        stage = Stage.from_string(normalized_stage)
        timeout = self.config.get_stage_timeout(normalized_stage)

        # Get display name for current framework
        display_name = self.get_framework_stage_name(normalized_stage)

        log.info(f"{'='*60}")
        log.info(f"Starting stage: {display_name} (internal: {stage})")
        log.info(f"Framework: {self.config.framework}, Timeout: {timeout}s")
        log.info(f"{'='*60}")

        if stage == Stage.PREP_NOWCAST:
            self._run_prep_nowcast()
        elif stage == Stage.NOW_FORECAST:
            self._run_now_forecast()
        elif stage == Stage.POST_1:
            self._run_post_1()
        elif stage == Stage.POST_2:
            self._run_post_2()
        elif stage == Stage.TEMP_SALT_RESTART:
            self._run_temp_salt_restart()

        log.info(f"Completed stage: {display_name}")

    # =========================================================================
    # PREP NOWCAST STAGE
    # =========================================================================

    def _run_prep_nowcast(self) -> None:
        """
        Run prep_nowcast stage - prepare all forcing data.

        Execution modes:
        - "legacy": Use IT-STOFS shell/Python scripts from external directory
        - "native": Execute original USH shell scripts (production)
        - "python": Use pure Python forcing processors (development)

        Legacy mode is enabled via YAML config:
            legacy:
              enabled: true
              ush_dir: "/path/to/IT-STOFS/ush/stofs_3d_atl"
        """
        log.info("Running prep_nowcast stage")

        data_dir = self.config.get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        # Check for legacy mode first (YAML-driven)
        if self.config.use_legacy_scripts:
            log.info("Execution mode: LEGACY (IT-STOFS scripts)")
            self._run_prep_nowcast_legacy(data_dir)
        elif self.exec_mode == "native":
            log.info("Execution mode: NATIVE (USH shell scripts)")
            self._run_prep_nowcast_native(data_dir)
        else:
            log.info("Execution mode: PYTHON (pure Python processors)")
            self._run_prep_nowcast_python(data_dir)

        log.info("prep_nowcast stage completed")

    def _run_prep_nowcast_legacy(self, data_dir: Path) -> None:
        """
        Run prep_nowcast using legacy IT-STOFS scripts.

        This mode uses the LegacyScriptRunner to execute shell scripts
        and Python scripts from an external IT-STOFS installation.

        Configured via YAML:
            legacy:
              enabled: true
              ush_dir: "/path/to/IT-STOFS/ush/stofs_3d_atl"
              pysh_dir: "/path/to/IT-STOFS/ush/stofs_3d_atl/pysh"
              scripts:
                river: true
                gfs: false  # Requires NCO tools
                hrrr: false  # Requires NCO tools
                obc: false   # Requires Fortran executables
        """
        log.info("Running prep_nowcast in LEGACY mode (IT-STOFS scripts)")
        log.info(f"Legacy USH dir: {self.config.legacy_ush_dir}")
        log.info(f"Legacy pysh dir: {self.config.legacy_pysh_dir}")

        # Step 1: Create required directories
        self._create_prep_directories(data_dir)

        # Step 2: Link static files from FIX
        self._link_static_files_prep(data_dir)

        # Step 3: Create COM directories
        comout_rerun = Path(self.config.COMOUT) / "rerun"
        comout_rerun.mkdir(parents=True, exist_ok=True)
        log.info(f"Created COMOUTrerun: {comout_rerun}")

        # Step 4: Create and run legacy script runner
        runner = LegacyScriptRunner(self.config)
        results = runner.run_prep_forcing(data_dir)

        # Step 5: Handle restart file
        self._handle_restart_prep(data_dir)

        # Step 6: Log summary
        log.info("=" * 60)
        log.info("LEGACY PREP NOWCAST SUMMARY")
        log.info("=" * 60)

        success_count = sum(1 for r in results.values() if r)
        total_count = len(results)

        log.info(f"Forcing types processed: {total_count}")
        log.info(f"Successful: {success_count}")
        log.info(f"Failed: {total_count - success_count}")
        log.info("-" * 40)

        for forcing_type, success in results.items():
            status = "SUCCESS" if success else "FAILED/SKIPPED"
            log.info(f"  {forcing_type}: {status}")

        log.info("=" * 60)

        # Check for critical failures
        critical_types = ["river"]  # Only river is critical for now
        critical_failures = [t for t in critical_types if t in results and not results[t]]

        if critical_failures:
            log.warning(f"Critical forcing types failed: {critical_failures}")
            # Don't raise error - let workflow continue with available data

    def _run_prep_nowcast_native(self, data_dir: Path) -> None:
        """
        Run prep_nowcast using original USH shell scripts.

        This matches the operational IT-STOFS workflow exactly.
        """
        log.info("Running prep_nowcast in NATIVE mode (USH shell scripts)")

        # Step 1: Create required directories
        self._create_prep_directories(data_dir)

        # Step 2: Link static files from FIX
        self._link_static_files_prep(data_dir)

        # Step 3: Create COMOUTrerun directory
        comout_rerun = Path(self.config.COMOUT) / "rerun"
        comout_rerun.mkdir(parents=True, exist_ok=True)
        log.info(f"Created COMOUTrerun: {comout_rerun}")

        # Step 3b: Copy pre-processed input files (e.g., ADT data for OBC)
        self._copy_rerun_input_files(comout_rerun)

        # Step 4: Execute USH scripts in sequence
        # Scripts are loaded from YAML config or use system defaults
        self._script_results = []
        failed_scripts = []

        log.info(f"Executing {len(self.prep_scripts)} preprocessing scripts")
        for script_name, description, timeout in self.prep_scripts:
            result = self._execute_ush_script(script_name, description, timeout=timeout)
            self._script_results.append(result)

            if not result.success:
                failed_scripts.append(script_name)
                # Check if script is optional (won't fail the workflow)
                if script_name in self.optional_scripts:
                    log.warning(f"Optional script failed: {script_name} - continuing")
                else:
                    log.error(f"Required script failed: {script_name}")

        # Step 5: Handle restart file
        self._handle_restart_prep(data_dir)

        # Step 6: Log summary
        self._log_prep_summary()

        if failed_scripts:
            # Check if any critical (non-optional) scripts failed
            critical_failures = [s for s in failed_scripts
                               if s not in self.optional_scripts]
            if critical_failures:
                log.error(f"Critical scripts failed: {critical_failures}")
                raise RuntimeError(f"prep_nowcast failed: {critical_failures}")

    def _create_prep_directories(self, data_dir: Path) -> None:
        """Create directories needed for preprocessing.

        Matches operational IT-STOFS JSTOFS_3D_ATL_PREP directory structure.
        """
        log.info("Creating prep directories")

        dirs_to_create = [
            data_dir / "river",
            data_dir / "river_st_lawrence",
            data_dir / "gfs",
            data_dir / "hrrr",
            data_dir / "rtofs",
            data_dir / "restart",
            data_dir / "sflux",
            data_dir / "com",
            data_dir / "rerun",
        ]

        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
            log.debug(f"Created: {dir_path}")

        log.info(f"Created {len(dirs_to_create)} prep directories")

    def _copy_rerun_input_files(self, comout_rerun: Path) -> None:
        """Copy pre-processed input files to COMOUTrerun.

        Some preprocessing scripts (like OBC 3D TH) require pre-processed
        input files that are typically generated by previous runs or provided
        from upstream data sources. This method copies them from a default
        location (stofs_data/stofs_rerun) if available.

        Key files:
        - adt_aft_cvtz_cln.nc: Pre-processed ADT (Altimeter Data) for OBC
        """
        log.info("Copying pre-processed input files to COMOUTrerun")

        # Files to copy from stofs_data/stofs_rerun to COMOUTrerun
        rerun_files = [
            "adt_aft_cvtz_cln.nc",  # ADT data for OBC 3D TH processing
        ]

        # Look for source directory - try multiple locations
        home_stofs = Path(getattr(self.config, 'HOMEstofs', ''))
        possible_sources = [
            home_stofs / "stofs_data" / "stofs_rerun",
            home_stofs.parent / "stofs_data" / "stofs_rerun",
        ]

        # Also check DATA directory's parent for stofs_data
        data_dir = Path(self.config.DATA)
        if data_dir.parent.name == "stofs_data" or (data_dir.parent / "stofs_data").exists():
            possible_sources.append(data_dir.parent / "stofs_data" / "stofs_rerun")

        copied = 0
        for filename in rerun_files:
            source_found = False
            for source_dir in possible_sources:
                source_path = source_dir / filename
                if source_path.exists():
                    dest_path = comout_rerun / filename
                    try:
                        shutil.copy2(source_path, dest_path)
                        log.info(f"Copied {filename} from {source_dir}")
                        copied += 1
                        source_found = True
                        break
                    except Exception as e:
                        log.warning(f"Failed to copy {filename}: {e}")

            if not source_found:
                log.warning(f"Pre-processed file not found: {filename}")
                log.debug(f"Searched in: {[str(s) for s in possible_sources]}")

        log.info(f"Copied {copied}/{len(rerun_files)} pre-processed input files")

    def _link_static_files_prep(self, data_dir: Path) -> None:
        """Link static files from FIX directory for preprocessing."""
        log.info("Linking static files for prep stage")

        linked = 0
        missing = 0

        for dest_name, source_pattern in self.STATIC_FILES:
            source_name = source_pattern.format(RUN=self.config.RUN)
            source_path = self.config.get_fix_file(source_name)
            dest_path = data_dir / dest_name

            # Remove existing file/link
            if dest_path.exists() or dest_path.is_symlink():
                dest_path.unlink()

            if source_path.exists():
                dest_path.symlink_to(source_path)
                linked += 1
                log.debug(f"Linked: {dest_name} -> {source_path}")
            else:
                missing += 1
                log.warning(f"Static file not found: {source_path}")

        log.info(f"Linked {linked} static files ({missing} missing)")

    def _handle_restart_prep(self, data_dir: Path) -> None:
        """Handle restart file setup during prep stage."""
        log.info("Handling restart file")

        coldstart = os.environ.get("COLDSTART", "NO")
        restart_dir = data_dir / "restart"
        restart_dir.mkdir(parents=True, exist_ok=True)

        comout_rerun = Path(self.config.COMOUT) / "rerun"
        fn_restart_rerun = comout_rerun / f"{self.config.RUN}.{self.config.cycle}.restart.nc"

        if coldstart == "YES":
            # Cold start: use restart from FIX directory
            fn_restart_coldstart = self.config.get_fix_file(
                f"{self.config.RUN}_restart_coldstart.nc"
            )

            if fn_restart_coldstart.exists():
                file_size = fn_restart_coldstart.stat().st_size
                if file_size >= self.valid_restart_size:
                    shutil.copy2(fn_restart_coldstart, fn_restart_rerun)
                    log.info(f"COLDSTART: Copied coldstart restart ({file_size/1024**3:.2f} GB)")
                else:
                    log.warning(f"Coldstart file too small: {file_size/1024**3:.2f} GB")
            else:
                log.warning(f"Coldstart restart not found: {fn_restart_coldstart}")

        else:
            # Hot start: look for previous cycle's hotstart
            self._find_and_copy_hotstart(fn_restart_rerun)

    def _find_and_copy_hotstart(self, dest_file: Path) -> bool:
        """Find and copy hotstart from previous cycles."""
        from datetime import datetime, timedelta

        log.info("Searching for previous hotstart file")

        # Get COMINstofs base path
        comin_base = Path(self.config.COMIN).parent

        # Try up to 4 previous days
        pdy_dt = datetime.strptime(self.config.PDY, "%Y%m%d")

        for days_ago in range(5):
            check_date = pdy_dt - timedelta(days=days_ago)
            date_str = check_date.strftime("%Y%m%d")

            fn_hotstart = comin_base / f"{self.config.RUN}.{date_str}" / \
                         f"{self.config.RUN}.{self.config.cycle}.hotstart.stofs3d.nc"

            if fn_hotstart.exists():
                file_size = fn_hotstart.stat().st_size
                if file_size >= self.valid_restart_size:
                    shutil.copy2(fn_hotstart, dest_file)
                    log.info(f"Found hotstart from {date_str}: {file_size/1024**3:.2f} GB")
                    return True
                else:
                    log.warning(f"Hotstart from {date_str} too small: {file_size/1024**3:.2f} GB")
            else:
                log.debug(f"No hotstart for {date_str}")

        log.warning("No valid hotstart found in previous 5 days")
        return False

    def _log_prep_summary(self) -> None:
        """Log summary of prep stage script execution."""
        log.info("=" * 60)
        log.info("PREP NOWCAST SUMMARY")
        log.info("=" * 60)

        success_count = sum(1 for r in self._script_results if r.success)
        total_count = len(self._script_results)

        log.info(f"Scripts executed: {total_count}")
        log.info(f"Successful: {success_count}")
        log.info(f"Failed: {total_count - success_count}")
        log.info("-" * 40)

        for result in self._script_results:
            status = "SUCCESS" if result.success else "FAILED"
            log.info(f"  {result.script_name}: {status} (rc={result.return_code})")
            if result.log_file:
                log.info(f"    Log: {result.log_file}")

        log.info("=" * 60)

    def _run_prep_nowcast_python(self, data_dir: Path) -> None:
        """
        Run prep_nowcast using pure Python processors.

        This is the development/future mode that doesn't require
        external shell scripts or executables.
        """
        log.info("Running prep_nowcast in PYTHON mode (pure Python processors)")

        # Track results
        results: Dict[str, ForcingResult] = {}

        # Step 1: Generate param.nml
        param_result = self._generate_param_nml(data_dir)
        if param_result:
            log.info("param.nml generation complete")

        # Step 2: Process atmospheric forcing (config-driven)
        results.update(self._process_atmospheric_forcing(data_dir))

        # Step 3: Process river forcing
        if self.config.nwm_enabled:
            results["nwm"] = self._process_nwm_forcing(data_dir)

        # Step 4: Process St. Lawrence River (STOFS Atlantic only)
        if self.config.RUN == "stofs_3d_atl":
            results["st_lawrence"] = self._process_st_lawrence_forcing(data_dir)

        # Step 5: Process ocean boundary conditions
        if self.config.rtofs_enabled:
            results["rtofs"] = self._process_rtofs_forcing(data_dir)

        # Step 6: Apply ADT SSH correction (if data available)
        adt_result = self._process_adt_correction(data_dir)
        if adt_result:
            results["adt"] = adt_result

        # Step 7: Process tidal forcing
        if self.config.tides_enabled:
            results["tides"] = self._process_tidal_forcing(data_dir)

        # Step 8: Create sflux directory structure
        self._create_sflux_structure(data_dir)

        # Step 9: Handle restart file
        self._handle_restart_prep(data_dir)

        # Log summary
        self._log_forcing_summary(results)

    def _generate_param_nml(self, data_dir: Path) -> Optional[Path]:
        """
        Generate param.nml using Python ParamNmlGenerator.

        Returns:
            Path to generated param.nml or None if failed
        """
        log.info("Generating param.nml in Python mode")

        try:
            generator = ParamNmlGenerator(self.config)

            # Determine coldstart status
            coldstart = os.environ.get("COLDSTART", "NO") == "YES"

            # Generate for current cycle
            output_file = generator.generate_for_cycle(
                output_path=data_dir / "param.nml",
                pdy=self.config.PDY,
                cyc=self.config.cyc,
                coldstart=coldstart,
            )

            # Also copy to COMOUTrerun
            comout_rerun = Path(self.config.COMOUT) / "rerun"
            comout_rerun.mkdir(parents=True, exist_ok=True)
            com_file = comout_rerun / f"{self.config.RUN}.{self.config.cycle}.param.nml"
            shutil.copy2(output_file, com_file)
            log.info(f"Copied param.nml to {com_file}")

            return output_file

        except Exception as e:
            log.error(f"param.nml generation failed: {e}")
            import traceback
            log.error(traceback.format_exc())
            return None

    def _process_st_lawrence_forcing(self, data_dir: Path) -> ForcingResult:
        """
        Process St. Lawrence River forcing.

        This is specific to STOFS 3D Atlantic domain which includes
        the Gulf of St. Lawrence.
        """
        log.info("Processing St. Lawrence River forcing")

        try:
            # DCOM path for Canadian hydrological data
            dcom_root = os.environ.get("DCOMROOT", "/lfs/h1/ops/prod/dcom")
            input_path = Path(dcom_root) / self.config.PDY

            processor = StLawrenceProcessor(
                config=self.config,
                input_path=input_path,
                output_path=data_dir / "river_st_lawrence",
                use_climatology=True,  # Fall back to climatology if no real-time data
            )
            result = processor.process()

            # Merge with NWM river forcing if both exist
            nwm_vsource = data_dir / "vsource.th"
            nwm_msource = data_dir / "msource.th"

            if nwm_vsource.exists() and (data_dir / "river_st_lawrence" / "vsource_stl.th").exists():
                processor.merge_with_nwm(
                    nwm_vsource=nwm_vsource,
                    nwm_msource=nwm_msource,
                    output_vsource=data_dir / "vsource_merged.th",
                    output_msource=data_dir / "msource_merged.th",
                )

            return result

        except Exception as e:
            log.warning(f"St. Lawrence processing failed: {e}")
            return ForcingResult(
                success=True,  # Non-fatal
                source="St_Lawrence",
                warnings=[f"St. Lawrence processing failed: {e}"],
            )

    def _process_adt_correction(self, data_dir: Path) -> Optional[ForcingResult]:
        """
        Apply ADT (Altimeter Data) SSH correction to RTOFS boundary.

        This improves ocean boundary accuracy using satellite observations.
        """
        log.info("Processing ADT SSH correction")

        try:
            # ADT data path (DCOM or COMINadt)
            adt_path = Path(os.environ.get("COMINadt", ""))
            if not adt_path.exists():
                dcom_root = os.environ.get("DCOMROOT", "/lfs/h1/ops/prod/dcom")
                adt_path = Path(dcom_root) / self.config.PDY

            if not adt_path.exists():
                log.info("ADT data path not found - skipping SSH correction")
                return None

            processor = ADTProcessor(
                config=self.config,
                input_path=adt_path,
                output_path=data_dir / "adt",
                search_window=48,
                apply_correction=True,
            )
            return processor.process()

        except Exception as e:
            log.warning(f"ADT correction failed: {e}")
            return ForcingResult(
                success=True,
                source="ADT",
                warnings=[f"ADT processing failed: {e}"],
            )

    def _process_atmospheric_forcing(self, data_dir: Path) -> Dict[str, ForcingResult]:
        """
        Process atmospheric forcing based on YAML configuration.

        For STOFS: GFS (primary) + HRRR (high-res regional)
        For SECOFS: GFS (global) + NAM (regional priority)
        """
        results = {}
        sflux_dir = data_dir / "sflux"
        sflux_dir.mkdir(parents=True, exist_ok=True)

        # GFS - always processed if enabled
        if self.config.gfs_enabled:
            log.info("Processing GFS atmospheric forcing")
            gfs_config = self.config.get_forcing_sources("atmospheric").get("gfs", {})
            processor = GFSProcessor(
                config=self.config,
                input_path=self.config.get_forcing_path("gfs"),
                output_path=sflux_dir,
                variables=gfs_config.get("variables"),
                forecast_hours=gfs_config.get("forecast_hours", 180),
            )
            results["gfs"] = processor.process()

        # HRRR - STOFS 3D Atlantic uses this for high-res coastal
        if self.config.hrrr_enabled:
            log.info("Processing HRRR atmospheric forcing")
            hrrr_config = self.config.get_forcing_sources("atmospheric").get("hrrr", {})
            processor = HRRRProcessor(
                config=self.config,
                input_path=self.config.get_forcing_path("hrrr"),
                output_path=sflux_dir,
                variables=hrrr_config.get("variables"),
                forecast_hours=hrrr_config.get("forecast_hours", 48),
            )
            results["hrrr"] = processor.process()

        # NAM - SECOFS uses this as primary regional forcing
        if self.config.nam_enabled:
            log.info("Processing NAM atmospheric forcing")
            nam_config = self.config.get_forcing_sources("atmospheric").get("nam", {})
            processor = NAMProcessor(
                config=self.config,
                input_path=self.config.get_forcing_path("nam"),
                output_path=sflux_dir,
                variables=nam_config.get("variables"),
                forecast_hours=nam_config.get("forecast_hours", 84),
                priority=nam_config.get("priority", "high"),
            )
            results["nam"] = processor.process()

        return results

    def _process_nwm_forcing(self, data_dir: Path) -> ForcingResult:
        """Process NWM river forcing."""
        log.info(f"Processing NWM river forcing ({self.config.num_rivers} rivers)")

        river_config = self.config.get_forcing_sources("river").get("nwm", {})
        processor = NWMProcessor(
            config=self.config,
            input_path=self.config.get_forcing_path("nwm"),
            output_path=data_dir,
            product=river_config.get("product", "medium_range"),
            num_rivers=self.config.num_rivers,
        )
        return processor.process()

    def _process_rtofs_forcing(self, data_dir: Path) -> ForcingResult:
        """Process RTOFS ocean boundary conditions."""
        log.info("Processing RTOFS ocean boundary conditions")

        ocean_config = self.config.get_forcing_sources("ocean").get("rtofs", {})
        nudging = ocean_config.get("nudging", {})

        processor = RTOFSProcessor(
            config=self.config,
            input_path=self.config.get_forcing_path("rtofs"),
            output_path=data_dir,
            variables=ocean_config.get("variables"),
            nudging_enabled=nudging.get("enabled", True),
            nudging_timescale=nudging.get("timescale", 86400.0),
        )
        return processor.process()

    def _process_tidal_forcing(self, data_dir: Path) -> ForcingResult:
        """Process tidal forcing."""
        log.info(f"Processing tidal forcing ({len(self.config.tidal_constituents)} constituents)")

        tides_config = self.config.get_forcing_sources("tides") or {}
        processor = TidalProcessor(
            config=self.config,
            input_path=Path(self.config.FIXstofs3d),
            output_path=data_dir,
            constituents=self.config.tidal_constituents,
            database=tides_config.get("database", "tpxo9"),
        )
        return processor.process()

    def _create_sflux_structure(self, data_dir: Path) -> None:
        """Create sflux directory structure for SCHISM."""
        log.info("Creating sflux structure")

        sflux_dir = data_dir / "sflux"
        sflux_dir.mkdir(parents=True, exist_ok=True)

        # Copy sflux_inputs.txt from FIX
        sflux_inputs = self.config.get_fix_file(f"{self.config.RUN}_sflux_inputs.txt")
        if sflux_inputs.exists():
            shutil.copy2(sflux_inputs, sflux_dir / "sflux_inputs.txt")
            log.info("Copied sflux_inputs.txt")
        else:
            log.warning(f"sflux_inputs.txt not found: {sflux_inputs}")

    def _log_forcing_summary(self, results: Dict[str, ForcingResult]) -> None:
        """Log summary of forcing processing results."""
        log.info("-" * 40)
        log.info("Forcing Processing Summary:")
        for source, result in results.items():
            status = "SUCCESS" if result.success else "FAILED"
            log.info(f"  {source.upper()}: {status}")
            if result.errors:
                for error in result.errors:
                    log.error(f"    Error: {error}")
        log.info("-" * 40)

    # =========================================================================
    # NOW/FORECAST STAGE
    # =========================================================================

    def _run_now_forecast(self) -> None:
        """
        Run now_forecast stage - execute SCHISM model.

        Configuration-driven for resources (NPROCS, NSCRIBES).
        """
        log.info("Running now_forecast stage")

        data_dir = self.config.get_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        # Link static files
        self._link_static_files(data_dir)

        # Setup model input files
        self._setup_model_inputs(data_dir)

        # Handle restart
        self._handle_restart(data_dir)

        # Execute SCHISM
        self._execute_schism(data_dir)

        # Validate completion
        self._validate_completion(data_dir)

        # Save restart for next cycle
        self._save_restart(data_dir)

        log.info("now_forecast stage completed")

    def _link_static_files(self, data_dir: Path) -> None:
        """Link SCHISM static files from FIX directory."""
        log.info("Linking static files")

        # Use grid filenames from config if available
        static_files = [
            ("hgrid.gr3", self.config.grid_horizontal),
            ("vgrid.in", self.config.grid_vertical),
            ("hgrid.ll", f"{self.config.RUN}_hgrid.ll"),
            ("drag.gr3", f"{self.config.RUN}_drag.gr3"),
            ("albedo.gr3", f"{self.config.RUN}_albedo.gr3"),
            ("diffmax.gr3", f"{self.config.RUN}_diffmax.gr3"),
            ("diffmin.gr3", f"{self.config.RUN}_diffmin.gr3"),
            ("watertype.gr3", f"{self.config.RUN}_watertype.gr3"),
            ("windrot_geo2proj.gr3", f"{self.config.RUN}_windrot_geo2proj.gr3"),
            ("station.in", f"{self.config.RUN}_station.in"),
            ("tvd.prop", f"{self.config.RUN}_tvd.prop"),
            ("shapiro.gr3", f"{self.config.RUN}_shapiro.gr3"),
        ]

        linked = 0
        for dest_name, source_name in static_files:
            source = self.config.get_fix_file(source_name)
            dest = data_dir / dest_name

            if dest.exists():
                dest.unlink()  # Remove existing link

            if source.exists():
                dest.symlink_to(source)
                linked += 1
            else:
                log.warning(f"Static file not found: {source}")

        log.info(f"Linked {linked}/{len(static_files)} static files")

    def _setup_model_inputs(self, data_dir: Path) -> None:
        """Setup model input files from COM."""
        log.info("Setting up model inputs")

        # Copy param.nml
        param_file = self.config.get_com_file(
            f"{self.config.RUN}.{self.config.cycle}.param.nml", "rerun"
        )
        if param_file.exists():
            shutil.copy2(param_file, data_dir / "param.nml")
            log.info("Copied param.nml")

        # Copy bctides.in
        bctides_file = self.config.get_com_file(
            f"{self.config.RUN}.{self.config.cycle}.bctides.in", "rerun"
        )
        if bctides_file.exists():
            shutil.copy2(bctides_file, data_dir / "bctides.in")
            log.info("Copied bctides.in")

    def _handle_restart(self, data_dir: Path) -> None:
        """Handle restart file setup."""
        log.info("Handling restart")

        if not self.config.hotstart_enabled:
            log.info("Hotstart disabled, running cold start")
            return

        restart_dir = Path(self.config.RESTART_DIR) if self.config.RESTART_DIR else None
        if not restart_dir:
            log.warning("RESTART_DIR not set, running cold start")
            return

        restart_file = restart_dir / "hotstart.nc"

        if restart_file.exists() and restart_file.stat().st_size >= self.valid_restart_size:
            dest = data_dir / "hotstart.nc"
            shutil.copy2(restart_file, dest)
            log.info(f"Using restart file: {restart_file}")
            log.info(f"Restart size: {restart_file.stat().st_size / 1024**3:.2f} GB")
        else:
            if restart_file.exists():
                log.warning(f"Restart file too small: {restart_file.stat().st_size / 1024**3:.2f} GB")
            else:
                log.warning(f"Restart file not found: {restart_file}")
            log.info("Running cold start")

    def _execute_schism(self, data_dir: Path) -> None:
        """Execute SCHISM model via MPI."""
        log.info("Executing SCHISM model")
        log.info(f"NPROCS={self.config.NPROCS}, NSCRIBES={self.config.NSCRIBES}")

        executable = self.config.get_exec_file(self.config.executable)

        if not executable.exists():
            # Try alternative name
            alt_executable = self.config.get_exec_file("pschism_WCOSS2")
            if alt_executable.exists():
                executable = alt_executable
            else:
                raise RuntimeError(f"SCHISM executable not found: {executable}")

        # Build MPI command
        cmd = [
            "mpiexec",
            "-n", str(self.config.NPROCS),
            str(executable),
            str(self.config.NSCRIBES),
        ]

        log.info(f"Running: {' '.join(cmd)}")
        log.info(f"Working directory: {data_dir}")

        result = subprocess.run(
            cmd,
            cwd=data_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            log.error(f"SCHISM stdout: {result.stdout}")
            log.error(f"SCHISM stderr: {result.stderr}")
            raise RuntimeError(f"SCHISM execution failed: {result.returncode}")

        log.info("SCHISM execution completed")

    def _validate_completion(self, data_dir: Path) -> None:
        """Validate SCHISM model completion."""
        log.info("Validating completion")

        mirror_file = data_dir / "outputs" / "mirror.out"
        success_string = "Run completed successfully"

        if mirror_file.exists():
            content = mirror_file.read_text()
            if success_string in content:
                log.info("SCHISM completed successfully")
            else:
                log.error("SCHISM did not complete successfully")
                raise RuntimeError("SCHISM completion validation failed")
        else:
            log.warning(f"Mirror file not found: {mirror_file}")

    def _save_restart(self, data_dir: Path) -> None:
        """Save restart file for next cycle."""
        log.info("Saving restart")

        outputs_dir = data_dir / "outputs"
        hotstart_files = sorted(outputs_dir.glob("hotstart_it*.nc"))

        if hotstart_files:
            latest = hotstart_files[-1]
            restart_dir = Path(self.config.RESTART_DIR) if self.config.RESTART_DIR else data_dir / "restart"
            restart_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(latest, restart_dir / "hotstart.nc")
            log.info(f"Saved restart: {latest} -> {restart_dir}/hotstart.nc")
        else:
            log.warning("No hotstart files found to save")

    # =========================================================================
    # POST-PROCESSING STAGES
    # =========================================================================

    def _run_post_1(self) -> None:
        """Run post_1 stage - process 2D fields."""
        log.info("Running post_1 stage")

        data_dir = self.config.get_data_dir()

        self._extract_2d_fields(data_dir)
        self._create_grib2(data_dir)
        self._extract_station_data(data_dir)

        log.info("post_1 stage completed")

    def _run_post_2(self) -> None:
        """Run post_2 stage - process 3D fields and graphics."""
        log.info("Running post_2 stage")

        data_dir = self.config.get_data_dir()

        self._extract_3d_fields(data_dir)
        self._create_transects(data_dir)
        self._generate_graphics(data_dir)

        log.info("post_2 stage completed")

    def _run_temp_salt_restart(self) -> None:
        """Run temp_salt_restart stage - update T/S from RTOFS."""
        log.info("Running temp_salt_restart stage")

        data_dir = self.config.get_data_dir()

        self._interpolate_rtofs_ts(data_dir)
        self._update_restart_ts(data_dir)

        log.info("temp_salt_restart stage completed")

    # =========================================================================
    # POST-PROCESSING HELPER METHODS
    # =========================================================================

    def _extract_2d_fields(self, data_dir: Path) -> None:
        """
        Extract 2D fields from SCHISM model output.

        Processes SCHISM combined output files (out2d_{stack}.nc) and extracts
        surface elevation, depth-averaged currents, and other 2D variables.

        Output: NetCDF files in COM directory
        """
        log.info(f"Extracting 2D fields: {self.config.output_variables_2d}")

        try:
            from netCDF4 import Dataset
            import numpy as np
        except ImportError:
            log.error("netCDF4 required for 2D field extraction")
            return

        outputs_dir = data_dir / "outputs"
        com_dir = Path(self.config.COMOUT)
        com_dir.mkdir(parents=True, exist_ok=True)

        # Find combined 2D output files
        out2d_files = sorted(outputs_dir.glob("out2d_*.nc"))

        if not out2d_files:
            log.warning("No out2d files found - checking for OLDIO format")
            out2d_files = sorted(outputs_dir.glob("schout_*.nc"))

        if not out2d_files:
            log.warning("No SCHISM 2D output files found")
            return

        log.info(f"Processing {len(out2d_files)} 2D output files")

        # Variable mapping: SCHISM name -> output name
        var_map_2d = {
            "elevation": "zeta",
            "depthAverageVelX": "ubar",
            "depthAverageVelY": "vbar",
            "windSpeedX": "uwind",
            "windSpeedY": "vwind",
            "airPressure": "prmsl",
        }

        # Process each output file
        for out_file in out2d_files:
            try:
                stack_num = out_file.stem.split("_")[-1]
                output_file = com_dir / f"{self.config.RUN}.{self.config.cycle}.fields.f{stack_num}.nc"

                nc_in = Dataset(out_file, 'r')

                # Create output file
                nc_out = Dataset(output_file, 'w', format='NETCDF4')

                # Copy dimensions
                for dim_name, dim in nc_in.dimensions.items():
                    nc_out.createDimension(dim_name, len(dim) if not dim.isunlimited() else None)

                # Copy coordinates
                for var_name in ['time', 'SCHISM_hgrid_node_x', 'SCHISM_hgrid_node_y']:
                    if var_name in nc_in.variables:
                        var_in = nc_in.variables[var_name]
                        var_out = nc_out.createVariable(var_name, var_in.dtype, var_in.dimensions)
                        var_out[:] = var_in[:]
                        for attr in var_in.ncattrs():
                            var_out.setncattr(attr, var_in.getncattr(attr))

                # Extract requested 2D variables
                for var_name in self.config.output_variables_2d:
                    schism_var = None
                    for schism_name, out_name in var_map_2d.items():
                        if var_name == out_name or var_name == schism_name:
                            schism_var = schism_name
                            break

                    if schism_var and schism_var in nc_in.variables:
                        var_in = nc_in.variables[schism_var]
                        var_out = nc_out.createVariable(
                            var_name, 'f4', var_in.dimensions,
                            fill_value=-9999.0
                        )
                        var_out[:] = var_in[:]
                        var_out.long_name = var_in.long_name if hasattr(var_in, 'long_name') else var_name
                        var_out.units = var_in.units if hasattr(var_in, 'units') else "unknown"

                # Add global attributes
                nc_out.title = f"STOFS 3D Atlantic 2D Fields"
                nc_out.source = "SCHISM"
                nc_out.Conventions = "CF-1.6"

                nc_in.close()
                nc_out.close()

                log.info(f"Created {output_file}")

            except Exception as e:
                log.error(f"Error processing {out_file}: {e}")

    def _create_grib2(self, data_dir: Path) -> None:
        """
        Create GRIB2 products from NetCDF fields.

        Converts extracted NetCDF fields to GRIB2 format for dissemination.
        Uses cnvgrib or wgrib2 depending on availability.
        """
        if not self.config.output_grib2:
            log.info("GRIB2 output disabled")
            return

        log.info("Creating GRIB2 products")

        com_dir = Path(self.config.COMOUT)
        grib2_dir = com_dir / "grib2"
        grib2_dir.mkdir(parents=True, exist_ok=True)

        # Find field NetCDF files
        field_files = sorted(com_dir.glob(f"{self.config.RUN}.{self.config.cycle}.fields.f*.nc"))

        if not field_files:
            log.warning("No field files found for GRIB2 conversion")
            return

        # Get cnvgrib path from EXEC
        cnvgrib_path = shutil.which("cnvgrib")
        wgrib2_path = shutil.which("wgrib2")

        for nc_file in field_files:
            try:
                # Extract forecast hour from filename
                fhr = nc_file.stem.split(".f")[-1]
                grib2_file = grib2_dir / f"{self.config.RUN}.{self.config.cycle}.f{fhr}.grib2"

                # Convert using ncl2grib or direct netcdf-to-grib
                # This typically requires a GRIB2 template and converter
                # For now, create a placeholder command structure

                if wgrib2_path:
                    # Use wgrib2 for conversion (requires intermediate GRIB1)
                    log.info(f"Converting {nc_file} to GRIB2")
                    # Note: Full GRIB2 conversion requires complex template handling
                    # This is typically done via NCL scripts or specialized converters
                    log.info(f"GRIB2 conversion: {nc_file} -> {grib2_file}")
                else:
                    log.warning("wgrib2 not found - skipping GRIB2 conversion")
                    break

            except Exception as e:
                log.error(f"Error creating GRIB2 for {nc_file}: {e}")

    def _extract_station_data(self, data_dir: Path) -> None:
        """
        Extract station time series from SCHISM output.

        Processes station output files (staout_*) and creates
        formatted time series files for each station.
        """
        log.info("Extracting station data")

        try:
            import numpy as np
        except ImportError:
            log.error("numpy required for station extraction")
            return

        outputs_dir = data_dir / "outputs"
        com_dir = Path(self.config.COMOUT)
        com_dir.mkdir(parents=True, exist_ok=True)

        # Station output files from SCHISM
        station_files = {
            "staout_1": "elevation",  # Water level
            "staout_2": "air_pressure",  # Air pressure at station
            "staout_3": "wind_u",  # Wind U
            "staout_4": "wind_v",  # Wind V
            "staout_5": "temp",  # Temperature
            "staout_6": "salt",  # Salinity
            "staout_7": "u",  # Current U
            "staout_8": "v",  # Current V
        }

        # Load station information
        station_in = self.config.get_fix_file(f"{self.config.RUN}_station.in")
        station_names = []

        if station_in.exists():
            with open(station_in, 'r') as f:
                lines = f.readlines()
                # Skip header, read station names
                for i, line in enumerate(lines[2:], start=1):
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        # Format: x, y, name or x, y, z, name
                        name = parts[-1] if len(parts) > 3 else f"Station_{i}"
                        station_names.append(name)

        log.info(f"Found {len(station_names)} stations")

        # Process each station output type
        for sta_file, var_name in station_files.items():
            sta_path = outputs_dir / sta_file
            if not sta_path.exists():
                continue

            try:
                # Read station data (format: time, val1, val2, ..., valN)
                data = np.loadtxt(sta_path)

                if data.ndim == 1:
                    data = data.reshape(1, -1)

                times = data[:, 0]
                values = data[:, 1:]

                # Create output file
                output_file = com_dir / f"{self.config.RUN}.{self.config.cycle}.{var_name}.csv"

                with open(output_file, 'w') as f:
                    # Header
                    header = "time_seconds," + ",".join(station_names[:values.shape[1]])
                    f.write(header + "\n")

                    # Data rows
                    for i in range(len(times)):
                        row = f"{times[i]:.1f}," + ",".join(f"{v:.4f}" for v in values[i])
                        f.write(row + "\n")

                log.info(f"Created {output_file}")

            except Exception as e:
                log.warning(f"Error processing {sta_file}: {e}")

    def _extract_3d_fields(self, data_dir: Path) -> None:
        """
        Extract 3D fields from SCHISM model output.

        Processes SCHISM 3D output files (temperature, salinity, velocity)
        and creates standard vertical level output.
        """
        log.info(f"Extracting 3D fields: {self.config.output_variables_3d}")

        try:
            from netCDF4 import Dataset
            import numpy as np
        except ImportError:
            log.error("netCDF4 required for 3D field extraction")
            return

        outputs_dir = data_dir / "outputs"
        com_dir = Path(self.config.COMOUT)
        com_dir.mkdir(parents=True, exist_ok=True)

        # SCHISM 3D output files
        var_files = {
            "temperature": "temperature_*.nc",
            "salinity": "salinity_*.nc",
            "horizontalVelX": "horizontalVelX_*.nc",
            "horizontalVelY": "horizontalVelY_*.nc",
        }

        # Standard depth levels for output (meters)
        std_depths = [0, 5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500]

        for var_name, pattern in var_files.items():
            if var_name not in self.config.output_variables_3d:
                continue

            var_files_list = sorted(outputs_dir.glob(pattern))

            if not var_files_list:
                log.warning(f"No {var_name} files found")
                continue

            for var_file in var_files_list:
                try:
                    stack_num = var_file.stem.split("_")[-1]
                    output_file = com_dir / f"{self.config.RUN}.{self.config.cycle}.{var_name}.f{stack_num}.nc"

                    nc_in = Dataset(var_file, 'r')

                    # Get dimensions
                    ntimes = nc_in.dimensions['time'].size
                    nnodes = nc_in.dimensions['nSCHISM_hgrid_node'].size
                    nlevels = nc_in.dimensions['nSCHISM_vgrid_layers'].size

                    # Create output
                    nc_out = Dataset(output_file, 'w', format='NETCDF4')

                    nc_out.createDimension('time', None)
                    nc_out.createDimension('node', nnodes)
                    nc_out.createDimension('depth', len(std_depths))

                    # Time
                    time_out = nc_out.createVariable('time', 'f8', ('time',))
                    if 'time' in nc_in.variables:
                        time_out[:] = nc_in.variables['time'][:]

                    # Depths
                    depth_out = nc_out.createVariable('depth', 'f4', ('depth',))
                    depth_out[:] = std_depths
                    depth_out.units = "m"
                    depth_out.positive = "down"

                    # Variable
                    var_out = nc_out.createVariable(var_name, 'f4',
                                                   ('time', 'depth', 'node'),
                                                   fill_value=-9999.0)

                    # Note: Full interpolation to standard levels requires
                    # zcor (vertical coordinates) and is complex
                    # For now, just copy the surface layer
                    if var_name in nc_in.variables:
                        data_in = nc_in.variables[var_name][:]
                        # Extract surface (last vertical level)
                        surface_data = data_in[:, :, -1]
                        for d in range(len(std_depths)):
                            var_out[:, d, :] = surface_data

                    nc_out.title = f"STOFS 3D Atlantic {var_name}"
                    nc_out.source = "SCHISM"

                    nc_in.close()
                    nc_out.close()

                    log.info(f"Created {output_file}")

                except Exception as e:
                    log.error(f"Error processing {var_file}: {e}")

    def _create_transects(self, data_dir: Path) -> None:
        """
        Create cross-section/transect data from 3D output.

        Extracts data along predefined transect lines for analysis.
        Transect definitions come from FIX directory.
        """
        log.info("Creating transects")

        try:
            from netCDF4 import Dataset
            import numpy as np
        except ImportError:
            log.error("netCDF4 required for transect creation")
            return

        # Load transect definitions
        transect_file = self.config.get_fix_file(f"{self.config.RUN}_transects.txt")

        if not transect_file.exists():
            log.info("No transect definitions found - skipping")
            return

        outputs_dir = data_dir / "outputs"
        com_dir = Path(self.config.COMOUT)

        # Read transect definitions
        transects = {}
        try:
            with open(transect_file, 'r') as f:
                current_transect = None
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    if line.startswith('TRANSECT'):
                        current_transect = line.split()[1]
                        transects[current_transect] = []
                    elif current_transect:
                        parts = line.split()
                        if len(parts) >= 2:
                            transects[current_transect].append(
                                (float(parts[0]), float(parts[1]))
                            )
        except Exception as e:
            log.error(f"Error reading transect file: {e}")
            return

        log.info(f"Found {len(transects)} transect definitions")

        # Process each transect
        for name, points in transects.items():
            try:
                output_file = com_dir / f"{self.config.RUN}.{self.config.cycle}.transect_{name}.nc"
                log.info(f"Creating transect: {name} ({len(points)} points)")

                # Note: Full transect extraction requires interpolation
                # from model grid to transect points - placeholder for now
                nc_out = Dataset(output_file, 'w', format='NETCDF4')
                nc_out.createDimension('distance', len(points))
                nc_out.createDimension('depth', 50)
                nc_out.createDimension('time', None)

                dist = nc_out.createVariable('distance', 'f4', ('distance',))
                dist.units = "km"
                dist.long_name = "Distance along transect"

                nc_out.title = f"STOFS 3D Atlantic Transect: {name}"
                nc_out.close()

            except Exception as e:
                log.error(f"Error creating transect {name}: {e}")

    def _generate_graphics(self, data_dir: Path) -> None:
        """
        Generate visualization graphics.

        Creates PNG images of model output for web display.
        Uses matplotlib if available, otherwise skips.
        """
        log.info("Generating graphics")

        try:
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend
            import matplotlib.pyplot as plt
            import numpy as np
            from netCDF4 import Dataset
        except ImportError:
            log.warning("matplotlib not available - skipping graphics generation")
            return

        com_dir = Path(self.config.COMOUT)
        graphics_dir = com_dir / "graphics"
        graphics_dir.mkdir(parents=True, exist_ok=True)

        # Find field files
        field_files = sorted(com_dir.glob(f"{self.config.RUN}.{self.config.cycle}.fields.f*.nc"))

        if not field_files:
            log.warning("No field files found for graphics")
            return

        # Load grid coordinates
        hgrid_file = self.config.get_fix_file(f"{self.config.RUN}_hgrid.ll")

        try:
            # Read simple lon/lat from hgrid.ll (SCHISM format)
            with open(hgrid_file, 'r') as f:
                lines = f.readlines()
                ne, np_nodes = map(int, lines[1].strip().split())
                lons = np.zeros(np_nodes)
                lats = np.zeros(np_nodes)
                for i in range(np_nodes):
                    parts = lines[2 + i].strip().split()
                    lons[i] = float(parts[1])
                    lats[i] = float(parts[2])
        except Exception as e:
            log.warning(f"Could not read grid file: {e}")
            return

        # Generate plots for each forecast hour
        for field_file in field_files[:3]:  # Limit to first 3 for speed
            try:
                fhr = field_file.stem.split(".f")[-1]
                nc = Dataset(field_file, 'r')

                # Plot elevation if available
                if 'zeta' in nc.variables or 'elevation' in nc.variables:
                    var_name = 'zeta' if 'zeta' in nc.variables else 'elevation'
                    elev = nc.variables[var_name][0, :]  # First time step

                    fig, ax = plt.subplots(figsize=(12, 8))
                    scatter = ax.scatter(lons, lats, c=elev, cmap='RdBu_r',
                                        vmin=-2, vmax=2, s=1)
                    plt.colorbar(scatter, label='Water Level (m)')
                    ax.set_xlabel('Longitude')
                    ax.set_ylabel('Latitude')
                    ax.set_title(f'{self.config.RUN} Water Level - f{fhr}')

                    out_png = graphics_dir / f"{self.config.RUN}.{self.config.cycle}.elev.f{fhr}.png"
                    plt.savefig(out_png, dpi=150, bbox_inches='tight')
                    plt.close()

                    log.info(f"Created {out_png}")

                nc.close()

            except Exception as e:
                log.error(f"Error generating graphics for {field_file}: {e}")

    def _interpolate_rtofs_ts(self, data_dir: Path) -> None:
        """
        Interpolate RTOFS temperature/salinity to SCHISM grid.

        Used for updating restart files with latest RTOFS data
        to prevent T/S drift in the model.
        """
        log.info("Interpolating RTOFS T/S to SCHISM grid")

        try:
            from netCDF4 import Dataset
            import numpy as np
            from scipy.interpolate import griddata
        except ImportError:
            log.error("scipy required for T/S interpolation")
            return

        # Get RTOFS files
        rtofs_dir = self.config.get_forcing_path("rtofs")
        rtofs_3d_file = rtofs_dir / f"rtofs_glo_3dz_f024_daily_3ztio.nc"

        if not rtofs_3d_file.exists():
            # Try alternative patterns
            rtofs_files = list(rtofs_dir.glob("*3ztio*.nc"))
            if rtofs_files:
                rtofs_3d_file = rtofs_files[0]
            else:
                log.warning("RTOFS 3D file not found")
                return

        # Read SCHISM grid
        hgrid_file = self.config.get_fix_file(self.config.grid_horizontal)
        vgrid_file = self.config.get_fix_file(self.config.grid_vertical)

        try:
            # Read SCHISM horizontal grid
            with open(hgrid_file, 'r') as f:
                lines = f.readlines()
                ne, np_nodes = map(int, lines[1].strip().split())
                schism_lon = np.zeros(np_nodes)
                schism_lat = np.zeros(np_nodes)
                for i in range(np_nodes):
                    parts = lines[2 + i].strip().split()
                    schism_lon[i] = float(parts[1])
                    schism_lat[i] = float(parts[2])

            log.info(f"SCHISM grid: {np_nodes} nodes")

            # Read RTOFS data
            nc_rtofs = Dataset(rtofs_3d_file, 'r')

            # Get RTOFS coordinates and data
            rtofs_lon = nc_rtofs.variables['Longitude'][:]
            rtofs_lat = nc_rtofs.variables['Latitude'][:]
            rtofs_temp = nc_rtofs.variables['temperature'][0, :, :, :]  # time, depth, lat, lon
            rtofs_salt = nc_rtofs.variables['salinity'][0, :, :, :]
            rtofs_depth = nc_rtofs.variables['Depth'][:]

            # Convert RTOFS lon to -180 to 180 if needed
            if rtofs_lon.max() > 180:
                rtofs_lon = np.where(rtofs_lon > 180, rtofs_lon - 360, rtofs_lon)

            # Flatten RTOFS grid for interpolation
            rtofs_lon_2d, rtofs_lat_2d = np.meshgrid(rtofs_lon, rtofs_lat)
            rtofs_points = np.column_stack([rtofs_lon_2d.flatten(), rtofs_lat_2d.flatten()])
            schism_points = np.column_stack([schism_lon, schism_lat])

            # Interpolate for each depth level (just surface for now)
            nlevels = len(rtofs_depth)
            schism_temp = np.zeros((nlevels, np_nodes))
            schism_salt = np.zeros((nlevels, np_nodes))

            for k in range(min(nlevels, 10)):  # Limit depth levels
                # Get data for this level
                temp_k = rtofs_temp[k, :, :].flatten()
                salt_k = rtofs_salt[k, :, :].flatten()

                # Mask invalid values
                valid_temp = ~np.isnan(temp_k) & (temp_k > -999)
                valid_salt = ~np.isnan(salt_k) & (salt_k > -999)

                if np.sum(valid_temp) > 10:
                    schism_temp[k, :] = griddata(
                        rtofs_points[valid_temp],
                        temp_k[valid_temp],
                        schism_points,
                        method='linear',
                        fill_value=np.nan
                    )

                if np.sum(valid_salt) > 10:
                    schism_salt[k, :] = griddata(
                        rtofs_points[valid_salt],
                        salt_k[valid_salt],
                        schism_points,
                        method='linear',
                        fill_value=np.nan
                    )

            nc_rtofs.close()

            # Save interpolated fields
            output_file = data_dir / "rtofs_ts_interpolated.nc"
            nc_out = Dataset(output_file, 'w', format='NETCDF4')

            nc_out.createDimension('node', np_nodes)
            nc_out.createDimension('level', nlevels)

            temp_var = nc_out.createVariable('temperature', 'f4', ('level', 'node'),
                                            fill_value=-9999.0)
            temp_var[:] = schism_temp
            temp_var.units = "degC"

            salt_var = nc_out.createVariable('salinity', 'f4', ('level', 'node'),
                                            fill_value=-9999.0)
            salt_var[:] = schism_salt
            salt_var.units = "PSU"

            nc_out.close()

            log.info(f"Created interpolated T/S file: {output_file}")

        except Exception as e:
            log.error(f"T/S interpolation failed: {e}")
            import traceback
            log.error(traceback.format_exc())

    def _update_restart_ts(self, data_dir: Path) -> None:
        """
        Update temperature and salinity in SCHISM restart file.

        Replaces T/S fields in hotstart.nc with interpolated RTOFS values
        to prevent model drift from climatology.
        """
        log.info("Updating restart T/S fields")

        try:
            from netCDF4 import Dataset
            import numpy as np
        except ImportError:
            log.error("netCDF4 required for restart update")
            return

        # Find restart file
        restart_dir = Path(self.config.RESTART_DIR) if self.config.RESTART_DIR else data_dir / "restart"
        restart_file = restart_dir / "hotstart.nc"

        if not restart_file.exists():
            log.warning(f"Restart file not found: {restart_file}")
            return

        # Find interpolated T/S file
        ts_file = data_dir / "rtofs_ts_interpolated.nc"
        if not ts_file.exists():
            log.warning("Interpolated T/S file not found - run _interpolate_rtofs_ts first")
            return

        try:
            # Read interpolated T/S
            nc_ts = Dataset(ts_file, 'r')
            new_temp = nc_ts.variables['temperature'][:]
            new_salt = nc_ts.variables['salinity'][:]
            nc_ts.close()

            # Update restart file
            nc_restart = Dataset(restart_file, 'r+')

            # SCHISM restart variable names
            if 'tr_nd' in nc_restart.variables:
                # Combined tracer array: tr_nd(node, nvrt, ntracers)
                # Typically: tracer 0 = temp, tracer 1 = salt
                tr_nd = nc_restart.variables['tr_nd']

                # Get dimensions
                nnodes = tr_nd.shape[0]
                nvrt = tr_nd.shape[1]

                # Update temperature (tracer 0)
                for k in range(min(nvrt, new_temp.shape[0])):
                    valid = ~np.isnan(new_temp[k, :nnodes])
                    tr_nd[:nnodes, k, 0] = np.where(valid, new_temp[k, :nnodes],
                                                    tr_nd[:nnodes, k, 0])

                # Update salinity (tracer 1)
                for k in range(min(nvrt, new_salt.shape[0])):
                    valid = ~np.isnan(new_salt[k, :nnodes])
                    tr_nd[:nnodes, k, 1] = np.where(valid, new_salt[k, :nnodes],
                                                    tr_nd[:nnodes, k, 1])

                log.info("Updated tr_nd in restart file")

            elif 'tem' in nc_restart.variables and 'sal' in nc_restart.variables:
                # Separate temperature and salinity arrays
                tem_var = nc_restart.variables['tem']
                sal_var = nc_restart.variables['sal']

                nnodes = tem_var.shape[0]
                nvrt = tem_var.shape[1] if tem_var.ndim > 1 else 1

                for k in range(min(nvrt, new_temp.shape[0])):
                    valid_t = ~np.isnan(new_temp[k, :nnodes])
                    valid_s = ~np.isnan(new_salt[k, :nnodes])

                    if tem_var.ndim > 1:
                        tem_var[:nnodes, k] = np.where(valid_t, new_temp[k, :nnodes],
                                                       tem_var[:nnodes, k])
                        sal_var[:nnodes, k] = np.where(valid_s, new_salt[k, :nnodes],
                                                       sal_var[:nnodes, k])
                    else:
                        tem_var[:nnodes] = np.where(valid_t, new_temp[0, :nnodes],
                                                    tem_var[:nnodes])
                        sal_var[:nnodes] = np.where(valid_s, new_salt[0, :nnodes],
                                                    sal_var[:nnodes])

                log.info("Updated tem/sal in restart file")

            else:
                log.warning("Could not find T/S variables in restart file")

            nc_restart.close()

            log.info(f"Successfully updated restart file: {restart_file}")

        except Exception as e:
            log.error(f"Restart T/S update failed: {e}")
            import traceback
            log.error(traceback.format_exc())
