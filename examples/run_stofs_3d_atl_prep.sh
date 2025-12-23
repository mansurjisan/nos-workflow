#!/bin/bash
# ============================================================================
# STOFS 3D Atlantic Preprocessing Script
# Storm Surge and Tide Operational Forecast System - IT-STOFS Framework
#
# This script runs STOFS 3D Atlantic preprocessing using YAML configuration.
#
# Usage:
#   ./run_stofs_3d_atl_prep.sh
#
# Before running:
#   1. Update PDY and cyc for your run date
#   2. Update CI_DATA path to your input data location
#   3. Ensure conda environment 'nos_ofs_prep' is available
#
# ============================================================================

set -a  # Export all variables

echo "============================================"
echo "STOFS 3D Atlantic Preprocessing"
echo "Using Python + YAML configuration"
echo "============================================"
echo ""

# ============================================================================
# CONDA ENVIRONMENT
# ============================================================================
# source ${HOME}/miniconda3/etc/profile.d/conda.sh  # UPDATE FOR YOUR SYSTEM
conda activate nos_ofs_prep

# ============================================================================
# DATE/TIME CONFIGURATION - MODIFY THESE FOR YOUR RUN
# ============================================================================
export PDY=20250504              # Run date (YYYYMMDD)
export cyc=12                    # Cycle hour (00, 06, 12, 18)
export cycle=t${cyc}z
export PDYHH=${PDY}${cyc}
export PDYHH_FCAST_BEGIN=${PDYHH}
export PDYHH_FCAST_END=2025050712      # Forecast end (5.5 days later)
export PDYHH_NCAST_BEGIN=2025050312    # Nowcast begin (6 hours before)

echo "Date/Time configuration:"
echo "  PDY=${PDY}, cyc=${cyc}"
echo "  PDYHH_NCAST_BEGIN=${PDYHH_NCAST_BEGIN}"
echo "  PDYHH_FCAST_BEGIN=${PDYHH_FCAST_BEGIN}"
echo "  PDYHH_FCAST_END=${PDYHH_FCAST_END}"
echo ""

# ============================================================================
# SYSTEM CONFIGURATION
# ============================================================================
export NET=stofs
export RUN=stofs_3d_atl

# ============================================================================
# DIRECTORY CONFIGURATION - MODIFY PATHS AS NEEDED
# ============================================================================
# Input data location (CI test data)
export CI_DATA=${CI_DATA:-/path/to/CI_DATA}

# Package home directory
export HOMEstofs=${HOMEstofs:-$(dirname $(dirname $(realpath $0)))}

# Working directory
export DATA=${HOMEstofs}/work/stofs_3d_atl
export COMOUT=${DATA}/output
export COMOUTrerun=${DATA}/rerun
export COMOUT_PREV=${DATA}/rerun

# STOFS-specific directories
export EXECstofs3d=${HOMEstofs}/exec/stofs_3d_atl
export FIXstofs3d=${CI_DATA}/extracted_fix/fix/stofs_3d_atl
export USHstofs3d=${HOMEstofs}/nos_ofs/ush/stofs_3d_atl
export PYstofs3d=${HOMEstofs}/nos_ofs/ush/stofs_3d_atl/pysh

# Python package and YAML config
export PYnos_ofs=${HOMEstofs}/nos_ofs/ush/python
export PYTHONPATH=${PYnos_ofs}:${PYTHONPATH}
export OFS_CONFIG=${HOMEstofs}/nos_ofs/parm/systems/stofs_3d_atl.yaml

# ============================================================================
# INPUT DATA PATHS - MODIFY FOR YOUR DATA LOCATION
# ============================================================================
export COMINgfs=${CI_DATA}/extracted_gfs/gfs/v16.3
export COMINhrrr=${CI_DATA}/extracted_hrrr/lfs/h1/ops/prod/com/hrrr/v4.1
export COMINnwm=${CI_DATA}/extracted_nwm/nwm/v3.0
export COMINrtofs=${CI_DATA}/extracted_rtofs/rtofs/v2.4

# ============================================================================
# WORKING SUBDIRECTORIES
# ============================================================================
export DATA_prep_gfs=${DATA}/gfs
export DATA_prep_hrrr=${DATA}/hrrr
export DATA_prep_nwm=${DATA}/river
export DATA_prep_rtofs=${DATA}/rtofs
export DATA_prep_river_st_lawrence=${DATA}/river_st_lawrence
export DATA_prep_restart=${DATA}/restart

# ============================================================================
# TOOL PATHS
# ============================================================================
export WGRIB2=${WGRIB2:-$(which wgrib2 2>/dev/null || echo "/path/to/wgrib2")}
export jlogfile=${DATA}/jlogfile
export pgmout=OUTPUT.$$

# Library paths
# export LD_LIBRARY_PATH=/path/to/conda/lib:$LD_LIBRARY_PATH  # Optional

set +a

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
cpreq() { cp -p "$@"; }
export -f cpreq

module() { :; }
export -f module

postmsg() { echo "$@"; }
export -f postmsg

# ============================================================================
# CREATE DIRECTORIES
# ============================================================================
echo "Creating directories..."
mkdir -p ${DATA}
mkdir -p ${COMOUT}
mkdir -p ${COMOUTrerun}
mkdir -p ${DATA_prep_gfs}
mkdir -p ${DATA_prep_hrrr}
mkdir -p ${DATA_prep_nwm}
mkdir -p ${DATA_prep_rtofs}
mkdir -p ${DATA_prep_river_st_lawrence}
mkdir -p ${DATA_prep_restart}

cd ${DATA}

# ============================================================================
# LOAD YAML CONFIGURATION
# ============================================================================
echo ""
echo "=== Loading YAML Configuration ==="
echo "Config file: $OFS_CONFIG"
echo ""

# Load YAML config (framework=stofs auto-detected)
eval $(python3 -m nos_ofs.cli export-env --config "$OFS_CONFIG" --framework stofs 2>/dev/null)

if [ $? -eq 0 ]; then
    echo "Configuration loaded successfully from YAML"
    echo "  LONMIN=$LONMIN, LONMAX=$LONMAX"
    echo "  LATMIN=$LATMIN, LATMAX=$LATMAX"
    echo "  nvrt=$nvrt, np_global=$np_global"
    echo "  N_RIVERS=$N_RIVERS"
    echo ""
else
    echo "ERROR: Failed to load YAML config"
    exit 1
fi

# ============================================================================
# RUN PREPROCESSING
# ============================================================================
echo "=== Starting Preprocessing ==="
echo "Start time: $(date)"
echo ""

# Create symlinks to fix files
ln -sf $FIXstofs3d/${RUN}_param.nml_6globaloutput param.nml_template 2>/dev/null
ln -sf $FIXstofs3d/${RUN}_bctides.in_template bctides.in_template 2>/dev/null

# Run the unified preprocessing script
echo "Running unified preprocessing script..."
${HOMEstofs}/nos_ofs/scripts/stofs_3d_atl/exstofs_3d_atl_prep_processing_unified.sh

echo ""
echo "Preprocessing completed at $(date) with exit code $?"

# ============================================================================
# VERIFY OUTPUTS
# ============================================================================
echo ""
echo "=== Output Files ==="
echo "GFS:"
ls -lh ${DATA_prep_gfs}/sflux_*.nc 2>/dev/null || echo "  No GFS files"
echo "HRRR:"
ls -lh ${DATA_prep_hrrr}/sflux_*.nc 2>/dev/null || echo "  No HRRR files"
echo "River:"
ls -lh ${DATA_prep_nwm}/*.th 2>/dev/null || echo "  No river files"
echo "Rerun:"
ls -lh ${COMOUTrerun}/*.nc 2>/dev/null || echo "  No rerun files"
