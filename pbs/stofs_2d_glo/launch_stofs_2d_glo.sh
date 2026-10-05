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
# STAGES selects a subset, e.g. STAGES="nowcast forecast" once prep has run. MJ (10/05/26)
set -eu

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <PDY:YYYYMMDD> [CYC:HH (00|06|12|18, default 12)]" >&2
  exit 2
fi
PDY="$1"
CYC="${2:-12}"
case "${CYC}" in 00|06|12|18) ;; *) echo "ERROR: CYC must be 00, 06, 12 or 18 (got ${CYC})" >&2; exit 2 ;; esac
PKG="${PKG:-/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow}"
PBSDIR="${PKG}/pbs/stofs_2d_glo"
# qsub -v replaces the job environment wholesale, so anything the cards need must be listed here. MJ (10/05/26)
VARS="PDY=${PDY},CYC=${CYC}"
for _v in COMROOT_2DGLO ADCIRC_EXEC_DIR ADCIRC_MODULE_PATH STOFS_RUNVER; do
  eval "_val=\${${_v}:-}"
  if [ -n "${_val}" ]; then
    VARS="${VARS},${_v}=${_val}"
  fi
done

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
