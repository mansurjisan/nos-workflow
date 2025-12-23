"""
Unified Configuration - Combines static SystemConfig + runtime RuntimeConfig

OFSConfig is the main configuration object used throughout the package.
It provides:
- Access to static system definition (from YAML)
- Access to runtime context (from environment)
- Computed properties (run times, paths, timesteps)
- Path resolution (combining FIXofs with filenames)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union

from .system import SystemConfig
from .runtime import RuntimeConfig
from .loader import YAMLConfigLoader


class ConfigurationError(Exception):
    """Raised when configuration is invalid."""

    pass


class DataNotFoundError(Exception):
    """Raised when required input data is missing."""

    pass


@dataclass
class OFSConfig:
    """
    Unified configuration combining static system definition with runtime context.

    This is the main configuration object used throughout the package.

    Usage:
        # Load by system name (automatic config file discovery)
        config = OFSConfig.load("stofs_3d_atl")

        # Load from specific YAML file
        config = OFSConfig.from_yaml("/path/to/config.yaml")

        # Access static system info
        print(config.system.model_type)  # "schism"
        print(config.system.forcing.atmospheric.primary)  # "gfs"
        print(config.system.physics.dt)  # 150.0

        # Access runtime info
        print(config.runtime.pdy)  # "20241201"
        print(config.runtime.cyc)  # 12
        print(config.runtime.comin_gfs)  # Path("/lfs/h1/ops/...")

        # Access computed properties
        print(config.run_start)  # datetime
        print(config.run_end)  # datetime
        print(config.n_timesteps)  # 3168
        print(config.output_prefix)  # "stofs_3d_atl.t12z"

    Attributes:
        system: Static SystemConfig from YAML
        runtime: Dynamic RuntimeConfig from environment
    """

    system: SystemConfig
    runtime: RuntimeConfig

    @classmethod
    def load(
        cls,
        system_name: str,
        config_dir: Optional[Path] = None,
        validate: bool = True,
        strict: bool = False,
    ) -> "OFSConfig":
        """
        Load configuration for a system by name.

        Searches for configuration file in standard locations and
        loads runtime from environment.

        Args:
            system_name: System name (e.g., 'stofs_3d_atl')
            config_dir: Optional config directory override
            validate: Whether to validate configuration
            strict: If True, treat warnings as errors

        Returns:
            Unified OFSConfig

        Raises:
            FileNotFoundError: If config file not found
            ConfigurationError: If validation fails
        """
        # Find system config file
        if config_dir:
            yaml_path = Path(config_dir) / f"{system_name}.yaml"
        else:
            yaml_path = YAMLConfigLoader.find_system_config(system_name)

        if yaml_path is None or not yaml_path.exists():
            raise FileNotFoundError(
                f"Configuration not found for system: {system_name}"
            )

        # Load system config
        system = SystemConfig.from_yaml(yaml_path)

        # Load runtime from environment
        runtime = RuntimeConfig.from_environment()

        # Set run name if not set
        if not runtime.run:
            runtime.run = system_name

        config = cls(system=system, runtime=runtime)

        # Validate
        if validate:
            result = runtime.validate(system)
            if strict:
                result.raise_if_invalid()
            elif not result.valid:
                # Log errors but continue in non-strict mode
                import warnings

                for error in result.errors:
                    warnings.warn(f"Configuration error: {error}")

        return config

    @classmethod
    def from_yaml(
        cls,
        yaml_path: Union[str, Path],
        validate: bool = True,
    ) -> "OFSConfig":
        """
        Load configuration from a specific YAML file.

        Args:
            yaml_path: Path to YAML configuration file
            validate: Whether to validate configuration

        Returns:
            Unified OFSConfig
        """
        system = SystemConfig.from_yaml(Path(yaml_path))
        runtime = RuntimeConfig.from_environment()

        if not runtime.run:
            runtime.run = system.name

        config = cls(system=system, runtime=runtime)

        if validate:
            result = runtime.validate(system)
            if result.errors:
                import warnings

                for error in result.errors:
                    warnings.warn(f"Configuration error: {error}")

        return config

    @classmethod
    def from_components(
        cls,
        system: SystemConfig,
        runtime: RuntimeConfig,
    ) -> "OFSConfig":
        """
        Create OFSConfig from pre-built components.

        Useful for testing or when you want full control over both configs.

        Args:
            system: SystemConfig instance
            runtime: RuntimeConfig instance

        Returns:
            Unified OFSConfig
        """
        return cls(system=system, runtime=runtime)

    # ─────────────────────────────────────────────────────────────────
    # Computed Properties - Logic belongs here, not in YAML
    # ─────────────────────────────────────────────────────────────────

    @property
    def run_start(self) -> datetime:
        """
        Compute run start time (cycle - hindcast).

        Returns:
            datetime for model run start
        """
        cycle = self.runtime.cycle_datetime
        hindcast = timedelta(days=self.system.hindcast_days)
        return cycle - hindcast

    @property
    def run_end(self) -> datetime:
        """
        Compute run end time (cycle + forecast).

        Returns:
            datetime for model run end
        """
        cycle = self.runtime.cycle_datetime
        forecast = timedelta(days=self.system.forecast_days)
        return cycle + forecast

    @property
    def total_run_days(self) -> float:
        """Total run length in days."""
        return self.system.hindcast_days + self.system.forecast_days

    @property
    def total_run_hours(self) -> float:
        """Total run length in hours."""
        return self.total_run_days * 24.0

    @property
    def total_run_seconds(self) -> float:
        """Total run length in seconds."""
        return self.total_run_days * 86400.0

    @property
    def output_prefix(self) -> str:
        """
        Standard output filename prefix: {name}.{cycle}

        Returns:
            Prefix like 'stofs_3d_atl.t12z'
        """
        return f"{self.system.name}.{self.runtime.cycle_str}"

    @property
    def n_timesteps(self) -> int:
        """
        Calculate number of model timesteps.

        Returns:
            Number of timesteps for the full run
        """
        return int(self.total_run_seconds / self.system.physics.dt)

    @property
    def cycle_datetime(self) -> datetime:
        """Alias for runtime.cycle_datetime."""
        return self.runtime.cycle_datetime

    # ─────────────────────────────────────────────────────────────────
    # Path Resolution - Combines FIXofs/runtime paths with filenames
    # ─────────────────────────────────────────────────────────────────

    def get_grid_file(self) -> Optional[Path]:
        """
        Get full path to horizontal grid file.

        Returns:
            Path to grid file or None if not configured
        """
        if not self.system.grid.horizontal:
            return None
        if self.runtime.fix_ofs:
            return self.runtime.fix_ofs / self.system.grid.horizontal
        return Path(self.system.grid.horizontal)

    def get_vgrid_file(self) -> Optional[Path]:
        """
        Get full path to vertical grid file.

        Returns:
            Path to vgrid file or None if not configured
        """
        if not self.system.grid.vertical:
            return None
        if self.runtime.fix_ofs:
            return self.runtime.fix_ofs / self.system.grid.vertical
        return Path(self.system.grid.vertical)

    def get_fix_file(self, filename: str) -> Path:
        """
        Get full path to a FIX file.

        Args:
            filename: Name of the file in FIXofs

        Returns:
            Full path to the file
        """
        if self.runtime.fix_ofs:
            return self.runtime.fix_ofs / filename
        return Path(filename)

    def get_exec_file(self, filename: str) -> Path:
        """
        Get full path to an executable.

        Args:
            filename: Name of the executable in EXECofs

        Returns:
            Full path to the executable
        """
        if self.runtime.exec_ofs:
            return self.runtime.exec_ofs / filename
        return Path(filename)

    def get_output_file(self, basename: str, ext: str = "nc") -> Path:
        """
        Generate standard output filename in COMOUT.

        Args:
            basename: Base name for the file (e.g., 'fields')
            ext: File extension (default: 'nc')

        Returns:
            Full path like 'COMOUT/stofs_3d_atl.t12z.fields.nc'
        """
        filename = f"{self.output_prefix}.{basename}.{ext}"
        if self.runtime.comout:
            return self.runtime.comout / filename
        return Path(filename)

    def get_work_file(self, filename: str) -> Path:
        """
        Get path for a file in the working directory.

        Args:
            filename: Name of the file

        Returns:
            Full path in DATA directory
        """
        if self.runtime.data:
            return self.runtime.data / filename
        return Path(filename)

    # ─────────────────────────────────────────────────────────────────
    # Forcing Path Resolution
    # ─────────────────────────────────────────────────────────────────

    def get_forcing_input_path(self, source: str) -> Optional[Path]:
        """
        Get input path for a forcing source.

        Args:
            source: Forcing source name (gfs, hrrr, nam, rtofs, nwm, adt)

        Returns:
            Path to forcing input directory or None
        """
        return self.runtime.get_forcing_path(source)

    def get_atmospheric_source(self) -> str:
        """
        Get the atmospheric forcing source to use.

        Checks if primary source exists, falls back if not.

        Returns:
            Source name to use ('gfs', 'hrrr', 'nam')

        Raises:
            DataNotFoundError: If no atmospheric data available
        """
        atm = self.system.forcing.atmospheric
        primary = atm.primary
        fallback = atm.fallback

        # Check if primary data exists
        if primary:
            primary_path = self.get_forcing_input_path(primary)
            if primary_path and primary_path.exists():
                return primary

        # Fall back if primary missing
        if fallback:
            fallback_path = self.get_forcing_input_path(fallback)
            if fallback_path and fallback_path.exists():
                return fallback

        raise DataNotFoundError(
            f"No atmospheric data found for primary={primary} or fallback={fallback}"
        )

    # ─────────────────────────────────────────────────────────────────
    # Convenience Accessors (avoid deep nesting in user code)
    # ─────────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """System name."""
        return self.system.name

    @property
    def model_type(self) -> str:
        """Model type (schism, fvcom, roms)."""
        return self.system.model_type

    @property
    def framework(self) -> str:
        """Framework (stofs, comf)."""
        return self.system.framework

    @property
    def pdy(self) -> str:
        """Production date YYYYMMDD."""
        return self.runtime.pdy

    @property
    def cyc(self) -> int:
        """Cycle hour."""
        return self.runtime.cyc

    @property
    def cycle(self) -> str:
        """Cycle string like 't12z'."""
        return self.runtime.cycle_str

    @property
    def dt(self) -> float:
        """Model timestep in seconds."""
        return self.system.physics.dt

    @property
    def nprocs(self) -> int:
        """Number of MPI processes."""
        return self.system.resources.nprocs

    @property
    def n_levels(self) -> int:
        """Number of vertical levels."""
        return self.system.grid.n_levels

    # Convenience methods for model type checking
    def is_schism(self) -> bool:
        """Check if this is a SCHISM-based system."""
        return self.system.is_schism

    def is_fvcom(self) -> bool:
        """Check if this is an FVCOM-based system."""
        return self.system.is_fvcom

    def is_roms(self) -> bool:
        """Check if this is a ROMS-based system."""
        return self.system.is_roms

    def is_stofs(self) -> bool:
        """Check if this uses STOFS framework."""
        return self.system.is_stofs

    def is_comf(self) -> bool:
        """Check if this uses COMF/NOSofs framework."""
        return self.system.is_comf

    def __repr__(self) -> str:
        return (
            f"OFSConfig(name={self.name}, model={self.model_type}, "
            f"pdy={self.pdy}, cyc={self.cyc})"
        )
