#!/usr/bin/env bash
# STOFS-3D-Atlantic stages of the Hercules Jenkins pipeline (OFS=stofs_3d_atl_ufs_standalone or stofs_3d_atl_ufs; manual builds only). MJ (10/14/26)
#   stofs_3d_atl.sh stage    Stage Data (called by stage_data.sh): frozen = link the dataset for PDY into a clean CI root ATL_CI_ROOT;
#                            live = stage_comin.py + hercules_atl_seed_init.sh + hercules_atl_seed_prev.sh on this login/front-end node
#                            (compute nodes have no internet), with the dcom case bundle DCOM_BUNDLE the user supplies
#   stofs_3d_atl.sh run      Run ATL: sbatch the variant's cards as an afterok chain with the CI account/qos, wait, check every job
#   stofs_3d_atl.sh verify   Verify ATL: compare_atl.py regress against the dataset's reference; ops comparison (report only) at full
#   stofs_3d_atl.sh seed <PDY> <standalone|coupled> [SRC_COMROOT [SRC_COMIN [SRC_DCOM]]]   one-time, by hand (see below)
# The variant comes from OFS: stofs_3d_atl_ufs_standalone = pschism (cards slurm/stofs_3d_atl_ufs_standalone, COMROOT_SA),
# stofs_3d_atl_ufs = DATM+CMEPS+SCHISM (cards slurm/stofs_3d_atl_ufs, COMROOT_UFS). Both run RUN=stofs_3d_atl_ufs, CYC=12 only.
# Env (Jenkinsfile): PDY CYC LEVEL DATA_MODE RT_DATA_ROOT NOS_PTMP PACKAGEROOT VENV_PATH SLURM_CI_ACCOUNT SLURM_CI_QOS; optional
# ATL_CI_ROOT (default $NOS_PTMP/$LOGNAME/atl_ci_<variant>), WAIT_S POLL_S (poll limit and interval, seconds), CMP_TOL (default 1e-3),
# OPS_WARN_MM (default 500), DCOM_BUNDLE (live only), COMPARE_ATL (path of compare_atl.py, default next to this script). MJ (10/14/26)
#
# LEVEL   cards run                    jobs  wait (s)  verify
#   smoke  prep nowcast                   2    14400   compare_atl.py regress --level smoke
#   cycle  prep nowcast forecast post     4    36000   regress --level cycle
#   full   prep nowcast forecast post     4    36000   regress --level cycle, then ops (report only)
# The waits are about 3x the expected healthy time (Hercules: prep 8 min standalone / 24 min coupled, nowcast stage 25-28 min,
# forecast and post not yet measured on Hercules, about 1.5 h and 1-2 h on WCOSS2) plus queue time for the 62/63-node jobs.
# The cards' own walltimes (3 h, 2.5 h, 6 h, 2 h) stop a hung job, and a job in FAILED, CANCELLED, TIMEOUT or any other bad state, or
# without STAGE_SUMMARY status=PASS in its log, fails the run stage. MJ (10/14/26)
#
# CI root ${ATL_CI_ROOT}: com/ (the variant's COMROOT), comin/ (COMROOT_STAGED), dcom/ (DCOMROOT), rpt/ (the cards' RPTDIR),
# slurm/ (jobs_<PDY><CYC>.txt and the cards' Slurm output), ops/ (live mode ops products). frozen clears it at stage.
#
# Dataset ${RT_DATA_ROOT}/stofs_3d_atl/<standalone|coupled>/<PDY><CYC>/ (bootstrap.sh copies it from ${SEED_RT}/ in frozen mode):
#   .seeded_ok
#   input/com/nos/stofs_3d_atl_ufs.<PDY>/stofs_3d_atl_ufs.t12z.<PDY>.init.nowcast.nc     first-cycle init state (NETCDF4_CLASSIC, 26 GB)
#   input/com/nos/stofs_3d_atl_ufs.<PDY-1>/staout_1                                      previous-cycle dynamic-adjust seed
#   input/com/nos/stofs_3d_atl_ufs.<PDY-1>/rerun/stofs_3d_atl_ufs.t12z.{avg_bias,param.nml}   (param.nml optional)
#   input/comin/{gfs,hrrr,rtofs,nwm}/...                                                 ush/stage_comin.py --profile stofs_3d_atl tree
#   input/dcom/<day>/coops_waterlvlobs/*.xml                                             day = PDY and PDY-1
#   input/dcom/<day>/validation_data/marine/cmems/ssh/nrt_global_allsat_phy_l4_<day>_<day>.nc
#   input/dcom/<day>/can_streamgauge/02OA016_hydrometric.csv
#   ref/nos/stofs_3d_atl_ufs.<PDY>/...                                                   what `compare_atl.py files --level cycle` lists
#   ref/ops/...                                                                          what `compare_atl.py ops-files` lists (optional)
# MJ (10/14/26)
#
# One-time seeding on Hercules from a finished run (all four stages PASS), as the user who owns it, once per variant:
#   bash .cicd/scripts/stofs_3d_atl.sh seed 20261001 standalone $COMROOT_SA $NOS_PTMP/$LOGNAME/comin_atl $B/dcom
#   bash .cicd/scripts/stofs_3d_atl.sh seed 20261001 coupled    $COMROOT_UFS $NOS_PTMP/$LOGNAME/comin_atl $B/dcom
# The three source arguments default to the run guide's layout (COMROOT_SA / COMROOT_UFS, $NOS_PTMP/$LOGNAME/comin_atl, $DCOMROOT).
# Optional env: SEED_RT (destination root, default /work2/noaa/nos-surge/mjisan/nos-workflow-rt, the Jenkins SEED_RT default),
# OPS_DIR (a directory that already holds the ops products; otherwise they are downloaded from the public bucket), NOS_PTMP,
# FORCE=1 (replace an existing dataset). The second variant hard-links what it shares with the first (comin, init). The destination
# is made world-readable for the CI account; the parent directories need chmod o+x (printed). MJ (10/14/26)
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEFAULT_PTMP=/work2/noaa/nos-surge/mjisan/nos-run/ptmp
OPS_URL=https://noaa-nos-stofs3d-pds.s3.amazonaws.com/STOFS-3D-Atl
RUN=stofs_3d_atl_ufs

usage() { sed -n '2,/^set -euo/{/^set -euo/d;s/^# \{0,1\}//;p}' "${BASH_SOURCE[0]}"; }

check_cycle_args() {
  case "${PDY:-}" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;; *) echo "FATAL: PDY must be YYYYMMDD (got '${PDY:-}')" >&2; exit 2 ;; esac
  [ "${CYC:-}" = 12 ] || { echo "FATAL: STOFS-3D-ATL runs the 12z cycle only: set CYC=12 (got '${CYC:-}')" >&2; exit 2; }
  PDYM1=$(date -u -d "${PDY} -1 day" +%Y%m%d)
}

set_variant() {
  case "$1" in
    standalone|stofs_3d_atl_ufs_standalone) VARIANT=standalone; CARDS=stofs_3d_atl_ufs_standalone; COMVAR=COMROOT_SA; SIBLING=coupled ;;
    coupled|stofs_3d_atl_ufs)               VARIANT=coupled;    CARDS=stofs_3d_atl_ufs;            COMVAR=COMROOT_UFS; SIBLING=standalone ;;
    *) echo "FATAL: variant must be standalone or coupled (got '$1')" >&2; exit 2 ;;
  esac
}

# The cycle's single files under the dataset input/ (or a COMROOT-shaped tree). MJ (10/14/26)
com_state_files() {
  echo "nos/${RUN}.${PDY}/${RUN}.t${CYC}z.${PDY}.init.nowcast.nc"
  echo "nos/${RUN}.${PDYM1}/staout_1"
  echo "nos/${RUN}.${PDYM1}/rerun/${RUN}.t${CYC}z.avg_bias"
}

# The dcom files the prep card and dynamic adjust read, as paths relative to the dcom root; $1 = 1 for the required ones only. MJ (10/14/26)
dcom_required() {
  echo "${PDY}/validation_data/marine/cmems/ssh/nrt_global_allsat_phy_l4_${PDY}_${PDY}.nc"
  echo "${PDYM1}/validation_data/marine/cmems/ssh/nrt_global_allsat_phy_l4_${PDYM1}_${PDYM1}.nc"
}
dcom_groups() {
  local d
  for d in "${PDY}" "${PDYM1}"; do
    echo "${d}/coops_waterlvlobs"
    echo "${d}/validation_data/marine/cmems/ssh/nrt_global_allsat_phy_l4_${d}_${d}.nc"
    echo "${d}/can_streamgauge/02OA016_hydrometric.csv"
  done
}

# Everything the stage, run and verify commands share. MJ (10/14/26)
level_setup() {
  check_cycle_args
  set_variant "${OFS}"
  LEVEL=${LEVEL:-smoke}
  case "${LEVEL}" in
    smoke) STAGES="prep nowcast";               EXPECT=2; WAIT_DEFAULT=14400 ;;
    cycle) STAGES="prep nowcast forecast post"; EXPECT=4; WAIT_DEFAULT=36000 ;;
    full)  STAGES="prep nowcast forecast post"; EXPECT=4; WAIT_DEFAULT=36000 ;;
    *) echo "FATAL: LEVEL must be smoke, cycle or full (got '${LEVEL}')" >&2; exit 2 ;;
  esac
  DATA_MODE=${DATA_MODE:-frozen}
  : "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"
  ATL_CI_ROOT=${ATL_CI_ROOT:-${NOS_PTMP}/${LOGNAME}/atl_ci_${VARIANT}}
  CI_COM="${ATL_CI_ROOT}/com"
  DS="${RT_DATA_ROOT}/stofs_3d_atl/${VARIANT}/${PDY}${CYC}"
  JOBS="${ATL_CI_ROOT}/slurm/jobs_${PDY}${CYC}.txt"
  LOGDIR="${WORKSPACE:-${PWD}}/ci_logs"
  export NOS_PTMP
}

# Clears the CI root. It is normalized first (//, symlinks), must sit at least two levels below NOS_PTMP ($p/<x>/<y>) and must never be,
# or contain, the shared com or the run guide's hand-run roots, which hold the live SECOFS cycles and the user's own ATL runs. MJ (10/14/26)
reset_root() {
  local c p s
  case "${ATL_CI_ROOT}" in
    *..*) echo "FATAL: refusing to clear ${ATL_CI_ROOT} (contains ..)" >&2; exit 1 ;;
  esac
  c=$(realpath -m -- "${ATL_CI_ROOT}")
  p=$(realpath -m -- "${NOS_PTMP}")
  case "${c}" in
    "${p}"/?*/?*) ;;
    *) echo "FATAL: refusing to clear ${c}: it is not under NOS_PTMP (${p}) by at least two levels (<x>/<y>)" >&2; exit 1 ;;
  esac
  for s in com com_atl_sa com_atl_ufs comin_atl; do
    s=$(realpath -m -- "${NOS_PTMP}/${LOGNAME}/${s}")
    case "${s}/" in
      "${c}"/*) echo "FATAL: refusing to clear ${c}: it is the shared ${s} or a parent of it" >&2; exit 1 ;;
    esac
  done
  rm -rf -- "${c}"
  mkdir -p -- "${c}"
}

# Downloads the ops products `compare_atl.py ops-files` lists into $1; a product that cannot be fetched is reported, not fatal. MJ (10/14/26)
fetch_ops() {
  local dir=$1 f got=0 cmp="${COMPARE_ATL:-${SCRIPT_DIR}/compare_atl.py}"
  mkdir -p "${dir}"
  for f in $(python3 "${cmp}" ops-files --pdy "${PDY}"); do
    if [ -s "${OPS_DIR:-/nonexistent}/${f}" ]; then
      cp -p "${OPS_DIR}/${f}" "${dir}/${f}" && got=$((got + 1))
    elif curl -fsSL --retry 3 -o "${dir}/${f}.part" "${OPS_URL}/stofs_3d_atl.${PDY}/${f}"; then
      mv "${dir}/${f}.part" "${dir}/${f}"; got=$((got + 1))
    else
      rm -f "${dir}/${f}.part"
      echo "WARN: no ops product ${f} (${OPS_URL}/stofs_3d_atl.${PDY}); the ops comparison will skip it" >&2
    fi
  done
  echo "ops products: ${got} in ${dir}"
}

cmd_stage() {
  level_setup
  case "${DATA_MODE}" in
    frozen)
      [ -f "${DS}/.seeded_ok" ] || {
        echo "FATAL: no ${DS}/.seeded_ok -- dataset missing or an interrupted copy (Bootstrap copies it from SEED_RT)."
        echo "Seed it once: bash .cicd/scripts/stofs_3d_atl.sh seed ${PDY} ${VARIANT} (see the script header), or use DATA_MODE=live with DCOM_BUNDLE."
        exit 1
      }
      local f miss=0 s
      for f in $(com_state_files | sed 's#^#com/#') $(dcom_required | sed 's#^#dcom/#'); do
        [ -s "${DS}/input/${f}" ] || { echo "MISSING: ${DS}/input/${f}" >&2; miss=1; }
      done
      for s in gfs hrrr rtofs nwm; do
        [ -n "$(ls -A "${DS}/input/comin/${s}" 2>/dev/null)" ] || { echo "MISSING: ${DS}/input/comin/${s}/ (empty)" >&2; miss=1; }
      done
      compgen -G "${DS}/input/dcom/${PDY}/coops_waterlvlobs/*.xml" >/dev/null || { echo "MISSING: ${DS}/input/dcom/${PDY}/coops_waterlvlobs/*.xml" >&2; miss=1; }
      compgen -G "${DS}/input/dcom/*/can_streamgauge/02OA016_hydrometric.csv" >/dev/null || { echo "MISSING: ${DS}/input/dcom/<day>/can_streamgauge/02OA016_hydrometric.csv" >&2; miss=1; }
      [ "${miss}" = 0 ] || { echo "FATAL: the dataset lacks what the ATL prep card reads (see the header of stofs_3d_atl.sh)"; exit 1; }
      reset_root
      echo "staging ${DS}/input -> ${ATL_CI_ROOT} (LEVEL=${LEVEL}, ${VARIANT})"
      # The cards only read these inputs (the init state is copied into the run directory), so they are hard-linked: ~125 GB would not copy in reasonable time. MJ (10/14/26)
      rsync -a --link-dest="${DS}/input" "${DS}/input/" "${ATL_CI_ROOT}/"
      du -sh "${ATL_CI_ROOT}"/*
      ;;
    live)
      : "${DCOM_BUNDLE:?DATA_MODE=live needs DCOM_BUNDLE=<case bundle dir holding dcom/ and seeds/dyn_seed_<PDY-1>/> (run guide section 4.2); otherwise use DATA_MODE=frozen}"
      local b="${DCOM_BUNDLE}" seeds="${DCOM_BUNDLE}/seeds/dyn_seed_${PDYM1}" miss=0 f
      for f in $(dcom_required | sed "s#^#${b}/dcom/#") "${seeds}/staout_1" "${seeds}/${RUN}.t${CYC}z.avg_bias"; do
        [ -s "${f}" ] || { echo "MISSING: ${f}" >&2; miss=1; }
      done
      [ "${miss}" = 0 ] || { echo "FATAL: DCOM_BUNDLE=${b} lacks the files above (before the ~100 GB download)"; exit 1; }
      reset_root
      mkdir -p "${CI_COM}" "${ATL_CI_ROOT}/comin"
      echo "staging the public inputs for ${PDY}${CYC} into ${ATL_CI_ROOT} (login node)"
      python3 "${HOMEnos}/ush/stage_comin.py" --pdy "${PDY}" --cyc "${CYC}" --comroot "${ATL_CI_ROOT}/comin" --profile stofs_3d_atl --jobs 8 \
        || { echo "FATAL: stage_comin.py failed"; exit 1; }
      bash "${HOMEnos}/tools/hercules_atl_seed_init.sh" "${PDY}" "${CI_COM}/nos/${RUN}.${PDY}" \
        || { echo "FATAL: hercules_atl_seed_init.sh failed"; exit 1; }
      bash "${HOMEnos}/tools/hercules_atl_seed_prev.sh" "${seeds}" "${CI_COM}" "${PDY}" \
        || { echo "FATAL: hercules_atl_seed_prev.sh failed"; exit 1; }
      ;;
    *) echo "FATAL: unknown DATA_MODE '${DATA_MODE}' (expected frozen|live)"; exit 1 ;;
  esac
  echo "stage_data PASS"
}

# sacct states that end a job unsuccessfully; --kill-on-invalid-dep turns the jobs behind a failure into CANCELLED. MJ (10/14/26)
BAD_STATES='FAILED|CANCELLED|TIMEOUT|NODE_FAIL|OUT_OF_MEMORY|BOOT_FAIL|DEADLINE|PREEMPTED|REVOKED|SPECIAL_EXIT'

cmd_run() {
  level_setup
  mkdir -p "${LOGDIR}" "${ATL_CI_ROOT}/slurm" "${ATL_CI_ROOT}/rpt"
  local wait_s=${WAIT_S:-${WAIT_DEFAULT}} poll_s=${POLL_S:-60}
  local dcom="${ATL_CI_ROOT}/dcom" st carddir="${HOMEnos}/slurm/${CARDS}" miss=0
  [ "${DATA_MODE}" != live ] || dcom="${DCOM_BUNDLE:?DCOM_BUNDLE not set}/dcom"
  for st in ${STAGES}; do
    [ -s "${carddir}/jnos_${st}_00.sh" ] || { echo "MISSING: ${carddir}/jnos_${st}_00.sh" >&2; miss=1; }
  done
  [ -s "${CI_COM}/nos/${RUN}.${PDY}/${RUN}.t${CYC}z.${PDY}.init.nowcast.nc" ] || { echo "MISSING: the init state under ${CI_COM} (Stage Data)" >&2; miss=1; }
  [ "${miss}" = 0 ] || exit 1

  # Inherited values would bypass what the cards derive; the cards also clear most of these themselves. MJ (10/14/26)
  unset COMOUT COMOUTroot DATA COMIN COMINgfs COMINhrrr COMINrtofs_2d COMINrtofs_3d COMINnwm COMINrerun COMROOT DATAROOT RPTDIR OFS_CONFIG
  local acct=()
  [ -z "${SLURM_CI_ACCOUNT:-}" ] || acct+=(--account="${SLURM_CI_ACCOUNT}")
  [ -z "${SLURM_CI_QOS:-}" ] || acct+=(--qos="${SLURM_CI_QOS}")
  local ev="OFS=${RUN},PDY=${PDY},CYC=${CYC},PACKAGEROOT=${PACKAGEROOT},NOS_PTMP=${NOS_PTMP},NOS_VENV=${VENV_PATH:-},${COMVAR}=${CI_COM}"
  ev="${ev},COMROOT_STAGED=${ATL_CI_ROOT}/comin,DCOMROOT=${dcom},RPTDIR=${ATL_CI_ROOT}/rpt,COLDSTART=NO"
  cd "${ATL_CI_ROOT}/slurm"
  [ ! -s "${JOBS}" ] || mv "${JOBS}" "${JOBS}.$(date +%y%m%d%H%M%S)"
  : > "${JOBS}"
  echo "submitting ${CARDS} LEVEL=${LEVEL} (${STAGES}) for ${PDY}${CYC}, account=${SLURM_CI_ACCOUNT:-card} qos=${SLURM_CI_QOS:-card}"
  local id prev="" label
  for st in ${STAGES}; do
    id=$(sbatch --parsable --kill-on-invalid-dep=yes ${acct[@]+"${acct[@]}"} ${prev:+--dependency=afterok:${prev}} \
         --export="ALL,${ev}" "${carddir}/jnos_${st}_00.sh") || {
      echo "ERROR: sbatch failed for ${st}; cancel what was queued: scancel \$(awk '{print \$2}' ${JOBS})" >&2
      awk 'NF>=2{printf "%s ", $2}' "${JOBS}" > "${LOGDIR}/current_jobid"
      exit 1
    }
    id=${id%%;*}
    echo "${st} ${id}" >> "${JOBS}"
    printf '%-9s: %s%s\n' "${st}" "${id}" "${prev:+   (afterok:${prev})}"
    prev=${id}
  done

  # post/unsuccessful in the Jenkinsfile scancels whatever is in this file, space separated; written before the count check so a mismatch still cancels what was queued. MJ (10/14/26)
  awk 'NF>=2{printf "%s ", $2}' "${JOBS}" > "${LOGDIR}/current_jobid"
  local n idlist
  n=$(awk 'NF>=2' "${JOBS}" | wc -l)
  [ "${n}" -eq "${EXPECT}" ] || { echo "FATAL: ${n} jobs queued, LEVEL=${LEVEL} expects ${EXPECT} (${JOBS})"; exit 1; }
  idlist=$(awk 'NF>=2{printf "%s%s", sep, $2; sep=","}' "${JOBS}")

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

  # The card writes <RPTDIR>/<prefix>_<stage>_00.<jobid>.out; the prefix is read from the card's _LOG_PREFIX line so the two cannot drift. MJ (10/14/26)
  local pfx bad="" log state
  printf '%-9s %-9s %-16s %s\n' job id state log
  while read -r label id; do
    [ -n "${id}" ] || continue
    pfx=$(sed -n 's#^_LOG_PREFIX=.*/\([^/]*\)\.\${_JOBID}.*#\1#p' "${carddir}/jnos_${label}_00.sh" | head -1)
    [ -n "${pfx}" ] || { echo "FATAL: no _LOG_PREFIX in ${carddir}/jnos_${label}_00.sh"; exit 1; }
    log="${ATL_CI_ROOT}/rpt/${pfx}.${id}.out"
    for f in "${log}" "${log%.out}.err"; do
      [ -r "${f}" ] && cp -p "${f}" "${LOGDIR}/" || true
    done
    state=$(awk -F'|' -v i="${id}" '$1==i{print $2}' <<<"${snap}")
    printf '%-9s %-9s %-16s %s\n' "${label}" "${id}" "${state:--}" "$(grep -o 'STAGE_SUMMARY.*' "${log}" 2>/dev/null | tail -1)"
    if [ "${state%% *}" != COMPLETED ] || ! grep -q 'STAGE_SUMMARY .*status=PASS' "${log}" 2>/dev/null; then bad="${bad}${label} "; fi
  done < "${JOBS}"
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
  local rc=0 ops_dir cmp="${COMPARE_ATL:-${SCRIPT_DIR}/compare_atl.py}"
  ops_dir="${DS}/ref/ops"
  [ "${DATA_MODE}" != live ] || ops_dir="${ATL_CI_ROOT}/ops"
  # The group runs in the pipeline's subshell, so it hands its verdict back through its exit status. MJ (10/14/26)
  {
    grc=0
    if [ -d "${DS}/ref" ]; then
      python3 "${cmp}" regress --ref "${DS}/ref" --out "${CI_COM}" --variant "${VARIANT}" --pdy "${PDY}" --level "${LEVEL/full/cycle}" --tol "${CMP_TOL:-1e-3}" || grc=1
    elif [ "${DATA_MODE}" = frozen ]; then
      echo "FAIL: ${DS}/ref is missing; the frozen dataset has no reference outputs"
      grc=1
    else
      echo "no frozen reference for ${PDY}${CYC} (live mode): regression comparison skipped"
    fi
    if [ "${LEVEL}" = full ]; then
      [ "${DATA_MODE}" != live ] || fetch_ops "${ops_dir}" || true
      python3 "${cmp}" ops --ops-dir "${ops_dir}" --out "${CI_COM}" --variant "${VARIANT}" --pdy "${PDY}" --warn-mm "${OPS_WARN_MM:-500}" || grc=1
    fi
    exit "${grc}"
  } 2>&1 | tee "${LOGDIR}/compare_atl.txt" || rc=$?
  [ "${rc}" -eq 0 ] || { echo "FAIL[verify]: LEVEL=${LEVEL}"; exit 1; }
  echo "PASS[verify]: LEVEL=${LEVEL}"
}

cmd_seed() {
  PDY=${1:?usage: stofs_3d_atl.sh seed <PDY> <standalone|coupled> [SRC_COMROOT [SRC_COMIN [SRC_DCOM]]]}
  set_variant "${2:?usage: stofs_3d_atl.sh seed <PDY> <standalone|coupled> [SRC_COMROOT [SRC_COMIN [SRC_DCOM]]]}"
  CYC=12
  check_cycle_args
  local ptmp=${NOS_PTMP:-${DEFAULT_PTMP}} user=${LOGNAME:-$(id -un)} cmp="${COMPARE_ATL:-${SCRIPT_DIR}/compare_atl.py}"
  local def_com=com_atl_sa
  [ "${VARIANT}" = standalone ] || def_com=com_atl_ufs
  local src_com=${3:-${!COMVAR:-${ptmp}/${user}/${def_com}}}
  local src_comin=${4:-${ptmp}/${user}/comin_atl}
  local src_dcom=${5:-${DCOMROOT:-}}
  [ -n "${src_dcom}" ] || { echo "FATAL: give the source dcom dir (the bundle's dcom/) as the fifth argument or DCOMROOT" >&2; exit 2; }
  local seed_rt=${SEED_RT:-/work2/noaa/nos-surge/mjisan/nos-workflow-rt}
  local top="${seed_rt}/stofs_3d_atl" dest="${seed_rt}/stofs_3d_atl/${VARIANT}/${PDY}${CYC}"
  local f s miss=0 refs
  refs=$(python3 "${cmp}" files --variant "${VARIANT}" --level cycle --pdy "${PDY}") || { echo "FATAL: compare_atl.py files failed" >&2; exit 1; }
  for f in $(com_state_files) ${refs}; do
    [ -s "${src_com}/${f}" ] || { echo "MISSING: ${src_com}/${f}" >&2; miss=1; }
  done
  for s in gfs hrrr rtofs nwm; do
    [ -n "$(ls -A "${src_comin}/${s}" 2>/dev/null)" ] || { echo "MISSING: ${src_comin}/${s}/ (empty)" >&2; miss=1; }
  done
  for f in $(dcom_required); do
    [ -s "${src_dcom}/${f}" ] || { echo "MISSING: ${src_dcom}/${f}" >&2; miss=1; }
  done
  compgen -G "${src_dcom}/${PDY}/coops_waterlvlobs/*.xml" >/dev/null || { echo "MISSING: ${src_dcom}/${PDY}/coops_waterlvlobs/*.xml" >&2; miss=1; }
  [ "${miss}" = 0 ] || { echo "FATAL: the sources above are not a finished ${VARIANT} ${PDY}${CYC} run (COMROOT, comin, dcom arguments)" >&2; exit 1; }
  if [ -e "${dest}" ]; then
    [ "${FORCE:-0}" = 1 ] || { echo "FATAL: ${dest} exists; FORCE=1 replaces it" >&2; exit 1; }
    rm -rf "${dest}"
  fi
  mkdir -p "${dest}/input/com" "${dest}/input/comin" "${dest}/input/dcom" "${dest}/ref"
  echo "seeding ${dest} from ${src_com}, ${src_comin}, ${src_dcom}"
  local lcom=() lcomin=() list
  if [ -d "${top}/${SIBLING}/${PDY}${CYC}/input" ]; then
    lcom=(--link-dest="${top}/${SIBLING}/${PDY}${CYC}/input/com")
    lcomin=(--link-dest="${top}/${SIBLING}/${PDY}${CYC}/input/comin")
  fi
  list=$(com_state_files)
  [ ! -s "${src_com}/nos/${RUN}.${PDYM1}/rerun/${RUN}.t${CYC}z.param.nml" ] || list+=$'\n'"nos/${RUN}.${PDYM1}/rerun/${RUN}.t${CYC}z.param.nml"
  # -L: the coupled init file is a symlink to the standalone one. MJ (10/14/26)
  echo "${list}" | rsync -aL --files-from=- ${lcom[@]+"${lcom[@]}"} "${src_com}/" "${dest}/input/com/"
  for s in gfs hrrr rtofs nwm; do
    rsync -a ${lcomin[@]+"${lcomin[@]}"} "${src_comin}/${s}" "${dest}/input/comin/"
  done
  dcom_groups | while read -r f; do [ ! -e "${src_dcom}/${f}" ] || echo "${f}"; done | rsync -a --files-from=- "${src_dcom}/" "${dest}/input/dcom/"
  echo "${refs}" | rsync -a --files-from=- "${src_com}/" "${dest}/ref/"
  fetch_ops "${dest}/ref/ops"
  touch "${dest}/.seeded_ok"
  chmod -R o+rX "${dest}" || true
  du -sh "${dest}"/* | sed 's/^/  /'
  echo "seed PASS: ${dest}"
  echo "the CI account reads it only if the parent directories are traversable: chmod o+x ${seed_rt} ${top} ${top}/${VARIANT}"
}

CMD=${1:-}
[ "$#" -eq 0 ] || shift
case "${CMD}" in
  seed)
    # common.sh is not sourced for the by-hand seed (it needs PACKAGEROOT); the variant arguments are explicit. MJ (10/14/26)
    cmd_seed "$@"
    ;;
  stage|run|verify)
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/common.sh"
    case "${OFS}" in stofs_3d_atl_ufs_standalone|stofs_3d_atl_ufs) ;; *) echo "FATAL: ${CMD} runs with CI_OFS=stofs_3d_atl_ufs_standalone or stofs_3d_atl_ufs (got ${OFS})" >&2; exit 2 ;; esac
    "cmd_${CMD}"
    ;;
  *) usage >&2; exit 2 ;;
esac
