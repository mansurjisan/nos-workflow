"""STOFS-3D-ATL ops river inputs: the fetch tool stages the FIX files nos-utils reads,
and the system standalone ATL yaml alone turns the ops river path on."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
FETCH = REPO / "tools" / "fetch_stofs_3d_atl_fix.sh"
SYSTEMS = REPO / "parm" / "systems"


def _fetch_map() -> dict:
    block = re.search(r'FILES="\n(.*?)"\n', FETCH.read_text(), re.S).group(1)
    return dict(line.split() for line in block.splitlines() if line.strip())


def test_fetch_tool_stages_the_ops_river_files_under_bare_names():
    nwm = pytest.importorskip("nos_utils.forcing.nwm")
    staged = _fetch_map()
    assert set(nwm._OPS_RIVER_FIX.values()) == {
        "stofs_3d_atl_river_source_sink.in",
        "stofs_3d_atl_river_msource.th",
        "stofs_3d_atl_river_vsink.th",
    }
    for name in nwm._OPS_RIVER_FIX.values():
        assert staged[name] == name  # nos-utils looks for the ops name next to the json
    assert staged["stofs_3d_atl_river_sources_conus.json"] == "stofs_3d_atl_river_sources_conus.json"


@pytest.mark.parametrize("name,expected", [
    ("stofs_3d_atl_ufs", False),
    ("stofs_3d_atl_ufs_standalone", True),
    ("secofs_ufs", False),
    ("stofs_3d_ak_ufs", False),
])
def test_yaml_enables_ops_river_for_standalone_atl_only(name, expected):
    pytest.importorskip("yaml")
    config = pytest.importorskip("nos_utils.config")
    cfg = config.ForcingConfig.from_yaml(SYSTEMS / f"{name}.yaml", pdy="20261001", cyc=12)
    assert cfg.river_ops_static is expected


def test_atl_yaml_names_the_json_the_fetch_tool_stages():
    yaml = pytest.importorskip("yaml")
    river = yaml.safe_load((SYSTEMS / "stofs_3d_atl_ufs.yaml").read_text())["forcing"]["river"]
    assert river["ops_static_files"] is False
    assert river["files"]["sources_json"] in _fetch_map()
