"""STOFS-3D-ATL coupled param.nml stays aligned with the ops param the standalone path uses."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
FIX = REPO / "fix" / "stofs_3d_atl_ufs"
COUPLED = FIX / "stofs_3d_atl_ufs.param.nml"
OPS = FIX / "stofs_3d_atl_ufs.standalone.param.nml"

# Runner-patched or coupling-specific; everything else must match ops. MJ (09/30/26)
_MAY_DIFFER = {
    "rnday", "nws", "ihot",
    "start_year", "start_month", "start_day", "start_hour",
}
# Ops keys the pinned coupled SCHISM does not declare (renamed or CPP-derived),
# plus the analysis outputs ops v3.1 does not write. MJ (09/30/26)
_OPS_ONLY_OK = {"isav", "isconsv", "meth_sink", "vclose_surf_frac"} | {
    f"iof_ana({i})" for i in range(1, 15)
}
_COUPLED_ONLY_OK = {
    "i_hmin_airsea_ex", "iveg", "nbins_veg_vert", "nmarsh_types",
    "relax_2_airt",
}


def _groups(path: Path) -> dict:
    """{group: {key: value}} per namelist group; fails on a duplicate key or a
    key outside a group. MJ (09/30/26)"""
    groups, current = {}, None
    for raw in path.read_text().splitlines():
        line = raw.split("!")[0].strip()
        if not line:
            continue
        if line.startswith("&"):
            current = line[1:].strip().upper()
            groups[current] = {}
        elif line == "/":
            current = None
        else:
            m = re.match(r"([\w()]+)\s*=\s*(\S+)", line)
            if m:
                assert current is not None, f"{path.name}: {line!r} outside a group"
                assert m.group(1) not in groups[current], f"{path.name}: duplicate {m.group(1)}"
                groups[current][m.group(1)] = m.group(2)
    return groups


def _parse(path: Path) -> dict:
    return {k: v for g in _groups(path).values() for k, v in g.items()}


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
    assert nowcast_steps % nhot_write == 0  # restart lands at nowcast end MJ (09/30/26)
    assert ihfskip == 288  # 12 h stacks, as in ops post MJ (09/30/26)


def test_coupled_prep_walltime():
    pbs = (REPO / "pbs" / "stofs_3d_atl_ufs" / "jnos_prep_00.pbs").read_text()
    assert "walltime=03:00:00" in pbs


def test_nudge_step_matches_nos_utils_files():
    """nos-utils writes TEM_nu/SAL_nu every 3 h (nudging.py target_dt); SCHISM
    picks records by time/step_nu_tr without checking the file's time axis."""
    for path in (COUPLED, OPS):
        assert _parse(path)["step_nu_tr"] == "10800."


def test_coupled_turns_off_air_temperature_relaxation():
    assert _groups(COUPLED)["OPT"]["relax_2_airt"] == "0."


def test_coupled_groups_match_ops_groups():
    """Each shared key sits in the same namelist group as in the ops file."""
    c, o = _groups(COUPLED), _groups(OPS)
    assert set(c) == {"CORE", "OPT", "SCHOUT"}
    where = {k: g for g, keys in o.items() for k in keys}
    moved = {k: (g, where[k]) for g, keys in c.items() for k in keys
             if k in where and where[k] != g}
    assert moved == {}
