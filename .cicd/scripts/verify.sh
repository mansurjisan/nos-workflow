#!/usr/bin/env bash
# Verify stage: confirm every stage's STAGE_SUMMARY PASS landed in the
# collected logs, and that $COMOUT holds non-trivial output. Prints a
# one-screen cycle report.
set -uo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

: "${PDY:?PDY not set}"
: "${CYC:?CYC not set}"
LOGDIR="${WORKSPACE:-.}/ci_logs"

NOWCAST_CARD="${HOMEnos}/slurm/${OFS}/jnos_nowcast_00.sh"
COMROOT=$(card_value "${NOWCAST_CARD}" COMROOT)
COMOUT="${COMROOT}/nos/${OFS}.${PDY}"

echo "=== ${OFS} cycle report: PDY=${PDY} CYC=${CYC} ==="
fail=0

for stage in prep nowcast forecast post; do
  log=$(ls -t "${LOGDIR}/${OFS}_${stage}_00."*.out 2>/dev/null | head -1)
  if [ -n "${log}" ] && grep -q "STAGE_SUMMARY stage=${stage} ofs=${OFS} status=PASS" "${log}"; then
    echo "  ${stage}: PASS ($(basename "${log}"))"
  else
    echo "  ${stage}: FAIL (no STAGE_SUMMARY PASS in collected log)"
    fail=1
  fi
done

RESTART_DIR="${COMOUT}/${OFS}.t${CYC}z.restart_outputs"
if [ -d "${RESTART_DIR}" ] && find "${RESTART_DIR}" -type f -size +1M | grep -q .; then
  echo "  output: OK (${RESTART_DIR}, $(du -sh "${RESTART_DIR}" 2>/dev/null | cut -f1))"
else
  echo "  output: FAIL (${RESTART_DIR} missing, empty, or no file >1MB)"
  fail=1
fi

echo "  COMOUT: ${COMOUT}"
if [ "${fail}" -eq 0 ]; then
  echo "=== cycle PASS ==="
else
  echo "=== cycle FAIL ==="
fi
exit "${fail}"
