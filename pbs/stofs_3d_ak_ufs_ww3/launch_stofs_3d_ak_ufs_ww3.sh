#!/bin/bash
# launch_stofs_3d_ak_ufs_ww3.sh
#
# Chain STOFS-3D-AK + WW3 (DATM+SCHISM+WW3, DRAFT) prep -> nowcast ->
# forecast -> post within nos_workflow using PBS afterok dependencies.
# Mirrors pbs/stofs_3d_ak_ufs/launch_stofs_3d_ak_ufs.sh with the OFS name
# switched; nowcast/forecast run at the 30-node/3600-rank layout-A PET
# budget instead of the base's 21 nodes/2513 ranks (see the yaml and PBS
# cards in this directory for the full rationale).
#
# NOT RUNNABLE YET: this system needs nos-utils' 4-component PET-bounds /
# coupling-interval patcher (branch feature/ufs-config-4component) merged,
# fv3_coastalSW.exe built, and the WW3 fix files hand-staged -- see the
# staging checklist at the top of parm/systems/stofs_3d_ak_ufs_ww3.yaml.
#
# Usage:    ./launch_stofs_3d_ak_ufs_ww3.sh <PDY:YYYYMMDD> [CYC:HH (default 00)]
# Example:  ./launch_stofs_3d_ak_ufs_ww3.sh 20260728 00
#
# Override $PKG / $NOS_ARCHIVE_MANIFEST via env if needed.
#
# CRITICAL: CYC is passed uppercase. The PBS cards read `cyc=${CYC:-00}`; a
# lowercase `cyc=` in -v is not seen by them and every cycle silently reruns
# as 00z.
set -eu

# cron runs with a bare environment: the PBS bin dir is not on PATH (so a
# bareword `qsub` fails with "command not found"), and USER/LOGNAME/HOME may be
# unset (which would trip `set -u`). Harden both, matching launch_secofs_ufs.sh.
export PATH=/opt/pbs/default/bin:/opt/pbs/bin:/usr/bin:/bin:${PATH:-}
LOGNAME=${LOGNAME:-${USER:-$(id -un)}}
export LOGNAME USER=${USER:-$LOGNAME}
export HOME=${HOME:-/u/${LOGNAME}}

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <PDY:YYYYMMDD> [CYC:HH (default 00)]" >&2
  exit 2
fi
PDY="$1"
cyc="${2:-00}"
PKG="${PKG:-/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow}"
PBSDIR="${PKG}/pbs/stofs_3d_ak_ufs_ww3"
VARS="PDY=${PDY},CYC=${cyc},NOS_ARCHIVE_MANIFEST=${NOS_ARCHIVE_MANIFEST:-YES}"

for stage in prep nowcast forecast post; do
  if [ ! -f "${PBSDIR}/jnos_${stage}_00.pbs" ]; then
    echo "ERROR: missing ${PBSDIR}/jnos_${stage}_00.pbs -- is the branch checked out and pulled?" >&2
    exit 1
  fi
done

echo "=== STOFS-3D-AK + WW3 chained launch (DRAFT) ==="
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
  Logs    : /lfs/h1/nos/ptmp/${LOGNAME}/rpt/stofs_3d_ak_ufs_ww3/stofs_3d_ak_ufs_ww3_{prep,nowcast,forecast,post}_00.<jobid>.{out,err}
  COMOUT  : /lfs/h1/nos/ptmp/${LOGNAME}/com/nos/stofs_3d_ak_ufs_ww3.${PDY}

If an upstream stage fails, the downstream jobs stay queued with an unsatisfied
dependency (state 'H'); clear them with:  qdel ${NOWCAST} ${FORECAST} ${POST}
EOM
