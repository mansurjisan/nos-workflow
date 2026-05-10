"""Concrete descriptor module tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from nos_workflow import registry
from nos_workflow.registry import load_all_descriptors, lookup


@pytest.fixture(autouse=True)
def _ensure_descriptors_loaded():
    """Make sure the bundled descriptor modules are registered."""
    original = dict(registry._REGISTRY)
    try:
        load_all_descriptors()
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(original)


def test_secofs_ufs_descriptor_shape():
    desc = lookup("secofs_ufs")
    assert desc.framework == "comf"
    assert desc.canonical_stages == ("prep", "nowcast", "forecast", "post")
    assert desc.stage_aliases == {}
    assert desc.yaml_path == Path("parm/systems/secofs_ufs.yaml")
    assert desc.runner_module == "nos_workflow.runners.ufs_coastal"


def test_stofs_3d_atl_aliases_map_legacy_names():
    desc = lookup("stofs_3d_atl")
    assert desc.framework == "stofs"
    assert desc.stage_aliases.get("prep_nowcast") == "prep"
    assert desc.stage_aliases.get("now_forecast") == "nowcast"
    assert desc.extra_stages == ("post_1", "post_2", "temp_salt_restart")
    # The aliases must round-trip through resolve_stage too.
    assert desc.resolve_stage("prep_nowcast") == "prep"
    assert desc.resolve_stage("now_forecast") == "nowcast"


def test_stofs_2d_glo_is_adcirc_with_no_extras():
    desc = lookup("stofs_2d_glo")
    assert desc.framework == "adcirc"
    assert desc.extra_stages == ()
    assert desc.stage_aliases == {}
    assert desc.canonical_stages == ("prep", "nowcast", "forecast", "post")


def test_descriptors_are_frozen():
    """Frozen dataclass: no field can be mutated after construction."""
    desc = lookup("secofs_ufs")
    with pytest.raises((AttributeError, Exception)):
        desc.framework = "stofs"  # type: ignore[misc]
