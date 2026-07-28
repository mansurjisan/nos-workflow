#!/bin/bash
# ---------------------------------------------------------------------------
# STOFS-3D-ATL UFS-COUPLED chained launch (prep -> nowcast -> forecast -> post)
#
# The coupled counterpart of
# pbs/stofs_3d_atl_ufs_standalone/launch_stofs_standalone.sh. Same chaining
# contract; the difference is the engine: these jobs run fv3_coastalS.exe with
# the NUOPC/DATM layer and OFS_CONFIG=parm/systems/stofs_3d_atl_ufs.yaml (each
# PBS job sets it from ${OFS}), whereas the standalone jobs pin the
# *_standalone.yaml overlay and run pschism_WCOSS2.
#
# Because the coupled build uses OLDIO, the run stages combine per-rank
# schout_<rank>_<stack>.nc into global stacks before archiving; the standalone
# (scribed) path skips that. Both feed the same canonical post products.
#
# Usage:
#   ./launch_stofs_3d_atl_ufs.sh <PDY:YYYYMMDD> [CYC:HH (default 12)]
#   STAGES="post" ./launch_stofs_3d_atl_ufs.sh 20260722 12   # rerun one stage
# ---------------------------------------------------------------------------
set -eu

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <PDY:YYYYMMDD> [CYC:HH (default 12)]" >&2
  exit 2
fi
PDY="$1"
CYC="${2:-12}"
PKG="${PKG:-/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow}"
PBSDIR="${PKG}/pbs/stofs_3d_atl_ufs"
VARS="PDY=${PDY},CYC=${CYC},NOS_ARCHIVE_MANIFEST=${NOS_ARCHIVE_MANIFEST:-YES}"
# qsub -v replaces the job environment wholesale, so a post override
# exported before calling this script would be silently dropped.
# PBS splits -v on commas only, so a space-separated product list
# survives as one value.
# qsub -v replaces the job environment wholesale, so anything not listed
# here is silently dropped. Enumerating them one at a time already cost a
# test run -- NOS_PROFILES_OUTSIDE was missing, so `--outside drop` was
# asked for, never arrived, and the job did the default thing instead.
# Keep this list in step with the post stage's env knobs:
#   grep -rhoE '"(NOS_[A-Z_]+|POST_[A-Z_]+)"' ush/python/nos_workflow/post/
# PBS splits -v on commas only, so a space-separated value survives whole.
for _v in NOS_POST_PRODUCTS NOS_POST_MAX_WORKERS NOS_PROFILES_OUTSIDE \
          POST_FIELDS_DEFLATE NOS_ARCHIVE_FIELDS NOS_COMBINE_OUTPUTS_SCRIPT; do
  eval "_val=\${${_v}:-}"
  if [ -n "${_val}" ]; then
    VARS="${VARS},${_v}=${_val}"
  fi
done

# STAGES is overridable so a rerun can skip completed legs, e.g.
#   STAGES="post" ./launch_stofs_3d_atl_ufs.sh 20260722 12
STAGES="${STAGES:-prep nowcast forecast post}"

for stage in ${STAGES}; do
  if [ ! -f "${PBSDIR}/jnos_${stage}_00.pbs" ]; then
    echo "ERROR: missing ${PBSDIR}/jnos_${stage}_00.pbs -- is the branch checked out and pulled?" >&2
    exit 1
  fi
done

echo "=== STOFS-3D-ATL UFS-coupled chained launch ==="
echo "  PDY=${PDY}  CYC=${CYC}"
echo "  PKG=${PKG}"
echo "==============================================="

# Submit the requested stages in order, each gated on the previous one's
# success. A subset works too -- STAGES="post" reruns just post against
# already-archived outputs, with no dependency to wait on.
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
  Logs    : /lfs/h1/nos/ptmp/${LOGNAME}/rpt/stofs_3d_atl_ufs/stofs_3d_atl_ufs_{prep,nowcast,forecast,post}_00.<jobid>.{out,err}
  COMOUT  : /lfs/h1/nos/ptmp/${LOGNAME}/com/nos/stofs_3d_atl_ufs.${PDY}

Note: the coupled path is roughly 5x slower than the standalone variant
(pbs/stofs_3d_atl_ufs_standalone/launch_stofs_standalone.sh) and, being
OLDIO, adds a per-rank field combine in the run stages. This launcher has
never been exercised end to end -- the coupled OLDIO chain itself is
validated on secofs_ufs at 2914 ranks, and the ATL post products on the
standalone variant. Watch the forecast hour labels on a first run: the
fields worker derives the phase offset from the data, so it handles a
continued or a restarted forecast clock either way, but ATL-coupled's
convention has not been observed yet.
EOM
