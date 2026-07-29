"""Unit tests for ``nos_workflow.runners.schism_ufs.mesh.generate_esmf_mesh``.

Mirrors the behavior of the inline Python heredoc that previously lived
in ``ush/nos_run.sh`` (lines 855-912 pre-PR-4). All cases use synthetic
NetCDF fixtures built in ``tmp_path`` -- no real forcing data needed.

Coverage:

  - Output structure: required dims (nodeCount, elementCount,
    maxNodePElement=4, coordDim=2) and variables (nodeCoords,
    elementConn, numElementConn, elementMask, centerCoords).
  - Counts: 10x10 forcing -> 100 quad elements (the data points),
    121 staggered corner nodes.
  - elementMask: ALL ONES (MEMORY.md lesson #18 -- 0 masks all elements
    in CMEPS bilinear regrid).
  - 1-D vs 2-D lon/lat input: both produce equivalent meshes.
  - Fallback path: ``x``/``y`` variable names work when
    ``longitude``/``latitude`` are absent.
  - Center coords: 4-node averages of element corners.
  - Attributes: title and gridType written.

Tests are auto-skipped when netCDF4 is not importable on the runner.
"""
from __future__ import annotations

from pathlib import Path

import pytest


netCDF4 = pytest.importorskip("netCDF4")
np = pytest.importorskip("numpy")

from nos_workflow.runners.schism_ufs.mesh import generate_esmf_mesh


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_forcing_1d(path: Path, nx: int = 10, ny: int = 10) -> Path:
    """Build a synthetic DATM forcing NetCDF with 1-D longitude/latitude."""
    ds = netCDF4.Dataset(str(path), 'w')
    ds.createDimension('longitude', nx)
    ds.createDimension('latitude', ny)
    lon = ds.createVariable('longitude', 'f8', ('longitude',))
    lat = ds.createVariable('latitude', 'f8', ('latitude',))
    lon[:] = np.linspace(-100.0, -80.0, nx)
    lat[:] = np.linspace(20.0, 40.0, ny)
    ds.close()
    return path


def _make_forcing_2d(path: Path, nx: int = 10, ny: int = 10) -> Path:
    """Build a synthetic DATM forcing NetCDF with 2-D longitude/latitude."""
    ds = netCDF4.Dataset(str(path), 'w')
    ds.createDimension('x', nx)
    ds.createDimension('y', ny)
    lon = ds.createVariable('longitude', 'f8', ('y', 'x'))
    lat = ds.createVariable('latitude', 'f8', ('y', 'x'))
    lon1d = np.linspace(-100.0, -80.0, nx)
    lat1d = np.linspace(20.0, 40.0, ny)
    lon2d, lat2d = np.meshgrid(lon1d, lat1d)
    lon[:] = lon2d
    lat[:] = lat2d
    ds.close()
    return path


def _make_forcing_xy(path: Path, nx: int = 10, ny: int = 10) -> Path:
    """Build a synthetic forcing using ``x``/``y`` 2-D vars (fallback path)."""
    ds = netCDF4.Dataset(str(path), 'w')
    ds.createDimension('x', nx)
    ds.createDimension('y', ny)
    # NOTE: deliberately omit ``longitude`` / ``latitude`` so the
    # KeyError fallback to ``x``/``y`` is exercised.
    xv = ds.createVariable('x', 'f8', ('y', 'x'))
    yv = ds.createVariable('y', 'f8', ('y', 'x'))
    lon1d = np.linspace(-100.0, -80.0, nx)
    lat1d = np.linspace(20.0, 40.0, ny)
    lon2d, lat2d = np.meshgrid(lon1d, lat1d)
    xv[:] = lon2d
    yv[:] = lat2d
    ds.close()
    return path


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------


def test_mesh_output_file_exists_and_is_valid_netcdf(tmp_path):
    """Generated mesh file opens cleanly with netCDF4."""
    forcing = _make_forcing_1d(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"

    rc = generate_esmf_mesh(forcing, out)

    assert rc == 0
    assert out.is_file()
    # Reopen to confirm the file is a valid NetCDF.
    ds = netCDF4.Dataset(str(out), 'r')
    ds.close()


def test_mesh_dimensions_match_expected_counts(tmp_path):
    """10x10 forcing -> 100 elements (one per data point) and 11x11 = 121
    corner nodes; canonical ESMF dims maxNodePElement=4 and coordDim=2
    are present."""
    forcing = _make_forcing_1d(tmp_path / "forcing.nc", nx=10, ny=10)
    out = tmp_path / "mesh.nc"

    rc = generate_esmf_mesh(forcing, out)
    assert rc == 0

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert len(ds.dimensions['nodeCount']) == 121
        assert len(ds.dimensions['elementCount']) == 100
        assert len(ds.dimensions['maxNodePElement']) == 4
        assert len(ds.dimensions['coordDim']) == 2
    finally:
        ds.close()


def test_mesh_required_variables_present(tmp_path):
    """All five canonical ESMF mesh variables exist."""
    forcing = _make_forcing_1d(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        names = set(ds.variables.keys())
    finally:
        ds.close()
    assert {"nodeCoords", "elementConn", "numElementConn",
            "elementMask", "centerCoords"} <= names


def test_mesh_nodeCoords_shape_is_nodes_by_2(tmp_path):
    """nodeCoords stores (lon, lat) pairs along coordDim=2."""
    forcing = _make_forcing_1d(tmp_path / "forcing.nc", nx=10, ny=10)
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert ds.variables['nodeCoords'].shape == (121, 2)
    finally:
        ds.close()


def test_mesh_elementConn_shape_is_elems_by_4(tmp_path):
    """elementConn stores 4 node indices per quad."""
    forcing = _make_forcing_1d(tmp_path / "forcing.nc", nx=10, ny=10)
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert ds.variables['elementConn'].shape == (100, 4)
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# elementMask -- MEMORY.md lesson #18 critical invariant
# ---------------------------------------------------------------------------


def test_mesh_elementMask_is_all_ones(tmp_path):
    """elementMask MUST be all 1s. MEMORY.md lesson #18: elementMask=0
    silently masks every element from the CMEPS ATM->OCN bilinear regrid
    and SCHISM receives zero atmospheric forcing -- model runs cleanly
    but produces garbage."""
    forcing = _make_forcing_1d(tmp_path / "forcing.nc", nx=10, ny=10)
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        mask = ds.variables['elementMask'][:]
    finally:
        ds.close()
    assert mask.shape == (100,)
    assert (mask == 1).all(), "elementMask must be all ones (CMEPS regrid)"


# ---------------------------------------------------------------------------
# Input variants: 1-D, 2-D, x/y fallback
# ---------------------------------------------------------------------------


def test_mesh_accepts_2d_longitude_latitude(tmp_path):
    """2-D lon/lat input produces the same node count as 1-D."""
    forcing = _make_forcing_2d(tmp_path / "forcing.nc", nx=10, ny=10)
    out = tmp_path / "mesh.nc"

    rc = generate_esmf_mesh(forcing, out)
    assert rc == 0

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert len(ds.dimensions['nodeCount']) == 121
        assert len(ds.dimensions['elementCount']) == 100
    finally:
        ds.close()


def test_mesh_falls_back_to_x_y_vars(tmp_path):
    """When longitude/latitude are missing, fall back to ``x``/``y``."""
    forcing = _make_forcing_xy(tmp_path / "forcing.nc", nx=10, ny=10)
    out = tmp_path / "mesh.nc"

    rc = generate_esmf_mesh(forcing, out)
    assert rc == 0

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert len(ds.dimensions['nodeCount']) == 121
        assert ds.variables['nodeCoords'].shape == (121, 2)
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# centerCoords correctness
# ---------------------------------------------------------------------------


def test_mesh_centerCoords_are_4node_averages(tmp_path):
    """Each centerCoords entry equals the mean of its 4 corner nodeCoords.
    Catches off-by-one in the 1-based ``start_index`` indexing."""
    forcing = _make_forcing_1d(tmp_path / "forcing.nc", nx=10, ny=10)
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        node_coords = ds.variables['nodeCoords'][:]
        conn = ds.variables['elementConn'][:]
        centers = ds.variables['centerCoords'][:]
    finally:
        ds.close()

    # Recompute centers from the connectivity (subtracting 1 to go from
    # ESMF 1-based to numpy 0-based).
    expected = node_coords[conn - 1].mean(axis=1)
    assert np.allclose(centers, expected, rtol=1e-12, atol=1e-12)


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


def test_mesh_attributes_match_heredoc(tmp_path):
    """``title`` and ``gridType`` match the verbatim strings from the
    pre-PR-4 heredoc (preserves byte-equivalence with the legacy mesh)."""
    forcing = _make_forcing_1d(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert ds.title == 'ESMF mesh generated from DATM forcing file'
        assert ds.gridType == 'unstructured mesh'
    finally:
        ds.close()


def test_mesh_nodeCoords_units_attribute(tmp_path):
    """nodeCoords and centerCoords carry the ``degrees`` units attribute."""
    forcing = _make_forcing_1d(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert ds.variables['nodeCoords'].units == 'degrees'
        assert ds.variables['centerCoords'].units == 'degrees'
        assert ds.variables['elementConn'].start_index == 1
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


def test_mesh_returns_nonzero_on_missing_forcing(tmp_path):
    """Missing forcing file -> non-zero rc (shell falls back to template
    mesh on this signal)."""
    out = tmp_path / "mesh.nc"
    rc = generate_esmf_mesh(tmp_path / "does_not_exist.nc", out)
    assert rc != 0
    # And the output file must not exist on failure.
    assert not out.exists()
