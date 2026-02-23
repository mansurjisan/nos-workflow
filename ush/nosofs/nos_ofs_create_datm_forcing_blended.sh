#!/bin/bash
# =============================================================================
# Script Name: nos_ofs_create_datm_forcing_blended.sh
#
# Purpose:
#   Orchestrator for creating blended HRRR+GFS DATM forcing for UFS-Coastal.
#   This script runs the full pipeline:
#     1. Extract GFS forcing (0.25 deg global)
#     2. Extract HRRR forcing (3km CONUS)
#     3. Generate ESMF meshes for both grids
#     4. Generate UFS config files from templates
#     5. Stage all artifacts to $DATA/INPUT for DATM
#
#   The "blending" is done by DATM itself at runtime through dual streams:
#     - Stream 01 (GFS): Primary, global coverage
#     - Stream 02 (HRRR): Secondary, overrides GFS over CONUS
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
#   NX_GFS, NY_GFS      - GFS grid dimensions (default: 101, 93)
#   NHOURS_FCST          - Forecast hours (default: 48)
#   DT_ATMOS             - Atmospheric timestep (default: 120)
#
# Output:
#   $DATA/INPUT/gfs_forcing.nc     - GFS forcing NetCDF
#   $DATA/INPUT/hrrr_forcing.nc    - HRRR forcing NetCDF (if blending)
#   $DATA/INPUT/gfs_esmf_mesh.nc   - GFS ESMF mesh
#   $DATA/INPUT/hrrr_esmf_mesh.nc  - HRRR ESMF mesh (if blending)
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
NHOURS_FCST=${NHOURS_FCST:-48}
DT_ATMOS=${DT_ATMOS:-120}
NX_GFS=${NX_GFS:-101}
NY_GFS=${NY_GFS:-93}
NHOUR=${NHOUR:-nhour}

# Compute time range for forcing
# Start: nowcast start time (6h before cycle)
TIME_START=${time_hotstart:-$($NDATE -6 ${PDY}${cyc})}
# Add 3h buffer before start
TIME_START_BUFFERED=$($NDATE -3 $TIME_START)
# End: cycle + forecast hours
TIME_END=$($NDATE ${NHOURS_FCST} ${PDY}${cyc})

echo "Forcing time range: $TIME_START_BUFFERED to $TIME_END"
echo "HRRR blending: $DATM_BLEND_HRRR_GFS"

# Create work directories
DATM_WORK=${DATA}/datm_forcing
mkdir -p $DATM_WORK
mkdir -p ${DATA}/INPUT

# =============================================================================
# Step 1: Extract GFS Forcing
# =============================================================================
echo ""
echo "============================================"
echo "Step 1/5: Extracting GFS forcing..."
echo "============================================"

GFS_DIR=${DATM_WORK}/gfs
mkdir -p $GFS_DIR

${USHnos}/nosofs/nos_ofs_create_datm_forcing.sh GFS25 $GFS_DIR \
    $TIME_START_BUFFERED $TIME_END
rc=$?

if [ $rc -ne 0 ] || [ ! -s ${GFS_DIR}/gfs_forcing.nc ]; then
    echo "ERROR: GFS forcing extraction failed (rc=$rc)"
    exit 1
fi

echo "GFS forcing: ${GFS_DIR}/gfs_forcing.nc"

# =============================================================================
# Step 2: Extract HRRR Forcing (if blending enabled)
# =============================================================================
if [ "$DATM_BLEND_HRRR_GFS" == "true" ] || [ "$DATM_BLEND_HRRR_GFS" == "1" ]; then
    echo ""
    echo "============================================"
    echo "Step 2/5: Extracting HRRR forcing..."
    echo "============================================"

    if [ -z "${COMINhrrr:-}" ]; then
        echo "WARNING: COMINhrrr not set, skipping HRRR extraction"
        DATM_BLEND_HRRR_GFS=false
    else
        HRRR_DIR=${DATM_WORK}/hrrr
        mkdir -p $HRRR_DIR

        ${USHnos}/nosofs/nos_ofs_create_datm_forcing.sh HRRR $HRRR_DIR \
            $TIME_START_BUFFERED $TIME_END
        rc=$?

        if [ $rc -ne 0 ] || [ ! -s ${HRRR_DIR}/hrrr_forcing.nc ]; then
            echo "WARNING: HRRR forcing extraction failed - continuing with GFS only"
            DATM_BLEND_HRRR_GFS=false
        else
            echo "HRRR forcing: ${HRRR_DIR}/hrrr_forcing.nc"
        fi
    fi
else
    echo ""
    echo "Step 2/5: HRRR blending disabled, skipping..."
fi

# =============================================================================
# Step 3: Generate ESMF Meshes
# =============================================================================
echo ""
echo "============================================"
echo "Step 3/5: Generating ESMF meshes..."
echo "============================================"

MESH_DIR=${DATM_WORK}/meshes
mkdir -p $MESH_DIR

# Check if cached meshes exist in FIXofs
GFS_MESH_CACHED=${FIXofs}/gfs_esmf_mesh.nc
HRRR_MESH_CACHED=${FIXofs}/hrrr_esmf_mesh.nc

# GFS mesh
if [ -s "$GFS_MESH_CACHED" ]; then
    echo "Using cached GFS ESMF mesh: $GFS_MESH_CACHED"
    cp $GFS_MESH_CACHED ${MESH_DIR}/gfs_esmf_mesh.nc
else
    echo "Generating GFS ESMF mesh..."
    # Find a representative GFS GRIB2 file for mesh generation
    GFS_SAMPLE=$(ls ${COMINgfs}/gfs.${PDY}/${cyc}/atmos/gfs.t${cyc}z.pgrb2.0p25.f000 2>/dev/null || true)
    if [ -z "$GFS_SAMPLE" ] || [ ! -s "$GFS_SAMPLE" ]; then
        # Try to find any recent GFS file
        GFS_SAMPLE=$(ls ${COMINgfs}/gfs.*/*/atmos/gfs.t*z.pgrb2.0p25.f000 2>/dev/null | tail -1 || true)
    fi

    if [ -n "$GFS_SAMPLE" ] && [ -s "$GFS_SAMPLE" ]; then
        ${USHnos}/nosofs/nos_ofs_create_esmf_mesh.sh GFS25 $GFS_SAMPLE $MESH_DIR
        rc=$?
        if [ $rc -ne 0 ] || [ ! -s ${MESH_DIR}/gfs_esmf_mesh.nc ]; then
            echo "ERROR: GFS ESMF mesh generation failed"
            exit 1
        fi
    else
        echo "ERROR: No GFS GRIB2 file found for mesh generation"
        exit 1
    fi
fi

# HRRR mesh
if [ "$DATM_BLEND_HRRR_GFS" == "true" ] || [ "$DATM_BLEND_HRRR_GFS" == "1" ]; then
    if [ -s "$HRRR_MESH_CACHED" ]; then
        echo "Using cached HRRR ESMF mesh: $HRRR_MESH_CACHED"
        cp $HRRR_MESH_CACHED ${MESH_DIR}/hrrr_esmf_mesh.nc
    else
        echo "Generating HRRR ESMF mesh..."
        HRRR_SAMPLE=$(ls ${COMINhrrr}/hrrr.${PDY}/conus/hrrr.t${cyc}z.wrfsfcf01.grib2 2>/dev/null || true)
        if [ -z "$HRRR_SAMPLE" ] || [ ! -s "$HRRR_SAMPLE" ]; then
            HRRR_SAMPLE=$(ls ${COMINhrrr}/hrrr.*/conus/hrrr.t*z.wrfsfcf01.grib2 2>/dev/null | tail -1 || true)
        fi

        if [ -n "$HRRR_SAMPLE" ] && [ -s "$HRRR_SAMPLE" ]; then
            ${USHnos}/nosofs/nos_ofs_create_esmf_mesh.sh HRRR $HRRR_SAMPLE $MESH_DIR
            rc=$?
            if [ $rc -ne 0 ] || [ ! -s ${MESH_DIR}/hrrr_esmf_mesh.nc ]; then
                echo "WARNING: HRRR ESMF mesh generation failed - continuing with GFS only"
                DATM_BLEND_HRRR_GFS=false
            fi
        else
            echo "WARNING: No HRRR GRIB2 file found for mesh generation - continuing with GFS only"
            DATM_BLEND_HRRR_GFS=false
        fi
    fi
fi

# =============================================================================
# Step 4: Generate UFS Config Files
# =============================================================================
echo ""
echo "============================================"
echo "Step 4/5: Generating UFS config files..."
echo "============================================"

# Set up variables for config generation
export NHOURS=${NHOURS_FCST}
export USE_HRRR=${DATM_BLEND_HRRR_GFS}

${USHnos}/nosofs/nos_ofs_gen_ufs_config.sh --verbose
rc=$?

if [ $rc -ne 0 ]; then
    echo "ERROR: UFS config generation failed"
    exit 1
fi

# =============================================================================
# Step 5: Stage Artifacts to DATM input directory
# =============================================================================
echo ""
echo "============================================"
echo "Step 5/5: Staging artifacts..."
echo "============================================"

DATM_DIR=${DATM_INPUT_DIR:-INPUT}
DATM_FORCING_FILE=${DATM_FORCING_FILE:-datm_forcing.nc}
DATM_MESH_FILE=${DATM_MESH_FILE:-datm_esmf_mesh.nc}
mkdir -p ${DATA}/${DATM_DIR}

# Stage forcing file (use GFS as primary forcing)
cp -p ${GFS_DIR}/gfs_forcing.nc ${DATA}/${DATM_DIR}/${DATM_FORCING_FILE}
echo "Staged: ${DATM_DIR}/${DATM_FORCING_FILE}"

# Stage ESMF mesh
cp -p ${MESH_DIR}/gfs_esmf_mesh.nc ${DATA}/${DATM_DIR}/${DATM_MESH_FILE}
echo "Staged: ${DATM_DIR}/${DATM_MESH_FILE}"

# If HRRR is also generated, stage alongside (for future dual-stream use)
if [ "$DATM_BLEND_HRRR_GFS" == "true" ] || [ "$DATM_BLEND_HRRR_GFS" == "1" ]; then
    if [ -f "${HRRR_DIR}/hrrr_forcing.nc" ]; then
        cp -p ${HRRR_DIR}/hrrr_forcing.nc ${DATA}/${DATM_DIR}/hrrr_forcing.nc
        echo "Staged: ${DATM_DIR}/hrrr_forcing.nc"
    fi
    if [ -f "${MESH_DIR}/hrrr_esmf_mesh.nc" ]; then
        cp -p ${MESH_DIR}/hrrr_esmf_mesh.nc ${DATA}/${DATM_DIR}/hrrr_esmf_mesh.nc
        echo "Staged: ${DATM_DIR}/hrrr_esmf_mesh.nc"
    fi
fi

# Export DATM file variables for config generation
export DATM_INPUT_DIR=${DATM_DIR}
export DATM_MESH_FILE=${DATM_MESH_FILE}
export DATM_FORCING_FILE=${DATM_FORCING_FILE}

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
echo "DATM dir:      ${DATA}/${DATM_DIR}/"
echo "Forcing file:  ${DATM_FORCING_FILE}"
echo "Mesh file:     ${DATM_MESH_FILE}"
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
