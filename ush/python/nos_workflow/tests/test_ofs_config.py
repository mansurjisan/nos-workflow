"""OFSConfig facade tests: round-trip + byte-parity vs the legacy yaml_to_env path.

The facade must produce shell exports **byte-identical** to
``yaml_to_env.export_for_shell`` (the canonical resolver). This is the gate that
lets later phases fold the dual resolvers into OFSConfig without changing the
shell-export output: as long as ``config.py`` keeps delegating, these pass by
construction; the moment a future change makes the facade transform anything,
they go red.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nos_workflow.config import OFSConfig
from nos_workflow.env import NCOEnv
from nos_workflow.errors import ConfigError
from nos_workflow.registry import list_ofs, load_all_descriptors, lookup
from nos_workflow.utils import yaml_to_env as yte


# .../nos_ofs/ush/python/nos_workflow/tests/test_ofs_config.py -> .../nos_ofs
REPO_ROOT = Path(__file__).resolve().parents[4]


def _existing_ofs():
    """Registered OFS whose YAML config actually exists on disk.

    (stofs_3d_atl / stofs_2d_glo are registered but have no parm/systems
    YAML yet, so they are skipped here rather than failing the parity gate.)
    """
    load_all_descriptors()
    return [
        desc.name
        for desc in list_ofs()
        if desc.yaml_path and (REPO_ROOT / desc.yaml_path).is_file()
    ]


@pytest.fixture(autouse=True)
def _frozen_env(monkeypatch):
    """Resolve relative yaml_paths against the repo root, with a fixed cycle so
    the computed time values are deterministic on both code paths."""
    monkeypatch.setenv("HOMEnos", str(REPO_ROOT))
    monkeypatch.setenv("PDY", "20260101")
    monkeypatch.setenv("cyc", "00")


@pytest.mark.parametrize("ofs", _existing_ofs())
def test_to_shell_string_byte_identical_to_legacy(ofs):
    desc = lookup(ofs)
    yaml_path = REPO_ROOT / desc.yaml_path
    # comf_standalone (ROMS/FVCOM) shares COMF's config-export family.
    mapped_fw = "comf" if desc.framework == "comf_standalone" else desc.framework

    cfg = OFSConfig.load(ofs)
    expected = yte.export_for_shell(yaml_path, framework=mapped_fw)

    assert cfg.to_shell_string() == expected


@pytest.mark.parametrize("ofs", _existing_ofs())
def test_to_shell_string_auto_framework_matches_legacy_auto(ofs):
    yaml_path = REPO_ROOT / lookup(ofs).yaml_path
    cfg = OFSConfig.load(ofs)
    assert cfg.to_shell_string(framework="auto") == yte.export_for_shell(
        yaml_path, framework="auto"
    )


@pytest.mark.parametrize("ofs", _existing_ofs())
def test_merged_yaml_round_trips_loader(ofs):
    yaml_path = REPO_ROOT / lookup(ofs).yaml_path
    base_dir = yaml_path.parent.parent  # parm/systems/<ofs>.yaml -> parm
    cfg = OFSConfig.load(ofs)
    assert cfg.merged == yte.load_yaml_with_inheritance(yaml_path, base_dir)


def test_load_does_not_require_nco_runtime_env(monkeypatch):
    """Config/shell-export use must not need COMOUT/DATA — the runtime env is
    lazy, so OFSConfig.load works for `list`/`env`/inspection paths."""
    monkeypatch.delenv("COMOUT", raising=False)
    monkeypatch.delenv("DATA", raising=False)
    cfg = OFSConfig.load("secofs_ufs")
    assert cfg.name == "secofs_ufs"
    assert "OFS=secofs_ufs" in cfg.to_shell_string()


def test_runtime_is_lazy_and_raises_without_env(monkeypatch):
    monkeypatch.delenv("COMOUT", raising=False)
    monkeypatch.delenv("DATA", raising=False)
    cfg = OFSConfig.load("secofs_ufs")
    with pytest.raises(ConfigError):
        _ = cfg.runtime


def test_runtime_returns_injected_env(monkeypatch):
    monkeypatch.setenv("COMOUT", "/tmp/comout_test")
    monkeypatch.setenv("DATA", "/tmp/data_test")
    env = NCOEnv.from_env(ofs="secofs_ufs")
    cfg = OFSConfig.load("secofs_ufs", env=env)
    assert cfg.runtime is env


def test_from_path_matches_load(monkeypatch):
    yaml_path = REPO_ROOT / "parm" / "systems" / "secofs_ufs.yaml"
    by_path = OFSConfig.from_path(yaml_path)
    by_load = OFSConfig.load("secofs_ufs")
    assert by_path.merged == by_load.merged
    # from_path has no descriptor, so it auto-detects framework from YAML;
    # secofs_ufs.yaml declares system.framework: comf, matching the descriptor.
    assert by_path.to_shell_string(framework="comf") == by_load.to_shell_string()


def test_unknown_ofs_raises():
    with pytest.raises(Exception):
        OFSConfig.load("not_a_real_ofs")
