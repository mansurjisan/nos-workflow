#=============================================================================
# nos_run_stage.h - run one nos-workflow J-job and gate on its STAGE_SUMMARY.
#
# Included by every ecf/scripts/jnos_<stage>.ecf after the environment and
# modules are set. Expects NOS_STAGE (prep|nowcast|forecast|post) and NOS_JJOB
# (JNOS_PREP, ...) to be set by the including script.
#
# The J-job exit code is not a reliable success signal (JNOS_* can end on
# postmsg/date after a model crash; see pbs/jnos_nowcast_00.pbs), so success is
# decided by the workflow's own contract line:
#
#   STAGE_SUMMARY stage=<stage> ofs=<ofs> status=PASS runtime_s=<s>
#
# A non-zero exit OR a missing PASS line aborts the task. ecFlow then requeues
# it up to ECF_TRIES times, which replaces the qsub blind-retry used by the
# development PBS cards (ParMETIS partition crash, nos-workflow #98).
#=============================================================================

_stage_log=$(mktemp "${TMPDIR:-/tmp}/nos_${OFS}_${NOS_STAGE}_${cyc}.XXXXXX.log")

set +e
"${HOMEnos}/jobs/${NOS_JJOB}" 2>&1 | tee "${_stage_log}"
_rc=${PIPESTATUS[0]}
set -e

if [ "${_rc}" -ne 0 ]; then
  ecflow_client --msg="***JOB ${ECF_NAME} ${NOS_JJOB} exited rc=${_rc} ***"
  rm -f "${_stage_log}"
  exit "${_rc}"          # head.h trap reports the abort
fi

if ! grep -q "STAGE_SUMMARY stage=${NOS_STAGE} ofs=${OFS} status=PASS" "${_stage_log}"; then
  ecflow_client --msg="***JOB ${ECF_NAME} ${NOS_JJOB} ended without STAGE_SUMMARY status=PASS ***"
  rm -f "${_stage_log}"
  exit 1
fi

grep "STAGE_SUMMARY stage=${NOS_STAGE}" "${_stage_log}" | tail -1 \
  | xargs -I{} ecflow_client --label=summary "{}" || true
rm -f "${_stage_log}"
