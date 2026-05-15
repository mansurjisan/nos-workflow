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
            n_nodes = ny * nx
            n_elems = (ny - 1) * (nx - 1)

            out = Dataset(str(output), 'w')
            out.createDimension('nodeCount', n_nodes)
            out.createDimension('elementCount', n_elems)
            out.createDimension('maxNodePElement', 4)
            out.createDimension('coordDim', 2)

            nodeCoords = out.createVariable('nodeCoords', 'f8', ('nodeCount', 'coordDim'))
            nodeCoords.units = 'degrees'
            coords = np.column_stack([lon2d.ravel(), lat2d.ravel()])
            nodeCoords[:] = coords

            j_idx, i_idx = np.mgrid[0:ny-1, 0:nx-1]
            n0 = (j_idx * nx + i_idx + 1).ravel()
            conn = np.column_stack([n0, n0 + 1, n0 + nx + 1, n0 + nx]).astype(np.int32)

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

            centerCoords = out.createVariable('centerCoords', 'f8', ('elementCount', 'coordDim'))
            centerCoords.units = 'degrees'
            clon = 0.25 * (coords[conn[:,0]-1,0] + coords[conn[:,1]-1,0] + coords[conn[:,2]-1,0] + coords[conn[:,3]-1,0])
            clat = 0.25 * (coords[conn[:,0]-1,1] + coords[conn[:,1]-1,1] + coords[conn[:,2]-1,1] + coords[conn[:,3]-1,1])
            centerCoords[:] = np.column_stack([clon, clat])

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
