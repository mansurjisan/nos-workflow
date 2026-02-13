"""
Ensemble Configuration

Defines dataclasses for ensemble forecasting settings, including perturbation
strategies, execution mode, and output statistics. Configuration is loadable
from YAML files and integrates with the existing OFSConfig system.

The ensemble configuration adds an 'ensemble:' section to the existing YAML
config format. It can be stored either alongside the system YAML or in a
separate file under parm/ensemble/.

Example YAML:
    ensemble:
      enabled: true
      n_members: 20
      seed: 42
      perturbations:
        initial_conditions:
          enabled: true
          method: gaussian
          variables:
            temperature: {std_dev: 0.5, correlation_length: 50}
            ...
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

log = logging.getLogger(__name__)

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ---------------------------------------------------------------------------
# Sub-configuration dataclasses
# ---------------------------------------------------------------------------


@dataclass
class VariablePerturbationConfig:
    """Configuration for perturbing a single variable (IC or OBC).

    Attributes:
        std_dev: Standard deviation of perturbation in native units.
        correlation_length: Spatial correlation length scale in km.
        clamp_min: Optional minimum allowable value after perturbation.
        clamp_max: Optional maximum allowable value after perturbation.
    """

    std_dev: float = 0.0
    correlation_length: float = 50.0
    clamp_min: Optional[float] = None
    clamp_max: Optional[float] = None


@dataclass
class ICPerturbationConfig:
    """Initial condition perturbation settings.

    Attributes:
        enabled: Whether IC perturbation is active.
        method: Perturbation method ('gaussian', 'eof', 'historical').
        variables: Per-variable settings keyed by variable name
                   (e.g., 'temperature', 'salinity', 'ssh').
        eof_modes: Number of EOF modes to retain (for method='eof').
        eof_data_path: Path to pre-computed EOF data file.
        historical_error_path: Path to historical error archive (for method='historical').
    """

    enabled: bool = False
    method: str = "gaussian"
    variables: Dict[str, VariablePerturbationConfig] = field(default_factory=dict)
    eof_modes: int = 10
    eof_data_path: Optional[str] = None
    historical_error_path: Optional[str] = None


@dataclass
class WindPerturbationConfig:
    """Atmospheric wind perturbation settings.

    Attributes:
        enabled: Whether wind perturbation is active.
        speed_std_pct: Standard deviation as percentage of wind speed.
        direction_std_deg: Standard deviation of wind direction in degrees.
        correlation_length: Spatial correlation length in km.
        correlation_time_hours: Temporal correlation timescale (AR(1)) in hours.
    """

    enabled: bool = False
    speed_std_pct: float = 10.0
    direction_std_deg: float = 15.0
    correlation_length: float = 200.0
    correlation_time_hours: float = 6.0


@dataclass
class PressurePerturbationConfig:
    """Atmospheric pressure perturbation settings.

    Attributes:
        enabled: Whether pressure perturbation is active.
        std_dev: Standard deviation in Pa.
        correlation_length: Spatial correlation length in km.
        correlation_time_hours: Temporal correlation timescale in hours.
    """

    enabled: bool = False
    std_dev: float = 100.0
    correlation_length: float = 500.0
    correlation_time_hours: float = 12.0


@dataclass
class PrecipPerturbationConfig:
    """Precipitation rate perturbation settings.

    Attributes:
        enabled: Whether precipitation perturbation is active.
        std_pct: Standard deviation as percentage of precipitation rate.
        correlation_length: Spatial correlation length in km.
        correlation_time_hours: Temporal correlation timescale in hours.
    """

    enabled: bool = False
    std_pct: float = 30.0
    correlation_length: float = 100.0
    correlation_time_hours: float = 3.0


@dataclass
class ForcingPerturbationConfig:
    """Atmospheric forcing perturbation settings (wind, pressure, precip).

    Attributes:
        enabled: Master toggle for all forcing perturbations.
        wind: Wind perturbation settings.
        pressure: Pressure perturbation settings.
        precipitation: Precipitation perturbation settings.
    """

    enabled: bool = False
    wind: WindPerturbationConfig = field(default_factory=WindPerturbationConfig)
    pressure: PressurePerturbationConfig = field(
        default_factory=PressurePerturbationConfig
    )
    precipitation: PrecipPerturbationConfig = field(
        default_factory=PrecipPerturbationConfig
    )


@dataclass
class OBCPerturbationConfig:
    """Ocean boundary condition perturbation settings.

    Attributes:
        enabled: Whether OBC perturbation is active.
        variables: Per-variable settings (e.g., 'temperature', 'salinity', 'ssh', 'velocity').
    """

    enabled: bool = False
    variables: Dict[str, VariablePerturbationConfig] = field(default_factory=dict)


@dataclass
class ParamPerturbationConfig:
    """Model parameter perturbation settings.

    Each sub-field uses std_pct (percentage of the nominal value) to define
    the perturbation amplitude.

    Attributes:
        enabled: Master toggle for parameter perturbation.
        bottom_friction_std_pct: Std dev as percent of bottom friction coefficient.
        wind_drag_std_pct: Std dev as percent of wind drag coefficient.
        mixing_std_pct: Std dev as percent of vertical mixing parameters.
    """

    enabled: bool = False
    bottom_friction_std_pct: float = 20.0
    wind_drag_std_pct: float = 15.0
    mixing_std_pct: float = 25.0


@dataclass
class StatisticsConfig:
    """Ensemble output statistics configuration.

    Attributes:
        variables: List of model output variables to compute statistics for.
        percentiles: List of percentile values (0-100).
        probability_thresholds: Variable-keyed thresholds for exceedance probability.
    """

    variables: List[str] = field(
        default_factory=lambda: ["zeta", "temp", "salt"]
    )
    percentiles: List[float] = field(
        default_factory=lambda: [5.0, 10.0, 25.0, 50.0, 75.0, 90.0, 95.0]
    )
    probability_thresholds: Dict[str, List[float]] = field(default_factory=dict)


@dataclass
class ExecutionConfig:
    """Ensemble execution settings.

    Attributes:
        mode: Execution mode ('sequential' or 'parallel').
        max_parallel: Maximum number of parallel members (for mode='parallel').
        share_base_forcing: Whether to prepare base forcing once and share
                            across members (only perturbed parts are per-member).
        checkpoint: Whether to enable checkpoint/restart for individual members.
        retry_failed: Number of times to retry a failed member.
    """

    mode: str = "sequential"
    max_parallel: int = 4
    share_base_forcing: bool = True
    checkpoint: bool = True
    retry_failed: int = 0


# ---------------------------------------------------------------------------
# Main ensemble configuration
# ---------------------------------------------------------------------------


@dataclass
class EnsembleConfig:
    """
    Top-level ensemble configuration.

    Collects all ensemble-related settings: number of members, random seed,
    perturbation strategies, statistics configuration, and execution mode.

    Can be loaded from YAML or constructed programmatically.

    Attributes:
        enabled: Master toggle for ensemble mode.
        n_members: Number of ensemble members.
        perturbation_seed: Random seed for reproducibility.
        ic_perturbation: Initial condition perturbation settings.
        forcing_perturbation: Atmospheric forcing perturbation settings.
        obc_perturbation: Ocean boundary perturbation settings.
        param_perturbation: Model parameter perturbation settings.
        statistics: Output statistics configuration.
        execution: Execution mode settings.
        output_dir: Root directory for ensemble outputs. Each member gets
                    a subdirectory named member_NNNN.
    """

    enabled: bool = True
    n_members: int = 10
    perturbation_seed: int = 42
    ic_perturbation: ICPerturbationConfig = field(
        default_factory=ICPerturbationConfig
    )
    forcing_perturbation: ForcingPerturbationConfig = field(
        default_factory=ForcingPerturbationConfig
    )
    obc_perturbation: OBCPerturbationConfig = field(
        default_factory=OBCPerturbationConfig
    )
    param_perturbation: ParamPerturbationConfig = field(
        default_factory=ParamPerturbationConfig
    )
    statistics: StatisticsConfig = field(default_factory=StatisticsConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    output_dir: Path = field(default_factory=lambda: Path("ensemble_output"))

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, yaml_path: Union[str, Path]) -> "EnsembleConfig":
        """
        Load ensemble configuration from a YAML file.

        The YAML file should contain an 'ensemble:' top-level key.

        Args:
            yaml_path: Path to ensemble YAML configuration file.

        Returns:
            EnsembleConfig instance.

        Raises:
            FileNotFoundError: If yaml_path does not exist.
            ImportError: If PyYAML is not available.
        """
        if not HAS_YAML:
            raise ImportError(
                "PyYAML is required for YAML config loading. "
                "Install with: pip install pyyaml"
            )

        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Ensemble config not found: {yaml_path}")

        with open(yaml_path, "r") as f:
            raw = yaml.safe_load(f)

        # Support both top-level 'ensemble:' key and flat structure
        data = raw.get("ensemble", raw)

        return cls._from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnsembleConfig":
        """
        Create ensemble configuration from a dictionary.

        Useful when the ensemble section is extracted from a larger
        OFSConfig YAML that already has an 'ensemble:' section.

        Args:
            data: Dictionary with ensemble settings.

        Returns:
            EnsembleConfig instance.
        """
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "EnsembleConfig":
        """Internal helper to parse a dictionary into EnsembleConfig."""
        config = cls()

        config.enabled = data.get("enabled", True)
        config.n_members = data.get("n_members", 10)
        config.perturbation_seed = data.get("seed", data.get("perturbation_seed", 42))

        if "output_dir" in data:
            config.output_dir = Path(data["output_dir"])

        # Parse perturbation sections
        pert_data = data.get("perturbations", {})

        # Initial conditions
        ic_data = pert_data.get("initial_conditions", {})
        config.ic_perturbation = _parse_ic_config(ic_data)

        # Atmospheric forcing
        atm_data = pert_data.get("atmospheric", {})
        config.forcing_perturbation = _parse_forcing_config(atm_data)

        # Boundary conditions
        obc_data = pert_data.get("boundary", {})
        config.obc_perturbation = _parse_obc_config(obc_data)

        # Model parameters
        param_data = pert_data.get("parameters", {})
        config.param_perturbation = _parse_param_config(param_data)

        # Statistics
        stats_data = data.get("statistics", {})
        config.statistics = _parse_stats_config(stats_data)

        # Execution
        exec_data = data.get("execution", {})
        config.execution = _parse_exec_config(exec_data)

        return config

    def validate(self) -> List[str]:
        """
        Validate ensemble configuration.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []

        if self.n_members < 2:
            errors.append(
                f"n_members must be >= 2 for ensemble, got {self.n_members}"
            )

        if self.n_members > 1000:
            errors.append(
                f"n_members={self.n_members} is unusually large. "
                "Consider reducing for resource efficiency."
            )

        # Check that at least one perturbation is enabled
        any_pert = (
            self.ic_perturbation.enabled
            or self.forcing_perturbation.enabled
            or self.obc_perturbation.enabled
            or self.param_perturbation.enabled
        )
        if not any_pert:
            errors.append(
                "No perturbation strategies are enabled. "
                "Enable at least one perturbation type for meaningful ensemble."
            )

        # Validate statistics
        if not self.statistics.variables:
            errors.append("No output variables specified for statistics.")

        # Validate execution mode
        if self.execution.mode not in ("sequential", "parallel"):
            errors.append(
                f"Invalid execution mode: {self.execution.mode}. "
                "Must be 'sequential' or 'parallel'."
            )

        return errors

    def summary(self) -> str:
        """Return a human-readable summary of the ensemble configuration."""
        lines = [
            f"Ensemble Configuration (enabled={self.enabled})",
            f"  Members: {self.n_members}",
            f"  Seed: {self.perturbation_seed}",
            f"  Output: {self.output_dir}",
            "",
            "  Perturbations:",
        ]

        if self.ic_perturbation.enabled:
            n_vars = len(self.ic_perturbation.variables)
            lines.append(
                f"    IC: {self.ic_perturbation.method} "
                f"({n_vars} variables)"
            )

        if self.forcing_perturbation.enabled:
            parts = []
            if self.forcing_perturbation.wind.enabled:
                parts.append(
                    f"wind({self.forcing_perturbation.wind.speed_std_pct}%)"
                )
            if self.forcing_perturbation.pressure.enabled:
                parts.append(
                    f"pressure({self.forcing_perturbation.pressure.std_dev}Pa)"
                )
            if self.forcing_perturbation.precipitation.enabled:
                parts.append(
                    f"precip({self.forcing_perturbation.precipitation.std_pct}%)"
                )
            lines.append(f"    Forcing: {', '.join(parts)}")

        if self.obc_perturbation.enabled:
            n_vars = len(self.obc_perturbation.variables)
            lines.append(f"    OBC: {n_vars} variables")

        if self.param_perturbation.enabled:
            parts = []
            if self.param_perturbation.bottom_friction_std_pct > 0:
                parts.append(
                    f"friction({self.param_perturbation.bottom_friction_std_pct}%)"
                )
            if self.param_perturbation.wind_drag_std_pct > 0:
                parts.append(
                    f"drag({self.param_perturbation.wind_drag_std_pct}%)"
                )
            if self.param_perturbation.mixing_std_pct > 0:
                parts.append(
                    f"mixing({self.param_perturbation.mixing_std_pct}%)"
                )
            lines.append(f"    Parameters: {', '.join(parts)}")

        lines.append("")
        lines.append(
            f"  Statistics: {self.statistics.variables} "
            f"percentiles={self.statistics.percentiles}"
        )
        lines.append(
            f"  Execution: {self.execution.mode} "
            f"(share_base_forcing={self.execution.share_base_forcing})"
        )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# YAML parsing helpers
# ---------------------------------------------------------------------------


def _parse_var_perturbation(data: Dict[str, Any]) -> VariablePerturbationConfig:
    """Parse a single variable perturbation config from a dict."""
    return VariablePerturbationConfig(
        std_dev=data.get("std_dev", 0.0),
        correlation_length=data.get("correlation_length", 50.0),
        clamp_min=data.get("clamp_min"),
        clamp_max=data.get("clamp_max"),
    )


def _parse_ic_config(data: Dict[str, Any]) -> ICPerturbationConfig:
    """Parse initial condition perturbation config."""
    config = ICPerturbationConfig(
        enabled=data.get("enabled", False),
        method=data.get("method", "gaussian"),
        eof_modes=data.get("eof_modes", 10),
        eof_data_path=data.get("eof_data_path"),
        historical_error_path=data.get("historical_error_path"),
    )

    # Parse per-variable settings
    vars_data = data.get("variables", {})
    for var_name, var_settings in vars_data.items():
        if isinstance(var_settings, dict):
            config.variables[var_name] = _parse_var_perturbation(var_settings)
        elif isinstance(var_settings, (int, float)):
            # Shorthand: just specify std_dev
            config.variables[var_name] = VariablePerturbationConfig(
                std_dev=float(var_settings)
            )

    return config


def _parse_forcing_config(data: Dict[str, Any]) -> ForcingPerturbationConfig:
    """Parse atmospheric forcing perturbation config."""
    config = ForcingPerturbationConfig(
        enabled=data.get("enabled", False),
    )

    # Wind
    wind_data = data.get("wind", {})
    if wind_data:
        config.wind = WindPerturbationConfig(
            enabled=wind_data.get("enabled", bool(wind_data)),
            speed_std_pct=wind_data.get("speed_std_pct", 10.0),
            direction_std_deg=wind_data.get("direction_std_deg", 15.0),
            correlation_length=wind_data.get("correlation_length", 200.0),
            correlation_time_hours=wind_data.get("correlation_time_hours", 6.0),
        )

    # Pressure
    pres_data = data.get("pressure", {})
    if pres_data:
        config.pressure = PressurePerturbationConfig(
            enabled=pres_data.get("enabled", bool(pres_data)),
            std_dev=pres_data.get("std_dev", 100.0),
            correlation_length=pres_data.get("correlation_length", 500.0),
            correlation_time_hours=pres_data.get("correlation_time_hours", 12.0),
        )

    # Precipitation
    precip_data = data.get("precipitation", {})
    if precip_data:
        config.precipitation = PrecipPerturbationConfig(
            enabled=precip_data.get("enabled", bool(precip_data)),
            std_pct=precip_data.get("std_pct", 30.0),
            correlation_length=precip_data.get("correlation_length", 100.0),
            correlation_time_hours=precip_data.get("correlation_time_hours", 3.0),
        )

    return config


def _parse_obc_config(data: Dict[str, Any]) -> OBCPerturbationConfig:
    """Parse ocean boundary condition perturbation config."""
    config = OBCPerturbationConfig(
        enabled=data.get("enabled", False),
    )

    vars_data = data.get("variables", {})
    for var_name, var_settings in vars_data.items():
        if isinstance(var_settings, dict):
            config.variables[var_name] = _parse_var_perturbation(var_settings)

    return config


def _parse_param_config(data: Dict[str, Any]) -> ParamPerturbationConfig:
    """Parse model parameter perturbation config."""
    config = ParamPerturbationConfig(
        enabled=data.get("enabled", False),
    )

    bf = data.get("bottom_friction", {})
    if isinstance(bf, dict):
        config.bottom_friction_std_pct = bf.get("std_pct", 20.0)
    elif isinstance(bf, (int, float)):
        config.bottom_friction_std_pct = float(bf)

    wd = data.get("wind_drag", {})
    if isinstance(wd, dict):
        config.wind_drag_std_pct = wd.get("std_pct", 15.0)
    elif isinstance(wd, (int, float)):
        config.wind_drag_std_pct = float(wd)

    mx = data.get("mixing", {})
    if isinstance(mx, dict):
        config.mixing_std_pct = mx.get("std_pct", 25.0)
    elif isinstance(mx, (int, float)):
        config.mixing_std_pct = float(mx)

    return config


def _parse_stats_config(data: Dict[str, Any]) -> StatisticsConfig:
    """Parse statistics configuration."""
    return StatisticsConfig(
        variables=data.get("variables", ["zeta", "temp", "salt"]),
        percentiles=data.get("percentiles", [5, 10, 25, 50, 75, 90, 95]),
        probability_thresholds=data.get("probability_thresholds", {}),
    )


def _parse_exec_config(data: Dict[str, Any]) -> ExecutionConfig:
    """Parse execution configuration."""
    return ExecutionConfig(
        mode=data.get("mode", "sequential"),
        max_parallel=data.get("max_parallel", 4),
        share_base_forcing=data.get("share_base_forcing", True),
        checkpoint=data.get("checkpoint", True),
        retry_failed=data.get("retry_failed", 0),
    )
