#!/bin/bash
################################################################################
# clean_work.sh — prune PBS work dirs, keeping only the newest prep/nc/fc/post
# per run (= the last cycle). Dirs whose job PBS still tracks (queued/running/
# held) are never removed, so it is safe to run at any point in a cycle.
#
# Expected layout (jobid = ${job}.${PBS_JOBID}, see pbs/jnos_*_00.pbs):
#   $WORK/<run>/<run>_<stage>_<cyc>_<envir>.<jobnum>.<server>
#   e.g. work/secofs_ufs/secofs_ufs_fc_00_dev.138423800.dbqs01
# Ranking is by PBS job number (monotonic), not mtime.
#
# Usage:  clean_work.sh [run ...]      default runs: secofs_ufs secofs_ufs_ww3
#         DRYRUN=1 clean_work.sh       list what would go, delete nothing
#         KEEP=2   clean_work.sh       keep the two newest per stage
# Cron (UTC), 10 min before each SECOFS-UFS launch:
#   05 1,7,13,19 * * *  /lfs/h1/nos/estofs/noscrub/<you>/packages/nos-workflow/pbs/clean_work.sh >> /lfs/h1/nos/ptmp/<you>/rpt/clean_work.log 2>&1
################################################################################
set -uo pipefail
export PATH=/opt/pbs/default/bin:/opt/pbs/bin:/usr/bin:/bin:${PATH:-}
USER=${USER:-${LOGNAME:-$(id -un)}}

WORK=${WORK:-/lfs/h1/nos/ptmp/${USER}/work}
KEEP=${KEEP:-1}
DRYRUN=${DRYRUN:-0}
STAGES="prep nc fc post"
RUNS=${*:-secofs_ufs secofs_ufs_ww3}

# Job numbers PBS still tracks: their dirs are off-limits. Fail closed if the
# scheduler cannot be queried rather than risk deleting under a live job.
command -v qselect >/dev/null 2>&1 || { echo "FATAL: qselect not on PATH"; exit 2; }
active=$(qselect -u "$USER" 2>&1) || { echo "FATAL: qselect failed: $active"; exit 2; }
active=" $(echo "$active" | cut -d. -f1 | tr '\n' ' ') "

echo "[$(date -u +%FT%TZ)] clean_work KEEP=$KEEP DRYRUN=$DRYRUN runs='$RUNS' active_jobs='${active}'"
for run in $RUNS; do
  cd "$WORK/$run" 2>/dev/null || { echo "skip: no $WORK/$run"; continue; }
  for stage in $STAGES; do
    ls -d "${run}_${stage}_"[0-9][0-9]_*.[0-9]*.* 2>/dev/null \
      | sort -t. -k2,2nr \
      | tail -n +$((KEEP + 1)) \
      | while read -r d; do
          jobnum=${d#*.}; jobnum=${jobnum%%.*}
          case "$active" in *" $jobnum "*) echo "keep (job $jobnum still in PBS): $run/$d"; continue ;; esac
          echo "rm: $run/$d"
          [ "$DRYRUN" = 1 ] || rm -rf -- "$d"
        done
  done
done
