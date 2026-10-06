#!/bin/bash
# launch_stofs_2d_glo.sh
#
# Chain STOFS-2D-Global (ADCIRC) prep -> nowcast -> forecast with PBS afterok
# dependencies. Mirrors launch_stofs_standalone.sh.
#
# Usage:    ./launch_stofs_2d_glo.sh <PDY:YYYYMMDD> [CYC:HH (00|06|12|18, default 12)]
# Example:  ./launch_stofs_2d_glo.sh 20261005 12
#
# Override $PKG via env if needed. COMROOT_2DGLO (default ptmp/.../com_2dglo) is forwarded when set.
# STAGES selects a subset, e.g. STAGES="nowcast forecast" once prep has run.
# Operator overrides, forwarded when set: ATMOSPHERIC_FORCING=false (tide-only), COLDSTART_SPINUP_DAYS,
# NOWCAST_HOURS (default 6; use 24 for a once-a-day 12z run so the restart is the previous day's 12z).
# A cold start spins up tide-only; GFS starts with the forecast. NCPU/NUM_WRITERS are tied to the card
# node counts, so they come from the yaml only. MJ (10/05/26)
# ADCIRC_MODE=ops submits one cycle as the stofs.v3.1.5 job chain (walltimes from ecf/*.ecf; STAGES is ignored);
# COLDSTART=YES prepends cold_adcprep and the spin-up. MJ (10/06/26)
set -eu

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <PDY:YYYYMMDD> [CYC:HH (00|06|12|18, default 12)]" >&2
  exit 2
fi
PDY="$1"
CYC="${2:-12}"
case "${CYC}" in 00|06|12|18) ;; *) echo "ERROR: CYC must be 00, 06, 12 or 18 (got ${CYC})" >&2; exit 2 ;; esac
PKG="${PKG:-$(cd "$(dirname "$0")/../.." && pwd)}"
PBSDIR="${PKG}/pbs/stofs_2d_glo"
# qsub -v replaces the job environment wholesale, so anything the cards need must be listed here. MJ (10/05/26)
VARS="PDY=${PDY},CYC=${CYC},PACKAGEROOT=$(dirname "${PKG}")"
for _v in COMROOT_2DGLO ADCIRC_EXEC_DIR ADCIRC_MODULE_PATH STOFS_RUNVER ATMOSPHERIC_FORCING COLDSTART_SPINUP_DAYS NOWCAST_HOURS; do
  eval "_val=\${${_v}:-}"
  if [ -n "${_val}" ]; then
    VARS="${VARS},${_v}=${_val}"
  fi
done

if [ "${ADCIRC_MODE:-single}" = ops ]; then
  OPSVARS="${VARS},KEEPDATA=NO,ADCIRC_MODE=ops"
  declare -A J
  # sub <label> <card> <walltime> <select|-> <extra vars|-> [dep labels...]; the first job of a stream waits for the spin-up. MJ (10/06/26)
  sub() {
    local label="$1" card="$2" wall="$3" sel="$4" xv="$5" v="${OPSVARS}" dep="" l
    shift 5
    [ "${xv}" = "-" ] || v="${v},${xv}"
    for l in "$@"; do dep="${dep}:${J[$l]}"; done
    local args=(-N "stofs_2d_glo_${label}" -l "walltime=${wall}")
    [ "${sel}" = "-" ] || args+=(-l "select=${sel}")
    [ -z "${dep}" ] || args+=(-W "depend=afterok${dep}")
    J[$label]=$(qsub "${args[@]}" -v "${v}" "${card}")
    printf '%-14s: %s%s\n' "${label}" "${J[$label]}" "${dep:+   (afterok${dep})}"
  }
  PREP="${PBSDIR}/jnos_prep_00.pbs"; NOW="${PBSDIR}/jnos_nowcast_00.pbs"; FC="${PBSDIR}/jnos_forecast_00.pbs"
  for _c in "${PREP}" "${NOW}" "${FC}"; do
    [ -f "${_c}" ] || { echo "ERROR: missing ${_c} -- is the branch checked out and pulled?" >&2; exit 1; }
  done
  PREPSEL="1:ncpus=1:prepost=true:mem=400gb"
  echo "=== STOFS-2D-Global ops-mode chain: PDY=${PDY} CYC=${CYC} PKG=${PKG} ==="
  COLD=""
  if [ "${COLDSTART:-NO}" = YES ]; then
    sub cold_adcprep "${PREP}" 2:00:00 "1:ncpus=1:prepost=true:mem=50gb" COLDSTART=YES
    sub cold_spinup "${NOW}" 1:00:00 - ADCIRC_SEGMENT=spinup cold_adcprep
    COLD="cold_spinup"
  fi
  sub gfs_ncst "${PREP}" 0:10:00 "${PREPSEL}" ADCIRC_SEGMENT=ncst ${COLD}
  sub gfs_fcst1 "${PREP}" 0:30:00 "${PREPSEL}" ADCIRC_SEGMENT=fcst1
  sub gfs_fcst2 "${PREP}" 0:10:00 "${PREPSEL}" ADCIRC_SEGMENT=fcst2
  sub tide_ncst "${NOW}" 0:15:00 - ADCIRC_STREAM=tide,ADCIRC_SEGMENT=ncst ${COLD}
  sub tide_fcst1 "${FC}" 0:30:00 - ADCIRC_STREAM=tide,ADCIRC_SEGMENT=fcst1 tide_ncst
  sub tide_fcst2 "${FC}" 0:25:00 - ADCIRC_STREAM=tide,ADCIRC_SEGMENT=fcst2 tide_fcst1
  sub surf_ncst "${NOW}" 0:15:00 - ADCIRC_STREAM=surf,ADCIRC_SEGMENT=ncst gfs_ncst ${COLD}
  sub surf_fcst1 "${FC}" 0:40:00 - ADCIRC_STREAM=surf,ADCIRC_SEGMENT=fcst1 surf_ncst gfs_fcst1
  sub surf_fcst2 "${FC}" 0:25:00 - ADCIRC_STREAM=surf,ADCIRC_SEGMENT=fcst2 surf_fcst1 gfs_fcst2
  sub post_ncdiff "${PREP}" 0:10:00 "1:ncpus=1:prepost=true:mem=100gb" ADCIRC_SEGMENT=ncdiff tide_fcst2 surf_fcst2
  sub post_ncrcat "${PREP}" 0:15:00 "1:ncpus=1:prepost=true:mem=100gb" ADCIRC_SEGMENT=ncrcat gfs_ncst gfs_fcst1 gfs_fcst2
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
  COMOUT  : ${COMROOT_2DGLO:-/lfs/h1/nos/ptmp/${LOGNAME}/com_2dglo}/nos/stofs_2d_glo.${PDY}

If an upstream stage fails, the downstream jobs stay queued with an unsatisfied
dependency (state 'H'); clear them with:  qdel <jobid> ...  (see the ids above)
EOM
