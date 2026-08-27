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

case "${STAGE}" in
  prep)     TIMEOUT_S=3600  ;;   # 60m  (measured 27m)
  nowcast)  TIMEOUT_S=2700  ;;   # 45m  (measured 16m)
  forecast) TIMEOUT_S=14400 ;;   # 240m (48h segment, ~15min/6h)
  post)     TIMEOUT_S=3600  ;;   # 60m
  *) echo "FATAL: unknown stage '${STAGE}' (expected prep|nowcast|forecast|post)"; exit 2 ;;
esac

CARD="${HOMEnos}/slurm/${OFS}/jnos_${STAGE}_00.sh"
[ -r "${CARD}" ] || { echo "FATAL: card not found: ${CARD}"; exit 2; }

RPTDIR=$(card_value "${CARD}" RPTDIR)
mkdir -p "${RPTDIR}"

echo "submitting ${CARD} (PDY=${PDY} CYC=${CYC})"
SBATCH_OUT=$(sbatch --export=ALL,PDY="${PDY}",CYC="${CYC}" "${CARD}")
echo "${SBATCH_OUT}"
JOBID=$(echo "${SBATCH_OUT}" | grep -oE '[0-9]+' | tail -1)
[ -n "${JOBID}" ] || { echo "FATAL: could not parse jobid from sbatch output"; exit 2; }
echo "jobid=${JOBID}"

LOG="${RPTDIR}/${OFS}_${STAGE}_00.${JOBID}.out"
ERRLOG="${RPTDIR}/${OFS}_${STAGE}_00.${JOBID}.err"

t0=$(date +%s)
STATE="UNKNOWN"
while true; do
  STATE=$(sacct -j "${JOBID}" -o State -n 2>/dev/null | head -1 | tr -d ' ')
  case "${STATE}" in
    COMPLETED|FAILED|CANCELLED*|TIMEOUT) break ;;
  esac
  elapsed=$(( $(date +%s) - t0 ))
  if [ "${elapsed}" -ge "${TIMEOUT_S}" ]; then
    echo "FATAL: stage=${STAGE} rc=timeout -- jobid ${JOBID} still '${STATE}' after ${elapsed}s"
    break
  fi
  sleep 30
done
echo "sacct final state: ${STATE} (elapsed $(( $(date +%s) - t0 ))s)"

mkdir -p "${WORKSPACE:-.}/ci_logs"
if [ -r "${LOG}" ]; then
  cp -p "${LOG}" "${WORKSPACE:-.}/ci_logs/"
else
  echo "WARN: no stdout log at ${LOG}"
fi
[ -r "${ERRLOG}" ] && cp -p "${ERRLOG}" "${WORKSPACE:-.}/ci_logs/" || true

if [ -r "${LOG}" ] && grep -q "STAGE_SUMMARY stage=${STAGE} ofs=${OFS} status=PASS" "${LOG}"; then
  echo "PASS[${STAGE}]: ${LOG}"
  exit 0
fi

echo "FAIL[${STAGE}]: no STAGE_SUMMARY PASS in ${LOG}"
[ -r "${LOG}" ] && tail -60 "${LOG}"
exit 1
