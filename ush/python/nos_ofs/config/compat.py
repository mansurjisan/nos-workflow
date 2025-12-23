"""
Backward Compatibility Layer

Provides LegacyConfigAdapter to allow old code using the flat OFSConfig
interface to work with the new layered SystemConfig + RuntimeConfig design.

This adapter:
- Exposes flat attributes matching the old OFSConfig interface
- Maps between old and new YAML formats
- Emits deprecation warnings to guide migration

Usage:
    # Old code continues to work
    config = LegacyConfigAdapter.from_yaml("stofs_3d_atl.yaml")
    print(config.ofs_name)    # Still works
    print(config.HOMEnos)     # Still works
    print(config.dt)          # Still works

    # But the new interface is also available
    print(config.system.name)         # New style
    print(config.runtime.home_nos)    # New style
"""

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from .system import SystemConfig
from .runtime import RuntimeConfig
from .unified import OFSConfig


@dataclass
class LegacyConfigAdapter:
    """
    Adapter providing backward compatibility with old OFSConfig interface.

    Wraps the new OFSConfig and exposes attributes matching the old flat
    interface. Emits deprecation warnings when legacy attributes are used.

    Attributes:
        _config: Underlying new-style OFSConfig
        _warned: Track which deprecation warnings have been shown
    """

    _config: OFSConfig
    _yaml_data: Dict[str, Any] = field(default_factory=dict, repr=False)
    _warned: set = field(default_factory=set, repr=False)

    @classmethod
    def from_yaml(
        cls, yaml_file: Union[str, Path], env_override: bool = True
    ) -> "LegacyConfigAdapter":
        """
        Load configuration from YAML file.

        Compatible with old OFSConfig.from_yaml() signature.

        Args:
            yaml_file: Path to YAML configuration file
            env_override: Whether environment variables override YAML values

        Returns:
            LegacyConfigAdapter instance
        """
        yaml_path = Path(yaml_file)

        # Load raw YAML
        with open(yaml_path, "r") as f:
            yaml_data = yaml.safe_load(f)

        # Create new-style config
        try:
            config = OFSConfig.from_yaml(yaml_path, validate=False)
        except Exception:
            # Fall back to building from raw YAML if new format fails
            config = cls._build_from_legacy_yaml(yaml_data)

        adapter = cls(_config=config, _yaml_data=yaml_data)

        # Apply environment overrides if requested
        if env_override:
            adapter._apply_env_overrides()

        return adapter

    @classmethod
    def from_environment(cls) -> "LegacyConfigAdapter":
        """
        Create configuration from environment variables only.

        Returns:
            LegacyConfigAdapter instance
        """
        runtime = RuntimeConfig.from_environment()
        system = SystemConfig()  # Empty system config

        config = OFSConfig.from_components(system, runtime)
        return cls(_config=config)

    @classmethod
    def _build_from_legacy_yaml(cls, data: Dict) -> OFSConfig:
        """Build OFSConfig from legacy YAML format."""
        system = SystemConfig._from_dict(data)
        runtime = RuntimeConfig.from_environment()

        # Apply YAML values to runtime if present
        env_section = data.get("environment", {})
        if env_section.get("HOMEnos"):
            runtime.home_nos = Path(env_section["HOMEnos"])
        if env_section.get("FIXofs"):
            runtime.fix_ofs = Path(env_section["FIXofs"])

        return OFSConfig.from_components(system, runtime)

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to runtime config."""
        env_mappings = {
            "NET": "net",
            "RUN": "run",
            "PDY": "pdy",
            "cyc": "cyc",
            "envir": "envir",
            "HOMEnos": "home_nos",
            "HOMEstofs": "home_nos",
            "FIXofs": "fix_ofs",
            "FIXstofs3d": "fix_ofs",
            "EXECofs": "exec_ofs",
            "EXECstofs3d": "exec_ofs",
            "DATA": "data",
            "COMOUT": "comout",
            "COMOUTrerun": "comout_rerun",
            "COMINgfs": "comin_gfs",
            "COMINhrrr": "comin_hrrr",
            "COMINnam": "comin_nam",
            "COMINrtofs": "comin_rtofs",
            "COMINnwm": "comin_nwm",
            "COMINadt": "comin_adt",
        }

        runtime = self._config.runtime

        for env_var, attr in env_mappings.items():
            if env_var in os.environ:
                value = os.environ[env_var]
                if attr == "cyc":
                    value = int(value)
                elif attr in (
                    "home_nos",
                    "fix_ofs",
                    "exec_ofs",
                    "data",
                    "comout",
                    "comout_rerun",
                    "comin_gfs",
                    "comin_hrrr",
                    "comin_nam",
                    "comin_rtofs",
                    "comin_nwm",
                    "comin_adt",
                ):
                    value = Path(value)
                setattr(runtime, attr, value)

    def _warn_deprecated(self, old_attr: str, new_path: str) -> None:
        """Emit deprecation warning for legacy attribute access."""
        if old_attr not in self._warned:
            self._warned.add(old_attr)
            warnings.warn(
                f"Accessing '{old_attr}' is deprecated. "
                f"Use '{new_path}' instead.",
                DeprecationWarning,
                stacklevel=3,
            )

    # ─────────────────────────────────────────────────────────────────
    # Legacy flat attributes - mapped to new structure
    # ─────────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """System name (new API)."""
        return self._config.system.name

    @property
    def ofs_name(self) -> str:
        self._warn_deprecated("ofs_name", "config.system.name")
        return self._config.system.name

    @property
    def model_type(self) -> str:
        return self._config.system.model_type

    @property
    def run_start(self):
        """Run start datetime (new API)."""
        return self._config.run_start

    @property
    def run_end(self):
        """Run end datetime (new API)."""
        return self._config.run_end

    @property
    def total_run_days(self) -> float:
        """Total run days (new API)."""
        return self._config.total_run_days

    @property
    def n_timesteps(self) -> int:
        """Number of timesteps (new API)."""
        return self._config.n_timesteps

    @property
    def output_prefix(self) -> str:
        """Output prefix (new API)."""
        return self._config.output_prefix

    @property
    def framework(self) -> str:
        return self._config.system.framework

    @property
    def version(self) -> str:
        return self._config.system.version

    @property
    def description(self) -> str:
        return self._config.system.description

    # NCO environment variables
    @property
    def NET(self) -> str:
        self._warn_deprecated("NET", "config.runtime.net")
        return self._config.runtime.net

    @property
    def RUN(self) -> str:
        self._warn_deprecated("RUN", "config.runtime.run")
        return self._config.runtime.run

    @property
    def PDY(self) -> str:
        self._warn_deprecated("PDY", "config.runtime.pdy")
        return self._config.runtime.pdy

    @property
    def cyc(self) -> int:
        return self._config.runtime.cyc

    @property
    def envir(self) -> str:
        return self._config.runtime.envir

    # Directory paths - return strings for legacy compatibility
    @property
    def HOMEnos(self) -> str:
        self._warn_deprecated("HOMEnos", "config.runtime.home_nos")
        return str(self._config.runtime.home_nos or "")

    @property
    def FIXofs(self) -> str:
        self._warn_deprecated("FIXofs", "config.runtime.fix_ofs")
        return str(self._config.runtime.fix_ofs or "")

    @property
    def EXECofs(self) -> str:
        self._warn_deprecated("EXECofs", "config.runtime.exec_ofs")
        return str(self._config.runtime.exec_ofs or "")

    @property
    def PARMofs(self) -> str:
        return str(self._config.runtime.parm_ofs or "")

    @property
    def USHofs(self) -> str:
        return str(self._config.runtime.ush_ofs or "")

    @property
    def DATA(self) -> str:
        self._warn_deprecated("DATA", "config.runtime.data")
        return str(self._config.runtime.data or "")

    @property
    def COMIN(self) -> str:
        return str(self._config.runtime.comin or "")

    @property
    def COMOUT(self) -> str:
        self._warn_deprecated("COMOUT", "config.runtime.comout")
        return str(self._config.runtime.comout or "")

    @property
    def COMOUTrerun(self) -> str:
        return str(self._config.runtime.comout_rerun or "")

    # Input data paths
    @property
    def COMINgfs(self) -> str:
        return str(self._config.runtime.comin_gfs or "")

    @property
    def COMINhrrr(self) -> str:
        return str(self._config.runtime.comin_hrrr or "")

    @property
    def COMINnam(self) -> str:
        return str(self._config.runtime.comin_nam or "")

    @property
    def COMINrtofs(self) -> str:
        return str(self._config.runtime.comin_rtofs or "")

    @property
    def COMINnwm(self) -> str:
        return str(self._config.runtime.comin_nwm or "")

    @property
    def COMINadt(self) -> str:
        return str(self._config.runtime.comin_adt or "")

    # Model configuration
    @property
    def nprocs(self) -> int:
        return self._config.system.resources.nprocs

    @property
    def dt(self) -> float:
        return self._config.system.physics.dt

    @property
    def run_days(self) -> float:
        return self._config.system.total_run_days

    # Grid information
    @property
    def grid_file(self) -> str:
        return self._config.system.grid.horizontal

    @property
    def vgrid_file(self) -> str:
        return self._config.system.grid.vertical or ""

    @property
    def n_levels(self) -> int:
        return self._config.system.grid.n_levels

    # Forcing flags
    @property
    def gfs_enabled(self) -> bool:
        atm = self._config.system.forcing.atmospheric
        return atm.primary == "gfs" or atm.fallback == "gfs"

    @property
    def hrrr_enabled(self) -> bool:
        atm = self._config.system.forcing.atmospheric
        return atm.primary == "hrrr" or atm.fallback == "hrrr"

    @property
    def nam_enabled(self) -> bool:
        atm = self._config.system.forcing.atmospheric
        return atm.primary == "nam" or atm.fallback == "nam"

    @property
    def nwm_enabled(self) -> bool:
        return self._config.system.forcing.river.enabled

    @property
    def rtofs_enabled(self) -> bool:
        return self._config.system.forcing.ocean.enabled

    @property
    def tides_enabled(self) -> bool:
        return self._config.system.forcing.tidal.enabled

    # Legacy flags
    @property
    def use_legacy_scripts(self) -> bool:
        return self._config.system.get_raw("legacy", "enabled", default=False)

    @property
    def legacy_ush_dir(self) -> str:
        return self._config.system.get_raw("legacy", "ush_dir", default="")

    # ─────────────────────────────────────────────────────────────────
    # Legacy methods
    # ─────────────────────────────────────────────────────────────────

    @property
    def cycle(self) -> str:
        """Return cycle string (e.g., 't12z')."""
        return self._config.runtime.cycle_str

    def is_schism(self) -> bool:
        return self._config.is_schism()

    def is_fvcom(self) -> bool:
        return self._config.is_fvcom()

    def is_roms(self) -> bool:
        return self._config.is_roms()

    def is_stofs(self) -> bool:
        return self._config.is_stofs()

    def is_comf(self) -> bool:
        return self._config.is_comf()

    def get_fix_file(self, filename: str) -> Path:
        return self._config.get_fix_file(filename)

    def get_exec_file(self, filename: str) -> Path:
        return self._config.get_exec_file(filename)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key."""
        return getattr(self, key, default)

    # ─────────────────────────────────────────────────────────────────
    # Access to new-style config
    # ─────────────────────────────────────────────────────────────────

    @property
    def system(self) -> SystemConfig:
        """Access the new SystemConfig."""
        return self._config.system

    @property
    def runtime(self) -> RuntimeConfig:
        """Access the new RuntimeConfig."""
        return self._config.runtime

    def to_new_config(self) -> OFSConfig:
        """Get the underlying new-style OFSConfig."""
        return self._config

    def __repr__(self) -> str:
        return f"LegacyConfigAdapter(ofs={self.RUN}, model={self.model_type})"


# Alias for backward compatibility
StofsConfig = LegacyConfigAdapter
