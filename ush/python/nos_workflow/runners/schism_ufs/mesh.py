"""Generate ESMF unstructured mesh from a DATM forcing NetCDF file."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ...bash_compat import preserve_preload

logger = logging.getLogger(__name__)


def _cell_edges(centers):
    """Cell boundaries for ``centers``: midpoints, extrapolated at the ends.

    Handles non-uniform spacing, so a stretched or subset grid works the same
    way as the regular 0.025 deg DATM grid.
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


def _axes_from(lon2d, lat2d):
    """Reduce 2-D coordinate arrays to the 1-D axes of a separable grid.

    The DATM forcing grid is built on a regular lat/lon mesh, so the rows of
    ``lon2d`` and the columns of ``lat2d`` are constant. Verified rather than
    assumed: a curvilinear grid cannot be expressed as element centres this
    way, and silently taking row 0 would misplace every point.
    """
    import numpy as np

    lon_axis = np.asarray(lon2d)[0, :]
    lat_axis = np.asarray(lat2d)[:, 0]
    if not np.allclose(np.asarray(lon2d), lon_axis[None, :]):
        raise ValueError("longitude varies along y — grid is not separable")
    if not np.allclose(np.asarray(lat2d), lat_axis[:, None]):
        raise ValueError("latitude varies along x — grid is not separable")
    return lon_axis, lat_axis


def generate_esmf_mesh(forcing: Path, output: Path) -> int:
    """Build a CMEPS-compatible ESMF unstructured mesh from a DATM forcing file.

    The mesh ELEMENTS are the data points. CDEPS reads every stream field at
    ``ESMF_MESHLOC_ELEMENT`` (``dshr_strdata_mod.F90`` creates all stream
    fields that way; there is no node-based read path), so a forcing file
    with ``nx*ny`` values needs exactly ``nx*ny`` elements centred ON those
    points.

    This previously treated the forcing coordinates as cell CORNERS --
    ``n_elems = (ny-1)*(nx-1)`` with centres half a cell to the north-east.
    CDEPS does not check element count against the file's dimensions, and
    since (nx-1)*(ny-1) < nx*ny, PIO silently read the first
    (nx-1)*(ny-1) values in flat order. The data is row-major with nx per
    row while elements ran nx-1 per row, so the mapping slipped one cell per
    row and sheared with latitude. Mirrors nos-utils esmf_mesh.py (#37).

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

            lon_axis, lat_axis = _axes_from(lon2d, lat2d)
            nx = lon_axis.size
            ny = lat_axis.size
            n_elems = nx * ny

            lon_edges = _cell_edges(lon_axis)
            lat_edges = _cell_edges(lat_axis)
            nxe, nye = nx + 1, ny + 1
            n_nodes = nxe * nye

            out = Dataset(str(output), 'w')
            out.createDimension('nodeCount', n_nodes)
            out.createDimension('elementCount', n_elems)
            out.createDimension('maxNodePElement', 4)
            out.createDimension('coordDim', 2)

            # Corner nodes on the staggered grid, x-fastest.
            nodeCoords = out.createVariable('nodeCoords', 'f8', ('nodeCount', 'coordDim'))
            nodeCoords.units = 'degrees'
            nodeCoords[:] = np.column_stack(
                [np.tile(lon_edges, nye), np.repeat(lat_edges, nxe)]
            )

            # Connectivity into the (ny+1) x (nx+1) node grid, 1-based CCW.
            # Element order is k = j*nx + i so it matches the forcing file's
            # flattened (y, x).
            jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing='ij')
            sw = (jj * nxe + ii + 1).ravel()
            conn = np.empty((n_elems, 4), dtype=np.int32)
            conn[:, 0] = sw               # SW
            conn[:, 1] = sw + 1           # SE
            conn[:, 2] = sw + nxe + 1     # NE
            conn[:, 3] = sw + nxe         # NW

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

            # Element centres ARE the data points -- this is the whole fix.
            centerCoords = out.createVariable('centerCoords', 'f8', ('elementCount', 'coordDim'))
            centerCoords.units = 'degrees'
            centerCoords[:] = np.column_stack(
                [np.tile(lon_axis, ny), np.repeat(lat_axis, nx)]
            )

            out.title = 'ESMF mesh generated from DATM forcing file'
            out.gridType = 'unstructured mesh'
            out.close()
            print('Generated ESMF mesh: {}x{} = {} elements (data points), {} corner nodes'.format(
                nx, ny, n_elems, n_nodes
            ))
        except Exception as exc:  # noqa: BLE001
            logger.error("ESMF mesh generation failed: %s", exc)
            return 2

    return 0


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
