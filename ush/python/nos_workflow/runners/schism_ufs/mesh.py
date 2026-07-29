"""Generate ESMF unstructured mesh from a DATM forcing NetCDF file."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ...bash_compat import preserve_preload

logger = logging.getLogger(__name__)


def generate_esmf_mesh(forcing: Path, output: Path) -> int:
    """Build a CMEPS-compatible ESMF unstructured mesh from a DATM forcing file.

    Returns 0 on success, non-zero on failure.
    """
    try:
        from netCDF4 import Dataset
        import numpy as np
    except ImportError as exc:
        logger.error("netCDF4/numpy not available: %s", exc)
        return 1

    # Strip LD_PRELOAD before touching netCDF4: Fortran J-jobs set
    # LD_PRELOAD=libnetcdff.so which segfaults the CPython netCDF4 extension.
    with preserve_preload():
        try:
            ds = Dataset(str(forcing), 'r')
            try:
                lons = ds.variables['longitude'][:]
                lats = ds.variables['latitude'][:]
                if lons.ndim == 1:
                    lon2d, lat2d = np.meshgrid(lons, lats)
                else:
                    lon2d, lat2d = lons, lats
            except KeyError:
                lon2d = ds.variables['x'][:]
                lat2d = ds.variables['y'][:]
            ds.close()

            ny, nx = lon2d.shape
            # CDEPS reads every stream field at ESMF_MESHLOC_ELEMENT
            # (dshr_strdata_mod.F90; there is no node-based read path), so a
            # forcing file with nx*ny values needs exactly nx*ny elements,
            # centred ON the data points. This built (nx-1)*(ny-1) elements
            # with centres half a cell away, treating the forcing coordinates
            # as cell CORNERS. CDEPS does not check element count against the
            # file, and (nx-1)*(ny-1) < nx*ny, so PIO silently read the first
            # (nx-1)*(ny-1) values in flat order -- slipping one cell west per
            # row and shearing with latitude. On the 1721x1721 SECOFS grid the
            # forcing arrived a median 1431 km from where it belonged.
            # Matches nos_utils.forcing.esmf_mesh (nos-utils #37).
            lon_ax = _axis(lon2d, axis=1)
            lat_ax = _axis(lat2d, axis=0)
            lon_edges = _cell_edges(lon_ax)
            lat_edges = _cell_edges(lat_ax)
            nxe, nye = nx + 1, ny + 1
            n_nodes = nxe * nye
            n_elems = nx * ny

            out = Dataset(str(output), 'w')
            out.createDimension('nodeCount', n_nodes)
            out.createDimension('elementCount', n_elems)
            out.createDimension('maxNodePElement', 4)
            out.createDimension('coordDim', 2)

            # Corner nodes on the half-cell staggered grid, x-fastest.
            nodeCoords = out.createVariable('nodeCoords', 'f8', ('nodeCount', 'coordDim'))
            nodeCoords.units = 'degrees'
            nodeCoords[:] = np.column_stack(
                [np.tile(lon_edges, nye), np.repeat(lat_edges, nxe)]
            )

            j_idx, i_idx = np.mgrid[0:ny, 0:nx]
            n0 = (j_idx * nxe + i_idx + 1).ravel()
            conn = np.column_stack([n0, n0 + 1, n0 + nxe + 1, n0 + nxe]).astype(np.int32)

            elemConn = out.createVariable('elementConn', 'i4', ('elementCount', 'maxNodePElement'))
            elemConn.long_name = 'Node indices that define the element connectivity'
            elemConn.start_index = 1
            elemConn[:] = conn

            numElemConn = out.createVariable('numElementConn', 'i4', ('elementCount',))
            numElemConn[:] = 4

            # elementMask MUST be all ones: setting it to 0 masks every element
            # out of CMEPS bilinear ATM->OCN regrid, so SCHISM receives zero
            # atmospheric forcing (model runs but is silently wrong).
            elementMask = out.createVariable('elementMask', 'i4', ('elementCount',))
            elementMask[:] = np.ones(n_elems, dtype=np.int32)

            # Element centres ARE the data points, ordered k = j*nx + i to
            # match the forcing file's flattened (y, x). That makes CDEPS's
            # flat read the identity instead of a shear.
            centerCoords = out.createVariable('centerCoords', 'f8', ('elementCount', 'coordDim'))
            centerCoords.units = 'degrees'
            centerCoords[:] = np.column_stack(
                [np.tile(lon_ax, ny), np.repeat(lat_ax, nx)]
            )

            out.title = 'ESMF mesh generated from DATM forcing file'
            out.gridType = 'unstructured mesh'
            out.close()
            print('Generated ESMF mesh: {}x{} = {} nodes, {} elements'.format(
                nx, ny, n_nodes, n_elems
            ))
        except Exception as exc:  # noqa: BLE001
            logger.error("ESMF mesh generation failed: %s", exc)
            return 2

    return 0


def _cell_edges(centers):
    """Cell boundaries: midpoints, extrapolated at the ends.

    Handles non-uniform spacing, so a stretched or subset grid works the
    same way as a regular one.
    """
    import numpy as np

    centers = np.asarray(centers, dtype=float)
    if centers.size < 2:
        raise ValueError("need at least 2 grid points to build cell edges")
    edges = np.empty(centers.size + 1, dtype=float)
    edges[1:-1] = 0.5 * (centers[:-1] + centers[1:])
    edges[0] = centers[0] - 0.5 * (centers[1] - centers[0])
    edges[-1] = centers[-1] + 0.5 * (centers[-1] - centers[-2])
    return edges


def _axis(coord2d, axis):
    """Reduce a 2-D coordinate array to its 1-D axis, refusing curvilinear.

    A separable lat/lon grid has constant rows (or columns); a curvilinear
    one does not, and cannot be described this way. Taking row 0 regardless
    would misplace every point -- fail loudly instead.
    """
    import numpy as np

    arr = np.asarray(coord2d, dtype=float)
    ax = arr[0, :] if axis == 1 else arr[:, 0]
    ref = np.broadcast_to(ax if axis == 1 else ax[:, None], arr.shape)
    if not np.allclose(arr, ref, rtol=0, atol=1e-9):
        raise ValueError(
            "forcing grid is curvilinear; a regular lat/lon ESMF mesh "
            "cannot represent it"
        )
    return ax


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate ESMF unstructured mesh from a DATM forcing NetCDF file.",
    )
    parser.add_argument(
        "--forcing", required=True, type=Path,
        help="Input DATM forcing NetCDF file",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="Output ESMF mesh NetCDF file",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    return generate_esmf_mesh(args.forcing, args.output)


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["generate_esmf_mesh", "main"]
