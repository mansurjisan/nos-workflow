#!/bin/bash
# ============================================================================
# CBOFS Preprocessing Script
# Chesapeake Bay Operational Forecast System - COMF/nosofs Framework
# Model: ROMS (Regional Ocean Modeling System)
#
# This script runs CBOFS preprocessing using YAML configuration
# combined with the nosofs (COMF) shell scripts.
#
# Usage:
#   ./run_cbofs_prep.sh
#
# Before running:
#   1. Update PDY and cyc for your run date
#   2. Update DCOMROOT path to your input data location
#   3. Ensure fix files exist in FIXofs directory
#   4. Ensure conda environment 'nos_ofs_prep' is available
#
# ============================================================================

set -a  # Export all variables

echo "============================================"
echo "CBOFS Preprocessing"
echo "Chesapeake Bay OFS (ROMS)"
echo "Using Python + YAML configuration (COMF framework)"
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
export envir=dev

# Time boundaries (computed from PDY/cyc)
# CBOFS: 6-hour nowcast, 48-hour forecast
export time_nowcastend=${PDY}${cyc}
export time_hotstart=$(date -d "${PDY} ${cyc}:00 6 hours ago" +%Y%m%d%H)
export time_forecastend=$(date -d "${PDY} ${cyc}:00 48 hours" +%Y%m%d%H)

echo "Date/Time configuration:"
echo "  PDY=${PDY}, cyc=${cyc}"
echo "  time_hotstart=${time_hotstart} (nowcast start)"
echo "  time_nowcastend=${time_nowcastend} (nowcast end / forecast start)"
echo "  time_forecastend=${time_forecastend} (forecast end)"
echo ""

# ============================================================================
# SYSTEM CONFIGURATION
# ============================================================================
export NET=nos
export RUN=cbofs
export OFS=cbofs
export PREFIXNOS=cbofs

# ============================================================================
# DIRECTORY CONFIGURATION - MODIFY PATHS AS NEEDED
# ============================================================================
# nosofs framework location
export HOMEnos=${HOMEnos:-/path/to/nosofs.v3.7.0}  # UPDATE

# nos_ofs package location
export HOMEnosofs=${HOMEnosofs:-$(dirname $(dirname $(realpath $0)))}

# Fix files location - UPDATE THIS PATH
# You need cbofs fix files (grid, forcing templates, etc.)
export FIXofs=${HOMEnos}/fix/cbofs

# Working directory
export DATA=${HOMEnosofs}/work/cbofs
export COMOUT=${DATA}/output
export COMOUTrerun=${DATA}/rerun
export GESOUT=${DATA}/ges
export jlogfile=${DATA}/jlogfile
export nosjlogfile=${DATA}/nos_jlogfile
export cormslogfile=${DATA}/corms.log

# Executables and scripts
export EXECnos=${HOMEnos}/exec
export USHnos=${HOMEnos}/ush
export PARMnos=${HOMEnos}/parm
export SCRIPTnos=${HOMEnos}/scripts

# ============================================================================
# INPUT DATA PATHS - MODIFY FOR YOUR DATA LOCATION
# ============================================================================
export DCOMROOT=${CI_DATA:-/path/to/CI_DATA}           # Update this path
export COMINnam=${DCOMROOT}/nam                 # NAM atmospheric (primary)
export COMINgfs=${DCOMROOT}/gfs                 # GFS atmospheric (fallback)
export COMINhrrr=${DCOMROOT}/hrrr               # HRRR atmospheric
export COMINrtofs=${DCOMROOT}/rtofs             # RTOFS ocean boundary
export COMINnwm=${DCOMROOT}/nwm                 # NWM river data
export DCOMINusgs=${DCOMROOT}/usgs              # USGS river observations

# ============================================================================
# PYTHON/YAML CONFIGURATION
# ============================================================================
export PYnos_ofs=${HOMEnosofs}/nos_ofs/ush/python
export PYTHONPATH=${PYnos_ofs}:${PYTHONPATH}
export OFS_CONFIG=${HOMEnosofs}/nos_ofs/parm/systems/cbofs.yaml

# ============================================================================
# TOOL PATHS
# ============================================================================
export WGRIB2=${WGRIB2:-$(which wgrib2 2>/dev/null || echo "/path/to/wgrib2")}
# export LD_LIBRARY_PATH=/path/to/conda/lib:$LD_LIBRARY_PATH  # Optional

# NDATE utility
ndate() {
    hours=$1
    base=$2
    date -d "${base:0:8} ${base:8:2}:00 ${hours} hours" +%Y%m%d%H
}
export -f ndate
export NDATE=ndate

set +a

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
cpreq() { cp -p "$@"; }
export -f cpreq

module() { echo "[module] $@"; }
export -f module

postmsg() { echo "[postmsg] $@"; }
export -f postmsg

prep_step() { echo "[prep_step] Preparing next step..."; }
export -f prep_step

err_chk() {
    if [ ${err:-0} -ne 0 ]; then
        echo "ERROR: Previous command failed with exit code $err"
        return $err
    fi
}
export -f err_chk

# ============================================================================
# CREATE DIRECTORIES
# ============================================================================
echo "Creating directories..."
mkdir -p ${DATA}
mkdir -p ${COMOUT}
mkdir -p ${COMOUTrerun}
mkdir -p ${GESOUT}

cd ${DATA}

# ============================================================================
# LOAD YAML CONFIGURATION
# ============================================================================
echo ""
echo "=== Loading YAML Configuration ==="
echo "Config file: $OFS_CONFIG"
echo ""

# Export YAML config as environment variables (framework=comf)
eval $(python3 -m nos_ofs.cli export-env --config "$OFS_CONFIG" 2>/dev/null)

if [ $? -eq 0 ]; then
    echo "Configuration loaded successfully from YAML"
    echo "  OCEAN_MODEL=${OCEAN_MODEL:-ROMS}"
    echo "  MINLON=$MINLON, MAXLON=$MAXLON"
    echo "  MINLAT=$MINLAT, MAXLAT=$MAXLAT"
    echo "  LEN_NOWCAST=${LEN_NOWCAST:-6} hours"
    echo "  LEN_FORECAST=${LEN_FORECAST:-48} hours"
    echo ""
else
    echo "WARNING: Failed to load YAML config, falling back to .ctl file"
    if [ -f ${FIXofs}/${PREFIXNOS}.ctl ]; then
        . ${FIXofs}/${PREFIXNOS}.ctl
        echo "Loaded configuration from ${FIXofs}/${PREFIXNOS}.ctl"
    else
        echo "WARNING: No .ctl file found either"
    fi
fi

# Set ROMS-specific defaults if not set
export OCEAN_MODEL=${OCEAN_MODEL:-ROMS}

# ============================================================================
# CHECK FIX FILES
# ============================================================================
echo "=== Checking Fix Files ==="

if [ ! -d "${FIXofs}" ]; then
    echo "WARNING: Fix directory not found: ${FIXofs}"
    echo ""
    echo "CBOFS requires fix files including:"
    echo "  - cbofs.ctl (control file)"
    echo "  - cbofs_grid.nc (ROMS grid file)"
    echo "  - cbofs_init.nc (initial conditions)"
    echo "  - cbofs_bry.nc (boundary file template)"
    echo "  - cbofs_rivers.nc (river forcing template)"
    echo ""
    echo "Please provide fix files or update FIXofs path."
else
    echo "Fix directory: ${FIXofs}"
    ls -la ${FIXofs}/ 2>/dev/null | head -15
fi

echo ""

# ============================================================================
# PREPROCESSING STEPS
# ============================================================================
echo "=== CBOFS Preprocessing Steps (ROMS) ==="
echo ""
echo "The COMF framework runs these steps via exnos_ofs_prep.sh:"
echo "  1. nos_ofs_launch.sh - Set up OFS configuration"
echo "  2. nos_ofs_create_forcing_met.sh - NAM/GFS atmospheric forcing"
echo "  3. nos_ofs_create_forcing_river.sh - River forcing (Susquehanna, Potomac, James)"
echo "  4. nos_ofs_create_forcing_obc.sh - RTOFS ocean boundary conditions"
echo "  5. nos_ofs_prep_roms_ctl.sh - ROMS control files (ocean.in)"
echo ""

# Check if input data exists
if [ ! -d "${COMINnam}" ] && [ ! -d "${COMINgfs}" ]; then
    echo "WARNING: Input data directories not found!"
    echo "  COMINnam=${COMINnam}"
    echo "  COMINgfs=${COMINgfs}"
    echo ""
    echo "To run the full preprocessing:"
    echo "  1. Provide input data (NAM/GFS, RTOFS, NWM)"
    echo "  2. Provide fix files in ${FIXofs}"
    echo "  3. Update paths in this script"
    echo "  4. Re-run this script"
else
    echo "Input data found."
    # Uncomment to run preprocessing
    # ${SCRIPTnos}/exnos_ofs_prep.sh
fi

# ============================================================================
# SUMMARY
# ============================================================================
echo ""
echo "=== Environment Summary ==="
echo "OFS: ${OFS} (${OCEAN_MODEL})"
echo "Working directory: ${DATA}"
echo "Fix files: ${FIXofs}"
echo "YAML config: ${OFS_CONFIG}"
echo ""
echo "Domain bounds:"
echo "  Longitude: ${MINLON} to ${MAXLON}"
echo "  Latitude: ${MINLAT} to ${MAXLAT}"
echo ""
echo "Forcing sources:"
echo "  Atmospheric: NAM (primary), GFS (fallback)"
echo "  Rivers: NWM + USGS (Susquehanna, Potomac, James)"
echo "  Ocean BC: RTOFS"
echo ""
echo "Setup completed at $(date)"
