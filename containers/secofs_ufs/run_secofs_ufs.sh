#!/bin/bash
# ============================================================================
# run_secofs_ufs.sh - Container entrypoint for SECOFS_UFS (nos-workflow develop)
#
# Mirrors the WCOSS2/develop environment, stages the data wiring that differs
# between the CI dataset and the operational package, then dispatches to the
# unified J-jobs (JNOS_PREP / JNOS_NOWCAST / JNOS_FORECAST / JNOS_POST), which
# run the Python orchestrator:
#   JNOS_PREP -> scripts/exnos_prep.sh -> python3 -m nos_workflow run prep
#
# Data wiring handled here (CI dataset -> develop expectations):
#   * FIXofs: develop expects $HOMEnos/fix/secofs_ufs/secofs_ufs.<x>; the CI
#     fix files are named secofs.<x> under a bind mount. We assemble a writable
#     FIXofs symlink farm with secofs_ufs.<x> aliases + the in-image UFS
#     templates + a shared/ link for river climatology resolution.
#   * Hotstart: nos_utils searches RESTART_DIR first, so we point it at the
#     mounted previous-cycle restart dir (COMIN would be the empty current dir).
#
# Usage:
#   run_secofs_ufs.sh [prep|nowcast|forecast|post|all] [--pdy YYYYMMDD]
#                     [--cyc HH] [--ofs NAME] [--dry-run]
# ============================================================================
set -u

# ---- Parse arguments --------------------------------------------------------
STAGE="${1:-prep}"
shift || true
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --pdy)     export PDY="$2"; shift 2 ;;
        --cyc)     export CYC="$2"; shift 2 ;;
        --ofs)     export OFS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ---- Core identity (develop layout) ----------------------------------------
export OFS=${OFS:-secofs_ufs}
export PDY=${PDY:-$(date -u +%Y%m%d)}
export CYC=${CYC:-18}
export cyc=$(printf '%02d' "${CYC}")
export cycle=t${cyc}z
export envir=dev
export LOGNAME=${LOGNAME:-nosuser}
export NET=nos
export RUN=${OFS}
export PREFIXNOS=${OFS}

# ---- Package paths ----------------------------------------------------------
export PACKAGEROOT=${PACKAGEROOT:-/lfs/h1/nos/nosofs/packages}
export HOMEnos=${HOMEnos:-/opt/nosofs}
export HOMEstofs=${HOMEnos}
[ -e "${PACKAGEROOT}/nos-workflow" ] || { mkdir -p "${PACKAGEROOT}"; ln -sf /opt/nosofs "${PACKAGEROOT}/nos-workflow"; }

export EXECnos=${EXECnos:-${HOMEnos}/exec}
export PARMnos=${PARMnos:-${HOMEnos}/parm}
export USHnos=${USHnos:-${HOMEnos}/ush}
export SCRIPTSnos=${SCRIPTSnos:-${HOMEnos}/scripts}
export OFS_CONFIG=${OFS_CONFIG:-${PARMnos}/systems/${OFS}.yaml}

# ---- Version strings (gfs_ver, hrrr_ver, ...) ------------------------------
. "${HOMEnos}/versions/run.ver" 2>/dev/null || true

# ---- Input data paths (bind targets) ---------------------------------------
export COMROOT=${COMROOT:-/lfs/h1/nos/ptmp/${LOGNAME}/com}
export DCOMROOT=${DCOMROOT:-/lfs/h1/ops/prod/dcom}
export COMINgfs=${COMINgfs:-/lfs/h1/ops/prod/com/gfs/${gfs_ver:-v16.3}}
export COMINhrrr=${COMINhrrr:-/lfs/h1/ops/prod/com/hrrr/${hrrr_ver:-v4.1}}
export COMINnwm=${COMINnwm:-/lfs/h1/ops/prod/com/nwm/${nwm_ver:-v3.1}}
export COMINrtofs=${COMINrtofs:-/lfs/h1/ops/prod/com/rtofs/${rtofs_ver:-v2.5}}
export COMINrtofs_2d=${COMINrtofs_2d:-${COMINrtofs}}
export COMINrtofs_3d=${COMINrtofs_3d:-${COMINrtofs}}

# ---- Tool handles -----------------------------------------------------------
export NDATE=$(command -v ndate || echo /opt/prod_util/bin/ndate)
export NHOUR=$(command -v nhour || echo "${NDATE}")
export WGRIB2=$(command -v wgrib2 || true)

# ---- Job control ------------------------------------------------------------
export KEEPDATA=YES
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO
export DATAROOT=${DATAROOT:-/lfs/h1/nos/ptmp/${LOGNAME}/work/${OFS}}
mkdir -p "${DATAROOT}"

# ---- Model-run environment (nowcast/forecast/all) --------------------------
# prep is pure Python and must NOT get spack libs on LD_LIBRARY_PATH; only the
# MPI model + combine_hotstart7 execs need them. The mpiexec shim also sources
# spack_libs.env, so this is belt-and-suspenders for the combine step.
#
# MPI sizing is overridable so Hercules SLURM can set the real values
# (e.g. TOTAL_TASKS from the YAML, PPN per node, NSCRIBES). On Hercules the
# site MPI/launcher is used; the container's OpenMPI shim is a fallback.
if [ "${STAGE}" != "prep" ] && [ "${STAGE}" != "post" ]; then
    [ -f /opt/nosofs/docker/spack_libs.env ] && . /opt/nosofs/docker/spack_libs.env
    export TOTAL_TASKS=${TOTAL_TASKS:-2914}
    export PPN=${PPN:-120}
    export NSCRIBES=${NSCRIBES:-0}
    # MPI_MAX_TASKS caps ranks for resource-limited hosts; unset = no cap
    # (Hercules runs the full TOTAL_TASKS).
    [ -n "${MPI_MAX_TASKS:-}" ] && export MPI_MAX_TASKS
fi

# ---- Assemble a writable FIXofs (secofs_ufs.<x> symlink farm) --------------
# Mounted CI fix data (read-only) lives at these bind targets.
FIX_SRC=""
for cand in /data/fix/secofs /data/fix/${OFS} /data/fix/secofs_ufs; do
    [ -d "$cand" ] && { FIX_SRC="$cand"; break; }
done
SHARED_SRC=""
for cand in /data/fix/shared; do
    [ -d "$cand" ] && { SHARED_SRC="$cand"; break; }
done

export FIXofs=${FIXofs:-${DATAROOT}/fix/${OFS}}
export FIXnos=${FIXnos:-${SHARED_SRC:-${HOMEnos}/fix/shared}}
mkdir -p "${FIXofs}" "${DATAROOT}/fix"

if [ -n "${FIX_SRC}" ]; then
    for f in "${FIX_SRC}"/*; do
        [ -e "$f" ] || continue
        base=$(basename "$f")
        # secofs.<suffix>  ->  secofs_ufs.<suffix>
        case "$base" in
            secofs.*)  ln -sf "$f" "${FIXofs}/${OFS}.${base#secofs.}" ;;
            ${OFS}.*)  ln -sf "$f" "${FIXofs}/${base}" ;;
        esac
        ln -sf "$f" "${FIXofs}/${base}"
    done
fi
# In-image UFS templates (datm*.template, ufs.configure, secofs_ufs.param.nml...)
if [ -d "${HOMEnos}/fix/secofs_ufs" ]; then
    for t in "${HOMEnos}"/fix/secofs_ufs/*; do
        [ -e "$t" ] || continue
        tb=$(basename "$t")
        [ -e "${FIXofs}/${tb}" ] || ln -sf "$t" "${FIXofs}/${tb}"
    done
fi
# shared/ links so nos_utils resolves river climatology (checks fix/shared,
# fix.parent/shared).
if [ -n "${SHARED_SRC}" ]; then
    [ -e "${FIXofs}/shared" ]        || ln -sf "${SHARED_SRC}" "${FIXofs}/shared"
    [ -e "${DATAROOT}/fix/shared" ]  || ln -sf "${SHARED_SRC}" "${DATAROOT}/fix/shared"
fi

# ---- Stage previous-cycle restart (hotstart) -------------------------------
export RESTART_DIR=${RESTART_DIR:-${DATAROOT}/restart}
mkdir -p "${RESTART_DIR}"
for hs in /data/com/nosofs/v3.7/secofs.${PDY} \
          /data/com/nosofs/v3.7.0/secofs.${PDY} \
          /data/com/nosofs/secofs.${PDY}; do
    [ -d "$hs" ] || continue
    for f in "$hs"/*; do
        [ -e "$f" ] || continue
        base=$(basename "$f")
        ln -sf "$f" "${RESTART_DIR}/${base}"
        case "$base" in
            secofs.*) ln -sf "$f" "${RESTART_DIR}/${OFS}.${base#secofs.}" ;;
        esac
    done
    break
done

# ---- Generate GRIB2 .idx files if missing (met forcing needs them) ---------
if [ -n "${WGRIB2}" ]; then
    for g in "${COMINgfs}"/gfs.${PDY}/*/atmos/gfs.t*z.pgrb2.0p25.f??? \
             "${COMINhrrr}"/hrrr.${PDY}/conus/hrrr.t*z.wrfsfcf??.grib2; do
        [ -f "$g" ] || continue
        [ -f "${g}.idx" ] && continue
        "${WGRIB2}" "$g" -s > "${g}.idx" 2>/dev/null || true
    done
fi

# ---- Banner -----------------------------------------------------------------
cat <<EOF
==============================================
 SECOFS_UFS Container Runner (nos-workflow develop)
==============================================
 OFS:        ${OFS}
 PDY/cyc:    ${PDY} ${cyc}z
 Stage:      ${STAGE}
 HOMEnos:    ${HOMEnos}
 FIXofs:     ${FIXofs}  ($(ls -1 "${FIXofs}" 2>/dev/null | wc -l) entries)
 FIXnos:     ${FIXnos}
 RESTART_DIR:${RESTART_DIR}  ($(ls -1 "${RESTART_DIR}" 2>/dev/null | wc -l) entries)
 COMINgfs:   ${COMINgfs}
 COMINhrrr:  ${COMINhrrr}
 COMINnwm:   ${COMINnwm}
 COMINrtofs: ${COMINrtofs}
 OFS_CONFIG: ${OFS_CONFIG}
==============================================
EOF
echo "--- path checks ---"
for p in "${OFS_CONFIG}:config" "${FIXofs}/${OFS}.hgrid.gr3:hgrid" \
         "${COMINgfs}/gfs.${PDY}:gfs" "${COMINhrrr}/hrrr.${PDY}:hrrr" \
         "${COMINnwm}/nwm.${PDY}:nwm"; do
    path="${p%%:*}"; label="${p##*:}"
    if [ -e "$path" ]; then echo "  OK:      ${label}"; else echo "  MISSING: ${label} (${path})"; fi
done
[ -d "${COMINrtofs}" ] && [ -n "$(ls -A "${COMINrtofs}" 2>/dev/null)" ] \
    && echo "  OK:      rtofs" || echo "  NOTE:    rtofs empty -> OBC/nudging skipped"
echo ""

# ---- Dispatch to J-job(s) ---------------------------------------------------
run_stage() {
    local stage=$1 jjob=$2 rc=0
    export job=${OFS}_${stage}_${cyc}_${envir}
    export jobid=${job}.docker
    export DATA=${DATAROOT}/${jobid}
    mkdir -p "${DATA}"; cd "${DATA}"
    export pgmout=${DATA}/OUTPUT.$$
    export jlogfile=${DATA}/jlogfile

    echo ">>> ${stage}: ${HOMEnos}/jobs/${jjob}"
    if [ "${DRY_RUN}" = true ]; then
        echo "    [DRY RUN] env staged; would exec ${HOMEnos}/jobs/${jjob}"
        return 0
    fi
    "${HOMEnos}/jobs/${jjob}"; rc=$?
    if [ $rc -eq 0 ]; then echo "    ${stage} OK"; else echo "    ${stage} FAILED rc=${rc}" >&2; fi
    return $rc
}

case "${STAGE}" in
    prep)     run_stage prep     JNOS_PREP ;;
    nowcast)  run_stage nowcast  JNOS_NOWCAST ;;
    forecast) run_stage forecast JNOS_FORECAST ;;
    post)     run_stage post     JNOS_POST ;;
    all)
        run_stage prep     JNOS_PREP     && \
        run_stage nowcast  JNOS_NOWCAST  && \
        run_stage forecast JNOS_FORECAST && \
        run_stage post     JNOS_POST ;;
    *) echo "Unknown stage: ${STAGE}" >&2
       echo "Usage: $0 [prep|nowcast|forecast|post|all]" >&2; exit 1 ;;
esac
rc=$?

echo ""
echo "=============================================="
echo " Done (rc=${rc}).  COMOUT=${COMROOT}/${NET}/${OFS}.${PDY}"
ls -la "${COMROOT}/${NET}/${OFS}.${PDY}/" 2>/dev/null | head -40 || echo " (no COMOUT yet)"
exit $rc
