#!/bin/bash
# =============================================================================
# Script Name: nos_ofs_blend_hrrr_gfs.sh
#
# Purpose:
#   Blend HRRR and GFS forcing files into a single NetCDF for CDEPS/DATM,
#   then generate SCRIP grid and ESMF mesh for the blended output.
#
#   Input files are on their NATIVE grids (no pre-regridding needed):
#     - HRRR: Lambert Conformal ~3km (from nos_ofs_create_datm_forcing.sh)
#     - GFS: Regular lat/lon 0.25 deg
#   The Python script handles all spatial + temporal interpolation using
#   scipy cKDTree and RegularGridInterpolator.
#
# Usage:
#   ./nos_ofs_blend_hrrr_gfs.sh HRRR_FILE GFS_FILE OUTPUT_FILE DOMAIN [RESOLUTION]
#
# Arguments:
#   HRRR_FILE   - Input HRRR forcing NetCDF (native grid)
#   GFS_FILE    - Input GFS forcing NetCDF (native grid)
#   OUTPUT_FILE - Output blended NetCDF file
#   DOMAIN      - Domain preset: ATLANTIC, SECOFS, STOFS3D_ATL
#   RESOLUTION  - Grid resolution in degrees (default: 0.025)
#
# Environment Variables:
#   USHnos   - Path to USH scripts directory
#   PYnos    - Path to Python modules (default: $USHnos/python/nos_ofs)
#
# Output Files:
#   ${OUTPUT_FILE}                           - Blended forcing (hourly)
#   ${OUTPUT_DIR}/${BASENAME}_scrip.nc       - SCRIP grid file
#   ${OUTPUT_DIR}/${BASENAME}_esmf_mesh.nc   - ESMF unstructured mesh
#
# Author: NOS-OFS Unified Workflow
# Date: February 2026
# =============================================================================

set -eu

# =============================================================================
# Parse Arguments
# =============================================================================
HRRR_FILE=${1:-""}
GFS_FILE=${2:-""}
OUTPUT_FILE=${3:-""}
DOMAIN=${4:-SECOFS}
RESOLUTION=${5:-0.025}

if [ -z "$HRRR_FILE" ] || [ -z "$GFS_FILE" ] || [ -z "$OUTPUT_FILE" ]; then
    echo "Usage: $0 HRRR_FILE GFS_FILE OUTPUT_FILE [DOMAIN] [RESOLUTION]"
    echo ""
    echo "Domain presets: ATLANTIC, SECOFS, STOFS3D_ATL"
    exit 1
fi

# Verify inputs
for f in "$HRRR_FILE" "$GFS_FILE"; do
    if [ ! -s "$f" ]; then
        echo "ERROR: Input file not found or empty: $f"
        exit 1
    fi
done

# =============================================================================
# Setup Environment
# =============================================================================
USHnos=${USHnos:-$(dirname $(dirname $0))}
PYnos=${PYnos:-${USHnos}/python/nos_ofs}

OUTPUT_DIR=$(dirname "$OUTPUT_FILE")
BASENAME=$(basename "$OUTPUT_FILE" .nc)
mkdir -p "$OUTPUT_DIR"

# Save and clear LD_PRELOAD to avoid conflicts with Python scipy/netCDF4
ORIG_LD_PRELOAD="${LD_PRELOAD:-}"
unset LD_PRELOAD 2>/dev/null || true

# Set stack size to unlimited (prevents segfaults in scipy)
ulimit -s unlimited 2>/dev/null || true

echo "============================================"
echo "HRRR+GFS Blending"
echo "============================================"
echo "HRRR:       $HRRR_FILE"
echo "GFS:        $GFS_FILE"
echo "Output:     $OUTPUT_FILE"
echo "Domain:     $DOMAIN"
echo "Resolution: $RESOLUTION deg"
echo "============================================"

# =============================================================================
# Step 1: Blend HRRR + GFS (spatial + temporal interpolation)
# =============================================================================
echo ""
echo "Step 1/3: Blending HRRR + GFS..."
echo "============================================"

BLEND_PY="${PYnos}/datm/blend_hrrr_gfs.py"

if [ ! -s "$BLEND_PY" ]; then
    echo "ERROR: Python blending script not found: $BLEND_PY"
    exit 1
fi

python3 "$BLEND_PY" "$HRRR_FILE" "$GFS_FILE" "$OUTPUT_FILE" "$DOMAIN" "$RESOLUTION"
BLEND_STATUS=$?

if [ $BLEND_STATUS -ne 0 ] || [ ! -s "$OUTPUT_FILE" ]; then
    echo "ERROR: Blending failed (exit code: $BLEND_STATUS)"
    exit 1
fi

echo "Blended: $OUTPUT_FILE ($(ls -lh "$OUTPUT_FILE" | awk '{print $5}'))"

# =============================================================================
# Step 2: Generate SCRIP Grid
# =============================================================================
echo ""
echo "Step 2/3: Generating SCRIP grid..."
echo "============================================"

SCRIP_FILE="${OUTPUT_DIR}/${BASENAME}_scrip.nc"
SCRIP_SCRIPT="${PYnos}/datm/proc_scrip.py"

if [ -s "$SCRIP_SCRIPT" ]; then
    python3 "$SCRIP_SCRIPT" --ifile "$OUTPUT_FILE" --ofile "$(basename $SCRIP_FILE)" --odir "$OUTPUT_DIR"
    SCRIP_STATUS=$?
    if [ $SCRIP_STATUS -ne 0 ] || [ ! -s "$SCRIP_FILE" ]; then
        echo "WARNING: SCRIP generation failed (exit code: $SCRIP_STATUS)"
    else
        echo "SCRIP: $SCRIP_FILE ($(ls -lh "$SCRIP_FILE" | awk '{print $5}'))"
    fi
else
    echo "WARNING: proc_scrip.py not found: $SCRIP_SCRIPT"
fi

# =============================================================================
# Step 3: Generate ESMF Unstructured Mesh
# =============================================================================
echo ""
echo "Step 3/3: Generating ESMF mesh..."
echo "============================================"

MESH_FILE="${OUTPUT_DIR}/${BASENAME}_esmf_mesh.nc"

# Find ESMF_Scrip2Unstruct
ESMF_SCRIP2UNSTRUCT="${ESMF_SCRIP2UNSTRUCT:-}"
if [ -z "$ESMF_SCRIP2UNSTRUCT" ] || [ ! -x "$ESMF_SCRIP2UNSTRUCT" ]; then
    if command -v ESMF_Scrip2Unstruct &> /dev/null; then
        ESMF_SCRIP2UNSTRUCT=$(command -v ESMF_Scrip2Unstruct)
    else
        # Search WCOSS2 hpc-stack
        for esmf_dir in /apps/prod/hpc-stack/*/intel-*/cray-mpich-*/esmf/*/bin; do
            if [ -x "${esmf_dir}/ESMF_Scrip2Unstruct" ]; then
                ESMF_SCRIP2UNSTRUCT="${esmf_dir}/ESMF_Scrip2Unstruct"
                break
            fi
        done
    fi
fi

if [ -n "$ESMF_SCRIP2UNSTRUCT" ] && [ -x "$ESMF_SCRIP2UNSTRUCT" ]; then
    if [ -s "$SCRIP_FILE" ]; then
        echo "Using: $ESMF_SCRIP2UNSTRUCT"

        # Setup LD_LIBRARY_PATH for ESMF's HDF5/NetCDF dependencies.
        # ESMF in hpc-stack is compiled against a specific HDF5 version
        # (e.g., 1.14.0) that may differ from the loaded hdf5 module.
        ESMF_DIR=$(cd "$(dirname "$ESMF_SCRIP2UNSTRUCT")/.." 2>/dev/null && pwd)
        MPI_DIR=$(cd "$ESMF_DIR/../.." 2>/dev/null && pwd)
        COMPILER_DIR=$(cd "$MPI_DIR/.." 2>/dev/null && pwd)
        for _lib_pkg in hdf5 netcdf; do
            for _lib_dir in "$MPI_DIR"/${_lib_pkg}/*/lib "$COMPILER_DIR"/${_lib_pkg}/*/lib; do
                if [ -d "$_lib_dir" ]; then
                    export LD_LIBRARY_PATH="${_lib_dir}:${LD_LIBRARY_PATH:-}"
                    echo "  Added to LD_LIBRARY_PATH: $_lib_dir"
                    break
                fi
            done
        done

        # Use || true to prevent set -e from aborting the script if ESMF fails.
        # The blended forcing file is already created; ESMF mesh is optional here
        # (the orchestrator has a fallback mesh generation path).
        $ESMF_SCRIP2UNSTRUCT "$SCRIP_FILE" "$MESH_FILE" 0 || true
        if [ -s "$MESH_FILE" ]; then
            echo "ESMF mesh: $MESH_FILE ($(ls -lh "$MESH_FILE" | awk '{print $5}'))"
        else
            echo "WARNING: ESMF mesh generation failed (non-fatal)"
        fi
    else
        echo "WARNING: Cannot generate ESMF mesh - SCRIP file missing"
    fi
else
    echo "WARNING: ESMF_Scrip2Unstruct not found"
    echo "Set ESMF_SCRIP2UNSTRUCT env var or install ESMF"
fi

# =============================================================================
# Restore environment
# =============================================================================
[ -n "${ORIG_LD_PRELOAD}" ] && export LD_PRELOAD="${ORIG_LD_PRELOAD}"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================"
echo "Blending COMPLETED"
echo "============================================"
echo "Output files:"
echo "  Forcing:   $OUTPUT_FILE"
[ -s "$SCRIP_FILE" ] && echo "  SCRIP:     $SCRIP_FILE"
[ -s "$MESH_FILE" ] && echo "  ESMF Mesh: $MESH_FILE"
echo "============================================"

exit 0
