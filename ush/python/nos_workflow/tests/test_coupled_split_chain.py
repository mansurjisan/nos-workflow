"""OLDIO coupled-path chain: combined schout -> split -> slab2d.

Every other product fixture hand-writes scribe-shaped inputs, which is
exactly why a coupled-only defect survived the suite: the splitter
guarded on the scribe spelling ``bottom_index_node`` while
``combine_output11`` writes ``node_bottom_index``, so slab2d silently
produced nothing on the coupled path and reported "skipped" -- identical
to "nothing was staged". This test drives the real converter over a
combine_output11-shaped stack.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# The repo's nos-utils submodule carries nos_utils.post; prefer it over
# any editable install that predates the package, so this exercises the
# real writer instead of silently skipping.
_NOS_UTILS = Path(__file__).resolve().parents[2] / "nos-utils"
if str(_NOS_UTILS) not in sys.path:
    sys.path.insert(0, str(_NOS_UTILS))

netCDF4 = pytest.importorskip("netCDF4")

_REPO_USH = Path(__file__).resolve().parents[3]
_COMBINE = _REPO_USH / "schism_combine_outputs.py"


def _write_oldio_schout(path: Path) -> None:
    """A stack shaped like combine_output11 output.

    Note the deliberate details: the OLDIO bottom-index spelling, a
    2-record time axis (which makes a naive first-size-2-axis search grab
    TIME instead of the vector component), and 3D vars as
    (time, node, layers) -- the Fortran declares (nv, node, time), which
    is that order once netCDF reverses it.
    """
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", 4)
        ds.createDimension("nSCHISM_hgrid_face", 2)
        ds.createDimension("nMaxSCHISM_hgrid_face_nodes", 4)
        ds.createDimension("nSCHISM_vgrid_layers", 3)
        ds.createDimension("two", 2)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-22 06:00:00"
        tv[:] = [3600.0, 7200.0]
        ds.createVariable("elev", "f4", ("time", "nSCHISM_hgrid_node"))[:] = 0.5
        fn = ds.createVariable(
            "SCHISM_hgrid_face_nodes", "i4",
            ("nSCHISM_hgrid_face", "nMaxSCHISM_hgrid_face_nodes"),
            fill_value=-99999,
        )
        fn[:] = [[1, 2, 3, -99999], [2, 4, 3, -99999]]
        ds.createVariable(
            "node_bottom_index", "i4", ("nSCHISM_hgrid_node",))[:] = 1
        for name, vals in (("SCHISM_hgrid_node_x", [0.0, 1.0, 0.0, 1.0]),
                           ("SCHISM_hgrid_node_y", [0.0, 0.0, 1.0, 1.0])):
            ds.createVariable(name, "f8", ("nSCHISM_hgrid_node",))[:] = vals
        ds.createVariable("depth", "f4", ("nSCHISM_hgrid_node",))[:] = 5.0
        d3 = ("time", "nSCHISM_hgrid_node", "nSCHISM_vgrid_layers")
        ds.createVariable("zcor", "f4", d3)[:] = -1.5
        ds.createVariable("temp", "f4", d3)[:] = 20.0
        ds.createVariable("salt", "f4", d3)[:] = 30.0
        hv = ds.createVariable("hvel", "f4", d3 + ("two",))
        hv[..., 0] = 0.5
        hv[..., 1] = -0.5


def _split(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("sco", _COMBINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        mod.convert_schout_to_split()
    finally:
        os.chdir(cwd)


def test_split_carries_mesh_and_vectors(tmp_path):
    _write_oldio_schout(tmp_path / "schout_1.nc")
    _split(tmp_path)

    with netCDF4.Dataset(tmp_path / "out2d_1.nc") as ds:
        # The element table AND the bottom index must survive, under the
        # scribe spelling, or downstream products no-op on this path only.
        assert "SCHISM_hgrid_face_nodes" in ds.variables
        assert "bottom_index_node" in ds.variables
        assert ds["SCHISM_hgrid_face_nodes"]._FillValue == -99999

    # The 2-record time axis must not be mistaken for the vector component.
    for comp in ("horizontalVelX", "horizontalVelY"):
        assert (tmp_path / f"{comp}_1.nc").is_file(), comp
    with netCDF4.Dataset(tmp_path / "horizontalVelX_1.nc") as ds:
        assert ds["horizontalVelX"][:].max() == pytest.approx(0.5)
    with netCDF4.Dataset(tmp_path / "horizontalVelY_1.nc") as ds:
        assert ds["horizontalVelY"][:].min() == pytest.approx(-0.5)
    # Source dimension order is preserved, not assumed.
    with netCDF4.Dataset(tmp_path / "temperature_1.nc") as ds:
        assert ds["temperature"].dimensions == (
            "time", "nSCHISM_hgrid_node", "nSCHISM_vgrid_layers")


def test_slab2d_publishes_from_a_coupled_stack(tmp_path):
    pytest.importorskip("nos_utils.post.slab2d")
    from nos_workflow.post.products import slab2d

    _write_oldio_schout(tmp_path / "schout_1.nc")
    _split(tmp_path)
    comout = tmp_path / "comout"
    comout.mkdir()

    rc = slab2d.main([
        "--staging", str(tmp_path), "--comout", str(comout),
        "--prefix", "secofs_ufs", "--cyc", "12", "--pdy", "20260722",
        "--phase", "forecast", "--base-date", "IGNORED-inherited-from-stack",
    ])
    assert rc == 0
    published = sorted(comout.glob("*.nc"))
    assert len(published) == 1, "slab2d produced nothing on the coupled path"
    with netCDF4.Dataset(published[0]) as ds:
        # Inherited from the stack, not the --base-date argument.
        assert ds["time"].units == "seconds since 2026-07-22 06:00:00"
