"""OFS descriptor type and process-global registry."""
from __future__ import annotations

import importlib
import pkgutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from .errors import OFSNotRegisteredError, StageNotFoundError


@dataclass(frozen=True)
class OFSDescriptor:
    """Static metadata for one OFS system."""

    name: str
    framework: str
    canonical_stages: Tuple[str, ...]
    stage_aliases: Mapping[str, str] = field(default_factory=dict)
    extra_stages: Tuple[str, ...] = ()
    yaml_path: Optional[Path] = None
    runner_module: str = ""
    notes: str = ""

    def resolve_stage(self, requested: str) -> str:
        """Map ``requested`` to a canonical or extra stage name."""
        if not isinstance(requested, str) or not requested:
            raise StageNotFoundError(
                f"stage name must be a non-empty string, got {requested!r}"
            )
        key = requested.strip().lower()

        for alias, canonical in self.stage_aliases.items():
            if alias.lower() == key:
                return canonical

        for stage in self.canonical_stages:
            if stage.lower() == key:
                return stage

        for stage in self.extra_stages:
            if stage.lower() == key:
                return stage

        known = list(self.canonical_stages) + list(self.extra_stages) + list(
            self.stage_aliases.keys()
        )
        raise StageNotFoundError(
            f"unknown stage {requested!r} for ofs={self.name!r}; "
            f"known: {sorted(set(known))}"
        )


_REGISTRY: Dict[str, OFSDescriptor] = {}


def register(desc: OFSDescriptor) -> None:
    """Add ``desc`` to the process-global registry."""
    if not isinstance(desc, OFSDescriptor):
        raise TypeError(
            f"register() expected OFSDescriptor, got {type(desc).__name__}"
        )
    _REGISTRY[desc.name.lower()] = desc


def lookup(name: str) -> OFSDescriptor:
    """Return the descriptor for ``name`` (case-insensitive)."""
    if not isinstance(name, str) or not name:
        raise OFSNotRegisteredError(
            f"ofs name must be a non-empty string, got {name!r}"
        )
    desc = _REGISTRY.get(name.strip().lower())
    if desc is None:
        raise OFSNotRegisteredError(
            f"no descriptor registered for ofs={name!r}; "
            f"registered: {sorted(_REGISTRY.keys())}"
        )
    return desc


def list_ofs() -> List[OFSDescriptor]:
    """Return every registered descriptor, sorted by ``name``."""
    return sorted(_REGISTRY.values(), key=lambda d: d.name)


def is_registered(name: str) -> bool:
    """Return True if ``name`` resolves to a descriptor."""
    if not isinstance(name, str) or not name:
        return False
    return name.strip().lower() in _REGISTRY


def load_all_descriptors() -> None:
    """Import every module under ``nos_workflow.descriptors``."""
    from . import descriptors as _pkg

    pkg_path = list(_pkg.__path__)
    for mod_info in pkgutil.iter_modules(pkg_path):
        if mod_info.name.startswith("_"):
            continue
        full_name = f"{_pkg.__name__}.{mod_info.name}"
        if full_name in sys.modules:
            importlib.reload(sys.modules[full_name])
        else:
            importlib.import_module(full_name)


__all__ = [
    "OFSDescriptor",
    "register",
    "lookup",
    "list_ofs",
    "is_registered",
    "load_all_descriptors",
]
