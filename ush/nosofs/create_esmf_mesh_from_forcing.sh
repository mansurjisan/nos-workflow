#!/bin/bash
# =============================================================================
# create_esmf_mesh_from_forcing.sh
#
# Generate ESMF unstructured mesh from a datm_forcing.nc file using
# ESMF_Scrip2Unstruct (not Python). This ensures the mesh node/element
# count matches what CDEPS expects.
#
# Usage:
#   create_esmf_mesh_from_forcing.sh <datm_forcing.nc> <output_mesh.nc>
#
# Requires:
#   - ESMF_Scrip2Unstruct (from esmf module)
#   - Python 3 with netCDF4, numpy
# =============================================================================

set -eu

FORCING_FILE=${1:?Usage: $0 <datm_forcing.nc> <output_mesh.nc>}
OUTPUT_MESH=${2:?Usage: $0 <datm_forcing.nc> <output_mesh.nc>}

WORKDIR=$(mktemp -d ${TMPDIR:-/tmp}/esmf_mesh_XXXXXX)
trap "rm -rf ${WORKDIR}" EXIT

echo "Creating ESMF mesh from: ${FORCING_FILE}"
echo "  Output: ${OUTPUT_MESH}"
echo "  Work dir: ${WORKDIR}"

# Step 1: Create SCRIP file from forcing NetCDF
SCRIP_FILE=${WORKDIR}/forcing_scrip.nc
echo "Step 1: Creating SCRIP file..."

python3 << PYEOF
import numpy as np
from netCDF4 import Dataset

ds = Dataset('${FORCING_FILE}', 'r')

# Read coordinates (handle both 1D and 2D)
for ln in ['longitude', 'lon', 'x']:
    if ln in ds.variables:
        lons = ds.variables[ln][:]
        break
for ln in ['latitude', 'lat', 'y']:
    if ln in ds.variables:
        lats = ds.variables[ln][:]
        break

if lons.ndim == 1:
    lon2d, lat2d = np.meshgrid(lons, lats)
else:
    lon2d, lat2d = lons, lats

ny, nx = lon2d.shape
grid_size = ny * nx
grid_corners = 4
grid_rank = 2
ds.close()

print(f'  Grid: {nx}x{ny} = {grid_size} cells')

# Create SCRIP format file
out = Dataset('${SCRIP_FILE}', 'w')
out.createDimension('grid_size', grid_size)
out.createDimension('grid_corners', grid_corners)
out.createDimension('grid_rank', grid_rank)

dims = out.createVariable('grid_dims', 'i4', ('grid_rank',))
dims[:] = [nx, ny]

center_lat = out.createVariable('grid_center_lat', 'f8', ('grid_size',))
center_lat.units = 'degrees'
center_lat[:] = lat2d.ravel()

center_lon = out.createVariable('grid_center_lon', 'f8', ('grid_size',))
center_lon.units = 'degrees'
center_lon[:] = lon2d.ravel()

imask = out.createVariable('grid_imask', 'i4', ('grid_size',))
imask.units = 'unitless'
imask[:] = np.ones(grid_size, dtype=np.int32)

# Corner coordinates
dlat = np.abs(lat2d[1, 0] - lat2d[0, 0]) / 2.0 if ny > 1 else 0.125
dlon = np.abs(lon2d[0, 1] - lon2d[0, 0]) / 2.0 if nx > 1 else 0.125

corner_lat = out.createVariable('grid_corner_lat', 'f8', ('grid_size', 'grid_corners'))
corner_lat.units = 'degrees'
corner_lon = out.createVariable('grid_corner_lon', 'f8', ('grid_size', 'grid_corners'))
corner_lon.units = 'degrees'

clat = lat2d.ravel()
clon = lon2d.ravel()
corner_lat[:, 0] = clat - dlat
corner_lat[:, 1] = clat - dlat
corner_lat[:, 2] = clat + dlat
corner_lat[:, 3] = clat + dlat
corner_lon[:, 0] = clon - dlon
corner_lon[:, 1] = clon + dlon
corner_lon[:, 2] = clon + dlon
corner_lon[:, 3] = clon - dlon

out.title = 'SCRIP grid file for DATM forcing'
out.close()
print(f'  SCRIP file: ${SCRIP_FILE}')
PYEOF

if [ ! -s "${SCRIP_FILE}" ]; then
    echo "ERROR: Failed to create SCRIP file" >&2
    exit 1
fi

# Step 2: Run ESMF_Scrip2Unstruct
echo "Step 2: Running ESMF_Scrip2Unstruct..."

ESMF_SCRIP2UNSTRUCT=$(which ESMF_Scrip2Unstruct 2>/dev/null || echo "")
if [ -z "${ESMF_SCRIP2UNSTRUCT}" ]; then
    echo "ERROR: ESMF_Scrip2Unstruct not found. Load esmf module first." >&2
    exit 1
fi

${ESMF_SCRIP2UNSTRUCT} ${SCRIP_FILE} ${WORKDIR}/esmf_mesh.nc 0
rc=$?

if [ $rc -ne 0 ] || [ ! -s "${WORKDIR}/esmf_mesh.nc" ]; then
    echo "ERROR: ESMF_Scrip2Unstruct failed (rc=$rc)" >&2
    exit 1
fi

# Step 3: Add elementMask (all ones = active)
echo "Step 3: Adding elementMask..."
python3 << PYEOF
from netCDF4 import Dataset
import numpy as np

ds = Dataset('${WORKDIR}/esmf_mesh.nc', 'a')
if 'elementMask' not in ds.variables:
    n_elems = len(ds.dimensions['elementCount'])
    em = ds.createVariable('elementMask', 'i4', ('elementCount',))
    em.units = 'unitless'
    em[:] = np.ones(n_elems, dtype=np.int32)
    print(f'  Added elementMask: {n_elems} elements (all active)')
else:
    em = ds.variables['elementMask']
    em[:] = np.ones(len(ds.dimensions['elementCount']), dtype=np.int32)
    print(f'  Set elementMask to all ones')
ds.close()
PYEOF

# Copy to output
cp -p ${WORKDIR}/esmf_mesh.nc ${OUTPUT_MESH}

# Report
python3 -c "
from netCDF4 import Dataset
ds = Dataset('${OUTPUT_MESH}', 'r')
print(f'  nodeCount:    {len(ds.dimensions[\"nodeCount\"])}')
print(f'  elementCount: {len(ds.dimensions[\"elementCount\"])}')
ds.close()
"
echo "Done: ${OUTPUT_MESH}"
