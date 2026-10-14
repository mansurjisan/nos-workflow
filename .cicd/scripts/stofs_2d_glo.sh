#!/usr/bin/env bash
# STOFS-2D-Global stages of the Hercules Jenkins pipeline (OFS=stofs_2d_glo; manual builds only). MJ (10/13/26)
#   stofs_2d_glo.sh stage    Stage Data (called by stage_data.sh): frozen = copy the dataset for PDY/CYC from the RT root into a clean
#                            CI COMROOT_2DGLO; live = tools/hercules_2d_glo_stage_forcing.sh on this login/front-end node, which is
#                            where the SECOFS live staging (stage_comin.py) runs too, since compute nodes have no internet
#   stofs_2d_glo.sh run      Run 2D-GLO: slurm/stofs_2d_glo/launch_stofs_2d_glo.sh with the CI account/qos, then wait for the chain
#   stofs_2d_glo.sh verify   Verify 2D-GLO: compare_2dglo.py against the dataset's reference / ops products
#   stofs_2d_glo.sh seed <PDY> <CYC> [cold]   one-time, by hand: build the frozen dataset from a finished run (see below)
# Env (Jenkinsfile): PDY CYC LEVEL DATA_MODE RT_DATA_ROOT NOS_PTMP PACKAGEROOT VENV_PATH SLURM_CI_ACCOUNT SLURM_CI_QOS; optional
# COMROOT_2DGLO (default $NOS_PTMP/$LOGNAME/com_2dglo_ci), WAIT_S POLL_S (poll limit and interval, seconds), CMP_TOL (default 1e-3),
# OPS_WARN_MM (default 500). MJ (10/13/26)
#
# LEVEL   launcher                  jobs  verify
#   smoke  COLD=0 STAGES=ncst         2    rerun/stofs_2d_glo_{tide,surf}.61.nc against the reference (bitwise, else <= CMP_TOL)
#   cycle  COLD=0                     6    the same plus points.*.nc against the reference; ops comparison reported
#   full   COLD=1                     8    points.{htp,cwl.noanomaly,swl}.nc against the ops products, reported only
# smoke and cycle continue from the previous cycle's hotstart/restart, so they use the 06z-type dataset; full cold-starts and uses the
# 00z-type dataset. A job in FAILED, CANCELLED, TIMEOUT or any other bad state, or without STAGE_SUMMARY status=PASS, fails the run
# stage. DATA_MODE=live continues from the state already in COMROOT_2DGLO (LEVEL=full first, then cycle at +6 h) and does not clear it;
# frozen clears it and starts from the dataset. MJ (10/13/26)
#
# Dataset ${RT_DATA_ROOT}/stofs_2d_glo/<PDY><CYC>/ (bootstrap.sh copies it from ${SEED_RT}/stofs_2d_glo/<PDY><CYC>/ in frozen mode):
#   .seeded_ok
#   input/nos/stofs_2d_glo/{stofs_2d_glo_nod_equi,stofs_2d_glo_4064.tar,stofs_2d_glo_4064.tar.json}          COMGES (not in a cold dataset)
#   input/nos/stofs_2d_glo.<PDY-6h>/stofs_2d_glo.t<HH-6h>z.{hotstart,restart}                              previous cycle (not in a cold dataset)
#   input/nos/stofs_2d_glo.<PDY>/<CYC>/rerun/stofs_2d_glo_{ncst,fcst}.{221,222,225}.nc                      staged ops forcing
#   ref/nos/stofs_2d_glo.<PDY>/<CYC>/rerun/stofs_2d_glo_{tide,surf}.61.nc and ref/nos/stofs_2d_glo.<PDY>/stofs_2d_glo.t<CYC>z.points.*.nc
#   ops/stofs_2d_glo.t<CYC>z.points.{htp,cwl.noanomaly,swl}.nc                                              ops products (optional)
# MJ (10/13/26)
#
# One-time seeding on Hercules, from the finished runs of 2026-10-12 (00z cold start, 06z COLD=0), as the user who owns them:
#   export COMROOT_2DGLO=/work2/noaa/nos-surge/mjisan/nos-run/ptmp/mjisan/com_2dglo_ops
#   bash .cicd/scripts/stofs_2d_glo.sh seed 20261012 00 cold
#   bash .cicd/scripts/stofs_2d_glo.sh seed 20261012 06
# Optional env: SEED_RT (destination root, default /work2/noaa/nos-surge/mjisan/nos-workflow-rt, the Jenkins SEED_RT default), OPS_DIR
# (the ops reference files hercules_2d_glo_stage_forcing.sh downloaded, default $NOS_PTMP/$LOGNAME/ops_s3/<PDY><CYC>/products),
# NOS_PTMP, FORCE=1 (replace an existing dataset). The destination is made world-readable for the CI account; the two parent
# directories need chmod o+x (printed). MJ (10/13/26)
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEFAULT_PTMP=/work2/noaa/nos-surge/mjisan/nos-run/ptmp

usage() { sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "${BASH_SOURCE[0]}"; }

# Paths under a COMROOT_2DGLO-shaped tree, one per line. $1 = 1 to include the cold-start products and previous chain files, then the
# forcing segments wanted. MJ (10/13/26)
input_files() {
  local with_state=$1 seg n kind
  shift
  if [ "${with_state}" = 1 ]; then
    for kind in stofs_2d_glo_nod_equi stofs_2d_glo_4064.tar stofs_2d_glo_4064.tar.json; do echo "nos/stofs_2d_glo/${kind}"; done
    for kind in hotstart restart; do echo "nos/stofs_2d_glo.${PREV:0:8}/stofs_2d_glo.t${PREV:8:2}z.${kind}"; done
  fi
  for seg in "$@"; do
    for n in 221 222 225; do echo "nos/stofs_2d_glo.${PDY}/${CYC}/rerun/stofs_2d_glo_${seg}.${n}.nc"; done
  done
}

check_cycle_args() {
  case "${PDY:-}" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;; *) echo "FATAL: PDY must be YYYYMMDD (got '${PDY:-}')" >&2; exit 2 ;; esac
  case "${CYC:-}" in 00|06|12|18) ;; *) echo "FATAL: CYC must be 00, 06, 12 or 18 (got '${CYC:-}')" >&2; exit 2 ;; esac
  PREV=$(date -u -d "${PDY} ${CYC}:00 6 hours ago" +%Y%m%d%H)
}

# Everything the stage, run and verify commands share. MJ (10/13/26)
level_setup() {
  check_cycle_args
  LEVEL=${LEVEL:-smoke}
  case "${LEVEL}" in
    smoke) COLD=0; STAGES=ncst; EXPECT=2; WAIT_DEFAULT=14400 ;;
    cycle) COLD=0; STAGES=all;  EXPECT=6; WAIT_DEFAULT=28800 ;;
    full)  COLD=1; STAGES=all;  EXPECT=8; WAIT_DEFAULT=43200 ;;
    *) echo "FATAL: LEVEL must be smoke, cycle or full (got '${LEVEL}')" >&2; exit 2 ;;
  esac
  DATA_MODE=${DATA_MODE:-frozen}
  : "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"
  COMROOT_2DGLO=${COMROOT_2DGLO:-${NOS_PTMP}/${LOGNAME}/com_2dglo_ci}
  DS="${RT_DATA_ROOT}/stofs_2d_glo/${PDY}${CYC}"
  JOBS="${NOS_PTMP}/${LOGNAME}/slurm_2dglo/jobs_${PDY}${CYC}.txt"
  OUTDAY="${COMROOT_2DGLO}/nos/stofs_2d_glo.${PDY}"
  LOGDIR="${WORKSPACE:-.}/ci_logs"
  export NOS_PTMP COMROOT_2DGLO
}

reset_comroot() {
  case "${COMROOT_2DGLO}" in
    *..*) echo "FATAL: refusing to clear ${COMROOT_2DGLO} (contains ..)" >&2; exit 1 ;;
    "${NOS_PTMP}"/?*) ;;
    *) echo "FATAL: refusing to clear ${COMROOT_2DGLO}: it is not under NOS_PTMP (${NOS_PTMP})" >&2; exit 1 ;;
  esac
  rm -rf "${COMROOT_2DGLO}"
  mkdir -p "${COMROOT_2DGLO}"
}

cmd_stage() {
  level_setup
  case "${DATA_MODE}" in
    frozen)
      [ -f "${DS}/.seeded_ok" ] || {
        echo "FATAL: no ${DS}/.seeded_ok -- dataset missing or an interrupted copy (Bootstrap copies it from SEED_RT)."
        echo "Seed it once: bash .cicd/scripts/stofs_2d_glo.sh seed ${PDY} ${CYC}$([ "${LEVEL}" = full ] && echo ' cold') (see the script header), or set DATA_MODE=live."
        exit 1
      }
      local segs=(ncst fcst) with_state=1 f miss=0
      [ "${LEVEL}" != smoke ] || segs=(ncst)
      [ "${LEVEL}" != full ] || with_state=0
      for f in $(input_files "${with_state}" "${segs[@]}"); do
        [ -s "${DS}/input/${f}" ] || { echo "MISSING: ${DS}/input/${f}" >&2; miss=1; }
      done
      [ "${miss}" = 0 ] || { echo "FATAL: the dataset lacks what LEVEL=${LEVEL} needs (a cold dataset has no COMGES/previous-cycle files; use the dataset of a COLD=0 cycle)"; exit 1; }
      reset_comroot
      echo "staging ${DS}/input -> ${COMROOT_2DGLO} (LEVEL=${LEVEL})"
      input_files "${with_state}" "${segs[@]}" | rsync -a --files-from=- "${DS}/input/" "${COMROOT_2DGLO}/"
      du -sh "${COMROOT_2DGLO}"
      ;;
    live)
      mkdir -p "${COMROOT_2DGLO}"
      local rc=0
      echo "staging the ops forcing for ${PDY}${CYC} into ${COMROOT_2DGLO} (login node, no clearing: the chain state stays)"
      bash "${HOMEnos}/tools/hercules_2d_glo_stage_forcing.sh" "${PDY}" "${CYC}" || rc=$?
      case "${rc}" in
        0) ;;
        3) echo "WARN: the ops reference station files were not downloaded; Verify skips the ops comparison" ;;
        *) echo "FATAL: hercules_2d_glo_stage_forcing.sh failed (rc=${rc})"; exit 1 ;;
      esac
      [ "${LEVEL}" = full ] || echo "NOTE: LEVEL=${LEVEL} continues from the chain files already in ${COMROOT_2DGLO}; the launcher preflight lists what is missing"
      ;;
    *) echo "FATAL: unknown DATA_MODE '${DATA_MODE}' (expected frozen|live)"; exit 1 ;;
  esac
  echo "stage_data PASS"
}

# sacct states that end a job unsuccessfully; --kill-on-invalid-dep turns the jobs behind a failure into CANCELLED. MJ (10/13/26)
BAD_STATES='FAILED|CANCELLED|TIMEOUT|NODE_FAIL|OUT_OF_MEMORY|BOOT_FAIL|DEADLINE|PREEMPTED|REVOKED|SPECIAL_EXIT'

cmd_run() {
  level_setup
  mkdir -p "${LOGDIR}"
  local wait_s=${WAIT_S:-${WAIT_DEFAULT}} poll_s=${POLL_S:-60}
  export NOS_VENV="${VENV_PATH:-}" ADCIRC_EXEC_DIR="${PACKAGEROOT}/adcirc_v56.1.0_exec"
  export COLD STAGES KEEPDATA=NO SERIAL=0 SUBMIT_GFS=0
  echo "launching LEVEL=${LEVEL} (COLD=${COLD} STAGES=${STAGES}) for ${PDY}${CYC}, account=${SLURM_CI_ACCOUNT:-card} qos=${SLURM_CI_QOS:-card}"
  bash "${HOMEnos}/slurm/stofs_2d_glo/launch_stofs_2d_glo.sh" "${PDY}" "${CYC}"

  [ -s "${JOBS}" ] || { echo "FATAL: the launcher left no job list at ${JOBS}"; exit 1; }
  local n idlist
  n=$(awk 'NF>=2' "${JOBS}" | wc -l)
  [ "${n}" -eq "${EXPECT}" ] || { echo "FATAL: ${n} jobs queued, LEVEL=${LEVEL} expects ${EXPECT} (${JOBS})"; exit 1; }
  idlist=$(awk 'NF>=2{printf "%s%s", sep, $2; sep=","}' "${JOBS}")
  # post/unsuccessful in the Jenkinsfile scancels whatever is in this file, space separated. MJ (10/13/26)
  awk 'NF>=2{printf "%s ", $2}' "${JOBS}" > "${LOGDIR}/current_jobid"

  local t0 snap verdict last="" elapsed
  t0=$(date +%s)
  while true; do
    snap=$(sacct -j "${idlist}" -X -n -P -o JobID,State 2>/dev/null || true)
    verdict=$(awk -F'|' -v n="${EXPECT}" -v bad="^(${BAD_STATES})" '
      NF >= 2 { st = $2; sub(/ .*/, "", st)
                if (st ~ bad) badlist = badlist " " $1 ":" st; else if (st == "COMPLETED") done++ }
      END { if (badlist != "") print "BAD" badlist; else if (done == n) print "DONE"; else print "WAIT" }' <<<"${snap}")
    if [ "${snap}" != "${last}" ]; then
      echo "[$(date -u +%T)] $(awk -F'|' 'NF>=2{printf "%s=%s ", $1, $2}' <<<"${snap}")"
      last="${snap}"
    fi
    case "${verdict}" in DONE|BAD*) break ;; esac
    elapsed=$(( $(date +%s) - t0 ))
    if [ "${elapsed}" -ge "${wait_s}" ]; then
      verdict="TIMEOUT after ${elapsed}s"
      break
    fi
    sleep "${poll_s}"
  done
  echo "chain verdict: ${verdict} (elapsed $(( $(date +%s) - t0 ))s)"
  case "${verdict}" in DONE) ;; *) scancel ${idlist//,/ } 2>/dev/null || true ;; esac

  local rpt="${NOS_PTMP}/${LOGNAME}/rpt/stofs_2d_glo" id f
  for id in ${idlist//,/ }; do
    for f in "${rpt}"/*."${id}".out "${rpt}"/*."${id}".err; do
      [ -r "${f}" ] && cp -p "${f}" "${LOGDIR}/" || true
    done
  done
  local table bad
  table=$(bash "${HOMEnos}/slurm/stofs_2d_glo/status_stofs_2d_glo.sh" "${JOBS}")
  echo "${table}"
  bad=$(awk 'NR>1 && ($3 != "COMPLETED" || $0 !~ /status=PASS/) {printf "%s ", $1}' <<<"${table}")
  if [ "${verdict}" != DONE ] || [ -n "${bad}" ]; then
    echo "FAIL[run]: LEVEL=${LEVEL} ${verdict}; not COMPLETED with status=PASS: ${bad:-none listed}"
    exit 1
  fi
  echo "PASS[run]: LEVEL=${LEVEL}, ${EXPECT} jobs COMPLETED with status=PASS"
}

cmd_verify() {
  level_setup
  setup_env
  mkdir -p "${LOGDIR}"
  local rc=0 ops_dir cmp="${SCRIPT_DIR}/compare_2dglo.py"
  ops_dir="${DS}/ops"
  [ "${DATA_MODE}" != live ] || ops_dir="${OPS_WORK:-${NOS_PTMP}/${LOGNAME}/ops_s3/${PDY}${CYC}}/products"
  # The group runs in the pipeline's subshell, so it hands its verdict back through its exit status. MJ (10/13/26)
  {
    grc=0
    if [ "${LEVEL}" != full ]; then
      if [ -d "${DS}/ref" ]; then
        python3 "${cmp}" regress --ref "${DS}/ref" --out "${COMROOT_2DGLO}" --pdy "${PDY}" --cyc "${CYC}" --level "${LEVEL}" --tol "${CMP_TOL:-1e-3}" || grc=1
      elif [ "${DATA_MODE}" = frozen ]; then
        echo "FAIL: ${DS}/ref is missing; the frozen dataset has no reference outputs"
        grc=1
      else
        echo "no frozen reference for ${PDY}${CYC} (live mode): regression comparison skipped"
      fi
    fi
    if [ "${LEVEL}" != smoke ]; then
      python3 "${cmp}" ops --out "${COMROOT_2DGLO}" --ops-dir "${ops_dir}" --pdy "${PDY}" --cyc "${CYC}" --warn-mm "${OPS_WARN_MM:-500}" || grc=1
    fi
    exit "${grc}"
  } 2>&1 | tee "${LOGDIR}/compare_2dglo.txt" || rc=$?
  [ "${rc}" -eq 0 ] || { echo "FAIL[verify]: LEVEL=${LEVEL}"; exit 1; }
  echo "PASS[verify]: LEVEL=${LEVEL}"
}

cmd_seed() {
  PDY=${1:?usage: stofs_2d_glo.sh seed <PDY> <CYC> [cold]}
  CYC=${2:?usage: stofs_2d_glo.sh seed <PDY> <CYC> [cold]}
  local mode=${3:-chain} with_state=1
  case "${mode}" in chain) ;; cold) with_state=0 ;; *) echo "FATAL: third argument must be 'cold' or empty (got '${mode}')" >&2; exit 2 ;; esac
  check_cycle_args
  local ptmp=${NOS_PTMP:-${DEFAULT_PTMP}} user=${LOGNAME:-$(id -un)}
  local src=${COMROOT_2DGLO:-${ptmp}/${user}/com_2dglo}
  local seed_rt=${SEED_RT:-/work2/noaa/nos-surge/mjisan/nos-workflow-rt}
  local dest="${seed_rt}/stofs_2d_glo/${PDY}${CYC}"
  local ops_dir=${OPS_DIR:-${ptmp}/${user}/ops_s3/${PDY}${CYC}/products}
  local day="nos/stofs_2d_glo.${PDY}" f miss=0 inputs refs=()
  inputs=$(input_files "${with_state}" ncst fcst)
  for f in ${inputs}; do
    [ -s "${src}/${f}" ] || { echo "MISSING: ${src}/${f}" >&2; miss=1; }
  done
  refs+=("${day}/${CYC}/rerun/stofs_2d_glo_tide.61.nc" "${day}/${CYC}/rerun/stofs_2d_glo_surf.61.nc")
  for f in htp cwl.noanomaly swl; do refs+=("${day}/stofs_2d_glo.t${CYC}z.points.${f}.nc"); done
  for f in "${refs[@]}"; do
    [ -s "${src}/${f}" ] || { echo "MISSING: ${src}/${f}" >&2; miss=1; }
  done
  [ "${miss}" = 0 ] || { echo "FATAL: ${src} is not a finished ${PDY}${CYC} run (COMROOT_2DGLO=... to point at it)" >&2; exit 1; }
  if [ -e "${dest}" ]; then
    [ "${FORCE:-0}" = 1 ] || { echo "FATAL: ${dest} exists; FORCE=1 replaces it" >&2; exit 1; }
    rm -rf "${dest}"
  fi
  mkdir -p "${dest}/input" "${dest}/ref" "${dest}/ops"
  echo "seeding ${dest} from ${src} (${mode})"
  echo "${inputs}" | rsync -a --files-from=- "${src}/" "${dest}/input/"
  {
    printf '%s\n' "${refs[@]}"
    (cd "${src}" && ls "${day}/stofs_2d_glo.t${CYC}z.points."*.nc)
  } | sort -u | rsync -a --files-from=- "${src}/" "${dest}/ref/"
  for f in htp cwl.noanomaly swl; do
    if [ -s "${ops_dir}/stofs_2d_glo.t${CYC}z.points.${f}.nc" ]; then
      cp -p "${ops_dir}/stofs_2d_glo.t${CYC}z.points.${f}.nc" "${dest}/ops/"
    else
      echo "WARN: no ops product ${ops_dir}/stofs_2d_glo.t${CYC}z.points.${f}.nc (OPS_DIR=...); the ops comparison will skip it" >&2
    fi
  done
  chmod -R o+rX "${dest}" || true
  touch "${dest}/.seeded_ok"
  du -sh "${dest}"/* | sed 's/^/  /'
  echo "seed PASS: ${dest}"
  echo "the CI account reads it only if the parent directories are traversable: chmod o+x ${seed_rt} ${seed_rt}/stofs_2d_glo"
}

CMD=${1:-}
[ "$#" -eq 0 ] || shift
case "${CMD}" in
  seed) cmd_seed "$@" ;;
  stage|run|verify)
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/common.sh"
    [ "${OFS}" = stofs_2d_glo ] || { echo "FATAL: ${CMD} runs with CI_OFS=stofs_2d_glo (got ${OFS})" >&2; exit 2; }
    "cmd_${CMD}"
    ;;
  *) usage >&2; exit 2 ;;
esac
