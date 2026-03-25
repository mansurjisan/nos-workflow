#!/bin/bash
# =============================================================================
# Script Name: nos_ofs_create_datm_forcing_blended.sh
#
# Purpose:
#   Orchestrator for creating blended HRRR+GFS DATM forcing for UFS-Coastal.
#   This script runs the full pipeline:
#     1. Extract GFS forcing (native 0.25 deg lat/lon grid)
#     2. Extract HRRR forcing (native ~3km Lambert Conformal grid)
#     3. Blend HRRR+GFS via Python (scipy spatial + temporal interpolation)
#     4. Generate ESMF mesh for the blended grid
#     5. Generate UFS config files from templates
#     6. Stage all artifacts to $DATA/INPUT for DATM
#
#   Input files are on their NATIVE grids (no pre-regridding needed).
#   The Python blend script (blend_hrrr_gfs.py) handles all interpolation:
#     - HRRR spatial: scipy cKDTree nearest-neighbor to target grid
#     - GFS spatial: scipy RegularGridInterpolator bilinear to target grid
#     - GFS temporal: scipy interp1d from 3-hourly to HRRR's hourly timesteps
#   Output is a regular lat/lon grid at configurable resolution.
#
# Usage:
#   nos_ofs_create_datm_forcing_blended.sh [DOMAIN]
#
# Arguments:
#   DOMAIN - Domain label (default: from $DATM_DOMAIN or "SECOFS")
#
# Required Environment Variables:
#   PDY, cyc         - Date/cycle
#   DATA             - Working directory
#   FIXofs           - Fix files directory (templates)
#   COMINgfs         - GFS input directory
#   COMINhrrr        - HRRR input directory
#   USHnos           - USH scripts directory
#   NDATE, NHOUR     - Date utilities
#   WGRIB2           - wgrib2 executable
#
# Optional Environment Variables:
#   DATM_BLEND_HRRR_GFS - Enable HRRR blending (default: true)
#   BLEND_RESOLUTION     - Target grid resolution in degrees (default: 0.025)
#   NHOURS_FCST          - Forecast hours (default: 48)
#   DT_ATMOS             - Atmospheric timestep (default: 720)
#
# Output:
#   $DATA/INPUT/datm_forcing.nc     - Blended HRRR+GFS forcing NetCDF
#   $DATA/INPUT/datm_esmf_mesh.nc   - ESMF mesh for blended grid
#   $DATA/model_configure           - UFS model config
#   $DATA/datm_in                   - DATM namelist
#   $DATA/datm.streams              - DATM stream definitions
#   $DATA/ufs.configure             - UFS/NEMS coupling config
#
# Author: NOS-OFS Unified Workflow
# Date: February 2026
# =============================================================================

set -x

DOMAIN=${1:-${DATM_DOMAIN:-SECOFS}}

echo "============================================"
echo "DATM Blended Forcing Orchestrator"
echo "============================================"
echo "Domain:    $DOMAIN"
echo "Date:      ${PDY}${cyc}"
echo "DATA:      $DATA"
echo "FIXofs:    $FIXofs"
echo "============================================"

# =============================================================================
# Validate Environment
# =============================================================================
for var in PDY cyc DATA FIXofs COMINgfs USHnos NDATE WGRIB2; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: Required variable $var is not set"
        exit 1
    fi
done

# Defaults
DATM_BLEND_HRRR_GFS=${DATM_BLEND_HRRR_GFS:-true}
DATM_PRIMARY_SOURCE=${DATM_PRIMARY_SOURCE:-GFS25}
DATM_OUTPUT_SUFFIX=${DATM_OUTPUT_SUFFIX:-}
BLEND_RESOLUTION=${BLEND_RESOLUTION:-0.025}
NHOURS_FCST=${NHOURS_FCST:-48}
DT_ATMOS=${DT_ATMOS:-720}
NHOUR=${NHOUR:-nhour}

# =============================================================================
# Compute Target Grid from Domain Bounds
# =============================================================================
# Domain presets (lon_min, lon_max, lat_min, lat_max)
case $DOMAIN in
    SECOFS)
        DOM_LON_MIN=${MINLON:--88.0}
        DOM_LON_MAX=${MAXLON:--63.0}
        DOM_LAT_MIN=${MINLAT:-17.0}
        DOM_LAT_MAX=${MAXLAT:-40.0}
        ;;
    STOFS3D_ATL|ATLANTIC)
        DOM_LON_MIN=-99.0
        DOM_LON_MAX=-52.0
        DOM_LAT_MIN=7.0
        DOM_LAT_MAX=53.0
        ;;
    *)
        # Use env vars or defaults
        DOM_LON_MIN=${MINLON:--88.0}
        DOM_LON_MAX=${MAXLON:--63.0}
        DOM_LAT_MIN=${MINLAT:-17.0}
        DOM_LAT_MAX=${MAXLAT:-40.0}
        ;;
esac

# Compute grid dimensions: nx = (lon_max - lon_min) / resolution + 1
# Use Python for float math (bc may not be available on all systems)
read NX_TARGET NY_TARGET <<< $(python3 -c "
import math
dx = $BLEND_RESOLUTION
nx = int(math.ceil(($DOM_LON_MAX - ($DOM_LON_MIN)) / dx)) + 1
ny = int(math.ceil(($DOM_LAT_MAX - ($DOM_LAT_MIN)) / dx)) + 1
print(nx, ny)
")

# Note: We do NOT export TARGET_GRID here. The extraction scripts produce
# native-grid files (HRRR Lambert Conformal, GFS 0.25 deg lat/lon).
# The Python blend script (blend_hrrr_gfs.py) handles all spatial + temporal
# interpolation internally using scipy cKDTree and RegularGridInterpolator.

echo ""
echo "Target grid (after blending):"
echo "  Domain:     ${DOM_LON_MIN} to ${DOM_LON_MAX} lon, ${DOM_LAT_MIN} to ${DOM_LAT_MAX} lat"
echo "  Resolution: ${BLEND_RESOLUTION} deg (~$(python3 -c "print(f'{$BLEND_RESOLUTION * 111:.1f}')")km)"
echo "  Dimensions: ${NX_TARGET} x ${NY_TARGET}"
echo ""

# Compute time range for forcing
# Start: nowcast start time (6h before cycle)
TIME_START=${time_hotstart:-$($NDATE -6 ${PDY}${cyc})}
# Add 3h buffer before start
TIME_START_BUFFERED=$($NDATE -3 $TIME_START)
# End: cycle + forecast hours + 3h buffer
# The buffer ensures DATM/CDEPS can interpolate at the exact forecast end time.
# Without it, taxMode=limit causes shr_stream_findBounds to error with
# "rDateIn gt rDategvd" when the model clock reaches the last forcing record.
TIME_END=$($NDATE $((NHOURS_FCST + 3)) ${PDY}${cyc})

echo "Forcing time range: $TIME_START_BUFFERED to $TIME_END"
echo "Primary source: $DATM_PRIMARY_SOURCE"
echo "HRRR blending: $DATM_BLEND_HRRR_GFS"
if [ -n "$DATM_OUTPUT_SUFFIX" ]; then
    echo "Output suffix: $DATM_OUTPUT_SUFFIX"
fi

# Create work directories
DATM_WORK=${DATA}/datm_forcing
mkdir -p $DATM_WORK
mkdir -p ${DATA}/INPUT

# =============================================================================
# Step 1: Extract GFS Forcing (native grid)
# =============================================================================
echo ""
echo "============================================"
echo "Step 1/6: Extracting primary forcing (${DATM_PRIMARY_SOURCE})..."
echo "============================================"

PRIMARY_DIR=${DATM_WORK}/primary
mkdir -p $PRIMARY_DIR

${USHnos}/nosofs/nos_ofs_create_datm_forcing.sh ${DATM_PRIMARY_SOURCE} $PRIMARY_DIR \
    $TIME_START_BUFFERED $TIME_END
rc=$?

# Determine the output filename based on source type
PRIMARY_FORCING_FILE=""
for candidate in ${PRIMARY_DIR}/gfs_forcing.nc ${PRIMARY_DIR}/gefs_*_forcing.nc; do
    if [ -s "$candidate" ]; then
        PRIMARY_FORCING_FILE="$candidate"
        break
    fi
done

if [ $rc -ne 0 ] || [ -z "$PRIMARY_FORCING_FILE" ]; then
    echo "ERROR: Primary forcing extraction failed (rc=$rc, source=${DATM_PRIMARY_SOURCE})"
    exit 1
fi

echo "Primary forcing: ${PRIMARY_FORCING_FILE} ($(ls -lh ${PRIMARY_FORCING_FILE} | awk '{print $5}'))"

# =============================================================================
# Step 2: Extract HRRR Forcing (native grid)
# =============================================================================
if [ "$DATM_BLEND_HRRR_GFS" == "true" ] || [ "$DATM_BLEND_HRRR_GFS" == "1" ]; then
    echo ""
    echo "============================================"
    echo "Step 2/6: Extracting HRRR forcing (native ~3km Lambert Conformal)..."
    echo "============================================"

    if [ -z "${COMINhrrr:-}" ]; then
        echo "WARNING: COMINhrrr not set, skipping HRRR — will use GFS only"
        DATM_BLEND_HRRR_GFS=false
    else
        HRRR_DIR=${DATM_WORK}/hrrr
        mkdir -p $HRRR_DIR

        ${USHnos}/nosofs/nos_ofs_create_datm_forcing.sh HRRR $HRRR_DIR \
            $TIME_START_BUFFERED $TIME_END
        rc=$?

        if [ $rc -ne 0 ] || [ ! -s ${HRRR_DIR}/hrrr_forcing.nc ]; then
            echo "WARNING: HRRR forcing extraction failed — continuing with GFS only"
            DATM_BLEND_HRRR_GFS=false
        else
            echo "HRRR forcing: ${HRRR_DIR}/hrrr_forcing.nc ($(ls -lh ${HRRR_DIR}/hrrr_forcing.nc | awk '{print $5}'))"
        fi
    fi
else
    echo ""
    echo "Step 2/6: HRRR blending disabled, skipping..."
fi

# =============================================================================
# Step 3: Blend HRRR + GFS
# =============================================================================
BLEND_DIR=${DATM_WORK}/blended
mkdir -p $BLEND_DIR

if [ "$DATM_BLEND_HRRR_GFS" == "true" ] || [ "$DATM_BLEND_HRRR_GFS" == "1" ]; then
    echo ""
    echo "============================================"
    echo "Step 3/6: Blending HRRR + GFS..."
    echo "============================================"

    # The blend script:
    #   1. Reads native HRRR (Lambert Conformal) and GFS (0.25 deg lat/lon)
    #   2. Creates a regular lat/lon target grid at BLEND_RESOLUTION
    #   3. Interpolates HRRR via cKDTree, GFS via RegularGridInterpolator
    #   4. Temporally interpolates GFS from 3-hourly to HRRR's hourly timesteps
    #   5. Combines: HRRR where CONUS coverage, GFS elsewhere
    #   6. Generates SCRIP grid and ESMF mesh for the blended output
    ${USHnos}/nosofs/nos_ofs_blend_hrrr_gfs.sh \
        ${HRRR_DIR}/hrrr_forcing.nc \
        ${PRIMARY_FORCING_FILE} \
        ${BLEND_DIR}/datm_forcing.nc \
        ${DOMAIN} \
        ${BLEND_RESOLUTION}
    rc=$?

    if [ $rc -ne 0 ] || [ ! -s ${BLEND_DIR}/datm_forcing.nc ]; then
        echo "WARNING: Blending failed — falling back to GFS only"
        DATM_BLEND_HRRR_GFS=false
    fi
fi

# Fallback: use primary source only (no blending)
if [ "$DATM_BLEND_HRRR_GFS" != "true" ] && [ "$DATM_BLEND_HRRR_GFS" != "1" ]; then
    echo ""
    echo "============================================"
    echo "Step 3/6: Using ${DATM_PRIMARY_SOURCE} only (no blending)..."
    echo "============================================"
    cp -p ${PRIMARY_FORCING_FILE} ${BLEND_DIR}/datm_forcing.nc
    echo "Copied ${DATM_PRIMARY_SOURCE} as datm_forcing.nc"
fi

# =============================================================================
# Step 4: Generate ESMF Mesh (if not already created by blend step)
# =============================================================================
echo ""
echo "============================================"
echo "Step 4/6: Checking ESMF mesh..."
echo "============================================"

DATM_MESH_FILE=datm_esmf_mesh.nc

if [ -s "${DATM_ESMF_MESH:-}" ]; then
    # Pre-generated mesh passed via env var (e.g., ensemble atmos prep)
    cp -p ${DATM_ESMF_MESH} ${BLEND_DIR}/${DATM_MESH_FILE}
    echo "Using pre-generated ESMF mesh: ${DATM_ESMF_MESH}"
elif [ -s "${BLEND_DIR}/datm_forcing_esmf_mesh.nc" ]; then
    # Blend script created the mesh
    cp -p ${BLEND_DIR}/datm_forcing_esmf_mesh.nc ${BLEND_DIR}/${DATM_MESH_FILE}
    echo "Using blended ESMF mesh"
elif [ -s "${FIXofs}/blended_esmf_mesh.nc" ]; then
    # Cached mesh in fix directory
    cp -p ${FIXofs}/blended_esmf_mesh.nc ${BLEND_DIR}/${DATM_MESH_FILE}
    echo "Using cached ESMF mesh from FIXofs"
else
    # Generate mesh from the forcing file
    echo "Generating ESMF mesh from forcing file..."
    ${USHnos}/nosofs/nos_ofs_create_esmf_mesh.sh GFS25 \
        "$(ls ${COMINgfs}/gfs.${PDY}/${cyc}/atmos/gfs.t${cyc}z.pgrb2.0p25.f000 2>/dev/null || \
           ls ${COMINgfs}/gfs.*/*/atmos/gfs.t*z.pgrb2.0p25.f000 2>/dev/null | tail -1)" \
        ${BLEND_DIR}
    rc=$?
    if [ $rc -eq 0 ] && [ -s ${BLEND_DIR}/gfs_esmf_mesh.nc ]; then
        cp -p ${BLEND_DIR}/gfs_esmf_mesh.nc ${BLEND_DIR}/${DATM_MESH_FILE}
        echo "Generated ESMF mesh from GFS sample"
    else
        echo "ERROR: Failed to generate ESMF mesh"
        exit 1
    fi
fi

echo "ESMF mesh: ${BLEND_DIR}/${DATM_MESH_FILE}"

# =============================================================================
# Step 5: Stage Artifacts to DATM INPUT directory
# =============================================================================
echo ""
echo "============================================"
echo "Step 5/6: Staging artifacts to INPUT/..."
echo "============================================"

DATM_DIR=${DATM_INPUT_DIR:-INPUT}
DATM_FORCING_FILE=${DATM_FORCING_FILE:-datm_forcing.nc}
mkdir -p ${DATA}/${DATM_DIR}

# Stage blended forcing
cp -p ${BLEND_DIR}/datm_forcing.nc ${DATA}/${DATM_DIR}/${DATM_FORCING_FILE}
echo "Staged: ${DATM_DIR}/${DATM_FORCING_FILE} ($(ls -lh ${DATA}/${DATM_DIR}/${DATM_FORCING_FILE} | awk '{print $5}'))"

# Stage ESMF mesh
cp -p ${BLEND_DIR}/${DATM_MESH_FILE} ${DATA}/${DATM_DIR}/${DATM_MESH_FILE}
echo "Staged: ${DATM_DIR}/${DATM_MESH_FILE}"

# Export for config generation
export DATM_INPUT_DIR=${DATM_DIR}
export DATM_MESH_FILE=${DATM_MESH_FILE}
export DATM_FORCING_FILE=${DATM_FORCING_FILE}

# Read actual grid dimensions from the forcing file (Python blend may use
# padded domain bounds that differ from the shell-computed NX/NY_TARGET)
FORCING_PATH=${DATA}/${DATM_DIR}/${DATM_FORCING_FILE}
ACTUAL_DIMS=$(python3 -c "
from netCDF4 import Dataset
ds = Dataset('${FORCING_PATH}', 'r')
print(len(ds.dimensions['x']), len(ds.dimensions['y']))
ds.close()
" 2>/dev/null) && {
    read NX_ACTUAL NY_ACTUAL <<< "$ACTUAL_DIMS"
    if [ "${NX_ACTUAL}" != "${NX_TARGET}" ] || [ "${NY_ACTUAL}" != "${NY_TARGET}" ]; then
        echo "NOTE: Forcing file dims (${NX_ACTUAL}x${NY_ACTUAL}) differ from shell-computed (${NX_TARGET}x${NY_TARGET})"
        echo "      Using actual file dimensions for datm_in"
    fi
    export NX_GLOBAL=${NX_ACTUAL}
    export NY_GLOBAL=${NY_ACTUAL}
} || {
    echo "WARNING: Could not read forcing file dims, using computed values"
    export NX_GLOBAL=${NX_TARGET}
    export NY_GLOBAL=${NY_TARGET}
}

# =============================================================================
# Step 6: Generate UFS Config Files
# Skip when DATM_SKIP_UFS_CONFIG=true (e.g., ensemble atmos prep — config
# files are generated once by the control prep job, not per member)
# =============================================================================
if [ "${DATM_SKIP_UFS_CONFIG:-false}" != "true" ]; then
    echo ""
    echo "============================================"
    echo "Step 6/6: Generating UFS config files..."
    echo "============================================"

    export NHOURS=${NHOURS_FCST}
    ${USHnos}/nosofs/nos_ofs_gen_ufs_config.sh --verbose
    rc=$?

    if [ $rc -ne 0 ]; then
        echo "ERROR: UFS config generation failed"
        exit 1
    fi
else
    echo ""
    echo "Step 6/6: Skipping UFS config generation (DATM_SKIP_UFS_CONFIG=true)"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================"
echo "DATM Blended Forcing COMPLETED SUCCESSFULLY"
echo "============================================"
echo ""
echo "Domain:        $DOMAIN"
echo "Time range:    $TIME_START_BUFFERED to $TIME_END"
echo "Target grid:   ${NX_TARGET} x ${NY_TARGET} at ${BLEND_RESOLUTION} deg"
echo "Primary src:   ${DATM_PRIMARY_SOURCE}"
if [ "$DATM_BLEND_HRRR_GFS" == "true" ] || [ "$DATM_BLEND_HRRR_GFS" == "1" ]; then
    echo "Blending:      HRRR+${DATM_PRIMARY_SOURCE} (HRRR over CONUS, primary global fill)"
else
    echo "Blending:      ${DATM_PRIMARY_SOURCE} only (no HRRR blend)"
fi
echo ""
echo "DATM dir:      ${DATA}/${DATM_DIR}/"
echo "Forcing file:  ${DATM_FORCING_FILE}"
echo "Mesh file:     ${DATM_MESH_FILE}"
echo "Grid dims:     nx=${NX_GLOBAL}, ny=${NY_GLOBAL}"
echo ""
echo "UFS configs:"
for f in model_configure datm_in datm.streams ufs.configure fd_ufs.yaml noahmptable.tbl; do
    if [ -s "${DATA}/${f}" ]; then
        echo "  OK: ${f}"
    else
        echo "  MISSING: ${f}"
    fi
done
echo ""
echo "DATM input directory:"
ls -lh ${DATA}/${DATM_DIR}/*.nc 2>/dev/null
echo ""
echo "============================================"

exit 0
