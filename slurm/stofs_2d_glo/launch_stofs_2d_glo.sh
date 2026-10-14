#!/bin/bash
# launch_stofs_2d_glo.sh
#
# Chain one STOFS-2D-Global (ADCIRC) ops-mode cycle on Hercules with Slurm afterok dependencies: the Slurm counterpart of
# pbs/stofs_2d_glo/launch_stofs_2d_glo.sh (ops mode only; the single-mode chain is not submitted from here). MJ (10/13/26)
#
# Usage:    ./launch_stofs_2d_glo.sh <PDY:YYYYMMDD> <CYC:HH (00|06|12|18)>
# Example:  ./launch_stofs_2d_glo.sh 20261012 06
#
# Run it from a login node shell (it refuses inside an srun/salloc allocation) and from the clone whose cards should run; the clone
# must be named nos-workflow because the cards derive HOMEnos from $PACKAGEROOT/nos-workflow. Optional env: ADCIRC_EXEC_DIR (dir
# holding padcirc and adcprep; default <parent of the clone>/adcirc_v56.1.0_exec, where tools/build_stofs_2d_glo_adcirc_hercules.sh
# installs), NOS_PTMP, COMROOT_2DGLO (default $NOS_PTMP/$LOGNAME/com_2dglo), COMROOT_STAGED (GFS under <it>/gfs), NOS_VENV. MJ (10/13/26)
# Cycle options: COLD=1 (default) prepends cold_adcprep + cold_spinup; COLD=spinup only the spin-up (nod_equi and the decomposition tar
# exist); COLD=0 neither (the previous 6-hourly cycle is in COMOUT). The preflight checks the files each option needs. COLD=spinup
# only works for the same PDY and CYC as the cold_adcprep that made nod_equi (the spin-up refuses another cycle). SERIAL=1 makes
# surf_ncst wait for tide_fcst, so 52 nodes are busy at a time instead of 103. KEEPDATA=YES keeps each job's $DATA (default NO). MJ (10/13/26)
# The surf forcing is read from $COMROOT_2DGLO/nos/stofs_2d_glo.<PDY>/<CYC>/rerun (staged from the ops files; the preflight checks it).
# SUBMIT_GFS=1 submits gfs_ncst and gfs_fcst instead, for a machine that has GFS sfcf (untested on Hercules; GFS location via COMROOT_STAGED). MJ (10/13/26)
# Walltimes are the Hercules measurements plus margin, not the ecf values (ncst took 1128 s tide and 1115 s surf; the ecf nowcast
# limit is 0:15 and the WCOSS2 launcher uses 0:25, #223). W_COLD W_SPIN W_TNC W_TFC W_SNC W_SFC W_DIFF W_CAT (W_GN W_GF for the
# GFS jobs) override them. MJ (10/13/26)
# Not submitted: post_anomaly, post_bias and post_grib2 need the ops executables and cfp, which Hercules lacks. MJ (10/13/26)
# STAGES=ncst submits only tide_ncst and surf_ncst (the nowcast smoke test; default all) and the preflight then needs only the ncst
# forcing files; it cannot be combined with SERIAL=1. SLURM_CI_ACCOUNT and SLURM_CI_QOS, when set, are passed to every sbatch as
# --account and --qos and override the cards' #SBATCH values (the Jenkins pipeline sets them, as for the SECOFS cards). MJ (10/13/26)
set -eu

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <PDY:YYYYMMDD> <CYC:HH (00|06|12|18)>" >&2
  exit 2
fi
PDY="$1"
CYC="$2"
case "${PDY}" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;; *) echo "ERROR: PDY must be YYYYMMDD (got ${PDY})" >&2; exit 2 ;; esac
case "${CYC}" in 00|06|12|18) ;; *) echo "ERROR: CYC must be 00, 06, 12 or 18 (got ${CYC})" >&2; exit 2 ;; esac
case "${COLD:-1}" in 1|spinup|0) ;; *) echo "ERROR: COLD must be 1, spinup or 0 (got ${COLD})" >&2; exit 2 ;; esac
case "${STAGES:-all}" in all|ncst) ;; *) echo "ERROR: STAGES must be all or ncst (got ${STAGES})" >&2; exit 2 ;; esac
if [ "${STAGES:-all}" = ncst ] && [ "${SERIAL:-0}" = 1 ]; then
  echo "ERROR: SERIAL=1 makes surf_ncst wait for tide_fcst, which STAGES=ncst does not submit" >&2
  exit 2
fi
STAGES="${STAGES:-all}"
# sbatch from inside an allocation inherits its SLURM_* variables and nests the jobs under it. MJ (10/13/26)
if [ -n "${SLURM_JOB_ID:-}" ]; then
  echo "ERROR: SLURM_JOB_ID=${SLURM_JOB_ID} is set (srun/salloc shell); exit the allocation and run the launcher from a login node shell" >&2
  exit 1
fi
PKG="$(cd "${PKG:-$(dirname "$(readlink -f "$0")")/../..}" && pwd)"
SLDIR="${PKG}/slurm/stofs_2d_glo"
if [ "$(readlink -f "$(dirname "${PKG}")/nos-workflow")" != "$(readlink -f "${PKG}")" ]; then
  echo "ERROR: ${PKG} is not named nos-workflow; the cards run \$PACKAGEROOT/nos-workflow (clone it as <dir>/nos-workflow)" >&2
  exit 1
fi

# sbatch exports this shell's whole environment to the cards; drop anything that could select another package or layout. MJ (10/13/26)
unset HOMEnos HOMEstofs EXECnos FIXnos FIXofs NOS_WORKFLOW_DIR NOS_UTILS_DIR PYTHONPATH OFS_CONFIG COMROOT DATAROOT
unset COMIN COMINgfs COMOUT COMOUTroot COMGES DATA ADCIRC_MODE ADCIRC_STREAM ADCIRC_SEGMENT COLDSTART NCPU NUM_WRITERS TOT_NCPU
unset NOWCAST_HOURS COLDSTART_SPINUP_DAYS ATMOSPHERIC_FORCING RPTDIR
export LOGNAME="${LOGNAME:-$(id -un)}"
export NOS_PTMP="${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}"
export COMROOT_2DGLO="${COMROOT_2DGLO:-${NOS_PTMP}/${LOGNAME}/com_2dglo}"
export ADCIRC_EXEC_DIR="${ADCIRC_EXEC_DIR:-$(dirname "${PKG}")/adcirc_v56.1.0_exec}"
export PACKAGEROOT="$(dirname "${PKG}")" HOMEnos="${PKG}"

PREP="${SLDIR}/jnos_prep_00.sh"; NOW="${SLDIR}/jnos_nowcast_00.sh"; FC="${SLDIR}/jnos_forecast_00.sh"
RR="${COMROOT_2DGLO}/nos/stofs_2d_glo.${PDY}/${CYC}/rerun"
# Preflight: list every missing piece at once, before anything is queued (the checks below run in one pass). MJ (10/13/26)
_miss=0
need() { [ "$1" "$2" ] || { echo "MISSING: $2" >&2; _miss=1; }; }
for _f in "${PREP}" "${NOW}" "${FC}"; do need -s "${_f}"; done
for _f in "${ADCIRC_EXEC_DIR}/padcirc" "${ADCIRC_EXEC_DIR}/adcprep" "${PKG}/exec/stofs_2d_glo_tide_fac"; do need -x "${_f}"; done
if [ "${SUBMIT_GFS:-0}" != 1 ]; then
  _segs=(ncst fcst)
  [ "${STAGES}" = all ] || _segs=(ncst)
  for _s in "${_segs[@]}"; do
    for _n in 221 222 225; do need -s "${RR}/stofs_2d_glo_${_s}.${_n}.nc"; done
  done
fi
# The fix files the ops runner reads from $HOMEnos/fix/stofs_2d_glo (the cards unset FIXofs). MJ (10/13/26)
for _f in "${PKG}"/fix/stofs_2d_glo/stofs_2d_glo_{grid,attr,body,tide.15,surf.15}; do need -s "${_f}"; done
# The cold-start products the later cycles read from COMGES: COLD=spinup and COLD=0 need nod_equi and the 4064-rank decomposition. MJ (10/13/26)
GES="${COMROOT_2DGLO}/nos/stofs_2d_glo"
if [ "${COLD:-1}" != 1 ]; then
  for _f in "${GES}/stofs_2d_glo_nod_equi" "${GES}/stofs_2d_glo_4064.tar" "${GES}/stofs_2d_glo_4064.tar.json"; do need -s "${_f}"; done
fi
# COLD=0 also continues from the previous cycle's chain files (PDY CYC minus 6 h). MJ (10/13/26)
if [ "${COLD:-1}" = 0 ]; then
  P6="$(date -u -d "${PDY} ${CYC}:00 6 hours ago" +%Y%m%d%H)"
  for _f in hotstart restart; do need -s "${COMROOT_2DGLO}/nos/stofs_2d_glo.${P6:0:8}/stofs_2d_glo.t${P6:8:2}z.${_f}"; done
fi
[ "${_miss}" = 0 ] || exit 1

JDIR="${NOS_PTMP}/${LOGNAME}/slurm_2dglo"
JOBS="${JDIR}/jobs_${PDY}${CYC}.txt"
mkdir -p "${JDIR}"
[ ! -s "${JOBS}" ] || mv "${JOBS}" "${JOBS}.$(date +%y%m%d%H%M%S)"
: > "${JOBS}"
# The cards' #SBATCH --output files (empty, the cards redirect to the rpt dir) land in the submit directory. MJ (10/13/26)
cd "${JDIR}"

OPSVARS="PDY=${PDY},CYC=${CYC},KEEPDATA=${KEEPDATA:-NO},ADCIRC_MODE=ops"
# CLI --account/--qos beat the cards' #SBATCH lines, so a CI service account charges an allocation it may use. MJ (10/13/26)
ACCT=()
[ -z "${SLURM_CI_ACCOUNT:-}" ] || ACCT+=(--account="${SLURM_CI_ACCOUNT}")
[ -z "${SLURM_CI_QOS:-}" ] || ACCT+=(--qos="${SLURM_CI_QOS}")
declare -A J
# sub <label> <card> <walltime> <extra sbatch flags|-> <extra export vars|-> [dep labels...]. MJ (10/13/26)
sub() {
  local label="$1" card="$2" wall="$3" flags="$4" xv="$5" v="${OPSVARS}" dep="" l id
  shift 5
  [ "${flags}" != - ] || flags=""
  [ "${xv}" = - ] || v="${v},${xv}"
  for l in "$@"; do dep="${dep}:${J[$l]}"; done
  id=$(sbatch --parsable --kill-on-invalid-dep=yes -J "stofs_2d_glo_${label}" -t "${wall}" ${ACCT[@]+"${ACCT[@]}"} ${flags} \
       ${dep:+--dependency=afterok${dep}} --export="ALL,${v}" "${card}") || {
    echo "ERROR: sbatch failed for ${label}; cancel what was queued: scancel \$(awk '{print \$2}' ${JOBS})" >&2
    exit 1
  }
  J[$label]="${id%%;*}"
  echo "${label} ${J[$label]}" >> "${JOBS}"
  printf '%-14s: %s%s\n' "${label}" "${J[$label]}" "${dep:+   (afterok${dep})}"
}

echo "=== STOFS-2D-Global ops-mode chain on Hercules: PDY=${PDY} CYC=${CYC} PKG=${PKG} COMROOT_2DGLO=${COMROOT_2DGLO} ==="
PRE=""
case "${COLD:-1}" in
  1)      sub cold_adcprep "${PREP}" "${W_COLD:-3:00:00}" "-N 1 -n 1 --mem=64G" COLDSTART=YES
          sub cold_spinup "${NOW}" "${W_SPIN:-1:00:00}" - ADCIRC_SEGMENT=spinup cold_adcprep
          PRE="cold_spinup" ;;
  spinup) sub cold_spinup "${NOW}" "${W_SPIN:-1:00:00}" - ADCIRC_SEGMENT=spinup
          PRE="cold_spinup" ;;
esac
GN=""; GF=""
if [ "${SUBMIT_GFS:-0}" = 1 ]; then
  sub gfs_ncst "${PREP}" "${W_GN:-0:10:00}" - ADCIRC_SEGMENT=ncst ${PRE}
  GN="gfs_ncst"
  if [ "${STAGES}" = all ]; then
    sub gfs_fcst "${PREP}" "${W_GF:-0:40:00}" - ADCIRC_SEGMENT=fcst
    GF="gfs_fcst"
  fi
fi
SER=""
[ "${SERIAL:-0}" != 1 ] || SER="tide_fcst"
# surf ncst/fcst launch 4064 + 32 writer ranks = 4096, which needs 52 x 80 slots, so they add -N 52. MJ (10/13/26)
sub tide_ncst "${NOW}" "${W_TNC:-0:40:00}" - ADCIRC_STREAM=tide,ADCIRC_SEGMENT=ncst ${PRE}
[ "${STAGES}" != all ] || sub tide_fcst "${FC}" "${W_TFC:-0:55:00}" - ADCIRC_STREAM=tide,ADCIRC_SEGMENT=fcst tide_ncst
sub surf_ncst "${NOW}" "${W_SNC:-0:40:00}" "-N 52" ADCIRC_STREAM=surf,ADCIRC_SEGMENT=ncst ${GN} ${PRE} ${SER}
if [ "${STAGES}" = all ]; then
  sub surf_fcst "${FC}" "${W_SFC:-1:05:00}" "-N 52" ADCIRC_STREAM=surf,ADCIRC_SEGMENT=fcst surf_ncst ${GF}
  sub post_ncdiff "${PREP}" "${W_DIFF:-0:30:00}" "-N 1 -n 1 --mem=100G" ADCIRC_SEGMENT=ncdiff tide_fcst surf_fcst
  sub post_ncrcat "${PREP}" "${W_CAT:-0:45:00}" "-N 1 -n 1 --mem=100G" ADCIRC_SEGMENT=ncrcat surf_fcst
fi

cat <<EOM

Chain submitted, each job gated on afterok of its upstream jobs (an upstream failure cancels the rest: --kill-on-invalid-dep=yes).
post_anomaly, post_bias and post_grib2 are not submitted on Hercules (they need the ops executables and cfp).
  Monitor : squeue -u ${LOGNAME}
  Status  : ${SLDIR}/status_stofs_2d_glo.sh ${PDY} ${CYC}
  Logs    : ${NOS_PTMP}/${LOGNAME}/rpt/stofs_2d_glo/stofs_2d_glo_{prep,nowcast,forecast}_00.<jobid>.{out,err}
  COMOUT  : ${COMROOT_2DGLO}/nos/stofs_2d_glo.${PDY}
  Job list: ${JOBS}
  Cancel  : scancel \$(awk '{print \$2}' ${JOBS})
EOM
