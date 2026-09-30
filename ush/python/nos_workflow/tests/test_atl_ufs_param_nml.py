"""STOFS-3D-ATL coupled param.nml stays aligned with the ops v3.1 values."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
FIX = REPO / "fix" / "stofs_3d_atl_ufs"
COUPLED = FIX / "stofs_3d_atl_ufs.param.nml"
OPS = FIX / "stofs_3d_atl_ufs.standalone.param.nml"

# Runner-patched or coupling-specific; everything else must match ops.
_MAY_DIFFER = {
    "rnday", "nws", "ihot",
    "start_year", "start_month", "start_day", "start_hour",
}
# Ops keys the pinned coupled SCHISM does not declare (renamed or CPP-derived).
_OPS_ONLY_OK = {"isav", "isconsv", "meth_sink", "vclose_surf_frac"}
_COUPLED_ONLY_OK = {
    "i_hmin_airsea_ex", "iveg", "nbins_veg_vert", "nmarsh_types",
    "vclose_surf_frac0",
}


def _parse(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        line = line.split("!")[0].strip()
        m = re.match(r"([\w()]+)\s*=\s*(\S+)", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def test_shared_keys_match_ops():
    c, o = _parse(COUPLED), _parse(OPS)
    bad = {k: (c[k], o[k]) for k in c.keys() & o.keys()
           if k not in _MAY_DIFFER and c[k] != o[k]}
    assert bad == {}


def test_key_set_differences_are_the_documented_ones():
    c, o = _parse(COUPLED), _parse(OPS)
    assert set(o) - set(c) == _OPS_ONLY_OK
    assert set(c) - set(o) == _COUPLED_ONLY_OK


def test_coupled_run_control_preserved():
    c = _parse(COUPLED)
    assert c["nws"] == "4"
    assert c["rnday"] == "rnday_value"
    assert c["start_year"] == "start_year_value"
    assert c["dt"] == "150."


def test_restart_cadence_consistent():
    c = _parse(COUPLED)
    ihfskip, nhot_write = int(c["ihfskip"]), int(c["nhot_write"])
    nowcast_steps = 24 * 3600 // 150
    assert nhot_write % int(c["ihfskip"]) == 0
    assert nhot_write % int(c["nspool_sta"]) == 0
    assert nowcast_steps % nhot_write == 0  # restart lands at nowcast end
    assert ihfskip == 288  # 12 h stacks, as in ops post


def test_coupled_prep_walltime():
    pbs = (REPO / "pbs" / "stofs_3d_atl_ufs" / "jnos_prep_00.pbs").read_text()
    assert "walltime=03:00:00" in pbs
