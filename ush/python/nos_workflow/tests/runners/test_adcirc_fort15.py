"""fort.15 / fort.rotm from nos-workflow vs Zach Cobell's generate_fort15.

Committed goldens were produced by his code from the same synthetic mesh and
config; when the read-only clone is present the comparison is also run live.
Set ADCIRC_REGEN_GOLDEN=1 to rewrite the goldens from the clone. MJ (10/05/26)
"""
from __future__ import annotations

import os
import socket
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.runners.adcirc.fort15 import Fort15Spec, write_fort15  # noqa: E402
from nos_workflow.runners.adcirc.mesh import read_mesh_info  # noqa: E402

GOLDEN = Path(__file__).resolve().parents[1] / "data" / "adcirc"
ZACH = Path(os.environ.get(
    "ZACH_REPO", "/mnt/d/NOS-Workflow-Project/STOFS_2DGLO_P0/zach_repo")) / "ush"

PHYSICS = {"preset": "jjw", "coordinate_rotation": [114.16991, 0.77432],
           "coordinate_system": 22}
TIDES = ["K1", "O1", "P1", "Q1", "M2", "S2", "N2", "K2", "MF", "MM", "M4", "MS4",
         "MN4", "SA", "SSA"]
CYCLE = datetime(2026, 10, 4, 12)
COLD = datetime(2026, 9, 16, 12)

# name: (coldstart, start, end, hotstart_unit)
PHASES = {
    "nowcast_cold": (COLD, COLD, CYCLE, 0),
    "nowcast_hot": (COLD, datetime(2026, 10, 4, 6), CYCLE, 67),
    "forecast": (COLD, CYCLE, datetime(2026, 10, 12), 67),
}
CASES = [(p, nws) for p in PHASES for nws in (0, 14)]


def _write_mesh(path: Path, rivers: bool) -> None:
    nodes = [(1, -170.0, -50.0, 10.0), (2, -60.0, 20.0, 20.0), (3, 30.0, 60.0, 30.0),
             (4, 100.0, -10.0, 40.0), (5, 150.0, 45.0, 50.0)]
    elems = [(1, 3, 1, 2, 3), (2, 3, 2, 3, 4), (3, 3, 3, 4, 5)]
    lines = ["synthetic", f"{len(elems)} {len(nodes)}"]
    lines += [f"{i} {x} {y} {z}" for i, x, y, z in nodes]
    lines += [" ".join(map(str, e)) for e in elems]
    lines += ["1 ! open", "2 ! total open nodes", "2 ! n", "1", "2"]
    if rivers:
        lines += ["2 ! land", "4 ! total", "2 22", "1", "2", "2 52", "3", "4"]
    else:
        lines += ["1 ! land", "3 ! total", "3 0", "3", "4", "5"]
    path.write_text("\n".join(lines) + "\n")


def _spec(mesh_path, phase, nws, tides):
    cold, start, end, unit = PHASES[phase]
    return Fort15Spec(
        name="gstofs", mesh_name="stofs2dglobal", coldstart_time=cold, start_time=start,
        end_time=end, dt=6.0, physics=PHYSICS, attributes=["mannings_n_at_sea_floor"],
        mesh=read_mesh_info(mesh_path), tides=tides, tide_constituents=TIDES,
        hotstart_unit=unit, nws=nws, ice=nws == 14, ramp=5.0)


def _tides(phase):
    from nos_utils.forcing.adcirc_tides import compute_adcirc_tides

    cold, _, end, _ = PHASES[phase]
    out = compute_adcirc_tides(TIDES, cold, (end - cold).total_seconds() / 86400.0)
    return {t.name.upper(): t for t in out}


def _zach(mesh_path: Path, phase: str, nws: int, out_dir: Path) -> Path:
    sys.path.insert(0, str(ZACH))
    sys.modules.setdefault("haversine", types.SimpleNamespace(Unit=None, haversine=None))
    try:
        from StofsWorkflow.executables import ModelExecutables  # noqa: F401
        from StofsWorkflow.models.adcirc.adcirc import Adcirc
        from StofsWorkflow.models.adcirc.adcirc_config import AdcircConfig
    except Exception as exc:  # his code needs Python >= 3.9. MJ (10/05/26)
        pytest.skip("Zach's StofsWorkflow does not import here: {!r}".format(exc))
    finally:
        sys.path.remove(str(ZACH))
    cold, start, end, unit = PHASES[phase]
    cfg = AdcircConfig(
        name="stofs2dglobal", dt=6.0, executables=None, mesh_file=str(mesh_path),
        attributes_file="fort.13", attributes=["mannings_n_at_sea_floor"],
        physics=dict(PHYSICS), tide_constituents=list(TIDES), ramp=5.0)
    model = Adcirc(
        name="gstofs", coldstart_time=cold, start_time=start, end_time=end,
        mesh_config=cfg, water_level=0.0, waves=False, ice=nws == 14, hotstart_unit=unit,
        output=20, ramp=5.0, wind_multiplier=1.0, nws=nws, wind_fields=None, wind_dt=3600,
        flow_rates=None, swan_hotstart=False, station_file=None, flux_settling=0,
        output_options=None)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.generate_fort15(str(out_dir / "fort.15"))
    return out_dir


@pytest.fixture(autouse=True)
def _host(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "testhost")


@pytest.fixture(params=[False, True], ids=["plain", "rivers"])
def rivers(request):
    return request.param


@pytest.fixture
def mesh_path(rivers, tmp_path):
    p = tmp_path / "fort.14"
    _write_mesh(p, rivers)
    return p


def _golden_name(rivers, phase, nws):
    return f"{'rivers' if rivers else 'plain'}_{phase}_nws{nws}"


@pytest.mark.parametrize("phase,nws", CASES)
def test_fort15_matches_golden(mesh_path, rivers, tmp_path, phase, nws):
    out = tmp_path / "run"
    out.mkdir()
    write_fort15(_spec(mesh_path, phase, nws, _tides(phase)), out / "fort.15")
    name = _golden_name(rivers, phase, nws)
    if os.environ.get("ADCIRC_REGEN_GOLDEN") == "1":
        z = _zach(mesh_path, phase, nws, tmp_path / "zach")
        (GOLDEN / f"{name}.fort.15").write_bytes((z / "fort.15").read_bytes())
        (GOLDEN / "fort.rotm").write_bytes((z / "fort.rotm").read_bytes())
    assert (out / "fort.15").read_bytes() == (GOLDEN / f"{name}.fort.15").read_bytes()
    assert (out / "fort.rotm").read_bytes() == (GOLDEN / "fort.rotm").read_bytes()


@pytest.mark.skipif(not ZACH.is_dir(), reason="Zach's read-only clone not present")
@pytest.mark.parametrize("phase,nws", CASES)
def test_fort15_matches_zach_live(mesh_path, tmp_path, phase, nws):
    out = tmp_path / "run"
    out.mkdir()
    write_fort15(_spec(mesh_path, phase, nws, _tides(phase)), out / "fort.15")
    z = _zach(mesh_path, phase, nws, tmp_path / "zach")
    assert (out / "fort.15").read_bytes() == (z / "fort.15").read_bytes()
    assert (out / "fort.rotm").read_bytes() == (z / "fort.rotm").read_bytes()


def test_fort15_key_values(mesh_path, tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    write_fort15(_spec(mesh_path, "nowcast_cold", 14, _tides("nowcast_cold")), out / "fort.15")
    text = (out / "fort.15").read_text()
    assert "-22                   ! ICS" in text
    assert "14014                      ! NWS" in text
    assert "0                   ! IHOT" in text
