# nos_run_stage.h - run the J-job of ${NOS_STAGE} and complete only on its STAGE_SUMMARY.
# The JNOS_* scripts exit 0 even when the stage fails, so the summary line is the gate (as in the PBS cards).
# The full output stays in the job output; only the summary lines are kept for the check. MJ (10/20/26)
_sum=$(mktemp "${TMPDIR:-/tmp}/stage_summary.XXXXXX")
set +e
${HOMEnos}/jobs/JNOS_${NOS_STAGE^^} 2>&1 | awk -v f="${_sum}" '{ print; fflush() } /STAGE_SUMMARY /{ print >> f }'
_rc=${PIPESTATUS[0]}
set -e

if [ "${_rc}" -ne 0 ]; then
  ecflow_client --msg="***JOB ${ECF_NAME} JNOS_${NOS_STAGE^^} exited rc=${_rc} ***"
  rm -f "${_sum}"
  exit "${_rc}"
fi
if ! grep -q "STAGE_SUMMARY stage=${NOS_STAGE} ofs=${OFS} status=PASS" "${_sum}"; then
  ecflow_client --msg="***JOB ${ECF_NAME} ended without STAGE_SUMMARY stage=${NOS_STAGE} ofs=${OFS} status=PASS ***"
  rm -f "${_sum}"
  exit 1
fi
_line=$(grep "STAGE_SUMMARY stage=${NOS_STAGE} ofs=${OFS} status=PASS" "${_sum}" | tail -1)
ecflow_client --label=summary "${_line#*STAGE_SUMMARY }" || true
rm -f "${_sum}"
