#!/bin/bash
# ============================================================================
# run_secofs_ufs.sh - Docker test runner for SECOFS UFS deterministic
#
# Replaces the PBS launcher for container-based testing.
# Runs the full workflow: prep -> nowcast -> forecast -> post
#
# Usage:
#   run_secofs_ufs.sh [all|prep|nowcast|forecast|post] [OPTIONS]
#
# Options:
#   --pdy YYYYMMDD    Set forecast date (default: from $PDY or today)
#   --cyc HH          Set cycle hour (default: from $CYC or 00)
#   --ofs NAME         OFS name (default: secofs_ufs)
#   --dry-run         Print commands without executing
#
# Environment:
#   DATA_COM    - Input data root (default: /data/com)
#   WORK_DIR    - Working directory (default: /work)
# ============================================================================
set -eu

# ---- Parse arguments ----
STAGE="${1:-all}"
shift || true

DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --pdy)    export PDY="$2"; shift 2 ;;
        --cyc)    export CYC="$2"; shift 2 ;;
        --ofs)    export OFS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ---- Core environment ----
export OFS=${OFS:-secofs_ufs}
export PDY=${PDY:-$(date +%Y%m%d)}
export CYC=${CYC:-00}
export cyc=$(printf '%02d' "${CYC}")
export cycle=t${cyc}z
export envir=dev

# Package paths
export nosofs_ver=v3.7.0
export nos_ofs_ver=${nosofs_ver}
export HOMEnos=${HOMEnos:-/opt/nosofs}
export HOMEstofs=${HOMEnos}
export PACKAGEROOT=$(dirname "${HOMEnos}")

# Directory paths
export EXECnos=${HOMEnos}/exec
export FIXnos=${HOMEnos}/fix/shared
export FIXofs=${HOMEnos}/fix/${OFS}
export PARMnos=${HOMEnos}/parm
export USHnos=${HOMEnos}/ush
export SCRIPTSnos=${HOMEnos}/scripts

# Data paths
export COMROOT=${COMROOT:-/data/com/nosofs}
export COMOUTroot=${COMROOT}/${nos_ofs_ver}
export COMOUT=${COMOUTroot}/${OFS}.${PDY}
export DCOMROOT=${DCOMROOT:-/data/dcom}
export DATAROOT=${DATAROOT:-/work/${OFS}}

# Input data paths
DATA_COM=${DATA_COM:-/data/com}
export COMINgfs=${DATA_COM}/gfs/v16.3
export COMINhrrr=${DATA_COM}/hrrr/v4.1
export COMINrtofs_2d=${DATA_COM}/rtofs/v2.5
export COMINrtofs_3d=${DATA_COM}/rtofs/v2.5
export COMINnwm=${DATA_COM}/nwm/v3.0
export COMINnam=${DATA_COM}/nam/v4.2
export COMINrap=${DATA_COM}/rap/v5.1
export COMINrtma=${DATA_COM}/rtma/v2.8

# YAML config
export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS}.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

# Job control
export NET=nosofs
export RUN=${OFS}
export PREFIXNOS=${OFS}
export KEEPDATA=YES
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO
export platform=ptmp
export TOTAL_TASKS=${TOTAL_TASKS:-12}

# Create working directories
mkdir -p "${COMOUT}" "${DATAROOT}"

echo "=============================================="
echo " SECOFS UFS Docker Test Runner"
echo "=============================================="
echo " OFS:    ${OFS}"
echo " PDY:    ${PDY}"
echo " CYC:    ${cyc}"
echo " Stage:  ${STAGE}"
echo " Tasks:  ${TOTAL_TASKS}"
echo " Config: ${OFS_CONFIG}"
echo " COMOUT: ${COMOUT}"
echo " DATA:   ${DATAROOT}"
echo "=============================================="

run_stage() {
    local stage=$1
    local jjob=$2

    echo ""
    echo ">>> Running ${stage}..."
    echo "    J-job: ${jjob}"

    if [ "$DRY_RUN" = true ]; then
        echo "    [DRY RUN] Would execute: ${HOMEnos}/jobs/${jjob}"
        return 0
    fi

    # Set job-specific variables
    export job=${OFS}_${stage}_${cyc}_${envir}
    export jobid=${job}.docker
    export DATA=${DATAROOT}/${job}
    mkdir -p "${DATA}"
    cd "${DATA}"

    export pgmout=${DATA}/OUTPUT.$$
    export jlogfile=${DATA}/jlogfile

    # Execute the J-job
    if "${HOMEnos}/jobs/${jjob}"; then
        echo "    ${stage} completed successfully"
    else
        echo "    ERROR: ${stage} FAILED (rc=$?)" >&2
        return 1
    fi
}

# ---- Execute stages ----
case "${STAGE}" in
    prep)
        run_stage prep JNOS_OFS_PREP
        ;;
    nowcast)
        run_stage nowcast JNOS_OFS_NOWCAST
        ;;
    forecast)
        run_stage forecast JNOS_OFS_FORECAST
        ;;
    post)
        run_stage post JNOS_OFS_POST
        ;;
    all)
        run_stage prep JNOS_OFS_PREP
        run_stage nowcast JNOS_OFS_NOWCAST
        run_stage forecast JNOS_OFS_FORECAST
        run_stage post JNOS_OFS_POST
        ;;
    *)
        echo "Unknown stage: ${STAGE}" >&2
        echo "Usage: $0 [all|prep|nowcast|forecast|post]" >&2
        exit 1
        ;;
esac

echo ""
echo "=============================================="
echo " All requested stages completed"
echo "=============================================="
echo " Output: ${COMOUT}/"
ls -la "${COMOUT}/" 2>/dev/null || echo " (empty)"
