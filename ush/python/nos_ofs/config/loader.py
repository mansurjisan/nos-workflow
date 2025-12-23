"""
YAML Configuration Loader with Inheritance Support

Provides YAML loading with:
- Base config inheritance via `_base` key
- Deep merging of nested dictionaries
- Path resolution relative to config directory
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union
import yaml


class YAMLConfigLoader:
    """
    Loads YAML configuration files with inheritance support.

    YAML files can specify a `_base` key to inherit from base configurations.
    The inheritance is resolved recursively, allowing multiple levels.

    Example:
        # config/systems/stofs_3d_atl.yaml
        _base: schism  # Inherits from config/base/schism.yaml

        system:
          name: stofs_3d_atl
          # ... overrides and additions
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize the loader.

        Args:
            base_dir: Base directory for resolving config paths.
                     Defaults to the config/ directory in the package.
        """
        if base_dir is None:
            base_dir = Path(__file__).parent
        self.base_dir = Path(base_dir)

    def load(self, path: Union[str, Path]) -> Dict[str, Any]:
        """
        Load a YAML file, resolving inheritance.

        Args:
            path: Path to the YAML file (absolute or relative to base_dir)

        Returns:
            Merged configuration dictionary
        """
        path = self._resolve_path(path)
        return self._load_with_inheritance(path)

    def load_with_inheritance(self, path: Union[str, Path]) -> Dict[str, Any]:
        """
        Load a YAML file with inheritance resolution.

        Alias for load() for backward compatibility.

        Args:
            path: Path to the YAML file

        Returns:
            Merged configuration dictionary
        """
        return self.load(path)

    def _resolve_path(self, path: Union[str, Path]) -> Path:
        """Resolve path to absolute."""
        path = Path(path)
        if path.is_absolute():
            return path
        # If the path exists relative to cwd, use it directly
        if path.exists():
            return path.absolute()
        # Otherwise try relative to base_dir
        return self.base_dir / path

    def _load_with_inheritance(self, path: Path) -> Dict[str, Any]:
        """
        Load YAML with recursive inheritance resolution.

        Args:
            path: Absolute path to YAML file

        Returns:
            Merged configuration dictionary
        """
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}

        # Check for inheritance
        base_name = data.pop("_base", None)
        if base_name:
            # Resolve base config path
            base_path = self._find_base_config(base_name)
            if base_path is None:
                raise FileNotFoundError(
                    f"Base configuration '{base_name}' not found. "
                    f"Looked in: {self.base_dir / 'base'}"
                )

            # Recursively load base (it may have its own _base)
            base_data = self._load_with_inheritance(base_path)

            # Merge: base first, then override with current
            data = self._deep_merge(base_data, data)

        return data

    def _find_base_config(self, base_name: str) -> Optional[Path]:
        """
        Find a base configuration file.

        Args:
            base_name: Name of the base config (without .yaml extension)

        Returns:
            Path to base config or None if not found
        """
        # Look in base/ subdirectory
        base_path = self.base_dir / "base" / f"{base_name}.yaml"
        if base_path.exists():
            return base_path

        # Also check base_dir itself (for flat layouts)
        base_path = self.base_dir / f"{base_name}.yaml"
        if base_path.exists():
            return base_path

        return None

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """
        Deep merge two dictionaries.

        Override values take precedence. Nested dicts are recursively merged.

        Args:
            base: Base dictionary
            override: Override dictionary (takes precedence)

        Returns:
            Merged dictionary
        """
        result = base.copy()

        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                # Recursively merge nested dicts
                result[key] = self._deep_merge(result[key], value)
            else:
                # Override scalar values and lists
                result[key] = value

        return result

    @classmethod
    def find_system_config(cls, system_name: str) -> Optional[Path]:
        """
        Find a system configuration file by name.

        Searches in:
        1. config/systems/{name}.yaml
        2. config/{name}.yaml
        3. {package_root}/{name}.yaml

        Args:
            system_name: System name (e.g., 'stofs_3d_atl')

        Returns:
            Path to config file or None if not found
        """
        config_dir = Path(__file__).parent
        package_dir = config_dir.parent

        search_paths = [
            config_dir / "systems" / f"{system_name}.yaml",
            config_dir / f"{system_name}.yaml",
            package_dir / f"{system_name}.yaml",
        ]

        for path in search_paths:
            if path.exists():
                return path

        return None
