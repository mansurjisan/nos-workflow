"""
Unified OFS Configuration

This module provides backward compatibility with the legacy flat OFSConfig
interface while the codebase migrates to the new layered configuration system.

New code should use:
    from nos_ofs.config import OFSConfig  # New layered config

Legacy code continues to work:
    from nos_ofs.config import OFSConfig  # Maps to LegacyConfigAdapter

The new configuration system separates:
- SystemConfig: Static system definition from YAML (immutable)
- RuntimeConfig: Runtime context from environment variables (mutable)
- OFSConfig: Unified access combining both with computed properties

See config/ module for full documentation.
"""

import warnings
from pathlib import Path
from typing import Any, Union

# Import from config submodules (avoid circular imports)
from .unified import OFSConfig as NewOFSConfig, ConfigurationError, DataNotFoundError
from .system import SystemConfig
from .runtime import RuntimeConfig
from .loader import YAMLConfigLoader
from .validation import ValidationResult, RuntimeValidator
from .compat import LegacyConfigAdapter


class OFSConfig(LegacyConfigAdapter):
    """
    Unified configuration for all OFS systems.

    MIGRATION NOTICE: This class now wraps the new layered configuration
    system while maintaining backward compatibility with the legacy flat
    interface. New code should use:

        from nos_ofs.config import OFSConfig
        config = OFSConfig.load("stofs_3d_atl")  # New API

        # Access new-style config
        print(config.system.model_type)
        print(config.runtime.pdy)
        print(config.run_start)  # Computed property

    Legacy flat attributes still work but emit deprecation warnings:

        print(config.HOMEnos)  # Works, but warns
        print(config.runtime.home_nos)  # Preferred

    Attributes:
        ofs_name: OFS system name (e.g., 'stofs_3d_atl', 'cbofs')
        model_type: Hydrodynamic model type ('schism', 'fvcom', 'roms')
        framework: Operational framework ('stofs', 'comf')
    """

    @classmethod
    def load(
        cls,
        system_name: str,
        config_dir: Path = None,
        validate: bool = True,
    ) -> "OFSConfig":
        """
        Load configuration for a system by name.

        This is the new preferred API. Searches for configuration file
        in standard locations and loads runtime from environment.

        Args:
            system_name: System name (e.g., 'stofs_3d_atl')
            config_dir: Optional config directory override
            validate: Whether to validate configuration

        Returns:
            OFSConfig instance
        """
        new_config = NewOFSConfig.load(
            system_name, config_dir=config_dir, validate=validate
        )
        adapter = cls.__new__(cls)
        adapter._config = new_config
        adapter._yaml_data = new_config.system._raw
        adapter._warned = set()
        return adapter

    @classmethod
    def from_yaml(
        cls, yaml_file: Union[str, Path], env_override: bool = True
    ) -> "OFSConfig":
        """
        Load configuration from YAML file.

        Maintains backward compatibility with legacy API.

        Args:
            yaml_file: Path to YAML configuration file
            env_override: Whether environment variables override YAML values

        Returns:
            OFSConfig instance
        """
        return LegacyConfigAdapter.from_yaml(yaml_file, env_override)

    @classmethod
    def from_environment(cls) -> "OFSConfig":
        """
        Create configuration from environment variables only.

        Returns:
            OFSConfig instance
        """
        return LegacyConfigAdapter.from_environment()


# Backward compatibility alias
StofsConfig = OFSConfig

# Export all config classes for convenient access
__all__ = [
    # Main classes
    "OFSConfig",
    "StofsConfig",  # Legacy alias
    # New-style classes
    "NewOFSConfig",
    "SystemConfig",
    "RuntimeConfig",
    # Utilities
    "YAMLConfigLoader",
    "ValidationResult",
    "RuntimeValidator",
    "LegacyConfigAdapter",
    # Exceptions
    "ConfigurationError",
    "DataNotFoundError",
]
