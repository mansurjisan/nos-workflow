"""Unified ``OFSConfig`` facade.

Composes the config pieces that today live apart — the registry descriptor,
the two-tier YAML loader (``parm/base/<model>.yaml`` + ``parm/systems/<ofs>.yaml``),
and the NCO runtime env — behind one object, so callers stop re-parsing YAML
and re-reading ``os.environ`` ad hoc.

This is a strangler-fig facade: it **delegates** to the existing
``utils.yaml_to_env`` loader/exporter and ``env.NCOEnv`` rather than
reimplementing them, so the shell-export output stays byte-identical to the
legacy path. Nothing else is rewired yet — consumers adopt it incrementally.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from . import registry
from .env import NCOEnv
from .errors import ConfigError
from .registry import OFSDescriptor
from .utils import yaml_to_env as _yte


def _resolve_yaml_path(yaml_path: Path) -> Path:
    """Resolve a (possibly relative) descriptor ``yaml_path`` against the package root."""
    yaml_path = Path(yaml_path)
    if yaml_path.is_absolute():
        return yaml_path
    root = os.environ.get("HOMEnos") or os.environ.get("PACKAGEROOT") or os.getcwd()
    return Path(root) / yaml_path


def _base_dir_for(yaml_path: Path) -> Path:
    """Mirror ``yaml_to_env.export_for_shell``: a ``systems/<ofs>.yaml`` file
    resolves its ``_base`` from the parent's parent (so ``parm/base/`` is found)."""
    if yaml_path.parent.name == "systems":
        return yaml_path.parent.parent
    return yaml_path.parent


class OFSConfig:
    """Unified, read-through view of one OFS system's configuration.

    Composes three existing pieces:
      * ``registry.OFSDescriptor`` — static per-system metadata
      * the deep-merged two-tier YAML (via
        ``utils.yaml_to_env.load_yaml_with_inheritance``)
      * ``env.NCOEnv`` — the NCO runtime/cycle env (lazy: only built on access,
        since ``NCOEnv.from_env`` requires COMOUT/DATA)

    Typed accessors return read-through views over the merged YAML; the
    ``to_shell_*`` methods delegate to ``utils.yaml_to_env`` so shell exports
    are byte-identical to the legacy resolver path.
    """

    def __init__(
        self,
        *,
        descriptor: Optional[OFSDescriptor],
        merged: Dict[str, Any],
        yaml_path: Optional[Path] = None,
        env: Optional[NCOEnv] = None,
    ) -> None:
        self._descriptor = descriptor
        self._merged = merged
        self._yaml_path = yaml_path
        self._env = env

    # ---- constructors -------------------------------------------------

    @classmethod
    def load(
        cls,
        ofs: str,
        env: Optional[NCOEnv] = None,
        *,
        config_path: Optional[Union[str, Path]] = None,
    ) -> "OFSConfig":
        """Build an ``OFSConfig`` for ``ofs`` via the registry.

        The runtime env is **not** eagerly built (``NCOEnv.from_env`` requires
        COMOUT/DATA); pass ``env`` to attach one, or let :attr:`runtime` build
        it lazily on first access.
        """
        registry.load_all_descriptors()
        descriptor = registry.lookup(ofs.lower() if isinstance(ofs, str) else ofs)

        if config_path is not None:
            yaml_path = Path(config_path)
        else:
            if descriptor.yaml_path is None:
                raise ConfigError(
                    f"descriptor for ofs={descriptor.name!r} has no yaml_path"
                )
            yaml_path = _resolve_yaml_path(descriptor.yaml_path)

        if not yaml_path.exists():
            raise ConfigError(f"YAML config not found: {yaml_path}")

        merged = _yte.load_yaml_with_inheritance(yaml_path, _base_dir_for(yaml_path))
        return cls(descriptor=descriptor, merged=merged, yaml_path=yaml_path, env=env)

    @classmethod
    def from_path(
        cls,
        config_path: Union[str, Path],
        env: Optional[NCOEnv] = None,
        descriptor: Optional[OFSDescriptor] = None,
    ) -> "OFSConfig":
        """Build directly from a YAML path (no registry lookup)."""
        yaml_path = Path(config_path)
        if not yaml_path.exists():
            raise ConfigError(f"YAML config not found: {yaml_path}")
        merged = _yte.load_yaml_with_inheritance(yaml_path, _base_dir_for(yaml_path))
        return cls(descriptor=descriptor, merged=merged, yaml_path=yaml_path, env=env)

    # ---- identity -----------------------------------------------------

    @property
    def name(self) -> str:
        if self._descriptor is not None:
            return self._descriptor.name
        return self.system.get("name", "")

    @property
    def descriptor(self) -> Optional[OFSDescriptor]:
        return self._descriptor

    @property
    def merged(self) -> Dict[str, Any]:
        """The fully-merged (base + system) YAML dict."""
        return self._merged

    @property
    def yaml_path(self) -> Optional[Path]:
        return self._yaml_path

    @property
    def export_framework(self) -> str:
        """The ``yaml_to_env`` framework family for shell exports.

        The descriptor's dispatch label is mapped to its config-export family:
        ``comf_standalone`` (ROMS/FVCOM standalone) shares COMF's export block.
        Falls back to ``auto`` (detect from ``system.framework`` in YAML).
        """
        fw = self._descriptor.framework if self._descriptor is not None else "auto"
        if fw == "comf_standalone":
            return "comf"
        return fw or "auto"

    # ---- typed accessors (read-through views over the merged YAML) ----

    @property
    def system(self) -> Mapping[str, Any]:
        return self._merged.get("system", {})

    @property
    def grid(self) -> Mapping[str, Any]:
        return self._merged.get("grid", {})

    @property
    def forcing(self) -> Mapping[str, Any]:
        return self._merged.get("forcing", {})

    @property
    def model(self) -> Mapping[str, Any]:
        return self._merged.get("model", {})

    @property
    def ufs_coastal(self) -> Mapping[str, Any]:
        return self._merged.get("ufs_coastal", {})

    @property
    def ensemble(self) -> Mapping[str, Any]:
        return self._merged.get("ensemble", {})

    @property
    def resources(self) -> Mapping[str, Any]:
        return self._merged.get("resources", {})

    @property
    def runtime(self) -> NCOEnv:
        """The NCO runtime env, built lazily from ``os.environ`` on first
        access (requires COMOUT/DATA — raises ``ConfigError`` if absent)."""
        if self._env is None:
            self._env = NCOEnv.from_env(ofs=self.name or None)
        return self._env

    # ---- shell-export adapter (delegates; byte-identical to legacy) ---

    def to_shell_exports(
        self,
        framework: Optional[str] = None,
        section: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Flat ``{shell_var: value}`` table — delegates to ``yaml_to_env``."""
        fw = framework or self.export_framework
        exports = _yte.export_shell_mappings(self._merged, fw)
        if section:
            exports = _yte.filter_by_section(exports, section)
        return exports

    def to_shell_string(
        self,
        framework: Optional[str] = None,
        section: Optional[str] = None,
        output_format: str = "shell",
    ) -> str:
        """Render the export table as shell/json/ctl — delegates to ``yaml_to_env``."""
        exports = self.to_shell_exports(framework=framework, section=section)
        if output_format == "json":
            return _yte.format_json(exports)
        if output_format == "ctl":
            return _yte.format_ctl_file(exports, self.system.get("name", "unknown"))
        return _yte.format_shell_exports(exports)


__all__ = ["OFSConfig"]
