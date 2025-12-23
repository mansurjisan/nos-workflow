"""
Configuration Validation

Provides validation for runtime configuration against system requirements.
Checks that required paths exist and forcing inputs are available.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .system import SystemConfig
    from .runtime import RuntimeConfig


@dataclass
class ValidationResult:
    """
    Result of configuration validation.

    Attributes:
        valid: Whether validation passed (no errors)
        errors: List of error messages (blocking issues)
        warnings: List of warning messages (non-blocking issues)
    """

    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Allow using ValidationResult in boolean context."""
        return self.valid

    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.errors.append(message)
        self.valid = False

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Merge another validation result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if other.errors:
            self.valid = False
        return self

    def raise_if_invalid(self) -> None:
        """Raise ConfigurationError if validation failed."""
        if not self.valid:
            from .unified import ConfigurationError

            raise ConfigurationError(
                f"Configuration validation failed:\n"
                + "\n".join(f"  - {e}" for e in self.errors)
            )


class RuntimeValidator:
    """
    Validates RuntimeConfig against SystemConfig requirements.

    Checks:
    - Required paths are set and exist
    - Forcing input paths are available for enabled forcing types
    - Cycle hour is valid
    """

    def __init__(
        self, runtime: "RuntimeConfig", system: "SystemConfig", strict: bool = False
    ):
        """
        Initialize validator.

        Args:
            runtime: RuntimeConfig to validate
            system: SystemConfig to validate against
            strict: If True, treat warnings as errors
        """
        self.runtime = runtime
        self.system = system
        self.strict = strict
        self.result = ValidationResult()

    def validate(self) -> ValidationResult:
        """
        Run all validations.

        Returns:
            ValidationResult with errors and warnings
        """
        self._validate_pdy()
        self._validate_cycle()
        self._validate_required_paths()
        self._validate_forcing_paths()

        if self.strict and self.result.warnings:
            # Convert warnings to errors in strict mode
            self.result.errors.extend(self.result.warnings)
            self.result.warnings = []
            self.result.valid = len(self.result.errors) == 0

        return self.result

    def _validate_pdy(self) -> None:
        """Validate PDY format."""
        pdy = self.runtime.pdy
        if not pdy:
            self.result.add_error("PDY is not set")
            return

        if len(pdy) != 8:
            self.result.add_error(f"PDY must be 8 digits (YYYYMMDD), got: {pdy}")
            return

        try:
            year = int(pdy[:4])
            month = int(pdy[4:6])
            day = int(pdy[6:8])
            if not (1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100):
                self.result.add_error(f"PDY has invalid date: {pdy}")
        except ValueError:
            self.result.add_error(f"PDY must be numeric: {pdy}")

    def _validate_cycle(self) -> None:
        """Validate cycle hour."""
        cyc = self.runtime.cyc
        standard_cycles = [0, 6, 12, 18]

        if cyc not in standard_cycles:
            self.result.add_warning(
                f"Non-standard cycle hour: {cyc}. "
                f"Standard cycles are: {standard_cycles}"
            )

        if not (0 <= cyc <= 23):
            self.result.add_error(f"Cycle hour must be 0-23, got: {cyc}")

    def _validate_required_paths(self) -> None:
        """Check required paths exist."""
        # These paths must be set
        required = [
            ("DATA", self.runtime.data, True),  # Can be created
            ("HOMEnos/HOMEstofs", self.runtime.home_nos, False),
            ("FIXofs/FIXstofs3d", self.runtime.fix_ofs, False),
        ]

        for name, path, can_create in required:
            if path is None:
                self.result.add_error(f"Required path {name} is not set")
            elif not path.exists():
                if can_create:
                    self.result.add_warning(f"Path {name}={path} does not exist (will be created)")
                else:
                    self.result.add_error(f"Path {name}={path} does not exist")

    def _validate_forcing_paths(self) -> None:
        """Check forcing input paths based on system config."""
        forcing = self.system.forcing

        # Atmospheric forcing
        if forcing.atmospheric.enabled:
            self._check_forcing_path(
                forcing.atmospheric.primary,
                "atmospheric",
                is_error=True,
            )
            if forcing.atmospheric.fallback:
                self._check_forcing_path(
                    forcing.atmospheric.fallback,
                    "atmospheric fallback",
                    is_error=False,
                )

        # Ocean forcing
        if forcing.ocean.enabled:
            self._check_forcing_path(
                forcing.ocean.primary,
                "ocean boundary",
                is_error=True,
            )

        # River forcing
        if forcing.river.enabled:
            self._check_forcing_path(
                forcing.river.primary or "nwm",
                "river",
                is_error=False,  # May fall back to USGS
            )

    def _check_forcing_path(
        self, source: str, forcing_type: str, is_error: bool = True
    ) -> None:
        """
        Check if a forcing input path is available.

        Args:
            source: Forcing source name (gfs, hrrr, etc.)
            forcing_type: Description for error messages
            is_error: If True, missing path is error; otherwise warning
        """
        if not source:
            return

        path = self.runtime.get_forcing_path(source)

        if path is None:
            msg = f"COMIN{source.upper()} not set but {forcing_type} forcing requires {source}"
            if is_error:
                self.result.add_error(msg)
            else:
                self.result.add_warning(msg)
        elif not path.exists():
            msg = f"COMIN{source.upper()}={path} does not exist"
            self.result.add_warning(msg)


class SystemValidator:
    """
    Validates SystemConfig for internal consistency.

    Checks:
    - Required fields are set
    - Model type is valid
    - Grid files are specified
    """

    VALID_MODEL_TYPES = ["schism", "fvcom", "roms"]
    VALID_FRAMEWORKS = ["stofs", "comf", "nosofs", ""]

    def __init__(self, system: "SystemConfig"):
        """
        Initialize validator.

        Args:
            system: SystemConfig to validate
        """
        self.system = system
        self.result = ValidationResult()

    def validate(self) -> ValidationResult:
        """
        Run all validations.

        Returns:
            ValidationResult with errors and warnings
        """
        self._validate_identity()
        self._validate_model_type()
        self._validate_grid()
        self._validate_run_config()

        return self.result

    def _validate_identity(self) -> None:
        """Validate system identity fields."""
        if not self.system.name:
            self.result.add_error("System name is not set")

    def _validate_model_type(self) -> None:
        """Validate model type."""
        model_type = self.system.model_type.lower()
        if not model_type:
            self.result.add_error("Model type is not set")
        elif model_type not in self.VALID_MODEL_TYPES:
            self.result.add_error(
                f"Invalid model type: {model_type}. "
                f"Must be one of: {self.VALID_MODEL_TYPES}"
            )

        framework = self.system.framework.lower()
        if framework and framework not in self.VALID_FRAMEWORKS:
            self.result.add_warning(
                f"Unknown framework: {framework}. "
                f"Expected one of: {self.VALID_FRAMEWORKS}"
            )

    def _validate_grid(self) -> None:
        """Validate grid configuration."""
        grid = self.system.grid

        if not grid.horizontal:
            self.result.add_error("Horizontal grid file not specified")

        if self.system.model_type.lower() == "schism" and not grid.vertical:
            self.result.add_warning("Vertical grid file not specified for SCHISM system")

    def _validate_run_config(self) -> None:
        """Validate run configuration."""
        if self.system.physics.dt <= 0:
            self.result.add_error(f"Timestep must be positive, got: {self.system.physics.dt}")

        if self.system.forecast_days <= 0:
            self.result.add_error(
                f"Forecast days must be positive, got: {self.system.forecast_days}"
            )

        if self.system.hindcast_days < 0:
            self.result.add_error(
                f"Hindcast days cannot be negative, got: {self.system.hindcast_days}"
            )
