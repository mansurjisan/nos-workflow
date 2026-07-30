#!/bin/bash
# launch_stofs_3d_ak_ufs.sh
#
# Chain STOFS-3D-AK UFS-coupled (DATM+SCHISM) prep -> nowcast -> forecast ->
# post within nos_workflow using PBS afterok dependencies.
#
# Usage:    ./launch_stofs_3d_ak_ufs.sh <PDY:YYYYMMDD> [CYC:HH (default 00)]
# Example:  ./launch_stofs_3d_ak_ufs.sh 20260728 00
#
# Override $PKG / $NOS_ARCHIVE_MANIFEST via env if needed.
#
# CRITICAL: CYC is passed uppercase. The PBS cards read `cyc=${CYC:-00}`; a
# lowercase `cyc=` in -v is not seen by them and every cycle silently reruns
# as 00z.
set -eu

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <PDY:YYYYMMDD> [CYC:HH (default 00)]" >&2
  exit 2
fi
PDY="$1"
cyc="${2:-00}"
PKG="${PKG:-/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow}"
PBSDIR="${PKG}/pbs/stofs_3d_ak_ufs"
VARS="PDY=${PDY},CYC=${cyc},NOS_ARCHIVE_MANIFEST=${NOS_ARCHIVE_MANIFEST:-YES}"

for stage in prep nowcast forecast post; do
  if [ ! -f "${PBSDIR}/jnos_${stage}_00.pbs" ]; then
    echo "ERROR: missing ${PBSDIR}/jnos_${stage}_00.pbs -- is the branch checked out and pulled?" >&2
    exit 1
  fi
done

echo "=== STOFS-3D-AK UFS-coupled chained launch ==="
echo "  PDY=${PDY}  CYC=${cyc}"
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

# 4. post -- runs only if forecast exits 0
POST=$(qsub -W depend=afterok:"${FORECAST}" -v "${VARS}" "${PBSDIR}/jnos_post_00.pbs")
echo "post     : ${POST}   (afterok:${FORECAST})"

cat <<EOM

Chain submitted (prep -> nowcast -> forecast -> post, gated on afterok).
  Monitor : qstat -u ${LOGNAME}
  Logs    : /lfs/h1/nos/ptmp/${LOGNAME}/rpt/stofs_3d_ak_ufs/stofs_3d_ak_ufs_{prep,nowcast,forecast,post}_00.<jobid>.{out,err}
  COMOUT  : /lfs/h1/nos/ptmp/${LOGNAME}/com/nos/stofs_3d_ak_ufs.${PDY}

If an upstream stage fails, the downstream jobs stay queued with an unsatisfied
dependency (state 'H'); clear them with:  qdel ${NOWCAST} ${FORECAST} ${POST}
EOM
