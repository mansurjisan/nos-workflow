"""Post-product registry and per-system product selection.

Selection precedence (first hit wins):

1. ``NOS_POST_PRODUCTS`` env var -- comma/space-separated product names
   (operator override for reruns and debugging).
2. The system YAML ``post.products`` list -- read from ``$OFS_CONFIG``
   when set, else ``$HOMEnos/<descriptor.yaml_path>``; follows the
   ``_base`` overlay chain until a ``post:`` section is found. Entries
   are either bare names or ``{name: ..., enabled: bool}`` mappings.
   An explicit empty list means "run no products".
3. Framework defaults (:data:`DEFAULT_PRODUCTS`).

YAML reading is best-effort: any parse/IO problem logs a warning and
falls through to the defaults -- product selection must never fail the
stage by itself.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Type

from .base import PostProduct

logger = logging.getLogger(__name__)

_REGISTRY: Dict[str, Type[PostProduct]] = {}

_PRODUCTS_ENV = "NOS_POST_PRODUCTS"
_MAX_BASE_HOPS = 4

DEFAULT_PRODUCTS: Dict[str, tuple] = {
    "comf": ("stations_nc", "bias_correct"),
    "stofs_ufs": ("stations_nc", "bias_correct"),
}
_FALLBACK_PRODUCTS = ("stations_nc",)


def register(cls: Type[PostProduct]) -> Type[PostProduct]:
    """Class decorator: add ``cls`` to the registry under ``cls.name``."""
    name = getattr(cls, "name", "")
    if not name:
        raise ValueError(f"post product {cls!r} has no name")
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"post product name {name!r} already registered by {existing!r}"
        )
    _REGISTRY[name] = cls
    return cls


def get_product(name: str) -> Optional[Type[PostProduct]]:
    """Return the product class for ``name``, or None if unregistered."""
    return _REGISTRY.get(name)


def available_products() -> tuple:
    """Registered product names, sorted."""
    return tuple(sorted(_REGISTRY))


def resolve_product_names(
    framework: str,
    env: Mapping[str, str],
    homenos: Optional[Path] = None,
    yaml_path: Optional[Path] = None,
) -> List[str]:
    """Return the ordered product-name list for this run (see module doc)."""
    override = env.get(_PRODUCTS_ENV, "")
    names = [n for n in re.split(r"[,\s]+", override) if n]
    if names:
        logger.info("post products from %s: %s", _PRODUCTS_ENV, names)
        return names

    yaml_file = _locate_yaml(env, homenos, yaml_path)
    if yaml_file is not None:
        from_yaml = _read_yaml_post_products(yaml_file)
        if from_yaml is not None:
            logger.info(
                "post products from %s: %s", yaml_file.name, from_yaml
            )
            return from_yaml

    defaults = list(DEFAULT_PRODUCTS.get(framework, _FALLBACK_PRODUCTS))
    logger.info(
        "post products from %s defaults: %s", framework, defaults
    )
    return defaults


def _locate_yaml(
    env: Mapping[str, str],
    homenos: Optional[Path],
    yaml_path: Optional[Path],
) -> Optional[Path]:
    """$OFS_CONFIG wins; else the descriptor's yaml under $HOMEnos."""
    ofs_config = env.get("OFS_CONFIG", "")
    if ofs_config:
        p = Path(ofs_config)
        if p.is_file():
            return p
    if homenos is not None and yaml_path is not None:
        p = Path(homenos) / yaml_path
        if p.is_file():
            return p
    return None


def _read_yaml_post_products(yaml_file: Path) -> Optional[List[str]]:
    """Extract ``post.products`` from ``yaml_file`` (with ``_base`` merge)."""
    post = _read_yaml_post_mapping(yaml_file)
    if post is None or "products" not in post:
        return None
    return _parse_products(post["products"], yaml_file)


def _read_yaml_post_mapping(yaml_file: Path) -> Optional[dict]:
    """Collect the merged ``post:`` mapping along the ``_base`` chain.

    Overlay keys win over base keys (key-level merge). Returns None when
    no ``post:`` mapping exists anywhere in the chain, or on any
    read/parse error.
    """
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML unavailable; using defaults")
        return None

    merged: Optional[dict] = None
    current: Optional[Path] = yaml_file
    for _ in range(_MAX_BASE_HOPS):
        if current is None or not current.is_file():
            return merged
        try:
            with current.open("r") as fh:
                doc = yaml.safe_load(fh) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read %s: %s", current, exc)
            return None
        if not isinstance(doc, dict):
            logger.warning(
                "%s: yaml root is not a mapping; ignoring", current
            )
            return None

        post_section = doc.get("post")
        if isinstance(post_section, dict):
            if merged is None:
                merged = dict(post_section)
            else:
                for key, val in post_section.items():
                    merged.setdefault(key, val)

        base = doc.get("_base")
        if not base:
            return merged
        base_name = str(base)
        if not base_name.endswith((".yaml", ".yml")):
            base_name += ".yaml"
        current = current.parent / base_name
    logger.warning("_base chain from %s too deep", yaml_file)
    return merged


_ARCHIVE_FIELDS_ENV = "NOS_ARCHIVE_FIELDS"


def resolve_archive_fields(env: Mapping[str, str]) -> bool:
    """True when the run stages should normalize and stage field outputs.

    Precedence: ``NOS_ARCHIVE_FIELDS`` env (yes/true/1 vs no/false/0) >
    yaml ``post.archive_fields`` (via ``$OFS_CONFIG``, else the
    registered descriptor's yaml under ``$HOMEnos``) > False.
    Best-effort: never raises.
    """
    raw = env.get(_ARCHIVE_FIELDS_ENV, "").strip().lower()
    if raw in ("yes", "true", "1"):
        return True
    if raw in ("no", "false", "0"):
        return False

    try:
        homenos, yaml_path = _descriptor_yaml_hint(env)
        yaml_file = _locate_yaml(env, homenos, yaml_path)
        if yaml_file is None:
            return False
        post = _read_yaml_post_mapping(yaml_file)
        if post is None:
            return False
        return bool(post.get("archive_fields", False))
    except Exception as exc:  # noqa: BLE001
        logger.warning("archive_fields resolution failed: %s", exc)
        return False


def _descriptor_yaml_hint(
    env: Mapping[str, str],
) -> "tuple[Optional[Path], Optional[Path]]":
    """(homenos, yaml_path) from the registered descriptor for $OFS."""
    homenos = env.get("HOMEnos")
    ofs = env.get("OFS")
    if not homenos or not ofs:
        return None, None
    try:
        from ..registry import load_all_descriptors, lookup

        load_all_descriptors()
        desc = lookup(ofs)
    except Exception:  # noqa: BLE001
        return None, None
    yaml_path = getattr(desc, "yaml_path", None)
    if yaml_path is None:
        return None, None
    return Path(homenos), Path(yaml_path)


def _parse_products(raw: object, src: Path) -> Optional[List[str]]:
    """Normalize a YAML products list to names; None on a malformed list."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        logger.warning("post.products in %s is not a list; ignoring", src)
        return None
    names: List[str] = []
    for entry in raw:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict) and entry.get("name"):
            if entry.get("enabled", True):
                names.append(str(entry["name"]))
        else:
            logger.warning(
                "post.products entry %r in %s not understood; skipped",
                entry, src,
            )
    return names


__all__ = [
    "DEFAULT_PRODUCTS",
    "available_products",
    "get_product",
    "register",
    "resolve_archive_fields",
    "resolve_product_names",
]
