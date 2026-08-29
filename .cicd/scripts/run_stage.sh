#!/usr/bin/env bash
# Submit one secofs_ufs Hercules Slurm card and gate on its STAGE_SUMMARY.
# Usage: run_stage.sh <prep|nowcast|forecast|post> <PDY> <CYC>
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"
setup_env

STAGE=${1:?usage: run_stage.sh stage PDY CYC}
PDY=${2:?usage: run_stage.sh stage PDY CYC}
CYC=${3:?usage: run_stage.sh stage PDY CYC}

# COMROOT_STAGED is computed here rather than read from stage_data.sh's
# export: each Jenkins stage runs its own `sh` step, so an export made in
# one script's process never reaches another. RT_DATA_ROOT comes from the
# Jenkins environment.
: "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"
COMROOT_STAGED="${RT_DATA_ROOT}/comin_${PDY}${CYC}"

# Mirrors pbs/launch_secofs_ufs.sh's PREP/NOWCAST/FORECAST/POST_TIMEOUT --
# pinned by ush/python/nos_workflow/tests/test_launcher_timeouts.py.
case "${STAGE}" in
  prep)     TIMEOUT_S=7800  ;;   # walltime 2:00 + 10 min (no retry)
  nowcast)  TIMEOUT_S=10800 ;;   # walltime 1:30, x2 for blind retry
  forecast) TIMEOUT_S=20400 ;;   # walltime 5:30 + 10 min
  post)     TIMEOUT_S=7800  ;;   # walltime 2:00 + headroom
  *) echo "FATAL: unknown stage '${STAGE}' (expected prep|nowcast|forecast|post)"; exit 2 ;;
esac

CARD="${HOMEnos}/slurm/${OFS}/jnos_${STAGE}_00.sh"
[ -r "${CARD}" ] || { echo "FATAL: card not found: ${CARD}"; exit 2; }

RPTDIR=$(card_value "${CARD}" RPTDIR)
mkdir -p "${RPTDIR}"
mkdir -p "${WORKSPACE:-.}/ci_logs"

echo "submitting ${CARD} (PDY=${PDY} CYC=${CYC})"
# CLI --account/--qos override the card's #SBATCH directives (nos-surge) so a
# service account (role-epic) charges an allocation it is authorized for.
ACCT_ARGS=()
[ -n "${SLURM_CI_ACCOUNT:-}" ] && ACCT_ARGS+=(--account="${SLURM_CI_ACCOUNT}")
[ -n "${SLURM_CI_QOS:-}" ] && ACCT_ARGS+=(--qos="${SLURM_CI_QOS}")
SBATCH_OUT=$(sbatch ${ACCT_ARGS[@]+"${ACCT_ARGS[@]}"} --export=ALL,PDY="${PDY}",CYC="${CYC}",COMROOT_STAGED="${COMROOT_STAGED}",NOS_VENV="${VENV_PATH:-}",NOS_PTMP="${NOS_PTMP}" "${CARD}")
echo "${SBATCH_OUT}"
JOBID=$(awk '/Submitted batch job/{print $NF}' <<<"${SBATCH_OUT}")
[ -n "${JOBID}" ] || { echo "FATAL: could not parse jobid from sbatch output"; exit 2; }
echo "jobid=${JOBID}"
echo "${JOBID}" > "${WORKSPACE:-.}/ci_logs/current_jobid"

LOG="${RPTDIR}/${OFS}_${STAGE}_00.${JOBID}.out"
ERRLOG="${RPTDIR}/${OFS}_${STAGE}_00.${JOBID}.err"

t0=$(date +%s)
STATE="UNKNOWN"
while true; do
  STATE=$(sacct -j "${JOBID}" -o State%20 -n 2>/dev/null | head -1 | tr -d ' ')
  case "${STATE}" in
    COMPLETED|FAILED|CANCELLED*|TIMEOUT|NODE_FAIL|PREEMPTED|OUT_OF_MEM*|BOOT_FAIL|DEADLINE|REVOKED) break ;;
  esac
  elapsed=$(( $(date +%s) - t0 ))
  if [ "${elapsed}" -ge "${TIMEOUT_S}" ]; then
    echo "FATAL: stage=${STAGE} rc=timeout -- jobid ${JOBID} still '${STATE}' after ${elapsed}s"
    scancel "${JOBID}" || true
    break
  fi
  sleep 30
done
echo "sacct final state: ${STATE} (elapsed $(( $(date +%s) - t0 ))s)"

if [ -r "${LOG}" ]; then
  cp -p "${LOG}" "${WORKSPACE:-.}/ci_logs/"
else
  echo "WARN: no stdout log at ${LOG}"
fi
[ -r "${ERRLOG}" ] && cp -p "${ERRLOG}" "${WORKSPACE:-.}/ci_logs/" || true

# Slurm's own epilogue (#SBATCH --output=%x.%j.out, written to the
# submission directory) is populated only on a kill the job never lived
# long enough to redirect itself (TIME LIMIT, node failure). It shares a
# basename with the real per-stage log above, so copy it under a distinct
# name rather than clobbering that copy.
for f in "${WORKSPACE:-.}"/*"${JOBID}"*.out "${WORKSPACE:-.}/slurm-${JOBID}.out"; do
  [ -r "${f}" ] || continue
  cp -p "${f}" "${WORKSPACE:-.}/ci_logs/slurm_epilogue.$(basename "${f}")"
done

if [ -r "${LOG}" ] && grep -q "STAGE_SUMMARY stage=${STAGE} ofs=${OFS} status=PASS" "${LOG}"; then
  echo "PASS[${STAGE}]: ${LOG}"
  exit 0
fi

echo "FAIL[${STAGE}]: no STAGE_SUMMARY PASS in ${LOG}"
[ -r "${LOG}" ] && tail -60 "${LOG}"
exit 1
