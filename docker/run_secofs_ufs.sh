#!/bin/bash
# ============================================================================
# run_secofs_ufs.sh - Docker test runner for SECOFS (WCOSS2-mirrored paths)
#
# Mirrors the WCOSS2 environment exactly:
#   PACKAGEROOT  = /lfs/h1/nos/nosofs/packages
#   HOMEnos      = /lfs/h1/nos/nosofs/packages/nosofs.v3.7.0
#   COMINgfs     = /lfs/h1/ops/prod/com/gfs/v16.3
#   COMROOT      = /lfs/h1/nos/ptmp/$LOGNAME/com
#   DATAROOT     = /lfs/h1/nos/ptmp/$LOGNAME/work/$OFS
#
# The nos_ofs workflow code lives at /opt/nosofs/ in the container image.
# This script creates symlinks from WCOSS2 paths → /opt/nosofs/ so that
# J-jobs and scripts see identical paths to WCOSS2.
#
# Usage:
#   run_secofs_ufs.sh [all|prep|nowcast|forecast|post] [OPTIONS]
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

# ---- Core environment (mirrors WCOSS2 PBS scripts) ----
export OFS=${OFS:-secofs}
export PDY=${PDY:-$(date +%Y%m%d)}
export CYC=${CYC:-00}
export cyc=$(printf '%02d' "${CYC}")
export cycle=t${cyc}z
export envir=dev
export LOGNAME=${LOGNAME:-nosuser}

# ---- WCOSS2-identical package paths ----
export nosofs_ver=v3.7.0
export nos_ofs_ver=${nosofs_ver}
export PACKAGEROOT=/lfs/h1/nos/nosofs/packages
export HOMEnos=${PACKAGEROOT}/nosofs.${nosofs_ver}
export HOMEstofs=${HOMEnos}

# Create WCOSS2 package path and symlink to container's /opt/nosofs
mkdir -p ${PACKAGEROOT}
if [ ! -e "${HOMEnos}" ]; then
    ln -sf /opt/nosofs ${HOMEnos}
fi

# ---- WCOSS2-identical directory paths ----
export EXECnos=${HOMEnos}/exec
export FIXnos=${HOMEnos}/fix/shared
export FIXofs=${HOMEnos}/fix/${OFS}
export PARMnos=${HOMEnos}/parm
export USHnos=${HOMEnos}/ush
export SCRIPTSnos=${HOMEnos}/scripts

# ---- WCOSS2-identical data paths ----
export COMROOT=/lfs/h1/nos/ptmp/${LOGNAME}/com
export COMOUTroot=${COMROOT}/nosofs/${nos_ofs_ver}
export COMOUT=${COMOUTroot}/${OFS}.${PDY}
export DCOMROOT=/lfs/h1/ops/prod/dcom
export DATAROOT=/lfs/h1/nos/ptmp/${LOGNAME}/work/${OFS}

# ---- WCOSS2-identical input data paths ----
# Source version file for data version strings
. ${HOMEnos}/versions/run.ver 2>/dev/null || true

export COMIN=/lfs/h1/ops/prod/com
export COMINgfs=/lfs/h1/ops/prod/com/gfs/${gfs_ver:-v16.3}
export COMINhrrr=/lfs/h1/ops/prod/com/hrrr/${hrrr_ver:-v4.1}
export COMINrtofs_2d=/lfs/h1/ops/prod/com/rtofs/${rtofs_ver:-v2.5}
export COMINrtofs_3d=/lfs/h1/ops/prod/com/rtofs/${rtofs_ver:-v2.5}
export COMINnwm=/lfs/h1/ops/prod/com/nwm/${nwm_ver:-v3.0}
export COMINnam=/lfs/h1/ops/prod/com/nam/${nam_ver:-v4.2}
export COMINrap=/lfs/h1/ops/prod/com/rap/${rap_ver:-v5.1}
export COMINrtma=/lfs/h1/ops/prod/com/rtma/${rtma_ver:-v2.8}
export COMINetss=/lfs/h1/ops/prod/com/petss/${petss_ver:-v1.1}
export COMPATH=/lfs/h1/ops/prod/com/nos

# ---- YAML config ----
export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS}.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

# ---- prod_util variables (WCOSS2 sets these via module load prod_util) ----
export NDATE=$(command -v ndate)
export NHOUR=${NHOUR:-$(command -v nhour 2>/dev/null || echo "$NDATE")}

# ---- Tool paths (WCOSS2 sets these via modules) ----
export WGRIB2=$(command -v wgrib2)
export NCODIR=$(dirname "$(command -v ncap2 2>/dev/null || echo /usr/bin/ncap2)")

# ---- spack-stack runtime libraries (for COMF Fortran executables) ----
# COMF execs link against libnetcdff.so.7, libnetcdf.so.19, libhdf5.so etc.
SI=${SI:-/opt/spack-stack/spack-stack-1.9.2/envs/ufs-wm-env/install/gcc/13.3.1}
if [ -d "$SI" ]; then
    SPACK_LIBS=$(find "$SI" -maxdepth 2 \( -name lib -o -name lib64 \) -type d 2>/dev/null | tr '\n' ':')
    export LD_LIBRARY_PATH="${SPACK_LIBS}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

# ---- Job control ----
export NET=nosofs
export RUN=${OFS}
export PREFIXNOS=${OFS}
export KEEPDATA=YES
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO
export platform=ptmp
export TOTAL_TASKS=${TOTAL_TASKS:-12}

# ---- Create WCOSS2 directory structure ----
mkdir -p "${COMOUT}" "${DATAROOT}" /lfs/h1/ops/prod/dcom

# Match nos_ofs_ver to whatever version directory exists with hotstart data
# WCOSS2 uses v3.7 for COMOUT, but run.ver sets nosofs_ver=v3.7.0
if [ -d "${COMROOT}/nosofs/v3.7" ] && [ ! -f "${COMROOT}/nosofs/${nos_ofs_ver}/secofs.${PDY}/"*.rst.*.nc 2>/dev/null ]; then
    export nos_ofs_ver=v3.7
    export COMOUTroot=${COMROOT}/nosofs/${nos_ofs_ver}
    export COMOUT=${COMOUTroot}/${OFS}.${PDY}
    echo "  Using nos_ofs_ver=v3.7 (hotstart found in v3.7/)"
fi

echo "=============================================="
echo " SECOFS Docker Test Runner (WCOSS2 paths)"
echo "=============================================="
echo " OFS:      ${OFS}"
echo " PDY:      ${PDY}"
echo " CYC:      ${cyc}"
echo " Stage:    ${STAGE}"
echo " HOMEnos:  ${HOMEnos}"
echo " FIXofs:   ${FIXofs}"
echo " COMINgfs: ${COMINgfs}"
echo " COMOUT:   ${COMOUT}"
echo " DATAROOT: ${DATAROOT}"
echo " Config:   ${OFS_CONFIG}"
echo "=============================================="

# Verify key paths
echo ""
echo "--- Path verification ---"
[ -f "${OFS_CONFIG}" ] && echo "  OK: YAML config" || echo "  MISSING: ${OFS_CONFIG}"
[ -d "${FIXofs}" ] && echo "  OK: FIXofs ($(ls ${FIXofs}/ | wc -l) files)" || echo "  MISSING: ${FIXofs}"
[ -d "${COMINgfs}" ] && echo "  OK: COMINgfs" || echo "  MISSING: ${COMINgfs}"
[ -d "${COMINhrrr}" ] && echo "  OK: COMINhrrr" || echo "  MISSING: ${COMINhrrr}"
[ -d "${COMINnwm}" ] && echo "  OK: COMINnwm" || echo "  MISSING: ${COMINnwm}"
[ -d "${COMINrtofs_2d}" ] && echo "  OK: COMINrtofs" || echo "  MISSING: ${COMINrtofs_2d} (expected — skip OBC)"
which nos_ofs_create_forcing_met >/dev/null 2>&1 && echo "  OK: COMF executables in PATH" || echo "  WARN: COMF executables not in PATH"
which wgrib2 >/dev/null 2>&1 && echo "  OK: wgrib2" || echo "  MISSING: wgrib2"
which ndate >/dev/null 2>&1 && echo "  OK: ndate" || echo "  MISSING: ndate"
echo ""

run_stage() {
    local stage=$1
    local jjob=$2

    echo ">>> Running ${stage}..."
    echo "    J-job: ${HOMEnos}/jobs/${jjob}"

    if [ "$DRY_RUN" = true ]; then
        echo "    [DRY RUN] Would execute: ${HOMEnos}/jobs/${jjob}"
        return 0
    fi

    # Set job-specific variables (mirrors PBS job script)
    export job=${OFS}_${stage}_${cyc}_${envir}
    export jobid=${job}.docker
    export DATA=${DATAROOT}/${job}
    mkdir -p "${DATA}"
    cd "${DATA}"

    export pgmout=${DATA}/OUTPUT.$$
    export jlogfile=${DATA}/jlogfile

    # Execute the J-job
    local rc=0
    "${HOMEnos}/jobs/${jjob}" || rc=$?

    if [ $rc -eq 0 ]; then
        echo "    ${stage} completed successfully"
    else
        echo "    ERROR: ${stage} FAILED (rc=${rc})" >&2
        return $rc
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
