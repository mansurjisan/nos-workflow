"""Production add_attr port: masking, attributes, isolated ponds."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

netCDF4 = pytest.importorskip("netCDF4")
pytest.importorskip("scipy")

from nos_workflow.post.products import fields, ops_fields  # noqa: E402

# 5 nodes in a line 0-1-2-3-4, plus an unrelated node 5 joined to 4 only
_EDGES = np.array([[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]])


def _out2d(path: Path, dry, base="' 2026  9 30      12.00       0.00'") -> None:
    nt, nn = dry.shape
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", nn)
        ds.createDimension("nSCHISM_vgrid_layers", 3)
        ds.createDimension("nSCHISM_hgrid_edge", len(_EDGES))
        ds.createDimension("two", 2)
        t = ds.createVariable("time", "f8", ("time",))
        t.units = "seconds since 2026-09-30T12:00:00+00"
        t.base_date = base.strip("'")
        t[:] = np.arange(nt) * 3600.0
        e = ds.createVariable("elevation", "f4", ("time", "nSCHISM_hgrid_node"))
        e[:] = 2.5
        d = ds.createVariable("dryFlagNode", "f4", ("time", "nSCHISM_hgrid_node"))
        d[:] = dry
        en = ds.createVariable("SCHISM_hgrid_edge_nodes", "i4", ("nSCHISM_hgrid_edge", "two"))
        en[:] = _EDGES + 1
        ds.createVariable("windSpeedX", "f4", ("time", "nSCHISM_hgrid_node"))[:] = 1.0


def test_parse_base_date_schism_and_iso():
    assert ops_fields.parse_base_date(" 2026  9 30      12.00       0.00") == (
        2026, 9, 30, 12.0, 0.0,
    )
    assert ops_fields.parse_base_date("2026-10-01 12:00:00")[:4] == (2026, 10, 1, 12.0)
    assert ops_fields.parse_base_date("garbage") is None


def test_time_attrs_match_production_strings():
    got = ops_fields.time_attrs((2026, 9, 30, 12.0, 0.0))
    assert got == {
        "units": "seconds since 2026-09-30 12:00:00 +0",
        "base_date": "2026 09 30 12 0",
    }


def test_isolated_ponds_flags_wet_component_without_seed():
    seed = np.array([1, 0, 0, 0, 0, 0], dtype=bool)
    wet = np.ones(6, dtype=bool)
    assert not ops_fields.isolated_ponds(wet, seed, _EDGES).any()
    wet[2] = False  # cuts the line: nodes 3,4,5 lose the seed
    pond = ops_fields.isolated_ponds(wet, seed, _EDGES)
    assert pond.tolist() == [False, False, False, True, True, True]
    seed2 = seed.copy()
    seed2[0] = False  # dry seed is no seed
    wet2 = np.array([0, 1, 1, 1, 1, 1], dtype=bool)
    assert ops_fields.isolated_ponds(wet2, seed2, _EDGES).sum() == 5


def test_seed_roundtrip(tmp_path):
    seed = np.zeros(13, dtype=bool)
    seed[[0, 5, 12]] = True
    ops_fields.save_pond_seed(tmp_path / "s.npz", seed)
    assert np.array_equal(ops_fields.read_pond_seed(tmp_path / "s.npz"), seed)


def test_stamp_stack_masks_stamps_and_is_idempotent(tmp_path):
    dry = np.zeros((2, 6), dtype="f4")
    dry[:, 2] = 1
    f = tmp_path / "out2d_1.nc"
    _out2d(f, dry)
    idmask = np.array([0, 1, 0, 0, 0, 1], dtype=np.int32)
    seed = np.array([1, 0, 0, 0, 0, 0], dtype=bool)
    for _ in range(2):
        ops_fields.stamp_stack(
            netCDF4.Dataset, f, "out2d", idmask=idmask, pond_seed=seed,
        )
    with netCDF4.Dataset(f) as ds:
        ds.set_auto_mask(False)
        elev = ds["elevation"][:]
        assert (elev[:, [1, 5]] == -99999).all() and (elev[:, [0, 2, 3, 4]] == 2.5).all()
        assert ds["elevation"].missing_value == np.float32(-99999)
        assert ds["elevation"].long_name == "water surface elevation above xgeoid20b"
        assert ds["windSpeedX"].units == "m/s"
        assert ds["time"].units == "seconds since 2026-09-30 12:00:00 +0"
        assert ds["time"].base_date == "2026 09 30 12 0"
        assert ds["idmask"][:].tolist() == idmask.tolist()
        assert ds["vgrid_dummy"].shape == (3,)
        assert ds["isolatedPondNode"][0].tolist() == [0, 0, 0, 1, 1, 1]
        assert ds["isolatedPondNode"].dtype == np.int8


def test_stamp_stack_3d_attrs_only(tmp_path):
    f = tmp_path / "salinity_1.nc"
    with netCDF4.Dataset(f, "w") as ds:
        ds.createDimension("time", None)
        ds.createDimension("n", 2)
        ds.createVariable("time", "f8", ("time",))[:] = [0.0]
        ds.createVariable("salinity", "f4", ("time", "n"))[:] = 1.0
    ops_fields.stamp_stack(
        netCDF4.Dataset, f, "salinity", fallback_base_date="2026-09-30 12:00:00",
    )
    with netCDF4.Dataset(f) as ds:
        assert ds["salinity"].units == "PSU"
        assert ds["salinity"].mesh == "SCHISM_hgrid"
        assert ds["time"].units == "seconds since 2026-09-30 12:00:00 +0"


def test_worker_ops_attrs_requires_idmask(tmp_path, capsys):
    st = tmp_path / "stg"
    st.mkdir()
    _out2d(st / "out2d_1.nc", np.zeros((1, 6), dtype="f4"))
    rc = fields.main([
        "--staging", str(st), "--comout", str(tmp_path), "--prefix", "p",
        "--cyc", "12", "--pdy", "20261001", "--phase", "nowcast", "--ops-attrs",
    ])
    assert rc == 5


def test_worker_without_flag_leaves_stack_untouched(tmp_path):
    st = tmp_path / "stg"
    st.mkdir()
    com = tmp_path / "com"
    com.mkdir()
    _out2d(st / "out2d_1.nc", np.zeros((1, 6), dtype="f4"))
    assert fields.main([
        "--staging", str(st), "--comout", str(com), "--prefix", "p",
        "--cyc", "12", "--pdy", "20261001", "--phase", "nowcast",
    ]) == 0
    with netCDF4.Dataset(st / "out2d_1.nc") as ds:
        assert "idmask" not in ds.variables
        assert "units" not in ds["elevation"].ncattrs()
