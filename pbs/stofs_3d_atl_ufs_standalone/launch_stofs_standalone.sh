#!/bin/bash
# launch_stofs_standalone.sh
#
# Chain STOFS-3D-ATL standalone (pschism) prep -> nowcast -> forecast within
# nos_workflow using PBS afterok dependencies. Mirrors the operational
# IT-STOFS launch_stofs.sh pattern, adapted for the nos_workflow standalone PBS.
#
# Usage:    ./launch_stofs_standalone.sh <PDY:YYYYMMDD> [CYC:HH (default 12)]
# Example:  ./launch_stofs_standalone.sh 20260603 12
#
# Override $PKG / $NOS_ARCHIVE_MANIFEST via env if needed.
#
# CRITICAL: this script intentionally does NOT pass OFS. The standalone PBS
# default OFS=stofs_3d_atl_ufs is load-bearing for fix/asset resolution; the
# standalone mode switch comes from OFS_CONFIG=stofs_3d_atl_ufs_standalone.yaml
# set inside the PBS. Passing OFS=stofs_3d_atl_ufs_standalone re-paths FIXofs to
# a nonexistent namespace and breaks prep.
set -eu

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <PDY:YYYYMMDD> [CYC:HH (default 12)]" >&2
  exit 2
fi
PDY="$1"
CYC="${2:-12}"
PKG="${PKG:-/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow}"
PBSDIR="${PKG}/pbs/stofs_3d_atl_ufs_standalone"
VARS="PDY=${PDY},CYC=${CYC},NOS_ARCHIVE_MANIFEST=${NOS_ARCHIVE_MANIFEST:-YES}"

for stage in prep nowcast forecast; do
  if [ ! -f "${PBSDIR}/jnos_${stage}_00.pbs" ]; then
    echo "ERROR: missing ${PBSDIR}/jnos_${stage}_00.pbs -- is the branch checked out and pulled?" >&2
    exit 1
  fi
done

echo "=== STOFS-3D-ATL standalone chained launch ==="
echo "  PDY=${PDY}  CYC=${CYC}"
echo "  PKG=${PKG}"
echo "=============================================="

# 1. prep
PREP=$(qsub -v "${VARS}" "${PBSDIR}/jnos_prep_00.pbs")
echo "prep     : ${PREP}"

# 2. nowcast -- runs only if prep exits 0
NOWCAST=$(qsub -W depend=afterok:"${PREP}" -v "${VARS}" "${PBSDIR}/jnos_nowcast_00.pbs")
echo "nowcast  : ${NOWCAST}   (afterok:${PREP})"

# 3. forecast -- runs only if nowcast exits 0
FORECAST=$(qsub -W depend=afterok:"${NOWCAST}" -v "${VARS}" "${PBSDIR}/jnos_forecast_00.pbs")
echo "forecast : ${FORECAST}   (afterok:${NOWCAST})"

cat <<EOM

Chain submitted (prep -> nowcast -> forecast, gated on afterok).
  Monitor : qstat -u ${LOGNAME}
  Logs    : /lfs/h1/nos/ptmp/${LOGNAME}/rpt/stofs_3d_atl_ufs/stofs_3d_atl_ufs_standalone_{prep,nowcast,forecast}_00.<jobid>.{out,err}
  COMOUT  : /lfs/h1/nos/ptmp/${LOGNAME}/com/nos/stofs_3d_atl_ufs.${PDY}

If prep fails, the downstream jobs stay queued with an unsatisfied dependency
(state 'H'); clear them with:  qdel ${NOWCAST} ${FORECAST}
EOM
