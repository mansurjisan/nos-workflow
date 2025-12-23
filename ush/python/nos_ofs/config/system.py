"""
System Configuration - Static definition from YAML

SystemConfig represents the immutable definition of an OFS system.
It captures "what is this system?" - model type, grid, physics, etc.

This is frozen (immutable) because the system definition should not
change during a run. Runtime context is handled by RuntimeConfig.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .loader import YAMLConfigLoader


@dataclass(frozen=True)
class GridConfig:
    """
    Grid file and domain configuration.

    Attributes:
        horizontal: Horizontal grid filename (e.g., 'hgrid.gr3')
        vertical: Vertical grid filename (e.g., 'vgrid.in')
        domain: Domain bounds as dict with lon_min, lon_max, lat_min, lat_max
        n_nodes: Number of grid nodes (optional)
        n_elements: Number of grid elements (optional)
        n_levels: Number of vertical levels
        grid_type: Grid type ('unstructured', 'curvilinear')
    """

    horizontal: str = ""
    vertical: Optional[str] = None
    domain: Dict[str, float] = field(default_factory=dict)
    n_nodes: int = 0
    n_elements: int = 0
    n_levels: int = 1
    grid_type: str = "unstructured"

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        """Return domain bounds as (lon_min, lon_max, lat_min, lat_max)."""
        return (
            self.domain.get("lon_min", -180.0),
            self.domain.get("lon_max", 180.0),
            self.domain.get("lat_min", -90.0),
            self.domain.get("lat_max", 90.0),
        )


@dataclass(frozen=True)
class ForcingSourceConfig:
    """
    Configuration for a single forcing source.

    Attributes:
        enabled: Whether this forcing source is enabled
        primary: Primary data source name (e.g., 'gfs', 'rtofs')
        fallback: Fallback source if primary unavailable
        variables: List of variables to extract
        source: Environment variable for input path (e.g., 'COMINgfs')
    """

    enabled: bool = True
    primary: Optional[str] = None
    fallback: Optional[str] = None
    variables: Tuple[str, ...] = ()
    source: str = ""
    # Additional source-specific settings stored as dict
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ForcingConfig:
    """
    Complete forcing configuration for an OFS system.

    Attributes:
        atmospheric: Atmospheric forcing (GFS, HRRR, NAM)
        ocean: Ocean boundary conditions (RTOFS)
        river: River forcing (NWM, USGS)
        tidal: Tidal forcing configuration
    """

    atmospheric: ForcingSourceConfig = field(
        default_factory=lambda: ForcingSourceConfig(primary="gfs")
    )
    ocean: ForcingSourceConfig = field(
        default_factory=lambda: ForcingSourceConfig(primary="rtofs")
    )
    river: ForcingSourceConfig = field(
        default_factory=lambda: ForcingSourceConfig(enabled=False)
    )
    tidal: ForcingSourceConfig = field(
        default_factory=lambda: ForcingSourceConfig(enabled=True)
    )


@dataclass(frozen=True)
class ModelPhysicsConfig:
    """
    Model physics parameters.

    Attributes:
        dt: Model timestep in seconds
        params: Additional physics parameters as dict
    """

    dt: float = 100.0
    params: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a physics parameter."""
        return self.params.get(key, default)


@dataclass(frozen=True)
class ResourceConfig:
    """
    Computational resource requirements.

    Attributes:
        nprocs: Number of MPI processes
        nscribes: Number of I/O processes (SCHISM-specific)
        memory_gb: Memory requirement in GB
        walltime_hours: Maximum walltime in hours
    """

    nprocs: int = 1
    nscribes: int = 0
    memory_gb: int = 100
    walltime_hours: float = 2.0


@dataclass(frozen=True)
class OutputConfig:
    """
    Model output configuration.

    Attributes:
        format: Output format ('netcdf', 'binary')
        variables_2d: 2D output variables
        variables_3d: 3D output variables
        stations_enabled: Whether station output is enabled
        station_interval: Station output interval in seconds
        history_interval: History output interval in hours
        hotstart_interval: Hotstart output interval in days
    """

    format: str = "netcdf"
    variables_2d: Tuple[str, ...] = ()
    variables_3d: Tuple[str, ...] = ()
    stations_enabled: bool = True
    station_interval: float = 360.0
    history_interval: float = 1.0
    hotstart_interval: float = 1.0


@dataclass(frozen=True)
class SystemConfig:
    """
    Static system configuration from YAML.

    This is IMMUTABLE - represents the system definition, not runtime state.
    All runtime context (PDY, cyc, paths) is in RuntimeConfig.

    Attributes:
        name: System name (e.g., 'stofs_3d_atl')
        model_type: Model type ('schism', 'fvcom', 'roms')
        description: Human-readable description
        region: Geographic region
        framework: Operational framework ('stofs', 'comf')
        version: System version string
        grid: Grid configuration
        forcing: Forcing configuration
        physics: Physics parameters
        resources: Computational resources
        output: Output configuration
        hindcast_days: Hindcast length in days
        forecast_days: Forecast length in days
        stages: Workflow stages for this system
    """

    # Identity
    name: str = ""
    model_type: str = ""  # schism, fvcom, roms
    description: str = ""
    region: str = ""
    framework: str = ""  # stofs, comf
    version: str = ""

    # Components
    grid: GridConfig = field(default_factory=GridConfig)
    forcing: ForcingConfig = field(default_factory=ForcingConfig)
    physics: ModelPhysicsConfig = field(default_factory=ModelPhysicsConfig)
    resources: ResourceConfig = field(default_factory=ResourceConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    # Run configuration
    hindcast_days: float = 0.25
    forecast_days: float = 5.0

    # Workflow stages
    stages: Tuple[str, ...] = ()

    # Raw YAML for anything not explicitly modeled
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False, hash=False)

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "SystemConfig":
        """
        Load system config from YAML file with inheritance.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            SystemConfig instance
        """
        loader = YAMLConfigLoader()
        data = loader.load(yaml_path)
        return cls._from_dict(data)

    @classmethod
    def from_name(cls, system_name: str) -> "SystemConfig":
        """
        Load system config by system name.

        Searches for the configuration file in standard locations.

        Args:
            system_name: System name (e.g., 'stofs_3d_atl')

        Returns:
            SystemConfig instance

        Raises:
            FileNotFoundError: If config file not found
        """
        yaml_path = YAMLConfigLoader.find_system_config(system_name)
        if yaml_path is None:
            raise FileNotFoundError(
                f"Configuration not found for system: {system_name}"
            )
        return cls.from_yaml(yaml_path)

    @classmethod
    def _from_dict(cls, data: Dict) -> "SystemConfig":
        """Build SystemConfig from dictionary."""
        # Parse system section
        system = data.get("system", {})

        # Parse grid
        grid = cls._parse_grid(data.get("grid", {}))

        # Parse forcing
        forcing = cls._parse_forcing(data.get("forcing", {}))

        # Parse physics
        model_data = data.get("model", {})
        physics = cls._parse_physics(model_data)

        # Parse resources
        resources = cls._parse_resources(model_data.get("resources", {}))

        # Parse output
        output = cls._parse_output(data.get("output", {}))

        # Parse run config
        run_data = model_data.get("run", model_data)
        hindcast_days = float(run_data.get("hindcast_days", 0.25))
        forecast_days = float(run_data.get("forecast_days", run_data.get("run_days", 5.0)))

        # Parse stages
        stages = tuple(data.get("stages", []))

        return cls(
            name=system.get("name", ""),
            model_type=system.get("model_type", data.get("model", {}).get("type", "")),
            description=system.get("description", ""),
            region=system.get("region", system.get("domain", "")),
            framework=system.get("framework", ""),
            version=system.get("version", ""),
            grid=grid,
            forcing=forcing,
            physics=physics,
            resources=resources,
            output=output,
            hindcast_days=hindcast_days,
            forecast_days=forecast_days,
            stages=stages,
            _raw=data,
        )

    @classmethod
    def _parse_grid(cls, data: Dict) -> GridConfig:
        """Parse grid configuration."""
        files = data.get("files", {})
        return GridConfig(
            horizontal=files.get("horizontal", files.get("grid", "")),
            vertical=files.get("vertical"),
            domain=data.get("domain", {}),
            n_nodes=int(data.get("n_nodes", 0)),
            n_elements=int(data.get("n_elements", 0)),
            n_levels=int(data.get("n_levels", data.get("kb", 1))),
            grid_type=data.get("type", "unstructured"),
        )

    @classmethod
    def _parse_forcing(cls, data: Dict) -> ForcingConfig:
        """Parse forcing configuration."""
        return ForcingConfig(
            atmospheric=cls._parse_forcing_source(
                data.get("atmospheric", {}), "gfs"
            ),
            ocean=cls._parse_forcing_source(data.get("ocean", {}), "rtofs"),
            river=cls._parse_forcing_source(data.get("river", {}), "nwm"),
            tidal=cls._parse_tidal_config(data.get("tidal", {})),
        )

    @classmethod
    def _parse_forcing_source(
        cls, data: Dict, default_primary: str = None
    ) -> ForcingSourceConfig:
        """Parse a forcing source configuration."""
        # Handle simple boolean
        if isinstance(data, bool):
            return ForcingSourceConfig(enabled=data, primary=default_primary)

        # Check if it's the old nested format (e.g., atmospheric.gfs.enabled)
        # vs new flat format (e.g., atmospheric.primary: gfs)
        if "primary" in data:
            # New format
            return ForcingSourceConfig(
                enabled=data.get("enabled", True),
                primary=data.get("primary"),
                fallback=data.get("fallback"),
                variables=tuple(data.get("variables", [])),
                source=data.get("source", ""),
                options=data,
            )

        # Old nested format - look for known sources
        known_sources = ["gfs", "hrrr", "nam", "rtofs", "nwm", "adt"]
        enabled = False
        primary = None
        fallback = None
        variables = []

        for source in known_sources:
            source_data = data.get(source, {})
            if isinstance(source_data, dict) and source_data.get("enabled", False):
                if primary is None:
                    primary = source
                    enabled = True
                    variables = source_data.get("variables", [])
                else:
                    fallback = source

        return ForcingSourceConfig(
            enabled=enabled,
            primary=primary or default_primary,
            fallback=fallback,
            variables=tuple(variables),
            source=data.get("source", ""),
            options=data,
        )

    @classmethod
    def _parse_tidal_config(cls, data: Dict) -> ForcingSourceConfig:
        """Parse tidal forcing configuration."""
        if isinstance(data, bool):
            return ForcingSourceConfig(enabled=data)

        constituents = data.get("constituents", [])
        return ForcingSourceConfig(
            enabled=data.get("enabled", True),
            primary=data.get("database", "tpxo"),
            variables=tuple(constituents),
            options=data,
        )

    @classmethod
    def _parse_physics(cls, data: Dict) -> ModelPhysicsConfig:
        """Parse physics configuration."""
        physics_data = data.get("physics", data)
        return ModelPhysicsConfig(
            dt=float(physics_data.get("dt", 100.0)),
            params=physics_data,
        )

    @classmethod
    def _parse_resources(cls, data: Dict) -> ResourceConfig:
        """Parse resources configuration."""
        return ResourceConfig(
            nprocs=int(data.get("nprocs", 1)),
            nscribes=int(data.get("nscribes", 0)),
            memory_gb=int(data.get("memory_gb", 100)),
            walltime_hours=float(data.get("walltime_hours", 2.0)),
        )

    @classmethod
    def _parse_output(cls, data: Dict) -> OutputConfig:
        """Parse output configuration."""
        fields_2d = data.get("fields_2d", {})
        fields_3d = data.get("fields_3d", {})
        stations = data.get("stations", {})
        intervals = data.get("intervals", {})

        return OutputConfig(
            format=data.get("format", "netcdf"),
            variables_2d=tuple(fields_2d.get("variables", [])),
            variables_3d=tuple(fields_3d.get("variables", [])),
            stations_enabled=stations.get("enabled", True),
            station_interval=float(stations.get("interval", 360.0)),
            history_interval=float(intervals.get("history_hours", 1.0)),
            hotstart_interval=float(intervals.get("hotstart_days", 1.0)),
        )

    # Convenience properties
    @property
    def is_schism(self) -> bool:
        """Check if this is a SCHISM-based system."""
        return self.model_type.lower() == "schism"

    @property
    def is_fvcom(self) -> bool:
        """Check if this is an FVCOM-based system."""
        return self.model_type.lower() == "fvcom"

    @property
    def is_roms(self) -> bool:
        """Check if this is a ROMS-based system."""
        return self.model_type.lower() == "roms"

    @property
    def is_stofs(self) -> bool:
        """Check if this uses STOFS framework."""
        return self.framework.lower() == "stofs"

    @property
    def is_comf(self) -> bool:
        """Check if this uses COMF/NOSofs framework."""
        return self.framework.lower() in ("comf", "nosofs")

    @property
    def total_run_days(self) -> float:
        """Total run length in days."""
        return self.hindcast_days + self.forecast_days

    def get_raw(self, *keys: str, default: Any = None) -> Any:
        """
        Access raw YAML data by nested keys.

        Args:
            keys: Sequence of keys to navigate nested structure
            default: Default value if key path not found

        Returns:
            Value at key path or default
        """
        result = self._raw
        for key in keys:
            if isinstance(result, dict):
                result = result.get(key)
            else:
                return default
            if result is None:
                return default
        return result
