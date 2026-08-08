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


def test_secofs_ufs_ww3_descriptor_shape():
    """SECOFS-UFS-WW3 (DATM+SCHISM+WW3) mirrors secofs_ufs's descriptor
    shape exactly -- same framework ("comf") and runner_module, since the
    wave-specific behavior lives inside the shared runner (gated on the
    WAV_TASKS env var), not on a separate dispatch label."""
    desc = lookup("secofs_ufs_ww3")
    assert desc.framework == "comf"
    assert desc.canonical_stages == ("prep", "nowcast", "forecast", "post")
    assert desc.stage_aliases == {}
    assert desc.yaml_path == Path("parm/systems/secofs_ufs_ww3.yaml")
    assert desc.runner_module == "nos_workflow.runners.ufs_coastal"


def test_stofs_3d_atl_ufs_descriptor_shape():
    """STOFS-3D-ATL on UFS-Coastal mirrors the secofs_ufs descriptor shape.

    Distinct framework label (``stofs_ufs``) so the dispatcher can branch
    on the UFS-Coastal stack without colliding with the legacy ``stofs``
    framework; canonical stage names directly (no ``prep_nowcast`` /
    ``now_forecast`` aliases like the standalone STOFS-3D-ATL descriptor);
    same UFS-Coastal runner as secofs_ufs.
    """
    desc = lookup("stofs_3d_atl_ufs")
    assert desc.framework == "stofs_ufs"
    assert desc.canonical_stages == ("prep", "nowcast", "forecast", "post")
    assert desc.stage_aliases == {}
    assert desc.yaml_path == Path("parm/systems/stofs_3d_atl_ufs.yaml")
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


def test_cbofs_descriptor_shape():
    """cbofs is ROMS standalone. The dispatch label ``comf_standalone`` keeps
    it off the SCHISM-UFS ``comf`` path (which is hardwired to
    nos_utils.nco_bridge); the YAML schema is unchanged (system.framework
    stays ``comf``)."""
    desc = lookup("cbofs")
    assert desc.framework == "comf_standalone"
    assert desc.canonical_stages == ("prep", "nowcast", "forecast", "post")
    assert desc.stage_aliases == {}
    assert desc.yaml_path == Path("parm/systems/cbofs.yaml")
    assert desc.runner_module == "nos_workflow.runners.comf_standalone"


def test_dbofs_descriptor_shape():
    desc = lookup("dbofs")
    assert desc.framework == "comf_standalone"
    assert desc.canonical_stages == ("prep", "nowcast", "forecast", "post")
    assert desc.yaml_path == Path("parm/systems/dbofs.yaml")
    assert desc.runner_module == "nos_workflow.runners.comf_standalone"


def test_ngofs2_descriptor_shape():
    desc = lookup("ngofs2")
    assert desc.framework == "comf_standalone"
    assert desc.canonical_stages == ("prep", "nowcast", "forecast", "post")
    assert desc.yaml_path == Path("parm/systems/ngofs2.yaml")
    assert desc.runner_module == "nos_workflow.runners.comf_standalone"


def test_descriptors_are_frozen():
    """Frozen dataclass: no field can be mutated after construction."""
    desc = lookup("secofs_ufs")
    with pytest.raises((AttributeError, Exception)):
        desc.framework = "stofs"  # type: ignore[misc]
