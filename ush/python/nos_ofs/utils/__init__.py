"""
Utility Functions Package

This package provides utility functions for NOS OFS:
- yaml_to_env: Convert YAML config to shell environment exports
- Logging utilities
- File handling helpers

Usage:
    from nos_ofs.utils import export_for_shell, load_yaml_with_inheritance

    # Load YAML with inheritance support
    config = load_yaml_with_inheritance("config.yaml")

    # Export to shell format
    output = export_for_shell("config.yaml", framework="stofs")
    print(output)  # export LONMIN=-98.5035\nexport LONMAX=...
"""

from .yaml_to_env import (
    load_yaml_with_inheritance,
    export_for_shell,
    export_shell_mappings,
    format_shell_exports,
    format_json,
    format_ctl_file,
    main as yaml_to_env_main,
)

__all__ = [
    "load_yaml_with_inheritance",
    "export_for_shell",
    "export_shell_mappings",
    "format_shell_exports",
    "format_json",
    "format_ctl_file",
    "yaml_to_env_main",
]
