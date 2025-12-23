#!/bin/bash
# ============================================================================
# SECOFS Preprocessing Script
# Southeast Coastal Ocean Forecast System - COMF/nosofs Framework
#
# This script runs SECOFS preprocessing using YAML configuration
# combined with the nosofs (COMF) shell scripts.
#
# Usage:
#   ./run_secofs_prep.sh
#
# Before running:
#   1. Update PDY and cyc for your run date
#   2. Update DCOMROOT path to your input data location
#   3. Ensure conda environment 'nos_ofs_prep' is available
#
# ============================================================================

set -a  # Export all variables

echo "============================================"
echo "SECOFS Preprocessing"
echo "Using Python + YAML configuration (COMF framework)"
echo "============================================"
echo ""

# ============================================================================
# CONDA ENVIRONMENT - UPDATE PATH FOR YOUR SYSTEM
# ============================================================================
# Uncomment and update for your conda installation:
# source ${HOME}/miniconda3/etc/profile.d/conda.sh
# conda activate nos_ofs_prep

# Or ensure wgrib2 and required tools are in PATH

# ============================================================================
# DATE/TIME CONFIGURATION - MODIFY THESE FOR YOUR RUN
# ============================================================================
export PDY=20250504              # Run date (YYYYMMDD)
export cyc=12                    # Cycle hour (00, 06, 12, 18)
export cycle=t${cyc}z
export envir=dev

# Time boundaries (computed from PDY/cyc)
# SECOFS: 6-hour nowcast, 48-hour forecast
export time_nowcastend=${PDY}${cyc}
# Nowcast start = 6 hours before cycle time
export time_hotstart=$(date -d "${PDY} ${cyc}:00 6 hours ago" +%Y%m%d%H)
# Forecast end = 48 hours after cycle time
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
export RUN=secofs
export OFS=secofs
export PREFIXNOS=secofs
export runtype=prep

# ============================================================================
# DIRECTORY CONFIGURATION - MODIFY PATHS AS NEEDED
# ============================================================================
# nosofs framework location
# UPDATE THESE PATHS FOR YOUR SYSTEM
export HOMEnos=${HOMEnos:-/path/to/nosofs.v3.7.0}

# nos_ofs package location (this repo)
export HOMEnosofs=${HOMEnosofs:-$(dirname $(dirname $(realpath $0)))}

# Fix files location (contains secofs grid, ctl, etc.)
export FIXofs=${HOMEnos}/fix/secofs

# Shared fix files (WOA climatology, river clim, harmonic constants)
export FIXnos=${HOMEnos}/fix/shared

# Working directory
export DATA=${HOMEnosofs}/work/secofs
export COMOUT=${DATA}/output
export COMOUTrerun=${DATA}/rerun
export COMOUTroot=${HOMEnosofs}/work   # Root for restart file search
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
# INPUT DATA PATHS - Using STOFS CI Data (covers SECOFS domain)
# ============================================================================
# UPDATE: Path to your CI/test data
export CI_DATA=${CI_DATA:-/path/to/STOFS_CI_DATA}
export COMINgfs=${CI_DATA}/extracted_gfs/lfs/h1/ops/prod/com/gfs/v16.3
export COMINhrrr=${CI_DATA}/extracted_hrrr/lfs/h1/ops/prod/com/hrrr/v4.1
export COMINrtofs=${CI_DATA}/extracted_rtofs/rtofs/v2.4
export COMINnwm=${CI_DATA}/extracted_nwm/nwm/v3.0
export DCOMINusgs=${CI_DATA}/usgs               # USGS observations (if available)
export DCOMINports=${CI_DATA}/ports             # Ports observations (if available)

# ============================================================================
# PYTHON/YAML CONFIGURATION
# ============================================================================
export PYnos_ofs=${HOMEnosofs}/nos_ofs/ush/python
export PYTHONPATH=${PYnos_ofs}:${PYTHONPATH}
export OFS_CONFIG=${HOMEnosofs}/nos_ofs/parm/systems/secofs.yaml

# ============================================================================
# TOOL PATHS
# ============================================================================
# wgrib2 location - update for your system or ensure it's in PATH
export WGRIB2=${WGRIB2:-$(which wgrib2 2>/dev/null || echo "/path/to/wgrib2")}
# Optional: Add library path if needed
# export LD_LIBRARY_PATH=/path/to/conda/lib:$LD_LIBRARY_PATH

# NDATE utility (for date calculations) - uses epoch for reliable arithmetic
ndate() {
    local hours=$1
    local base=$2
    local base_date="${base:0:8}"
    local base_hour="${base:8:2}"
    local epoch=$(date -d "${base_date} ${base_hour}:00:00" +%s 2>/dev/null)
    if [ -n "$epoch" ]; then
        local new_epoch=$((epoch + hours * 3600))
        date -d "@${new_epoch}" +%Y%m%d%H
    else
        date -d "${base_date} ${base_hour}:00 ${hours} hours" +%Y%m%d%H 2>/dev/null
    fi
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
mkdir -p ${DATA}/outputs
mkdir -p ${DATA}/sflux
mkdir -p ${DATA}/data
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

# Export YAML config as environment variables (auto-detects framework=comf)
eval $(python3 -m nos_ofs.cli export-env --config "$OFS_CONFIG" 2>/dev/null)

if [ $? -eq 0 ]; then
    echo "Configuration loaded successfully from YAML"
    echo "  OCEAN_MODEL=$OCEAN_MODEL"
    echo "  MINLON=$MINLON, MAXLON=$MAXLON"
    echo "  MINLAT=$MINLAT, MAXLAT=$MAXLAT"
    echo "  np_global=$np_global, ne_global=$ne_global, nvrt=$nvrt"
    echo "  DBASE_MET_NOW=$DBASE_MET_NOW, DBASE_MET_NOW2=$DBASE_MET_NOW2"
    echo "  DBASE_WL_NOW=$DBASE_WL_NOW, DBASE_TS_NOW=$DBASE_TS_NOW"
    echo "  LEN_NOWCAST=$LEN_NOWCAST hours, LEN_FORECAST=$LEN_FORECAST hours"
    echo ""
else
    echo "WARNING: Failed to load YAML config, falling back to .ctl file"
    if [ -f ${FIXofs}/${PREFIXNOS}.ctl ]; then
        . ${FIXofs}/${PREFIXNOS}.ctl
        echo "Loaded configuration from ${FIXofs}/${PREFIXNOS}.ctl"
    else
        echo "ERROR: No configuration found!"
        exit 1
    fi
fi

# ============================================================================
# COPY STATIC FILES
# ============================================================================
echo "=== Copying Static Files from FIXofs ==="

# Grid files
for file in \
    ${GRIDFILE} \
    ${GRIDFILE_LL} \
    ${VGRID_CTL} \
    ${HC_FILE_OBC} \
    ${Nudging_weight} \
    ${STA_OUT_CTL}
do
    if [ -f "${FIXofs}/${file}" ]; then
        cp -p ${FIXofs}/${file} ${DATA}/
        echo "  Copied: ${file}"
    else
        echo "  WARNING: Not found: ${FIXofs}/${file}"
    fi
done

# Additional SCHISM files (gr3, prop, ic, in)
for file in ${FIXofs}/${PREFIXNOS}.*; do
    if [ -f "$file" ]; then
        cp -p "$file" ${DATA}/ 2>/dev/null
    fi
done

echo ""

# ============================================================================
# PREPROCESSING
# ============================================================================
echo "=== Starting Preprocessing ==="
echo "Start time: $(date)"
echo ""

# Check if input data exists
if [ ! -d "${COMINgfs}" ] || [ ! -d "${COMINrtofs}" ]; then
    echo "WARNING: Input data directories not found!"
    echo "  COMINgfs=${COMINgfs}"
    echo "  COMINrtofs=${COMINrtofs}"
    echo ""
    echo "To run the full preprocessing, you need to:"
    echo "  1. Download/provide input data (GFS, RTOFS, etc.)"
    echo "  2. Update the DCOMROOT path in this script"
    echo "  3. Re-run this script"
    echo ""
    echo "For now, showing environment setup only."
    echo ""
    echo "Preprocessing steps for SECOFS (COMF framework):"
    echo "  1. nos_ofs_launch.sh - Set up OFS configuration"
    echo "  2. nos_ofs_create_forcing_met.sh - Atmospheric forcing (GFS nowcast)"
    echo "  3. nos_ofs_create_forcing_met.sh - Atmospheric forcing (HRRR nowcast)"
    echo "  4. nos_ofs_create_forcing_river.sh - River forcing"
    echo "  5. nos_ofs_create_forcing_obc.sh - Ocean boundary conditions"
    echo "  6. nos_ofs_create_forcing_nudg.sh - T/S nudging (if enabled)"
    echo "  7. nos_ofs_create_forcing_met.sh - Atmospheric forcing (forecast)"
    echo "  8. nos_ofs_prep_schism_ctl.sh - SCHISM control files"
else
    echo "Input data found. Running preprocessing..."

    # Override rm to keep all temp files for debugging
    rm() {
        echo "[KEEP] Would delete: $@"
    }
    export -f rm

    # Set positional parameters for sourced scripts
    set -- $OFS prep

    # Run the main prep script
    ${SCRIPTnos}/exnos_ofs_prep.sh
fi

# ============================================================================
# SUMMARY
# ============================================================================
echo ""
echo "=== Environment Summary ==="
echo "Working directory: ${DATA}"
echo "Fix files: ${FIXofs}"
echo "Scripts: ${USHnos}"
echo "YAML config: ${OFS_CONFIG}"
echo ""
echo "Key YAML-derived variables:"
echo "  OCEAN_MODEL=${OCEAN_MODEL}"
echo "  GRIDFILE=${GRIDFILE}"
echo "  MET sources: ${DBASE_MET_NOW} + ${DBASE_MET_NOW2}"
echo "  OBC source: ${DBASE_WL_NOW}"
echo ""
echo "Static files in work directory:"
ls -1 ${DATA}/*.gr3 ${DATA}/*.in 2>/dev/null | head -10
echo ""
echo "Preprocessing setup completed at $(date)"
