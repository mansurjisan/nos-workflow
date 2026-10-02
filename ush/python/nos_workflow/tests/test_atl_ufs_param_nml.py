"""STOFS-3D-ATL coupled param.nml vs the ops v3.1.5 param the standalone path uses; standalone == ops."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
FIX = REPO / "fix" / "stofs_3d_atl_ufs"
COUPLED = FIX / "stofs_3d_atl_ufs.param.nml"
OPS = FIX / "stofs_3d_atl_ufs.standalone.param.nml"
OPS_V315 = Path(__file__).resolve().parent / "data" / "stofs_3d_atl_ops_v3.1.5.param.nml"

# Runner-patched or coupling-specific; everything else must match ops. MJ (09/30/26)
_MAY_DIFFER = {
    "rnday", "nws", "ihot",
    "start_year", "start_month", "start_day", "start_hour",
    # ops v3.1.5 values the coupled SCHISM build/output set does not follow. MJ (10/02/26)
    "flag_ic(7)", "iof_hydro(2)", "iof_hydro(17)", "iof_hydro(21)",
    "drampwafo", "nbins_veg_vert",
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


def test_coupled_only_keys_are_the_documented_ones():
    c, o = _parse(COUPLED), _parse(OPS)
    assert set(c) - set(o) == {"relax_2_airt"}


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
    """nos-utils writes 6-hourly TEM_nu/SAL_nu phase files (ops-effective nudging);
    SCHISM picks records by time/step_nu_tr without checking the file's time axis."""
    for path in (COUPLED, OPS):
        assert _parse(path)["step_nu_tr"] == "21600."


def test_coupled_turns_off_air_temperature_relaxation():
    assert _groups(COUPLED)["OPT"]["relax_2_airt"] == "0."


def test_coupled_groups_match_ops_groups():
    """Each shared key sits in the same namelist group as in the ops file."""
    c, o = _groups(COUPLED), _groups(OPS)
    assert set(c) == {"CORE", "OPT", "SCHOUT"}
    assert set(o) == {"CORE", "OPT", "SCHOUT"}
    where = {k: g for g, keys in o.items() for k in keys}
    moved = {k: (g, where[k]) for g, keys in c.items() for k in keys
             if k in where and where[k] != g}
    assert moved == {}


def _strip_port_header(text: str) -> str:
    marker = "! ---- end port header ----\n"
    assert text.count(marker) == 1
    return text.split(marker, 1)[1]


def test_standalone_template_is_ops_v315_except_step_nu_tr():
    """Standalone param.nml == the stored ops v3.1.5 template, line for line,
    except the port header and the one deliberate step_nu_tr edit. MJ (10/02/26)"""
    ops = OPS_V315.read_text().splitlines()
    ours = _strip_port_header(OPS.read_text()).splitlines()
    assert len(ours) == len(ops)
    diff = [(a, b) for a, b in zip(ours, ops) if a != b]
    assert len(diff) == 1
    assert diff[0][0].strip().startswith("step_nu_tr = 21600.")
    assert diff[0][1].strip().startswith("step_nu_tr = 216000.")


def test_standalone_template_has_every_runner_patched_key():
    """The runner's patchers (configure.patch_param_nml) must match each key. MJ (10/02/26)"""
    text = OPS.read_text()
    for key in ("rnday", "start_year", "start_month", "start_day", "start_hour"):
        assert re.search(rf"^\s*{key}\s*=\s*[0-9.]*", text, re.M), key
    for key in ("ihot", "nws"):
        assert re.search(rf"\b{key} = [0-9]*", text), key


def test_standalone_runner_patches_only_documented_keys(tmp_path):
    """Run the real patcher for both phases; only the run-control keys change. MJ (10/02/26)"""
    import shutil
    from nos_workflow.runners.schism_ufs import configure
    from nos_workflow.runners.schism_ufs.context import SchismRunContext

    base = _parse(OPS)
    for phase, start, days in (("nowcast", "2026092612", "1.0"),
                               ("forecast", "2026092712", "4.0")):
        data = tmp_path / phase
        data.mkdir()
        shutil.copy(OPS, data / "param.nml")
        ctx = SchismRunContext(
            comout=tmp_path, data=data, phase=phase, run="x", cycle="t12z",
            pdy="20260927", cyc="12", prefixnos="stofs_3d_atl_ufs",
            time_hotstart="2026092612", time_nowcastend="2026092712",
            len_nowcast="24", len_forecast="96",
        )
        import os
        old = os.environ.get("USE_DATM")
        os.environ["USE_DATM"] = "false"
        try:
            configure.patch_param_nml(ctx, phase)
        finally:
            if old is None:
                os.environ.pop("USE_DATM")
            else:
                os.environ["USE_DATM"] = old
        got = _parse(data / "param.nml")
        changed = {k for k in got if got[k] != base[k]}
        assert changed <= {"rnday", "start_year", "start_month", "start_day", "start_hour"}
        assert got["rnday"] == days
        assert (got["start_year"], got["start_month"], got["start_day"]) == (
            start[:4], str(int(start[4:6])), str(int(start[6:8])))
        assert got["ihot"] == "1" and got["nws"] == "2"
