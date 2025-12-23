"""
NOS OFS Configuration Module

Provides a layered configuration system:
- SystemConfig: Static system definition from YAML (immutable)
- RuntimeConfig: Runtime context from environment variables (mutable)
- OFSConfig: Unified access combining both with computed properties

Usage:
    from nos_ofs.config import OFSConfig

    # Load configuration for a system
    config = OFSConfig.load("stofs_3d_atl")

    # Access static system info
    print(config.system.model_type)  # "schism"
    print(config.system.forcing.atmospheric.primary)  # "gfs"

    # Access runtime info
    print(config.runtime.pdy)  # "20241201"
    print(config.runtime.cyc)  # 12

    # Access computed properties
    print(config.run_start)  # datetime
    print(config.output_prefix)  # "stofs_3d_atl.t12z"
"""

from .system import (
    SystemConfig,
    GridConfig,
    ForcingConfig,
    ForcingSourceConfig,
    ModelPhysicsConfig,
    ResourceConfig,
)
from .runtime import RuntimeConfig
from .unified import OFSConfig, ConfigurationError, DataNotFoundError
from .loader import YAMLConfigLoader
from .validation import ValidationResult, RuntimeValidator
from .compat import LegacyConfigAdapter

__all__ = [
    # Main config class
    "OFSConfig",
    # Component configs
    "SystemConfig",
    "RuntimeConfig",
    "GridConfig",
    "ForcingConfig",
    "ForcingSourceConfig",
    "ModelPhysicsConfig",
    "ResourceConfig",
    # Utilities
    "YAMLConfigLoader",
    "ValidationResult",
    "RuntimeValidator",
    "LegacyConfigAdapter",
    # Exceptions
    "ConfigurationError",
    "DataNotFoundError",
]
