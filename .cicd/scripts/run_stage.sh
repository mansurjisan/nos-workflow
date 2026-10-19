#!/usr/bin/env bash
# Submit one SECOFS, STOFS-3D-ATL or STOFS-2D-Global Hercules Slurm card and gate on its STAGE_SUMMARY. MJ (10/15/26)
# Usage: run_stage.sh <prep|nowcast|forecast|post> <PDY> <CYC>
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"
setup_env

STAGE=${1:?usage: run_stage.sh stage PDY CYC}
PDY=${2:?usage: run_stage.sh stage PDY CYC}
CYC=${3:?usage: run_stage.sh stage PDY CYC}

# Computed here rather than read from stage_data.sh's export: each Jenkins stage runs its own `sh` step, so an export made in one script's process never reaches another.
: "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"
COMROOT_STAGED="${RT_DATA_ROOT}/comin_${PDY}${CYC}"

# Mirrors pbs/launch_secofs_ufs.sh's PREP/NOWCAST/FORECAST/POST_TIMEOUT -- pinned by ush/python/nos_workflow/tests/test_launcher_timeouts.py.
case "${STAGE}" in
  prep)     TIMEOUT_S=7800  ;;   # walltime 2:00 + 10 min (no retry)
  nowcast)  TIMEOUT_S=10800 ;;   # walltime 1:30, x2 for blind retry
  forecast) TIMEOUT_S=20400 ;;   # walltime 5:30 + 10 min
  post)     TIMEOUT_S=7800  ;;   # walltime 2:00 + headroom
  *) echo "FATAL: unknown stage '${STAGE}' (expected prep|nowcast|forecast|post)"; exit 2 ;;
esac

# The STOFS-3D-ATL variants share this template; stofs_3d_atl.sh card-env supplies what differs (extra exports, the card's RPTDIR default, RUN). MJ (10/15/26)
ATL_EXPORTS=""; ATL_LOGPFX=""; ATL_RPTDIR=""; ATL_CLEAN=0; STAGE_CARD=""; STAGE_SBATCH=""   # nothing inherited may leak into the SECOFS path. MJ (10/15/26)
GATE_OFS="${OFS}"
case "${OFS}" in
  stofs_3d_atl_ufs_standalone|stofs_3d_atl_ufs)
    # Walltime of the ATL card + 30 min of headroom (Slurm's --time ends a long run first); the coupled post card is 4 h. MJ (10/19/26)
    case "${STAGE}" in
      prep)     TIMEOUT_S=12600 ;;
      nowcast)  TIMEOUT_S=10800 ;;
      forecast) TIMEOUT_S=23400 ;;
      post)     TIMEOUT_S=9000; [ "${OFS}" = stofs_3d_atl_ufs ] && TIMEOUT_S=16200 ;;
    esac
    _env=$(PDY="${PDY}" CYC="${CYC}" bash "${SCRIPT_DIR}/stofs_3d_atl.sh" card-env "${STAGE}") || exit 2   # eval of a command substitution would hide its failure. MJ (10/15/26)
    eval "${_env}"
    COMROOT_STAGED="${ATL_COMIN}"
    GATE_OFS="${ATL_RUN}"
    ATL_CLEAN=1
    ;;
  stofs_2d_glo)
    # The same hook for STOFS-2D-Global: card-env also gives the card (post runs on the prep card), the job's sbatch flags and walltime, and the timeout; the jobs run
    # with KEEPDATA=NO, so there is no run directory to clean. MJ (10/15/26)
    _env=$(PDY="${PDY}" CYC="${CYC}" bash "${SCRIPT_DIR}/stofs_2d_glo.sh" card-env "${STAGE}") || exit 2
    eval "${_env}"
    COMROOT_STAGED="${ATL_COMIN}"
    GATE_OFS="${ATL_RUN}"
    ;;
esac

CARD="${STAGE_CARD:-${HOMEnos}/slurm/${OFS}/jnos_${STAGE}_00.sh}"
[ -r "${CARD}" ] || { echo "FATAL: card not found: ${CARD}"; exit 2; }

if [ -n "${ATL_EXPORTS}" ]; then RPTDIR="${ATL_RPTDIR}"; else RPTDIR=$(card_value "${CARD}" RPTDIR); fi
mkdir -p "${RPTDIR}"
mkdir -p "${WORKSPACE:-.}/ci_logs"

echo "submitting ${CARD} (PDY=${PDY} CYC=${CYC})"
# CLI --account/--qos override the card's #SBATCH directives so a service account (role-epic) charges an allocation it is authorized for.
ACCT_ARGS=()
[ -n "${SLURM_CI_ACCOUNT:-}" ] && ACCT_ARGS+=(--account="${SLURM_CI_ACCOUNT}")
[ -n "${SLURM_CI_QOS:-}" ] && ACCT_ARGS+=(--qos="${SLURM_CI_QOS}")
SBATCH_OUT=$(sbatch ${ACCT_ARGS[@]+"${ACCT_ARGS[@]}"} ${STAGE_SBATCH} --export=ALL,PDY="${PDY}",CYC="${CYC}",COMROOT_STAGED="${COMROOT_STAGED}",NOS_VENV="${VENV_PATH:-}",NOS_PTMP="${NOS_PTMP}"${ATL_EXPORTS:+,"${ATL_EXPORTS}"} "${CARD}")
echo "${SBATCH_OUT}"
JOBID=$(awk '/Submitted batch job/{print $NF}' <<<"${SBATCH_OUT}")
[ -n "${JOBID}" ] || { echo "FATAL: could not parse jobid from sbatch output"; exit 2; }
echo "jobid=${JOBID}"
# "<build> <jobid>": the Jenkinsfile post step cancels only a job its own build submitted. MJ (10/16/26)
echo "${BUILD_NUMBER:-manual} ${JOBID}" > "${WORKSPACE:-.}/ci_logs/current_jobid"

LOGPFX="${ATL_LOGPFX:-${RPTDIR}/${OFS}_${STAGE}_00}"
LOG="${LOGPFX}.${JOBID}.out"
ERRLOG="${LOGPFX}.${JOBID}.err"

t0=$(date +%s)
STATE="UNKNOWN"
while true; do
  STATE=$(sacct -j "${JOBID}" -o State%20 -n 2>/dev/null | head -1 | tr -d ' ')
  case "${STATE}" in
    COMPLETED|FAILED|CANCELLED*|TIMEOUT|NODE_FAIL|PREEMPTED|OUT_OF_MEM*|BOOT_FAIL|DEADLINE|REVOKED) break ;;
    # The limit is run time: the clock starts when the job leaves the queue, so a long Hercules queue wait cannot use it up (build #24); the 16 h build timeout
    # bounds the wait, and a job that can never start (held, over a per-job or partition limit, bad account or QOS) fails at once. MJ (10/19/26)
    PENDING)
      WHY=$(squeue -h -j "${JOBID}" -o %r 2>/dev/null || true)
      case "${WHY}" in
        *[Hh]eld*|*PerJob*|Partition*Limit|Invalid*) echo "FATAL: stage=${STAGE} rc=unstartable -- jobid ${JOBID} pending (${WHY})"; scancel "${JOBID}" || true; break ;;
      esac
      t0=$(date +%s) ;;
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

# Slurm's own epilogue shares a basename with the real per-stage log above, so copy it under a distinct name rather than clobbering that copy.
for f in "${WORKSPACE:-.}"/*"${JOBID}"*.out "${WORKSPACE:-.}"/*"${JOBID}"*.err "${WORKSPACE:-.}/slurm-${JOBID}.out"; do
  [ -r "${f}" ] || continue
  cp -p "${f}" "${WORKSPACE:-.}/ci_logs/slurm_epilogue.$(basename "${f}")"
done

if [ -r "${LOG}" ] && grep -q "STAGE_SUMMARY stage=${STAGE} ofs=${GATE_OFS} status=PASS" "${LOG}"; then
  # A passing ATL stage no longer needs its run directory (~150 GB a cycle); a failed one is kept for debugging. MJ (10/15/26)
  [ "${ATL_CLEAN}" != 1 ] || bash "${SCRIPT_DIR}/stofs_3d_atl.sh" clean-job "${JOBID}" || echo "WARN: could not clean the run directory of job ${JOBID}"
  echo "PASS[${STAGE}]: ${LOG}"
  exit 0
fi

echo "FAIL[${STAGE}]: no STAGE_SUMMARY PASS in ${LOG}"
[ -r "${LOG}" ] && tail -60 "${LOG}"
exit 1
