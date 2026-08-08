"""Registry / descriptor tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from nos_workflow import registry
from nos_workflow.errors import OFSNotRegisteredError, StageNotFoundError
from nos_workflow.registry import (
    OFSDescriptor,
    is_registered,
    list_ofs,
    load_all_descriptors,
    lookup,
    register,
)


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    """Snapshot the registry around every test in this module.

    Prevents tests that register fakes from leaking into ``test_descriptors``
    and vice-versa.
    """
    original = dict(registry._REGISTRY)
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(original)


def _fake_desc(name: str = "fake_ofs", **overrides) -> OFSDescriptor:
    base = dict(
        name=name,
        framework="comf",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={"prep_nowcast": "prep"},
        extra_stages=("post_1",),
        yaml_path=Path("parm/systems/fake.yaml"),
        runner_module="nos_workflow.runners.fake",
        notes="fake for tests",
    )
    base.update(overrides)
    return OFSDescriptor(**base)


def test_register_and_lookup_round_trip():
    desc = _fake_desc()
    register(desc)
    assert lookup("fake_ofs") is desc
    assert is_registered("fake_ofs") is True


def test_lookup_is_case_insensitive():
    desc = _fake_desc()
    register(desc)
    assert lookup("FAKE_OFS") is desc
    assert lookup("Fake_Ofs") is desc
    assert is_registered("FAKE_OFS") is True


def test_list_ofs_includes_registered_and_is_sorted():
    register(_fake_desc(name="zzz_ofs"))
    register(_fake_desc(name="aaa_ofs"))
    names = [d.name for d in list_ofs()]
    assert "aaa_ofs" in names
    assert "zzz_ofs" in names
    assert names == sorted(names)


def test_lookup_unknown_raises_ofs_not_registered():
    with pytest.raises(OFSNotRegisteredError):
        lookup("nope")


def test_is_registered_handles_empty_and_non_string():
    assert is_registered("") is False
    assert is_registered(None) is False  # type: ignore[arg-type]


def test_register_rejects_non_descriptor():
    with pytest.raises(TypeError):
        register("not a descriptor")  # type: ignore[arg-type]


def test_resolve_stage_canonical_round_trip():
    desc = _fake_desc()
    assert desc.resolve_stage("prep") == "prep"
    assert desc.resolve_stage("forecast") == "forecast"


def test_resolve_stage_alias_resolves_to_canonical():
    desc = _fake_desc()
    assert desc.resolve_stage("prep_nowcast") == "prep"


def test_resolve_stage_extra_round_trips():
    desc = _fake_desc()
    assert desc.resolve_stage("post_1") == "post_1"


def test_resolve_stage_is_case_insensitive():
    desc = _fake_desc()
    assert desc.resolve_stage("PREP") == "prep"
    assert desc.resolve_stage("Prep_Nowcast") == "prep"
    assert desc.resolve_stage("POST_1") == "post_1"


def test_resolve_stage_unknown_raises():
    desc = _fake_desc()
    with pytest.raises(StageNotFoundError):
        desc.resolve_stage("vacuum")


def test_resolve_stage_rejects_empty_input():
    desc = _fake_desc()
    with pytest.raises(StageNotFoundError):
        desc.resolve_stage("")


def test_load_all_descriptors_registers_known_ofses():
    # Wipe registry so we know the names we see came from the loader.
    registry._REGISTRY.clear()
    load_all_descriptors()
    for name in ("secofs_ufs", "secofs_ufs_ww3", "stofs_3d_atl", "stofs_3d_atl_ufs",
                 "stofs_3d_ak_ufs", "stofs_2d_glo",
                 "cbofs", "dbofs", "ngofs2"):
        assert lookup(name).name == name


def test_stofs_3d_atl_ufs_resolves_via_registry():
    """End-to-end: descriptor module registers + framework label survives.

    Mirrors the secofs_ufs assertion style — we round-trip the descriptor
    through ``load_all_descriptors`` and then read back the static identity
    bits the dispatcher cares about. The framework label is the key
    discriminator: it must be ``stofs_ufs`` (not ``comf``, not ``stofs``)
    so dispatch logic branches onto the UFS-Coastal stack.
    """
    registry._REGISTRY.clear()
    load_all_descriptors()
    desc = lookup("stofs_3d_atl_ufs")
    assert desc.name == "stofs_3d_atl_ufs"
    assert desc.framework == "stofs_ufs"
    # SCHISM-based runner — same module as secofs_ufs.
    assert desc.runner_module == "nos_workflow.runners.ufs_coastal"


def test_stofs_3d_ak_ufs_resolves_via_registry():
    """STOFS-3D-AK-UFS registers with the stofs_ufs framework label.

    Alaska is the coupled DATM+SCHISM member of the STOFS family, so the
    same discriminator as the ATL sibling applies: the framework must be
    ``stofs_ufs`` so dispatch branches onto the SCHISM UFS-Coastal stack,
    and the runner module is shared with secofs_ufs / stofs_3d_atl_ufs.
    """
    registry._REGISTRY.clear()
    load_all_descriptors()
    desc = lookup("stofs_3d_ak_ufs")
    assert desc.name == "stofs_3d_ak_ufs"
    assert desc.framework == "stofs_ufs"
    assert desc.runner_module == "nos_workflow.runners.ufs_coastal"
    assert desc.yaml_path == Path("parm/systems/stofs_3d_ak_ufs.yaml")


def test_secofs_ufs_ww3_resolves_via_registry():
    """SECOFS-UFS-WW3 (DATM+SCHISM+WW3) shares secofs_ufs's framework and
    runner module -- the wave-specific behavior is entirely internal to
    the runner (gated on the WAV_TASKS env var), not a dispatch label."""
    registry._REGISTRY.clear()
    load_all_descriptors()
    desc = lookup("secofs_ufs_ww3")
    assert desc.name == "secofs_ufs_ww3"
    assert desc.framework == "comf"
    assert desc.runner_module == "nos_workflow.runners.ufs_coastal"
    assert desc.yaml_path == Path("parm/systems/secofs_ufs_ww3.yaml")
