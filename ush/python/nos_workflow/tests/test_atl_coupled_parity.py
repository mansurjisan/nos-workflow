"""STOFS-3D-ATL coupled ops-parity wiring: executable, rivers, atmospheric flags, gating. MJ (10/03/26)"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from nos_workflow.runners.schism_ufs import stage_files
from nos_workflow.runners.schism_ufs.context import SchismRunContext
from nos_workflow.utils import yaml_to_env

SYSTEMS = Path(__file__).resolve().parents[4] / "parm" / "systems"


def _env(name):
    pytest.importorskip("yaml")
    data = yaml_to_env.load_yaml_with_inheritance(SYSTEMS / f"{name}.yaml", SYSTEMS)
    return yaml_to_env.export_shell_mappings(data)


def test_coupled_atl_exports_its_own_executable(monkeypatch):
    monkeypatch.delenv("UFS_EXEC_NAME", raising=False)
    assert _env("stofs_3d_atl_ufs")["UFS_EXEC_NAME"] == "fv3_stofs_3d_atl.exe"


def test_standalone_keeps_the_ops_pschism(monkeypatch):
    monkeypatch.delenv("UFS_EXEC_NAME", raising=False)
    assert _env("stofs_3d_atl_ufs_standalone")["UFS_EXEC_NAME"] == "stofs_3d_atl_pschism_v3.1.5"


@pytest.mark.parametrize("name", ["secofs_ufs", "secofs_ufs_ww3", "stofs_3d_ak_ufs", "stofs_3d_pac_ufs"])
def test_other_systems_export_no_executable_name(name, monkeypatch):
    monkeypatch.delenv("UFS_EXEC_NAME", raising=False)
    path = SYSTEMS / f"{name}.yaml"
    if not path.is_file():
        pytest.skip(f"{name}.yaml absent")
    assert "UFS_EXEC_NAME" not in _env(name)


def test_atl_yaml_atmospheric_parity_keys():
    yaml = pytest.importorskip("yaml")
    atm = yaml.safe_load((SYSTEMS / "stofs_3d_atl_ufs.yaml").read_text())["forcing"]["atmospheric"]
    assert atm["gfs"]["ops_timeline"] is True
    assert atm["hrrr"] == {"rotate_winds": False, "blend_rotate_winds": False, "small_grib": True}


@pytest.mark.parametrize("name,rotates", [
    ("stofs_3d_atl_ufs", False), ("stofs_3d_atl_ufs_standalone", False),
    ("secofs_ufs", True), ("stofs_3d_ak_ufs", True), ("stofs_3d_pac_ufs", True),
])
def test_forcing_config_resolves_per_system(name, rotates):
    pytest.importorskip("yaml")
    config = pytest.importorskip("nos_utils.config")
    path = SYSTEMS / f"{name}.yaml"
    if not path.is_file():
        pytest.skip(f"{name}.yaml absent")
    cfg = config.ForcingConfig.from_yaml(path, pdy="20261001", cyc=12)
    assert cfg.hrrr_rotate_winds is rotates
    assert cfg.datm_rotate_hrrr_winds is rotates
    assert cfg.gfs_ops_timeline is (not rotates)
    assert cfg.hrrr_small_grib is (not rotates)


def _ctx(tmp_path, prefix="stofs_3d_atl_ufs"):
    for d in ("comout", "data", "fix", "exec"):
        (tmp_path / d).mkdir(exist_ok=True)
    return SchismRunContext(
        comout=tmp_path / "comout", data=tmp_path / "data", phase="nowcast",
        run="x", cycle="t12z", prefixnos=prefix,
        fixofs=tmp_path / "fix", execnos=tmp_path / "exec",
    )


def test_coupled_atl_missing_executable_hard_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("USE_DATM", raising=False)
    monkeypatch.setenv("UFS_EXEC_NAME", "fv3_stofs_3d_atl.exe")
    with pytest.raises(FileNotFoundError, match="fv3_stofs_3d_atl.exe"):
        stage_files.stage_executable(_ctx(tmp_path), "nowcast")


def test_coupled_atl_executable_staged_from_execnos(tmp_path, monkeypatch):
    monkeypatch.delenv("USE_DATM", raising=False)
    monkeypatch.setenv("UFS_EXEC_NAME", "fv3_stofs_3d_atl.exe")
    ctx = _ctx(tmp_path)
    exe = ctx.execnos / "fv3_stofs_3d_atl.exe"
    exe.write_bytes(b"x")
    os.chmod(exe, 0o755)
    assert stage_files.stage_executable(ctx, "nowcast") == 1
    assert (ctx.data / "fv3_stofs_3d_atl.exe").is_file()


def test_other_ufs_systems_stay_silent_when_the_executable_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("USE_DATM", raising=False)
    monkeypatch.setenv("UFS_EXEC_NAME", "fv3_coastalSW.exe")
    assert stage_files.stage_executable(_ctx(tmp_path, "secofs_ufs_ww3"), "nowcast") == 0
