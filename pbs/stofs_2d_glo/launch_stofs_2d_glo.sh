#!/bin/bash
# launch_stofs_2d_glo.sh
#
# Chain STOFS-2D-Global (ADCIRC) prep -> nowcast -> forecast with PBS afterok
# dependencies. Mirrors launch_stofs_standalone.sh.
#
# Usage:    ./launch_stofs_2d_glo.sh <PDY:YYYYMMDD> [CYC:HH (00|06|12|18, default 12)]
# Example:  ./launch_stofs_2d_glo.sh 20261005 12
#
# Override $PKG via env if needed. COMROOT_2DGLO (default ptmp/.../com, as SECOFS and coupled ATL) is forwarded when set. MJ (10/13/26)
# STAGES selects a subset, e.g. STAGES="nowcast forecast" once prep has run.
# Operator overrides, forwarded when set: ATMOSPHERIC_FORCING=false (tide-only), COLDSTART_SPINUP_DAYS,
# NOWCAST_HOURS (default 6; use 24 for a once-a-day 12z run so the restart is the previous day's 12z).
# A cold start spins up tide-only; GFS starts with the forecast. NCPU/NUM_WRITERS are tied to the card
# node counts, so they come from the yaml only. MJ (10/05/26)
# Ops mode:  ADCIRC_MODE=ops [COLDSTART=YES] [STAGES="prep nowcast forecast post"] [STREAMS="tide surf"] ./launch_stofs_2d_glo.sh <PDY> [CYC]. MJ (10/14/26)
# ADCIRC_MODE=ops submits one cycle as four jobs, prep -> nowcast -> forecast -> post, each afterok on the one before. The tide and surf
# streams run one after the other inside a job, on the same 32 nodes. Each job runs the steps of its ADCIRC_SEGMENT / ADCIRC_STREAM list
# in order (the stofs.v3.1.5 jobs it replaces, with their walltimes summed: the ecf values except ncst 0:25, adcprep 3:00 and ncrcat 0:25):
#   prep      [adcprep], GFS ncst, GFS fcst forcing                  0:50 (cold 3:50)   1 cpu, 400 GB
#   nowcast   [spinup], tide ncst, surf ncst                         0:50 (cold 1:50)   the card's 32 nodes
#   forecast  tide fcst, surf fcst                                   2:00               the card's 32 nodes
#   post      anomaly, bias, ncdiff, grib2, ncrcat                   3:10               8 x 32 cpus exclusive, 800 GB (the bias shape)
# COLDSTART=YES (launcher side only: the jobs never read it) adds adcprep to prep and the spin-up to nowcast. STAGES is a subset of
# "prep nowcast forecast post" in that order (default all); only the submitted jobs are linked. STREAMS (default "tide surf") is
# passed as ADCIRC_STREAM, in the order tide surf. The jobs get their lists as space separated values (qsub -v splits at commas), so type
# them by hand inside one pair of quotes around the whole -v value; see the comment block in jnos_nowcast_00.pbs. Gempak is not ported. MJ (10/14/26)
# There are no done-markers: recover a failed job by resubmitting it with a narrower list. After a failed nowcast step resubmit
# STAGES="nowcast forecast post" (one launch; tide_ncst re-runs from the same input chain file and adds about 13 min, which is safe).
# To redo only a stream in two launches, STAGES=nowcast STREAMS=surf first and STAGES="forecast post" only after that job finishes.
# After a failed surf fcst: STAGES="forecast post" STREAMS=surf (a fcst cannot run twice). GFS prep skips forcing that exists. MJ (10/14/26)
# Longer than ecf: cold_adcprep 3:00 (full adcprep with fort.24 plus the cache tar, untimed here) and ncrcat 0:25
# (ncks cuts of the hourly fcst before ncrcat). KEEPDATA=YES keeps each job's $DATA for debugging. MJ (10/13/26)
# ncst 0:25: the first WCOSS2 cycle took 750 s (tide) and 821 s (surf) of the ecf 0:15, mostly decomposition extract and staging. MJ (10/13/26)
set -eu

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <PDY:YYYYMMDD> [CYC:HH (00|06|12|18, default 12)]" >&2
  exit 2
fi
PDY="$1"
CYC="${2:-12}"
case "${CYC}" in 00|06|12|18) ;; *) echo "ERROR: CYC must be 00, 06, 12 or 18 (got ${CYC})" >&2; exit 2 ;; esac
PKG="$(cd "${PKG:-$(dirname "$(readlink -f "$0")")/../..}" && pwd)"
PBSDIR="${PKG}/pbs/stofs_2d_glo"
# qsub -v replaces the job environment wholesale, so anything the cards need must be listed here. MJ (10/05/26)
VARS="PDY=${PDY},CYC=${CYC},PACKAGEROOT=$(dirname "${PKG}"),HOMEnos=${PKG}"
for _v in COMROOT_2DGLO ADCIRC_EXEC_DIR ADCIRC_MODULE_PATH STOFS_RUNVER DCOMROOT ATMOSPHERIC_FORCING COLDSTART_SPINUP_DAYS NOWCAST_HOURS; do
  eval "_val=\${${_v}:-}"
  if [ -n "${_val}" ]; then
    VARS="${VARS},${_v}=${_val}"
  fi
done

if [ "${ADCIRC_MODE:-single}" = ops ]; then
  OPSVARS="${VARS},KEEPDATA=${KEEPDATA:-NO},ADCIRC_MODE=ops"
  declare -A J
  # sub <label> <card> <walltime> <select|-> <extra vars|-> [dep labels...]. qsub -v splits at commas, so a list value is space separated. MJ (10/14/26)
  sub() {
    local label="$1" card="$2" wall="$3" sel="$4" xv="$5" v="${OPSVARS}" dep="" l place="${PLACE:-}"
    shift 5
    [ "${xv}" = "-" ] || v="${v},${xv}"
    for l in "$@"; do dep="${dep}:${J[$l]}"; done
    local args=(-N "stofs_2d_glo_${label}" -l "walltime=${wall}")
    [ "${sel}" = "-" ] || args+=(-l "select=${sel}")
    [ -z "${place}" ] || args+=(-l "place=${place}")
    [ -z "${dep}" ] || args+=(-W "depend=afterok${dep}")
    J[$label]=$(qsub "${args[@]}" -v "${v}" "${card}")
    printf '%-14s: %s%s\n' "${label}" "${J[$label]}" "${dep:+   (afterok${dep})}"
  }
  PREP="${PBSDIR}/jnos_prep_00.pbs"; NOW="${PBSDIR}/jnos_nowcast_00.pbs"; FC="${PBSDIR}/jnos_forecast_00.pbs"
  for _c in "${PREP}" "${NOW}" "${FC}"; do
    [ -f "${_c}" ] || { echo "ERROR: missing ${_c} -- is the branch checked out and pulled?" >&2; exit 1; }
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
  PREPSEL="1:ncpus=1:prepost=true:mem=400gb"
  POSTSEL="8:ncpus=32:prepost=true:mem=800gb"
  echo "=== STOFS-2D-Global ops-mode chain: PDY=${PDY} CYC=${CYC} PKG=${PKG} STAGES='${STAGES}' STREAMS='${STREAMS}' ==="
  [ "${STAGES}" = "prep nowcast forecast post" ] || echo "NOTE: STAGES is a subset, so only these jobs are submitted: ${STAGES}"
  PSEG="ncst fcst"; PWALL=0:50:00; NSEG=ncst; NWALL=0:50:00
  [ "${COLDSTART:-NO}" != YES ] || { PSEG="adcprep ${PSEG}"; PWALL=3:50:00; NSEG="spinup ${NSEG}"; NWALL=1:50:00; }
  PREV=""
  for _s in ${STAGES}; do
    case "${_s}" in
      prep)     sub prep "${PREP}" "${PWALL}" "${PREPSEL}" "ADCIRC_SEGMENT=${PSEG}" ${PREV} ;;
      nowcast)  sub nowcast "${NOW}" "${NWALL}" - "ADCIRC_SEGMENT=${NSEG},ADCIRC_STREAM=${STREAMS}" ${PREV} ;;
      forecast) sub forecast "${FC}" 2:00:00 - "ADCIRC_SEGMENT=fcst,ADCIRC_STREAM=${STREAMS}" ${PREV} ;;
      post)     PLACE=vscatter:exclhost sub post "${PREP}" 3:10:00 "${POSTSEL}" "ADCIRC_SEGMENT=anomaly bias ncdiff grib2 ncrcat" ${PREV} ;;
    esac
    PREV="${_s}"
  done
  exit 0
fi

STAGES="${STAGES:-prep nowcast forecast}"

for stage in ${STAGES}; do
  if [ ! -f "${PBSDIR}/jnos_${stage}_00.pbs" ]; then
    echo "ERROR: missing ${PBSDIR}/jnos_${stage}_00.pbs -- is the branch checked out and pulled?" >&2
    exit 1
  fi
done

echo "=== STOFS-2D-Global chained launch ==="
echo "  PDY=${PDY}  CYC=${CYC}"
echo "  PKG=${PKG}"
echo "======================================"

DEP=""
for stage in ${STAGES}; do
  if [ -n "${DEP}" ]; then
    JID=$(qsub -W depend=afterok:"${DEP}" -v "${VARS}" "${PBSDIR}/jnos_${stage}_00.pbs")
    printf '%-9s: %s   (afterok:%s)\n' "${stage}" "${JID}" "${DEP}"
  else
    JID=$(qsub -v "${VARS}" "${PBSDIR}/jnos_${stage}_00.pbs")
    printf '%-9s: %s\n' "${stage}" "${JID}"
  fi
  DEP="${JID}"
done

cat <<EOM

Chain submitted (${STAGES}), each gated on afterok of the previous.
  Monitor : qstat -u ${LOGNAME}
  Logs    : /lfs/h1/nos/ptmp/${LOGNAME}/rpt/stofs_2d_glo/stofs_2d_glo_{prep,nowcast,forecast}_00.<jobid>.{out,err}
  COMOUT  : ${COMROOT_2DGLO:-/lfs/h1/nos/ptmp/${LOGNAME}/com}/nos/stofs_2d_glo.${PDY}

If an upstream stage fails, the downstream jobs stay queued with an unsatisfied
dependency (state 'H'); clear them with:  qdel <jobid> ...  (see the ids above)
EOM
