#!/bin/bash
################################################################################
# launch_secofs_ufs.sh — cron-driven SECOFS-UFS cycle orchestrator
#
# Runs one full cycle: prep -> nowcast -> forecast -> post, sequentially.
# Each stage is submitted with `qsub`, then this wrapper WAITS for it by
# watching the deterministic STAGE_SUMMARY line the workflow writes to
# $RPTDIR/secofs_ufs_<stage>_00.<jobid>.out. It transparently follows the
# nowcast/forecast blind-retry: a crashed attempt resubmits itself under a
# NEW jobid, and the successful attempt's .out carries `status=PASS` — so
# polling the STAGE_SUMMARY (not a single jobid) is retry-safe. This is why
# `-W depend=afterok:` is NOT used (a crashed leg exits non-zero and the
# replacement jobid is invisible to an afterok dependent).
#
# Usage:   launch_secofs_ufs.sh <CYC>           CYC in {00,06,12,18}
# Cron (UTC; prod launches each cycle at cycle+~1h15m):
#   15 1  * * *  /lfs/h1/nos/estofs/noscrub/<you>/packages/nos-workflow/ush/launch_secofs_ufs.sh 00
#   15 7  * * *  .../ush/launch_secofs_ufs.sh 06
#   15 13 * * *  .../ush/launch_secofs_ufs.sh 12
#   15 19 * * *  .../ush/launch_secofs_ufs.sh 18
#
# Safe test before going live:  DRYRUN=1 ./launch_secofs_ufs.sh 00
# The clone MUST be on a ref that carries the PBS blind-retry (PR #99 /
# develop once merged), else nowcast/forecast won't self-retry.
################################################################################
set -uo pipefail
umask 022
export PATH=/opt/pbs/default/bin:/opt/pbs/bin:/usr/bin:/bin:${PATH:-}

# cron often runs with a bare environment: USER/LOGNAME may be unset, which
# would trip `set -u` on the first ${USER} expansion below. Pin it defensively.
USER=${USER:-${LOGNAME:-$(id -un)}}
export USER LOGNAME=${LOGNAME:-$USER}
export HOME=${HOME:-/u/${USER}}

# ---- config (override via env) ----------------------------------------------
PKG=${PKG:-/lfs/h1/nos/estofs/noscrub/${USER}/packages/nos-workflow}
RPTDIR=${RPTDIR:-/lfs/h1/nos/ptmp/${USER}/rpt/secofs_ufs}
DRYRUN=${DRYRUN:-0}
POLL=${POLL:-60}                       # seconds between status polls
PREP_TIMEOUT=${PREP_TIMEOUT:-5400}     # 90 min  (prep has no retry)
NOWCAST_TIMEOUT=${NOWCAST_TIMEOUT:-10800}  # 3 h   (clean ~30m + retry headroom)
FORECAST_TIMEOUT=${FORECAST_TIMEOUT:-14400} # 4 h  (clean ~60m + retry headroom)
POST_TIMEOUT=${POST_TIMEOUT:-1800}     # 30 min
STAGES=${STAGES:-"prep nowcast forecast post"}   # override e.g. STAGES=post for single-stage recovery

# ---- args -------------------------------------------------------------------
cyc=${1:-}
case "$cyc" in
  00|06|12|18) ;;
  *) echo "FATAL: CYC must be one of 00 06 12 18 (got '${cyc}')" >&2; exit 2 ;;
esac
for _s in $STAGES; do case "$_s" in
  prep|nowcast|forecast|post) ;;
  *) echo "FATAL: STAGES has unknown stage '${_s}' (allowed: prep nowcast forecast post)" >&2; exit 2 ;;
esac; done
PDY=${PDY:-$(date -u +%Y%m%d)}         # cycle is always the same UTC day
TAG="${PDY}t${cyc}z"
mkdir -p "$RPTDIR" 2>/dev/null || { echo "FATAL: cannot mkdir $RPTDIR" >&2; exit 2; }

WLOG="$RPTDIR/launch_secofs_ufs.${TAG}.log"
STATUS_FILE="$RPTDIR/launch_secofs_ufs.${TAG}.status"
log(){ echo "[$(date -u +%FT%TZ)] $*" | tee -a "$WLOG" ; }

# ---- single-instance lock per (PDY,cyc): guards a double cron fire ----------
LOCK="$RPTDIR/.launch_${TAG}.lock"
exec 9>"$LOCK" || { echo "FATAL: cannot open lock $LOCK" >&2; exit 2; }
if ! flock -n 9; then
  log "ABORT: another launch for ${TAG} is already running (lock held). Exiting."
  exit 0
fi

trap 'log "INTERRUPTED (signal) — aborting cycle ${TAG}"; echo FAIL > "$STATUS_FILE"; exit 130' INT TERM

command -v qsub  >/dev/null 2>&1 || { log "FATAL: qsub not on PATH"; echo FAIL >"$STATUS_FILE"; exit 2; }

log "=== SECOFS-UFS launch  PDY=${PDY} cyc=${cyc}  PKG=${PKG}  DRYRUN=${DRYRUN} ==="
echo RUNNING > "$STATUS_FILE"

# ---- per-stage submit + wait ------------------------------------------------
# Completion is read ONLY from $RPTDIR/secofs_ufs_<stage>_00.*.out files that
# are newer than a sentinel touched right before qsub:
#   PASS      : a fresh .out has `STAGE_SUMMARY ... status=PASS`
#   FAIL/parm : a fresh .out has `PARMETIS_RETRY: max retries ( ... exhausted`
#   FAIL/hard : a fresh .out has `status=FAIL` OR a `FATAL: stage=… rc=`
#               one-liner, and NO `PARMETIS_RETRY:` line (terminal non-ParMETIS
#               failure: prep error, missing script/hotstart) — fails fast even
#               when the stage FATALs before emitting STAGE_SUMMARY
#   else      : still running, or mid-retry (a fresh .out shows
#               `PARMETIS_RETRY: ... resubmitting`) — keep polling
submit_and_wait(){
  local stage="$1" timeout="$2"
  local pbs="$PKG/pbs/jnos_${stage}_00.pbs"
  local pfx="secofs_ufs_${stage}_00"
  local sentinel="$RPTDIR/.launch_${TAG}.${stage}.start"
  [ -r "$pbs" ] || { log "FATAL[$stage]: PBS not found/readable: $pbs"; return 3; }

  : > "$sentinel"          # mtime reference; fresh = .out newer than this
  local t0; t0=$(date +%s)

  if [ "$DRYRUN" = "1" ]; then
    log "DRYRUN[$stage]: would qsub -v PDY=${PDY},CYC=${cyc} $pbs"
    return 0
  fi

  local jid
  jid=$(qsub -v "PDY=${PDY},CYC=${cyc}" "$pbs" 2>&1)
  if [ $? -ne 0 ] || [ -z "$jid" ]; then
    log "FATAL[$stage]: qsub failed: ${jid}"
    return 3
  fi
  log "SUBMIT[$stage]: jobid=${jid}  (waiting on STAGE_SUMMARY, timeout=${timeout}s)"

  while :; do
    # newest fresh .out for this stage (handles blind-retry jobid hops)
    local newest
    newest=$(find "$RPTDIR" -maxdepth 1 -name "${pfx}.*.out" -newer "$sentinel" \
               -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)

    if [ -n "$newest" ] && [ -r "$newest" ]; then
      if grep -q "STAGE_SUMMARY .*status=PASS" "$newest" 2>/dev/null; then
        log "PASS[$stage]: $(basename "$newest")  (elapsed $(( $(date +%s)-t0 ))s)"
        return 0
      fi
      if grep -Eq 'PARMETIS_RETRY: max retries \(.*exhausted' "$newest" 2>/dev/null; then
        log "FAIL[$stage]: ParMETIS blind-retry exhausted — $(basename "$newest")"
        return 1
      fi
      if grep -qE 'status=FAIL|FATAL: stage=.* rc=' "$newest" 2>/dev/null \
         && ! grep -q "PARMETIS_RETRY:" "$newest" 2>/dev/null; then
        local why
        why=$(grep -m1 -E 'FATAL:|failed_step=' "$newest" 2>/dev/null | tail -1)
        log "FAIL[$stage]: terminal non-ParMETIS failure — $(basename "$newest") :: ${why}"
        return 1
      fi
      # status=FAIL WITH 'PARMETIS_RETRY: ... resubmitting' => a successor was
      # queued; keep polling for the next attempt's .out.
    fi

    local elapsed=$(( $(date +%s) - t0 ))
    if [ "$elapsed" -ge "$timeout" ]; then
      log "FAIL[$stage]: TIMEOUT after ${elapsed}s (no STAGE_SUMMARY=PASS)"
      return 1
    fi
    # liveness backstop (pre-first-output only): confirm the exact submitted
    # jobid is still known to PBS before declaring the submission lost.
    # `qstat -u $USER` truncates the Name column and a busy queue can hold a
    # job well past the grace, so the old name-grep falsely aborted healthy
    # queued cycles. A transient qstat error must stay inconclusive (keep
    # polling), never a false "lost" — hence the second sample. ($jid is the
    # first submission; on a ParMETIS retry an .out exists so $newest != ""
    # and this block is skipped.)
    if [ -z "$newest" ] && [ "$elapsed" -ge 1800 ]; then
      if ! qstat "$jid" >/dev/null 2>&1; then
        sleep 15
        if ! qstat "$jid" >/dev/null 2>&1; then
          log "FAIL[$stage]: jobid ${jid} unknown to PBS after ${elapsed}s (submission lost)"
          return 1
        fi
      fi
    fi
    sleep "$POLL"
  done
}

# ---- run the chain ----------------------------------------------------------
overall=0
log "stages: ${STAGES}"
for st in $STAGES; do
  case "$st" in
    prep)     to=$PREP_TIMEOUT     ;;
    nowcast)  to=$NOWCAST_TIMEOUT  ;;
    forecast) to=$FORECAST_TIMEOUT ;;
    post)     to=$POST_TIMEOUT     ;;
  esac
  log "--- stage: ${st} ---"
  if ! submit_and_wait "$st" "$to"; then
    log "ABORT cycle ${TAG}: stage '${st}' did not succeed; dependent stages skipped."
    overall=1
    break
  fi
  # advisory sanity check (non-gating: COMOUT path may vary by deploy)
  if [ "$st" = "nowcast" ] && [ "$DRYRUN" != "1" ]; then
    rst="${COMOUT:-/lfs/h1/nos/ptmp/${USER}/com/nos/secofs_ufs.${PDY}}/secofs_ufs.t${cyc}z.${PDY}.rst.nowcast.nc"
    if [ -s "$rst" ]; then log "OK: nowcast restart present ($(du -h "$rst" 2>/dev/null|cut -f1))"
    else log "WARN: STAGE_SUMMARY=PASS but rst not at expected path ($rst) — forecast stage_hotstart will self-verify"; fi
  fi
done

if [ "$overall" -eq 0 ]; then
  log "=== CYCLE ${TAG} COMPLETE — prep+nowcast+forecast+post all PASS ==="
  echo PASS > "$STATUS_FILE"
else
  log "=== CYCLE ${TAG} FAILED — see above ==="
  echo FAIL > "$STATUS_FILE"
fi
exit "$overall"
