"""Parity test: mesh.py (Python module) vs the pre-PR-4 inline heredoc.

PR 4 ships a structural-equivalence test (dim list, var list, attribute
strings, elementMask invariant). Full byte-diff parity against a
captured datm_esmf_mesh.nc fixture needs the parity-fixture infra coming
in PR 5+; this test will be extended then.

For now we re-run the algorithm against a synthetic 12x14 forcing and
assert the structural invariants that the legacy heredoc upheld:

  - Dim list is exactly {nodeCount, elementCount, maxNodePElement,
    coordDim} (no extras, no missing).
  - Var list is exactly {nodeCoords, elementConn, numElementConn,
    elementMask, centerCoords}.
  - elementMask is all ones (lesson #18 -- never zeros).
  - elementConn.start_index == 1 (ESMF 1-based).
  - title and gridType strings are byte-identical to the heredoc.
  - Quad ordering (n0, n0+1, n0+nx+1, n0+nx) is preserved -- catches
    refactors that accidentally swap CCW for CW.

If anyone changes the heredoc-port algorithm in mesh.py in a way that
breaks one of these invariants, this test fires before WCOSS2 sees it.
"""
from __future__ import annotations

from pathlib import Path

import pytest


netCDF4 = pytest.importorskip("netCDF4")
np = pytest.importorskip("numpy")

from nos_workflow.runners.schism_ufs.mesh import generate_esmf_mesh


# Use slightly non-square dims to catch any ny/nx ordering bugs that a
# square test would mask.
NX, NY = 12, 14


def _build_synthetic_forcing(path: Path) -> Path:
    """1-D longitude/latitude forcing, ``NX``x``NY``."""
    ds = netCDF4.Dataset(str(path), 'w')
    ds.createDimension('longitude', NX)
    ds.createDimension('latitude', NY)
    lon = ds.createVariable('longitude', 'f8', ('longitude',))
    lat = ds.createVariable('latitude', 'f8', ('latitude',))
    lon[:] = np.linspace(-100.0, -80.0, NX)
    lat[:] = np.linspace(20.0, 40.0, NY)
    ds.close()
    return path


def test_parity_dim_list_matches_heredoc(tmp_path):
    """Dim set is exactly the 4 ESMF mesh dims, no more, no less."""
    forcing = _build_synthetic_forcing(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    rc = generate_esmf_mesh(forcing, out)
    assert rc == 0

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        dims = set(ds.dimensions.keys())
    finally:
        ds.close()
    assert dims == {"nodeCount", "elementCount", "maxNodePElement", "coordDim"}


def test_parity_var_list_matches_heredoc(tmp_path):
    """Var set is exactly the 5 ESMF mesh vars."""
    forcing = _build_synthetic_forcing(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        vars_ = set(ds.variables.keys())
    finally:
        ds.close()
    assert vars_ == {
        "nodeCoords", "elementConn", "numElementConn",
        "elementMask", "centerCoords",
    }


def test_parity_element_mask_is_ones_not_zeros(tmp_path):
    """The single most important parity invariant: elementMask = 1.
    If anyone refactors this to ``np.zeros`` the test catches it
    before WCOSS2 wastes a 7-hour cycle on zero atm forcing
    (MEMORY.md lesson #18)."""
    forcing = _build_synthetic_forcing(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        mask = ds.variables['elementMask'][:]
    finally:
        ds.close()
    assert mask.dtype == np.int32, "elementMask must be i4 (matches heredoc)"
    assert (mask == 1).all()
    # Belt-and-suspenders: explicitly check no zeros sneaked in.
    assert (mask != 0).all()


def test_parity_element_conn_start_index_is_one(tmp_path):
    """ESMF uses 1-based connectivity; the heredoc sets start_index=1."""
    forcing = _build_synthetic_forcing(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert ds.variables['elementConn'].start_index == 1
        # numElementConn is always 4 for our quad meshes.
        assert (ds.variables['numElementConn'][:] == 4).all()
    finally:
        ds.close()


def test_parity_attributes_byte_identical_to_heredoc(tmp_path):
    """``title`` and ``gridType`` are byte-identical to the heredoc.
    nccopy + ncdump diff on WCOSS2 will catch any string drift, but
    this saves a 7-hour round-trip if the diff is just an attribute."""
    forcing = _build_synthetic_forcing(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert ds.title == 'ESMF mesh generated from DATM forcing file'
        assert ds.gridType == 'unstructured mesh'
    finally:
        ds.close()


def test_parity_quad_connectivity_order_preserved(tmp_path):
    """Quad nodes are emitted CCW as (SW, SE, NE, NW). Swapping this order
    changes element orientation and breaks CMEPS bilinear regrid."""
    forcing = _build_synthetic_forcing(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        conn = ds.variables['elementConn'][:]
    finally:
        ds.close()

    # Corners live on the staggered (ny+1) x (nx+1) node grid, so a row of
    # nodes is nxe = NX + 1 wide -- not NX. The first element's corners are
    # therefore 1, 2, nxe+2, nxe+1.
    nxe = NX + 1
    expected_first_quad = np.array([1, 2, nxe + 2, nxe + 1], dtype=np.int32)
    assert (conn[0] == expected_first_quad).all(), (
        f"first quad ordering drift: got {conn[0]}, want {expected_first_quad}"
    )


def test_parity_counts_are_cell_centred(tmp_path):
    """elementCount = nx*ny, nodeCount = (nx+1)*(ny+1).

    CDEPS reads stream fields at ESMF_MESHLOC_ELEMENT, so there must be one
    element per data point. The earlier cell-cornered layout gave
    (nx-1)*(ny-1) elements; PIO then read the first (nx-1)*(ny-1) values in
    flat order and the mapping sheared one cell per row. Also guards against
    an ny/nx swap.
    """
    forcing = _build_synthetic_forcing(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        assert len(ds.dimensions['elementCount']) == NX * NY
        assert len(ds.dimensions['nodeCount']) == (NX + 1) * (NY + 1)
    finally:
        ds.close()


def test_parity_element_centres_are_the_data_points(tmp_path):
    """The load-bearing property: centerCoords[k] is the forcing file's own
    k-th point, in the same flattened (y, x) order the data is stored in."""
    forcing = _build_synthetic_forcing(tmp_path / "forcing.nc")
    out = tmp_path / "mesh.nc"
    generate_esmf_mesh(forcing, out)

    src = netCDF4.Dataset(str(forcing), 'r')
    try:
        lons = np.asarray(src.variables['longitude'][:])
        lats = np.asarray(src.variables['latitude'][:])
    finally:
        src.close()
    if lons.ndim == 2:
        lons, lats = lons[0, :], lats[:, 0]

    ds = netCDF4.Dataset(str(out), 'r')
    try:
        centres = ds.variables['centerCoords'][:]
    finally:
        ds.close()

    expected = np.column_stack([np.tile(lons, len(lats)), np.repeat(lats, len(lons))])
    assert np.allclose(centres, expected), (
        "element centres are not the data points — the cell-cornered "
        "regression is back"
    )
