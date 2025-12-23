"""
STOFS Configuration Module - YAML-First, NCO Compliant

Generalized configuration management for NOS ocean forecast systems.
Supports multiple forecast systems (STOFS 3D Atlantic, SECOFS, etc.)
through YAML configuration files.

Configuration Priority:
1. System environment variables (set by J-job) - highest priority
2. YAML 'environment' section (sets env vars if not already set)
3. YAML configuration sections (model, forcing, output, etc.)
4. Default values - lowest priority

Supported Systems:
- STOFS 3D Atlantic (STOFS)
- STOFS 3D Pacific (STOFS)
- SECOFS (COMF)
- Other SCHISM-based systems
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from yaml import safe_load
except ImportError:
    safe_load = None

log = logging.getLogger(__name__)


@dataclass
class StofsConfig:
    """
    Generalized configuration class for NOS ocean forecast workflows.

    This class supports multiple forecast systems through YAML configuration.
    The same Python workflow code can run different systems by switching
    the YAML config file.

    Attributes:
        config_file: Path to YAML configuration file (recommended)

    Example:
        # For STOFS 3D Atlantic
        config = StofsConfig.from_yaml("stofs_3d_atl_config.yaml")

        # For SECOFS
        config = StofsConfig.from_yaml("secofs_config.yaml")
    """

    config_file: Optional[str] = None

    def __post_init__(self) -> None:
        """Initialize configuration from YAML and environment."""
        # Load YAML configuration (primary source)
        self._yaml_config: Dict[str, Any] = {}
        if self.config_file and safe_load:
            config_path = Path(self.config_file)
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    self._yaml_config = safe_load(f) or {}
                log.info(f"Loaded configuration from {config_path}")
            else:
                log.warning(f"Config file not found: {config_path}")

        # Step 1: Apply YAML environment section (sets env vars if not set)
        self._apply_yaml_environment()

        # Step 2: Initialize from environment (now includes YAML env vars)
        self._init_from_environment()

        # Step 3: Load system identification from YAML
        self._load_system_info()

        # Step 4: Load model-specific configuration from YAML
        self._load_model_config()

        # Step 5: Load forcing configuration from YAML
        self._load_forcing_config()

        # Step 6: Load output configuration from YAML
        self._load_output_config()

    def _apply_yaml_environment(self) -> None:
        """
        Apply environment variables from YAML 'environment' section.

        This allows YAML to be the single source of truth while still
        respecting pre-existing environment variables from J-jobs.
        """
        yaml_env = self._yaml_config.get("environment", {})
        for key, value in yaml_env.items():
            if key not in os.environ:
                os.environ[key] = str(value)
                log.debug(f"Set env from YAML: {key}={value}")

    def _init_from_environment(self) -> None:
        """Initialize configuration from NCO environment variables."""
        # Basic NCO variables
        self.NET = os.environ.get("NET", "stofs")
        self.RUN = os.environ.get("RUN", "stofs_3d_atl")
        self.cyc = int(os.environ.get("cyc", "12"))
        self.cycle = f"t{self.cyc:02d}z"
        self.PDY = os.environ.get("PDY", datetime.now().strftime("%Y%m%d"))
        self.jobid = os.environ.get("jobid", f"stofs_{os.getpid()}")
        self.envir = os.environ.get("envir", "prod")

        # NCO control flags
        self.SENDCOM = os.environ.get("SENDCOM", "YES")
        self.SENDDBN = os.environ.get("SENDDBN", "YES")
        self.KEEPDATA = os.environ.get("KEEPDATA", "NO")

        # NCO directory paths (set by J-job or module)
        self.HOMEstofs = os.environ.get("HOMEstofs", os.environ.get("HOMEnosofs", ""))
        self.EXECstofs3d = os.environ.get("EXECstofs3d", os.environ.get("EXECnosofs", ""))
        self.FIXstofs3d = os.environ.get("FIXstofs3d", os.environ.get("FIXnosofs", ""))
        self.PARMstofs3d = os.environ.get("PARMstofs3d", os.environ.get("PARMnosofs", ""))
        self.USHstofs3d = os.environ.get("USHstofs3d", os.environ.get("USHnosofs", ""))
        self.SCRIstofs3d = os.environ.get("SCRIstofs3d", os.environ.get("SCRInosofs", ""))

        # Working and COM directories
        self.DATA = os.environ.get("DATA", "")
        self.DATAROOT = os.environ.get("DATAROOT", "/lfs/h1/ops/prod/tmp")
        self.COMIN = os.environ.get("COMIN", "")
        self.COMOUT = os.environ.get("COMOUT", "")
        self.COMOUTrerun = os.environ.get("COMOUTrerun", "")
        self.RESTART_DIR = os.environ.get("RESTART_DIR", "")

        # Forcing data paths
        self.COMINgfs = os.environ.get("COMINgfs", "")
        self.COMINhrrr = os.environ.get("COMINhrrr", "")
        self.COMINnam = os.environ.get("COMINnam", "")  # For SECOFS
        self.COMINrtofs = os.environ.get("COMINrtofs", "")
        self.COMINnwm = os.environ.get("COMINnwm", "")
        self.COMINadt = os.environ.get("COMINadt", "")  # ADT satellite data
        self.DCOMROOT = os.environ.get("DCOMROOT", "")  # St. Lawrence River data

        # Model execution parameters (can be overridden by YAML)
        self.NPROCS = int(os.environ.get("NPROCS", "0"))
        self.NSCRIBES = int(os.environ.get("NSCRIBES", "0"))
        self.NHOT = int(os.environ.get("NHOT", "1"))

    def _load_system_info(self) -> None:
        """Load system identification from YAML."""
        system = self._yaml_config.get("system", {})
        self.system_name = system.get("name", self.RUN.upper())
        self.system_version = system.get("version", "1.0.0")
        self.system_description = system.get("description", "")
        self.model_type = system.get("model_type", "schism")
        self.domain = system.get("domain", "unknown")
        self.framework = system.get("framework", "stofs")  # stofs or comf

    def _load_model_config(self) -> None:
        """Load model configuration from YAML."""
        model = self._yaml_config.get("model", {})

        # Executable
        self.executable = model.get("executable", "pschism_WCOSS2")

        # Grid files
        grid = model.get("grid", {})
        self.grid_horizontal = grid.get("horizontal", f"{self.RUN}_hgrid.gr3")
        self.grid_vertical = grid.get("vertical", f"{self.RUN}_vgrid.in")

        # Resources (YAML provides defaults, env vars override)
        resources = model.get("resources", {})
        if self.NPROCS == 0:
            self.NPROCS = resources.get("nprocs", 960)
        if self.NSCRIBES == 0:
            self.NSCRIBES = resources.get("nscribes", 8)
        self.nodes = resources.get("nodes", 40)
        self.ppn = resources.get("ppn", 24)

        # Time stepping
        self.dt = model.get("dt", 150.0)

        # Hotstart
        hotstart = model.get("hotstart", {})
        self.hotstart_enabled = hotstart.get("enabled", True)
        self.ihot = hotstart.get("ihot", 1)

        # Domain configuration
        domain = self._yaml_config.get("domain", {})
        self.lon_min = domain.get("lon_min", -180.0)
        self.lon_max = domain.get("lon_max", 180.0)
        self.lat_min = domain.get("lat_min", -90.0)
        self.lat_max = domain.get("lat_max", 90.0)
        self.nvrt = domain.get("nvrt", 51)

    def _load_forcing_config(self) -> None:
        """Load forcing configuration from YAML."""
        self.forcing = self._yaml_config.get("forcing", {})

        # Atmospheric forcing
        atmos = self.forcing.get("atmospheric", {})
        self.gfs_enabled = atmos.get("gfs", {}).get("enabled", True)
        self.hrrr_enabled = atmos.get("hrrr", {}).get("enabled", False)
        self.nam_enabled = atmos.get("nam", {}).get("enabled", False)

        # River forcing
        river = self.forcing.get("river", {})
        self.nwm_enabled = river.get("nwm", {}).get("enabled", True)
        self.num_rivers = river.get("nwm", {}).get("num_rivers", 534)

        # Ocean boundary
        ocean = self.forcing.get("ocean", {})
        self.rtofs_enabled = ocean.get("rtofs", {}).get("enabled", True)

        # Tides
        tides = self.forcing.get("tides", {})
        self.tides_enabled = tides.get("enabled", True)
        self.tidal_constituents = tides.get("constituents", ["M2", "S2", "N2", "K1", "O1"])

    def _load_output_config(self) -> None:
        """Load output configuration from YAML."""
        output = self._yaml_config.get("output", {})
        self.output_interval_2d = output.get("interval_2d", 3600)
        self.output_interval_3d = output.get("interval_3d", 3600)
        self.output_interval_station = output.get("interval_station", 360)

        self.output_variables_2d = output.get("variables_2d", ["elev", "dahv"])
        self.output_variables_3d = output.get("variables_3d", ["temp", "salt"])

        formats = output.get("formats", {})
        self.output_netcdf = formats.get("netcdf", True)
        self.output_grib2 = formats.get("grib2", True)

        # Cycle configuration
        cycles = self._yaml_config.get("cycles", {})
        self.cycle_hours = cycles.get("hours", [0, 6, 12, 18])
        self.nowcast_length = cycles.get("nowcast_length", 6)
        self.forecast_length = cycles.get("forecast_length", 48)

        # Stage configuration
        self.stages = self._yaml_config.get("stages", {})

        # Load native mode scripts configuration
        self._load_native_scripts_config()

        # Legacy script execution mode
        self._load_legacy_config()

    def _load_native_scripts_config(self) -> None:
        """
        Load native mode preprocessing scripts configuration from YAML.

        This allows different forecast systems (STOFS, SECOFS, etc.) to define
        their own preprocessing scripts in YAML configuration files.

        YAML structure:
            native:
              prep_scripts:
                - name: "script_name.sh"
                  description: "What this script does"
                  timeout: 300
                  optional: false
        """
        native = self._yaml_config.get("native", {})

        # Load preprocessing scripts (default to empty - workflow.py has fallback)
        self.prep_scripts: List[Dict[str, Any]] = native.get("prep_scripts", [])

        # Load optional scripts list (scripts that won't fail the workflow if they error)
        self.optional_scripts: List[str] = native.get("optional_scripts", [])

        # Load static files configuration (files to link from FIX directory)
        self.static_files: List[Dict[str, str]] = native.get("static_files", [])

        # Load restart configuration
        restart = native.get("restart", {})
        self.restart_min_size = restart.get("min_size_gb", 20) * 1024**3  # Convert to bytes

        if self.prep_scripts:
            log.info(f"Loaded {len(self.prep_scripts)} prep scripts from YAML")
        if self.optional_scripts:
            log.debug(f"Optional scripts: {self.optional_scripts}")

    def _load_legacy_config(self) -> None:
        """
        Load legacy script execution configuration from YAML.

        This allows the Python workflow to delegate to the original
        STOFS shell scripts from /ush instead of using Python
        forcing generators.
        """
        legacy = self._yaml_config.get("legacy", {})

        # Master switch: use legacy shell scripts instead of Python modules
        self.use_legacy_scripts = legacy.get("enabled", False)

        # Path to legacy USH directory (STOFS shell scripts)
        self.legacy_ush_dir = legacy.get("ush_dir", "")
        if not self.legacy_ush_dir:
            # Try to find STOFS ush directory relative to HOMEstofs
            if self.HOMEstofs:
                possible_path = Path(self.HOMEstofs).parent / "STOFS" / "ush" / "stofs_3d_atl"
                if possible_path.exists():
                    self.legacy_ush_dir = str(possible_path)

        # Path to legacy Python scripts (pysh directory)
        self.legacy_pysh_dir = legacy.get("pysh_dir", "")
        if not self.legacy_pysh_dir and self.legacy_ush_dir:
            pysh_path = Path(self.legacy_ush_dir) / "pysh"
            if pysh_path.exists():
                self.legacy_pysh_dir = str(pysh_path)

        # Path to legacy FIX directory (if different from FIXstofs3d)
        self.legacy_fix_dir = legacy.get("fix_dir", self.FIXstofs3d)

        # Individual script overrides (use legacy for specific forcing types)
        scripts = legacy.get("scripts", {})
        self.legacy_river_enabled = scripts.get("river", self.use_legacy_scripts)
        self.legacy_gfs_enabled = scripts.get("gfs", self.use_legacy_scripts)
        self.legacy_hrrr_enabled = scripts.get("hrrr", self.use_legacy_scripts)
        self.legacy_obc_enabled = scripts.get("obc", self.use_legacy_scripts)
        self.legacy_tides_enabled = scripts.get("tides", self.use_legacy_scripts)

        # Script names (can be customized)
        script_names = legacy.get("script_names", {})
        self.legacy_script_river = script_names.get(
            "river", "stofs_3d_atl_create_river_forcing_nwm.sh"
        )
        self.legacy_script_gfs = script_names.get(
            "gfs", "stofs_3d_atl_create_surface_forcing_gfs.sh"
        )
        self.legacy_script_hrrr = script_names.get(
            "hrrr", "stofs_3d_atl_create_surface_forcing_hrrr.sh"
        )
        self.legacy_script_obc = script_names.get(
            "obc", "stofs_3d_atl_create_obc_3d_th.sh"
        )
        self.legacy_script_tides = script_names.get(
            "tides", "stofs_3d_atl_create_bctides_in.sh"
        )

        if self.use_legacy_scripts:
            log.info(f"Legacy script mode ENABLED")
            log.info(f"  Legacy USH dir: {self.legacy_ush_dir}")
            log.info(f"  Legacy pysh dir: {self.legacy_pysh_dir}")

    def get_data_dir(self) -> Path:
        """Get the DATA working directory."""
        if self.DATA:
            return Path(self.DATA)
        return Path(self.DATAROOT) / self.jobid

    def get_fix_file(self, filename: str) -> Path:
        """Get path to a FIX file."""
        return Path(self.FIXstofs3d) / filename

    def get_exec_file(self, filename: str) -> Path:
        """Get path to an executable."""
        return Path(self.EXECstofs3d) / filename

    def get_com_file(self, filename: str, com_type: str = "out") -> Path:
        """
        Get path to a COM file.

        Args:
            filename: Name of the file
            com_type: 'in' for COMIN, 'out' for COMOUT, 'rerun' for COMOUTrerun
        """
        if com_type == "in":
            return Path(self.COMIN) / filename
        elif com_type == "rerun":
            return Path(self.COMOUTrerun) / filename
        return Path(self.COMOUT) / filename

    def get_forcing_path(self, source: str) -> Path:
        """Get path to forcing data source."""
        paths = {
            "gfs": self.COMINgfs,
            "hrrr": self.COMINhrrr,
            "nam": self.COMINnam,
            "rtofs": self.COMINrtofs,
            "nwm": self.COMINnwm,
        }
        return Path(paths.get(source, ""))

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "StofsConfig":
        """
        Create configuration from YAML file.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            StofsConfig instance
        """
        return cls(config_file=yaml_path)

    @classmethod
    def from_environment(cls) -> "StofsConfig":
        """
        Create configuration from environment variables only.

        Returns:
            StofsConfig instance
        """
        return cls()

    # =========================================================================
    # Forcing Configuration Helpers
    # =========================================================================

    def get_forcing_sources(self, forcing_type: str) -> Dict[str, Any]:
        """
        Get configuration for a specific forcing type.

        Args:
            forcing_type: 'atmospheric', 'river', 'ocean', or 'tides'

        Returns:
            Dictionary of forcing source configurations
        """
        return self.forcing.get(forcing_type, {})

    def is_forcing_enabled(self, forcing_type: str, source: str) -> bool:
        """
        Check if a specific forcing source is enabled.

        Args:
            forcing_type: 'atmospheric', 'river', 'ocean', or 'tides'
            source: Source name (e.g., 'gfs', 'hrrr', 'nwm', 'rtofs')

        Returns:
            True if the forcing source is enabled
        """
        sources = self.get_forcing_sources(forcing_type)
        return sources.get(source, {}).get("enabled", False)

    def get_forcing_variables(self, forcing_type: str, source: str) -> List[str]:
        """
        Get list of variables for a forcing source.

        Args:
            forcing_type: 'atmospheric', 'river', 'ocean', or 'tides'
            source: Source name

        Returns:
            List of variable names
        """
        sources = self.get_forcing_sources(forcing_type)
        return sources.get(source, {}).get("variables", [])

    def get_stage_config(self, stage_name: str) -> Dict[str, Any]:
        """
        Get configuration for a workflow stage.

        Args:
            stage_name: Stage name (e.g., 'prep_nowcast', 'now_forecast')

        Returns:
            Stage configuration dictionary
        """
        return self.stages.get(stage_name, {})

    def get_stage_timeout(self, stage_name: str) -> int:
        """
        Get timeout for a workflow stage in seconds.

        Args:
            stage_name: Stage name

        Returns:
            Timeout in seconds (default 3600)
        """
        stage = self.get_stage_config(stage_name)
        return stage.get("timeout", 3600)

    # =========================================================================
    # System Information
    # =========================================================================

    def is_stofs(self) -> bool:
        """Check if this is a STOFS system (STOFS)."""
        return self.framework.lower() == "stofs"

    def is_comf(self) -> bool:
        """Check if this is a COMF system (nosofs)."""
        return self.framework.lower() == "comf"

    def get_system_info(self) -> Dict[str, str]:
        """
        Get system identification information.

        Returns:
            Dictionary with system name, version, model type, domain
        """
        return {
            "name": self.system_name,
            "version": self.system_version,
            "description": self.system_description,
            "model_type": self.model_type,
            "domain": self.domain,
            "framework": self.framework,
        }

    def __repr__(self) -> str:
        """Return string representation of config."""
        return (
            f"StofsConfig(system={self.system_name}, "
            f"model={self.model_type}, domain={self.domain}, "
            f"RUN={self.RUN}, cyc={self.cyc:02d})"
        )
