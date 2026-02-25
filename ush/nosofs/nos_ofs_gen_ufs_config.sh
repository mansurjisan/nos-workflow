#!/bin/bash
#############################################
# nos_ofs_gen_ufs_config.sh
#
# Generate UFS-Coastal configuration files from templates
# for SECOFS and other SCHISM-based OFS systems
#
# Usage:
#   nos_ofs_gen_ufs_config.sh [OPTIONS]
#
# Required Environment Variables:
#   PDY        - Forecast date (YYYYMMDD)
#   cyc        - Cycle hour (00, 06, 12, 18)
#   DATA       - Working directory
#   FIXofs     - Fix files directory (contains templates)
#
# Optional Environment Variables:
#   NHOURS          - Forecast length (default: 48)
#   DT_ATMOS        - Atmospheric timestep (default: 720)
#   DATM_INPUT_DIR  - DATM forcing subdirectory (default: INPUT)
#   DATM_MESH_FILE  - ESMF mesh filename (default: datm_esmf_mesh.nc)
#   DATM_FORCING_FILE - Forcing filename (default: datm_forcing.nc)
#   NX_GLOBAL       - DATM grid x-dimension (default: 1721)
#   NY_GLOBAL       - DATM grid y-dimension (default: 1721)
#
# Output Files (in $DATA):
#   model_configure
#   datm_in
#   datm.streams
#   ufs.configure (copied from FIXofs)
#   fd_ufs.yaml (copied from FIXofs)
#   noahmptable.tbl (copied from FIXofs)
#
#############################################

set -eu

#############################################
# Parse Arguments
#############################################
VERBOSE=${VERBOSE:-false}

while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [-v|--verbose] [-h|--help]"
            echo ""
            echo "Generate UFS-Coastal config files from templates"
            echo ""
            echo "Required environment variables:"
            echo "  PDY, cyc, DATA, FIXofs"
            echo ""
            echo "Optional environment variables:"
            echo "  NHOURS, DT_ATMOS, DATM_INPUT_DIR, DATM_MESH_FILE,"
            echo "  DATM_FORCING_FILE, NX_GLOBAL, NY_GLOBAL"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

#############################################
# Validate Required Variables
#############################################
log_msg() {
    if [ "$VERBOSE" == "true" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    fi
}

error_exit() {
    echo "ERROR: $1" >&2
    exit 1
}

[ -z "${PDY:-}" ] && error_exit "PDY not set"
[ -z "${cyc:-}" ] && error_exit "cyc not set"
[ -z "${DATA:-}" ] && error_exit "DATA not set"
[ -z "${FIXofs:-}" ] && error_exit "FIXofs not set"

#############################################
# Set Default Values
#############################################
NHOURS=${NHOURS:-48}
DT_ATMOS=${DT_ATMOS:-720}
DATM_INPUT_DIR=${DATM_INPUT_DIR:-INPUT}
DATM_MESH_FILE=${DATM_MESH_FILE:-datm_esmf_mesh.nc}
DATM_FORCING_FILE=${DATM_FORCING_FILE:-datm_forcing.nc}
# DATM grid dimensions: must match the blended forcing NetCDF file
# If not set, compute from domain bounds and blend resolution
if [ -z "${NX_GLOBAL:-}" ] && [ -n "${MINLON:-}" ] && [ -n "${MAXLON:-}" ] && [ -n "${BLEND_RESOLUTION:-}" ]; then
    NX_GLOBAL=$(python3 -c "print(int(round((${MAXLON} - (${MINLON}))/${BLEND_RESOLUTION}) + 1))" 2>/dev/null || echo 1001)
fi
if [ -z "${NY_GLOBAL:-}" ] && [ -n "${MINLAT:-}" ] && [ -n "${MAXLAT:-}" ] && [ -n "${BLEND_RESOLUTION:-}" ]; then
    NY_GLOBAL=$(python3 -c "print(int(round((${MAXLAT} - (${MINLAT}))/${BLEND_RESOLUTION}) + 1))" 2>/dev/null || echo 921)
fi
NX_GLOBAL=${NX_GLOBAL:-1001}
NY_GLOBAL=${NY_GLOBAL:-921}

# Extract date components
YYYY=${PDY:0:4}
MM=${PDY:4:2}
DD=${PDY:6:2}
HH=${cyc}

log_msg "============================================"
log_msg "UFS-Coastal Config Generation"
log_msg "============================================"
log_msg "PDY:              $PDY"
log_msg "cyc:              $cyc"
log_msg "DATA:             $DATA"
log_msg "FIXofs:           $FIXofs"
log_msg "NHOURS:           $NHOURS"
log_msg "DT_ATMOS:         $DT_ATMOS"
log_msg "DATM_INPUT_DIR:   $DATM_INPUT_DIR"
log_msg "DATM_MESH_FILE:   $DATM_MESH_FILE"
log_msg "DATM_FORCING_FILE: $DATM_FORCING_FILE"
log_msg "NX_GLOBAL:        $NX_GLOBAL"
log_msg "NY_GLOBAL:        $NY_GLOBAL"
log_msg "============================================"

#############################################
# Check Template Files Exist
#############################################
TEMPLATE_DIR="${FIXofs}"

for template in model_configure.template datm_in.template datm.streams.template ufs.configure; do
    if [ ! -f "${TEMPLATE_DIR}/${template}" ]; then
        error_exit "Template not found: ${TEMPLATE_DIR}/${template}"
    fi
done

log_msg "All template files found"

#############################################
# Create DATM input directory if needed
#############################################
mkdir -p ${DATA}/${DATM_INPUT_DIR}
mkdir -p ${DATA}/RESTART

#############################################
# Generate model_configure
#############################################
log_msg "Generating model_configure..."

sed -e "s/@\[YYYY\]/${YYYY}/g" \
    -e "s/@\[MM\]/${MM}/g" \
    -e "s/@\[DD\]/${DD}/g" \
    -e "s/@\[HH\]/${HH}/g" \
    -e "s/@\[NHOURS\]/${NHOURS}/g" \
    -e "s/@\[DT_ATMOS\]/${DT_ATMOS}/g" \
    ${TEMPLATE_DIR}/model_configure.template > ${DATA}/model_configure

log_msg "Created: ${DATA}/model_configure"

#############################################
# Generate datm_in
#############################################
log_msg "Generating datm_in..."

sed -e "s|@\[DATM_INPUT_DIR\]|${DATM_INPUT_DIR}|g" \
    -e "s|@\[DATM_MESH_FILE\]|${DATM_MESH_FILE}|g" \
    -e "s/@\[NX_GLOBAL\]/${NX_GLOBAL}/g" \
    -e "s/@\[NY_GLOBAL\]/${NY_GLOBAL}/g" \
    ${TEMPLATE_DIR}/datm_in.template > ${DATA}/datm_in

log_msg "Created: ${DATA}/datm_in"

#############################################
# Generate datm.streams
#############################################
log_msg "Generating datm.streams..."

sed -e "s/@\[YYYY\]/${YYYY}/g" \
    -e "s|@\[DATM_INPUT_DIR\]|${DATM_INPUT_DIR}|g" \
    -e "s|@\[DATM_MESH_FILE\]|${DATM_MESH_FILE}|g" \
    -e "s|@\[DATM_FORCING_FILE\]|${DATM_FORCING_FILE}|g" \
    ${TEMPLATE_DIR}/datm.streams.template > ${DATA}/datm.streams

log_msg "Created: ${DATA}/datm.streams"

#############################################
# Copy ufs.configure (static, patched later per phase)
#############################################
log_msg "Copying ufs.configure..."

cp ${TEMPLATE_DIR}/ufs.configure ${DATA}/ufs.configure

log_msg "Created: ${DATA}/ufs.configure"

#############################################
# Copy fd_ufs.yaml and noahmptable.tbl
#############################################
for f in fd_ufs.yaml noahmptable.tbl; do
    if [ -f "${TEMPLATE_DIR}/${f}" ]; then
        cp ${TEMPLATE_DIR}/${f} ${DATA}/${f}
        log_msg "Copied: ${DATA}/${f}"
    else
        log_msg "WARNING: ${f} not found in ${TEMPLATE_DIR}"
    fi
done

#############################################
# Verify Output Files
#############################################
log_msg "============================================"
log_msg "Verifying output files..."

for config in model_configure datm_in datm.streams ufs.configure; do
    if [ -f "${DATA}/${config}" ]; then
        log_msg "OK: ${config} ($(wc -l < ${DATA}/${config}) lines)"
    else
        error_exit "Failed to create: ${config}"
    fi
done

log_msg "============================================"
log_msg "UFS-Coastal config generation complete!"
log_msg "============================================"

exit 0
