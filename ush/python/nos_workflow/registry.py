"""OFS descriptor type and process-global registry.

The architecture is *descriptors-as-data*: each OFS gets a small frozen
dataclass that names its framework, canonical workflow stages, alias
mapping, runner module, and YAML path. The CLI dispatches via these
descriptors instead of subclassing a model hierarchy — see strategic
plan issue #219 for the rationale.

Concrete descriptor modules live under ``nos_workflow.descriptors``;
each one calls :func:`register` at import time. The CLI triggers those
imports via :func:`load_all_descriptors`.
"""
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
    """Static metadata for one OFS system.

    Frozen so descriptor modules can't accidentally mutate registry
    state at runtime. Anything that would need to vary at runtime
    (cycle, PDY, member id, resource counts) belongs in the YAML or
    ``NCOEnv``, not here.
    """

    name: str
    framework: str
    canonical_stages: Tuple[str, ...]
    stage_aliases: Mapping[str, str] = field(default_factory=dict)
    extra_stages: Tuple[str, ...] = ()
    yaml_path: Optional[Path] = None
    runner_module: str = ""
    notes: str = ""

    def resolve_stage(self, requested: str) -> str:
        """Map ``requested`` to a canonical or extra stage name.

        Resolution order:
            1. ``stage_aliases`` (e.g. STOFS ``prep_nowcast`` → ``prep``)
            2. ``canonical_stages``
            3. ``extra_stages``

        Input is matched case-insensitively but the returned name is
        always the descriptor's own casing.

        Raises:
            StageNotFoundError: ``requested`` is not in any of the three
                tables.
        """
        if not isinstance(requested, str) or not requested:
            raise StageNotFoundError(
                f"stage name must be a non-empty string, got {requested!r}"
            )
        key = requested.strip().lower()

        # Aliases (case-insensitive on the alias key)
        for alias, canonical in self.stage_aliases.items():
            if alias.lower() == key:
                return canonical

        # Canonical stages
        for stage in self.canonical_stages:
            if stage.lower() == key:
                return stage

        # Extra stages
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


# ---------------------------------------------------------------------------
# Process-global registry
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, OFSDescriptor] = {}


def register(desc: OFSDescriptor) -> None:
    """Add ``desc`` to the process-global registry.

    Re-registering the same name with a different descriptor replaces
    the previous entry. Tests that swap descriptors in and out should
    snapshot ``_REGISTRY`` at setup and restore it at teardown.
    """
    if not isinstance(desc, OFSDescriptor):
        raise TypeError(
            f"register() expected OFSDescriptor, got {type(desc).__name__}"
        )
    _REGISTRY[desc.name.lower()] = desc


def lookup(name: str) -> OFSDescriptor:
    """Return the descriptor for ``name``. Case-insensitive.

    Raises:
        OFSNotRegisteredError: no descriptor module has registered the
            name yet (likely missed :func:`load_all_descriptors`).
    """
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
    """Return every registered descriptor, sorted by ``name``.

    Used by ``nos_uw list``. Order is stable for golden-output tests.
    """
    return sorted(_REGISTRY.values(), key=lambda d: d.name)


def is_registered(name: str) -> bool:
    """Return True if ``name`` resolves to a descriptor. Case-insensitive."""
    if not isinstance(name, str) or not name:
        return False
    return name.strip().lower() in _REGISTRY


def load_all_descriptors() -> None:
    """Import every module under ``nos_workflow.descriptors``.

    Each descriptor module registers itself at import time via
    ``register(...)``. To stay idempotent across tests that clear the
    registry mid-session, we ``reload`` already-imported modules so
    their top-level ``register`` calls fire again.
    """
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
