#!/bin/bash
# launch_stofs_2d_glo.sh
#
# Chain one STOFS-2D-Global (ADCIRC) ops-mode cycle on Hercules with Slurm afterok dependencies: the Slurm counterpart of
# pbs/stofs_2d_glo/launch_stofs_2d_glo.sh (ops is the only mode; this launcher always sets ADCIRC_MODE=ops for the jobs). MJ (10/19/26)
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
# 52 nodes: the surf runs launch 4064 + 5 writer ranks = 4069, which fit 51 x 80 (srun -N 51); the job keeps -N 52, and -N 51
# is a possible follow-up. MJ (10/17/26) The tide stream (4064 ranks) uses 51 of
# the 52 nodes (srun -N 51, set by the ADCIRC runner), the same layout as before, so results match the separate-job layout. MJ (10/14/26) The launcher passes the lists in the
# environment of sbatch (--export=ALL), space separated: sbatch --export splits values at commas. MJ (10/14/26)
# Cycle options: COLD=1 (default) adds adcprep to prep and the spin-up to nowcast; COLD=spinup only the spin-up (nod_equi and the decomposition
# tar exist); COLD=0 neither (the previous 6-hourly cycle is in COMOUT). The preflight checks the files each option needs. COLD=spinup
# only works for the same PDY and CYC as the adcprep step that made nod_equi (the spin-up refuses another cycle). KEEPDATA=YES keeps each
# job's $DATA (default NO). STAGES is a subset of "prep nowcast forecast post" in that order (default all; only the submitted jobs are
# linked); STREAMS (default "tide surf", in that order, no repeats) is passed as ADCIRC_STREAM. COLD=1 (the default) needs the prep job, so
# a STAGES with nowcast and without prep needs COLD=spinup or COLD=0. The retired names W_COLD W_SPIN W_TNC W_TFC W_SNC W_SFC W_DIFF
# W_CAT W_GN W_GF and SERIAL stop the launcher (the streams always run serially now). MJ (10/14/26)
# The surf forcing is read from $COMROOT_2DGLO/nos/stofs_2d_glo.<PDY>/<CYC>/rerun (staged from the ops files; the preflight checks it).
# The prep job always runs the ncst and fcst steps; they skip when the staged files exist. SUBMIT_GFS=1 lets them build from GFS instead:
# ADCIRC_GFS_SOURCE (sfcf|sflux, forwarded to the jobs; default sflux with SUBMIT_GFS=1, since sfcf past f012 is not public) picks the file
# family, read from <COMROOT_STAGED default $NOS_PTMP/$LOGNAME/comin_2dglo>/gfs. On Hercules stage the public flux files first, on a login node:
#   tools/hercules_2d_glo_stage_forcing.sh --source gfs <PDY> <CYC>
# The preflight then lists every file the builder reads for the submitted stages (one nos-utils call) instead of the rerun files. The prep
# job's whole node (the card's --mem=0) is plenty: the builder streams one record at a time, so the forcing needs only a few GB, and the
# adcprep step (cold start) is what sets the memory. Only a submission with the prep job builds forcing, so without
# prep in STAGES the preflight checks the staged rerun files as without SUBMIT_GFS. NCST_RECORDS (default 7) sets the ncst window of the
# file list; after a gap, when the chain start is older than cycle - 6 h, stage and launch with NCST_RECORDS=<hours since the chain start + 1>. The forcing is not bitwise equal to ops (GRIB2 vs netCDF packing). MJ (10/14/26)
# Walltimes are the Hercules measurements plus margin, not the ecf values (ncst took 1128 s tide and 1115 s surf; the ecf nowcast
# limit is 0:15 and the WCOSS2 launcher uses 0:25). W_PREP W_NOWCAST W_FORECAST W_POST override them; the defaults are the sums of the
# former per-job values (prep 0:50, +3:00 with adcprep; nowcast 1:20, +1:00 with the spin-up; forecast 2:00; post 1:15). MJ (10/14/26)
# Not submitted: anomaly, bias and grib2 need the ops executables and cfp, which Hercules lacks. MJ (10/14/26)
# There are no done-markers: redo a failed step by resubmitting its job with a narrower list. After a failed nowcast step resubmit
# COLD=0 STAGES="nowcast forecast post" (one launch; tide_ncst re-runs from the same input chain file and adds about 13 min, which is
# safe). To redo only a stream in two launches, COLD=0 STAGES=nowcast STREAMS=surf first and COLD=0 STAGES="forecast post" only after that
# job finishes. After a failed surf fcst: COLD=0 STAGES="forecast post" STREAMS=surf (a fcst cannot run twice). On a cold cycle where
# adcprep passed and the spin-up or the rest of prep failed, one COLD=spinup launch redoes the cycle (STAGES="nowcast forecast post" skips
# prep; the preflight needs this cycle's nod_equi and the decomposition tar). SLURM_CI_ACCOUNT and SLURM_CI_QOS, when set, are passed to every
# sbatch as --account and --qos and override the cards' #SBATCH values. The Jenkins pipeline does not call this launcher: it submits the same four jobs one
# stage at a time through .cicd/scripts/run_stage.sh (stofs_2d_glo.sh card-env repeats the flags and walltimes below; a test compares them). MJ (10/15/26)
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
for _v in W_COLD W_SPIN W_TNC W_TFC W_SNC W_SFC W_DIFF W_CAT W_GN W_GF SERIAL; do
  [ -z "${!_v+x}" ] || { echo "ERROR: ${_v} is retired: use W_PREP, W_NOWCAST, W_FORECAST and W_POST for the walltimes; the streams always run one after the other now, so there is no SERIAL" >&2; exit 2; }
done
STAGES="${STAGES:-prep nowcast forecast post}"
_want=""
for _s in prep nowcast forecast post; do
  case " ${STAGES} " in *" ${_s} "*) _want="${_want:+${_want} }${_s}" ;; esac
done
[ "${_want}" = "$(echo ${STAGES})" ] || { echo "ERROR: STAGES must be a subset of 'prep nowcast forecast post' in that order (got '${STAGES}')" >&2; exit 2; }
STAGES="${_want}"
STREAMS="$(echo ${STREAMS:-tide surf} | tr -s ' ,' ' ' | sed 's/^ //;s/ $//')"
case "${STREAMS}" in "tide surf"|tide|surf) ;; *) echo "ERROR: STREAMS must be tide, surf or 'tide surf' in that order (got '${STREAMS}')" >&2; exit 2 ;; esac
case " ${STAGES} " in
  *" nowcast "*) case " ${STAGES} " in
    *" prep "*) ;;
    *) [ "${COLD:-1}" != 1 ] || { echo "ERROR: COLD=1 (the default) adds adcprep to the prep job, which STAGES='${STAGES}' does not submit; use COLD=spinup or COLD=0" >&2; exit 2; } ;;
  esac ;;
esac
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
# sfcf past f012 is not public, so a SUBMIT_GFS=1 build on Hercules reads the sflux files unless told otherwise. MJ (10/14/26)
[ "${SUBMIT_GFS:-0}" != 1 ] || export ADCIRC_GFS_SOURCE="${ADCIRC_GFS_SOURCE:-sflux}"
case "${ADCIRC_GFS_SOURCE:-sfcf}" in sfcf|sflux) ;; *) echo "ERROR: ADCIRC_GFS_SOURCE must be sfcf or sflux (got ${ADCIRC_GFS_SOURCE})" >&2; exit 2 ;; esac
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
# prep and post (ncrcat) use both forcing segments, nowcast the ncst one, forecast the fcst one. MJ (10/14/26)
_segs=""
for _s in ${STAGES}; do
  case "${_s}" in prep|post) _segs="${_segs} ncst fcst" ;; nowcast) _segs="${_segs} ncst" ;; forecast) _segs="${_segs} fcst" ;; esac
done
_segs="$(printf '%s\n' ${_segs} | sort -u | tr '\n' ' ')"
_prep=0; case " ${STAGES} " in *" prep "*) _prep=1 ;; esac
if [ "${SUBMIT_GFS:-0}" != 1 ] || [ "${_prep}" = 0 ]; then
  for _s in ${_segs}; do
    for _n in 221 222 225; do need -s "${RR}/stofs_2d_glo_${_s}.${_n}.nc"; done
  done
else
  # every GFS file the builder will read; prep is the only job that builds forcing. The python call needs numpy: the launcher
  # unsets PYTHONPATH, so load the modules and the venv as the stage tool does. MJ (10/14/26)
  _gl=$( set +u
         if ! type module >/dev/null 2>&1; then
           for _m in /etc/profile.d/modules.sh "${LMOD_PKG:-/nonexistent}/init/bash"; do [ -r "${_m}" ] && { . "${_m}"; break; }; done
         fi
         if type module >/dev/null 2>&1; then
           module purge; module use "${PKG}/modulefiles"; . "${PKG}/versions/run.hercules.ver"; module load nos_hercules.intel
         fi
         _v="${NOS_VENV:-${VENV_PATH:-$HOME/nos-venv}}"; [ ! -f "${_v}/bin/activate" ] || . "${_v}/bin/activate"
         python3 "${PKG}/tools/stage_stofs_2d_glo_ops_forcing.py" --gfs-files "${COMROOT_STAGED:-${NOS_PTMP}/${LOGNAME}/comin_2dglo}/gfs" \
           --cycle "${PDY}${CYC}" --segments "$(echo ${_segs} | tr ' ' ',')" --gfs-source "${ADCIRC_GFS_SOURCE}" \
           --ncst-records "${NCST_RECORDS:-7}" --nos-utils "${PKG}/ush/python/nos-utils" ) || {
    echo "ERROR: cannot list the GFS ${ADCIRC_GFS_SOURCE} files (python3 needs numpy: module nos_hercules.intel / NOS_VENV; nos-utils needs gfs_input_files)" >&2; exit 1; }
  _gm=()
  while IFS= read -r _f; do [ -z "${_f}" ] || [ -s "${_f}" ] || _gm+=("${_f}"); done <<< "${_gl}"
  if [ "${#_gm[@]}" -gt 0 ]; then
    echo "MISSING: ${#_gm[@]} of $(echo "${_gl}" | wc -l) GFS ${ADCIRC_GFS_SOURCE} files; the first ones:" >&2
    printf '  %s\n' "${_gm[@]:0:3}" >&2
    echo "  run: tools/hercules_2d_glo_stage_forcing.sh --source gfs ${PDY} ${CYC}" >&2
    _miss=1
  fi
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

OPSVARS="PDY=${PDY},CYC=${CYC},KEEPDATA=${KEEPDATA:-NO},ADCIRC_MODE=ops${ADCIRC_GFS_SOURCE:+,ADCIRC_GFS_SOURCE=${ADCIRC_GFS_SOURCE}}"
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
PSEG="ncst fcst"; PW=0:50:00; NSEG=ncst; NW=1:20:00
case "${COLD:-1}" in
  1)      PSEG="adcprep ${PSEG}"; PW=3:50:00; NSEG="spinup ${NSEG}"; NW=2:20:00 ;;
  spinup) NSEG="spinup ${NSEG}"; NW=2:20:00 ;;
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
    post)     sub post "${PREP}" "${W_POST:-1:15:00}" "-N 1 -n 1 --mem=100G" "ncdiff ncrcat" - ${PREV} ;;
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
