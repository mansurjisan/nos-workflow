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
# installs), NOS_PTMP, COMROOT_2DGLO (default $NOS_PTMP/$LOGNAME/com, the cards' default), COMROOT_STAGED (GFS under <it>/gfs), NOS_VENV. MJ (10/13/26)
# One cycle is four jobs, prep -> nowcast -> forecast -> post, each afterok on the one before. The tide and surf streams run one after the
# other inside a job, on the job's own allocation. Each job runs the steps of its ADCIRC_SEGMENT / ADCIRC_STREAM list in order:
#   prep      [adcprep], GFS ncst, GFS fcst forcing      -N 1 -n 1 --mem=64G (the card's whole node with SUBMIT_GFS=1)
#   nowcast   [spinup], tide ncst, surf ncst             -N 52
#   forecast  tide fcst, surf fcst                       -N 52
#   post      ncdiff, ncrcat                             -N 1 -n 1 --mem=100G
# 52 nodes because the surf runs launch 4064 + 32 writer ranks = 4096, which needs 52 x 80 slots. The launcher passes the lists in the
# environment of sbatch (--export=ALL), as --export cannot carry a value with a comma. MJ (10/14/26)
# Cycle options: COLD=1 (default) adds adcprep to prep and the spin-up to nowcast; COLD=spinup only the spin-up (nod_equi and the decomposition
# tar exist); COLD=0 neither (the previous 6-hourly cycle is in COMOUT). The preflight checks the files each option needs. COLD=spinup
# only works for the same PDY and CYC as the cold_adcprep that made nod_equi (the spin-up refuses another cycle). KEEPDATA=YES keeps each
# job's $DATA (default NO). STAGES is a subset of "prep nowcast forecast post" in that order (default all; only the submitted jobs are
# linked); STREAMS (default "tide surf") is passed as ADCIRC_STREAM. MJ (10/14/26)
# The surf forcing is read from $COMROOT_2DGLO/nos/stofs_2d_glo.<PDY>/<CYC>/rerun (staged from the ops files; the preflight checks it).
# The prep job always runs the ncst and fcst steps; they skip when the staged files exist. SUBMIT_GFS=1 lets them build from GFS instead,
# for a machine that has GFS sfcf (untested on Hercules; GFS location via COMROOT_STAGED). MJ (10/14/26)
# Walltimes are the Hercules measurements plus margin, not the ecf values (ncst took 1128 s tide and 1115 s surf; the ecf nowcast
# limit is 0:15 and the WCOSS2 launcher uses 0:25). W_PREP W_NOWCAST W_FORECAST W_POST override them; the defaults are the sums of the
# former per-job values (prep 0:50, +3:00 with adcprep; nowcast 1:20, +1:00 with the spin-up; forecast 2:00; post 1:15). MJ (10/14/26)
# Not submitted: anomaly, bias and grib2 need the ops executables and cfp, which Hercules lacks. MJ (10/13/26)
# There are no done-markers: redo a failed step by resubmitting its job with a narrower list, e.g. STAGES="nowcast forecast post"
# STREAMS=surf COLD=0 after the surf ncst failed (ncst re-runs from the same chain file; the prep forcing is staged). The CI smoke test
# is STAGES=nowcast; the preflight then needs only the ncst forcing. SLURM_CI_ACCOUNT and SLURM_CI_QOS, when set, are passed to every
# sbatch as --account and --qos and override the cards' #SBATCH values (the Jenkins pipeline sets them, as for the SECOFS cards). MJ (10/14/26)
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
STAGES="${STAGES:-prep nowcast forecast post}"
_want=""
for _s in prep nowcast forecast post; do
  case " ${STAGES} " in *" ${_s} "*) _want="${_want:+${_want} }${_s}" ;; esac
done
[ "${_want}" = "$(echo ${STAGES})" ] || { echo "ERROR: STAGES must be a subset of 'prep nowcast forecast post' in that order (got '${STAGES}')" >&2; exit 2; }
STREAMS="$(echo ${STREAMS:-tide surf} | tr -s ' ,' ',')"
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
export COMROOT_2DGLO="${COMROOT_2DGLO:-${NOS_PTMP}/${LOGNAME}/com}"
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
  # prep and post (ncrcat) use both forcing segments, nowcast the ncst one, forecast the fcst one. MJ (10/14/26)
  _segs=""
  for _s in ${STAGES}; do
    case "${_s}" in prep|post) _segs="${_segs} ncst fcst" ;; nowcast) _segs="${_segs} ncst" ;; forecast) _segs="${_segs} fcst" ;; esac
  done
  for _s in $(printf '%s\n' ${_segs} | sort -u); do
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
# sub <label> <card> <walltime> <extra sbatch flags|-> <ADCIRC_SEGMENT list> <ADCIRC_STREAM list|-> [dep labels...]. The lists go in the
# environment (--export=ALL): --export would split them at their commas. MJ (10/14/26)
sub() {
  local label="$1" card="$2" wall="$3" flags="$4" seg="$5" stream="$6" dep="" l id
  shift 6
  [ "${flags}" != - ] || flags=""
  [ "${stream}" != - ] || stream=""
  for l in "$@"; do dep="${dep}:${J[$l]}"; done
  id=$(ADCIRC_SEGMENT="${seg}" ADCIRC_STREAM="${stream}" \
       sbatch --parsable --kill-on-invalid-dep=yes -J "stofs_2d_glo_${label}" -t "${wall}" ${ACCT[@]+"${ACCT[@]}"} ${flags} \
       ${dep:+--dependency=afterok${dep}} --export="ALL,${OPSVARS}" "${card}") || {
    echo "ERROR: sbatch failed for ${label}; cancel what was queued: scancel \$(awk '{print \$2}' ${JOBS})" >&2
    exit 1
  }
  J[$label]="${id%%;*}"
  echo "${label} ${J[$label]}" >> "${JOBS}"
  printf '%-14s: %s%s\n' "${label}" "${J[$label]}" "${dep:+   (afterok${dep})}"
}

echo "=== STOFS-2D-Global ops-mode chain on Hercules: PDY=${PDY} CYC=${CYC} PKG=${PKG} COMROOT_2DGLO=${COMROOT_2DGLO} STAGES='${STAGES}' STREAMS=${STREAMS} ==="
# Walltime defaults are the sums of the former per-job ones; the cold start adds adcprep (3:00) and the spin-up (1:00). MJ (10/14/26)
PSEG=ncst,fcst; PW=0:50:00; NSEG=ncst; NW=1:20:00
case "${COLD:-1}" in
  1)      PSEG="adcprep,${PSEG}"; PW=3:50:00; NSEG="spinup,${NSEG}"; NW=2:20:00 ;;
  spinup) NSEG="spinup,${NSEG}"; NW=2:20:00 ;;
esac
# prep needs more than 64 GB only when it builds the forcing from GFS; the card's whole node covers that. MJ (10/14/26)
PFLAGS="-N 1 -n 1 --mem=64G"
[ "${SUBMIT_GFS:-0}" != 1 ] || PFLAGS=-
PREV=""
for _s in ${STAGES}; do
  case "${_s}" in
    prep)     sub prep "${PREP}" "${W_PREP:-${PW}}" "${PFLAGS}" "${PSEG}" - ${PREV} ;;
    nowcast)  sub nowcast "${NOW}" "${W_NOWCAST:-${NW}}" "-N 52" "${NSEG}" "${STREAMS}" ${PREV} ;;
    forecast) sub forecast "${FC}" "${W_FORECAST:-2:00:00}" "-N 52" fcst "${STREAMS}" ${PREV} ;;
    post)     sub post "${PREP}" "${W_POST:-1:15:00}" "-N 1 -n 1 --mem=100G" ncdiff,ncrcat - ${PREV} ;;
  esac
  PREV="${_s}"
done

cat <<EOM

Chain submitted, each job gated on afterok of the job before it (an upstream failure cancels the rest: --kill-on-invalid-dep=yes).
anomaly, bias and grib2 are not run on Hercules (they need the ops executables and cfp); the post job is ncdiff and ncrcat.
  Monitor : squeue -u ${LOGNAME}
  Status  : ${SLDIR}/status_stofs_2d_glo.sh ${PDY} ${CYC}
  Logs    : ${NOS_PTMP}/${LOGNAME}/rpt/stofs_2d_glo/stofs_2d_glo_{prep,nowcast,forecast}_00.<jobid>.{out,err}
  COMOUT  : ${COMROOT_2DGLO}/nos/stofs_2d_glo.${PDY}
  Job list: ${JOBS}
  Cancel  : scancel \$(awk '{print \$2}' ${JOBS})
EOM
