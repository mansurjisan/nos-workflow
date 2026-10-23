#!/usr/bin/env bash
# STOFS-3D-Atlantic stages of the Hercules Jenkins pipeline (OFS=stofs_3d_atl_ufs_standalone or stofs_3d_atl_ufs; manual builds only). MJ (10/14/26)
#   stofs_3d_atl.sh stage    Stage Data (called by stage_data.sh): frozen = hard-link the dataset's com state into the shared CI com; MJ (10/15/26)
#                            live = stage_comin.py + hercules_atl_seed_init.sh + hercules_atl_seed_prev.sh on this login/front-end node
#                            (compute nodes have no internet), with the dcom case bundle DCOM_BUNDLE the user supplies
#   stofs_3d_atl.sh card-env <stage>   eval-able shell for run_stage.sh: the variant's extra sbatch exports (ATL_EXPORTS), log prefix, unset list
#   stofs_3d_atl.sh clean-job <jobid>  delete that job's run directory (run_stage.sh calls it after a passing stage)
#   stofs_3d_atl.sh verify   Verify ATL: compare_atl.py regress against the dataset's reference; ops comparison at full (pass/fail) MJ (10/22/26)
#   stofs_3d_atl.sh seed <PDY> <standalone|coupled> [SRC_COMROOT [SRC_COMIN [SRC_DCOM]]]   one-time, by hand (see below)
# The variant comes from OFS: stofs_3d_atl_ufs_standalone = pschism (cards slurm/stofs_3d_atl_ufs_standalone, COMROOT_SA),
# stofs_3d_atl_ufs = DATM+CMEPS+SCHISM (cards slurm/stofs_3d_atl_ufs, COMROOT_UFS). Both run RUN=stofs_3d_atl_ufs, CYC=12 only.
# Env (Jenkinsfile): PDY CYC LEVEL DATA_MODE RT_DATA_ROOT NOS_PTMP PACKAGEROOT VENV_PATH; SLURM_CI_ACCOUNT and SLURM_CI_QOS are read by run_stage.sh; optional
# CMP_TOL (default 1e-3), OPS_WARN_MM (default 500), OPS_FAIL_MEDIAN_MM (default 5 standalone, 15 coupled) and OPS_FAIL_OVER_10CM (default 10), DCOM_BUNDLE (live only),
# COMPARE_ATL (path of compare_atl.py, default next to this script). MJ (10/15/26)
#
# The model stages are the SECOFS Jenkins stages: Prep, Nowcast, Forecast and Post each call run_stage.sh <stage> <PDY> <CYC>, which submits the variant's
# card, waits (timeouts in run_stage.sh), gates on its STAGE_SUMMARY and deletes the job's run directory on a pass. Then Verify calls `verify`.
# LEVEL   Jenkins stages run                       Verify
#   smoke  Prep Nowcast                             compare_atl.py regress --level smoke
#   cycle  Prep Nowcast Forecast Post               regress --level cycle
#   full   Prep Nowcast Forecast Post               regress --level cycle, then ops (pass/fail) MJ (10/22/26)
# MJ (10/15/26)
#
# Layout, the SECOFS one (no per-variant roots): com/, rpt/ and work/ are the shared $NOS_PTMP/$LOGNAME/{com,rpt,work} and the cards' own defaults;
# comin (COMROOT_STAGED) and dcom (DCOMROOT) are read in place from the frozen dataset's input/ (read-only to the CI; prep never writes there).
#   com   $NOS_PTMP/$LOGNAME/com  COMROOT_SA or COMROOT_UFS; both variants run RUN=stofs_3d_atl_ufs, so they share com/nos/stofs_3d_atl_ufs.<day> and
#         the second variant overwrites the first (one CI build at a time). Stage removes only nos/stofs_3d_atl_ufs.<8 digits> day dirs (all earlier cycles), then
#         hard-links the PDY-1 and PDY day dirs of the dataset back in (a copy if the dataset is on another filesystem); SECOFS's com/nos/secofs_ufs.* is never touched.
#   rpt   the card's RPTDIR default $NOS_PTMP/$LOGNAME/rpt/stofs_3d_atl_ufs;  work/  the cards' shared work dir.
#   live  comin is staged to $RT_DATA_ROOT/stofs_3d_atl/live/<PDY><CYC>/comin (ops/ there too), dcom is read from DCOM_BUNDLE/dcom.
# The dataset files are read-only (seed and Bootstrap chmod a-w; com shares their inodes). The cfgrib fallback (used only without wgrib2, always present on Hercules)
# would write .idx files next to the GRIBs in the read-only comin. Stage also removes earlier cycles' nos/stofs_3d_atl_ufs.<8 digits> and live/<PDY>12 dirs and the old per-variant roots $NOS_PTMP/$LOGNAME/atl_ci_standalone and atl_ci_coupled once. MJ (10/15/26)
#
# Dataset ${RT_DATA_ROOT}/stofs_3d_atl/<standalone|coupled>/<PDY><CYC>/ (bootstrap.sh copies it from ${SEED_RT}/ in frozen mode):
#   .seeded_ok                                                                           one line, level=smoke|cycle (empty or no level = cycle)
#   input/com/nos/stofs_3d_atl_ufs.<PDY>/stofs_3d_atl_ufs.t12z.<PDY>.init.nowcast.nc     first-cycle init state (NETCDF4_CLASSIC, 26 GB)
#   input/com/nos/stofs_3d_atl_ufs.<PDY-1>/staout_1                                      previous-cycle dynamic-adjust seed
#   input/com/nos/stofs_3d_atl_ufs.<PDY-1>/rerun/stofs_3d_atl_ufs.t12z.{avg_bias,param.nml}   (param.nml optional)
#   input/comin/{gfs,hrrr,rtofs,nwm}/...                                                 ush/stage_comin.py --profile stofs_3d_atl tree
#   input/dcom/<day>/coops_waterlvlobs/*.xml                                             day = PDY and PDY-1
#   input/dcom/<day>/validation_data/marine/cmems/ssh/nrt_global_allsat_phy_l4_<day>_<day>.nc
#   input/dcom/<day>/can_streamgauge/02OA016_hydrometric.csv
#   ref/nos/stofs_3d_atl_ufs.<PDY>/...                                                   what `compare_atl.py files --level <level>` lists (smoke: the 8 nowcast staout files)
#   ref/ops/...                                                                          what `compare_atl.py ops-files` lists (optional; cycle datasets only)
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
#
# SEED_LEVEL=smoke|cycle (default cycle) = how much of the source run the dataset holds. smoke seeds from a run that has finished prep and nowcast:
# it copies only the nowcast staout references and no ops products, and Stage refuses LEVEL=cycle or full on it. Seed it now, run LEVEL=smoke:
#   SEED_LEVEL=smoke bash .cicd/scripts/stofs_3d_atl.sh seed 20261001 standalone $COMROOT_SA $NOS_PTMP/$LOGNAME/comin_atl $B/dcom
# Once the source run has finished forecast and post, upgrade the same dataset with the default level and no FORCE (it adds the cycle references and
# the ops products on top, giving what a fresh cycle seed gives):
#   bash .cicd/scripts/stofs_3d_atl.sh seed 20261001 standalone $COMROOT_SA $NOS_PTMP/$LOGNAME/comin_atl $B/dcom
# Any other re-seed of an existing dataset (cycle over cycle, smoke over anything) still needs FORCE=1. A Jenkins copy of the dataset under
# RT_DATA_ROOT is refreshed by Bootstrap when the source in SEED_RT has a higher level. MJ (10/14/26)
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

# The level a dataset directory was seeded at: the level= line of .seeded_ok, cycle when it has none (older datasets). MJ (10/14/26)
dataset_level() {
  local l
  l=$(sed -n 's/^level=//p' "$1/.seeded_ok" 2>/dev/null | head -1) || true
  echo "${l:-cycle}"
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
    echo "${d}/coops_waterlvlobs/"
    echo "${d}/validation_data/marine/cmems/ssh/nrt_global_allsat_phy_l4_${d}_${d}.nc"
    echo "${d}/can_streamgauge/02OA016_hydrometric.csv"
  done
}

# The shared com and the inputs the cards read (comin from the dataset, or the live staging dir), from the variant. MJ (10/15/26)
ci_paths() {
  : "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"
  CI_COM="${NOS_PTMP}/${LOGNAME}/com"
  DS="${RT_DATA_ROOT}/stofs_3d_atl/${VARIANT}/${PDY}${CYC}"
  LIVE="${RT_DATA_ROOT}/stofs_3d_atl/live/${PDY}${CYC}"
  CI_COMIN="${DS}/input/comin"
  [ "${DATA_MODE:-frozen}" != live ] || CI_COMIN="${LIVE}/comin"
}

# Everything the stage and verify commands share. MJ (10/15/26)
level_setup() {
  check_cycle_args
  set_variant "${OFS}"
  LEVEL=${LEVEL:-smoke}
  case "${LEVEL}" in smoke|cycle|full) ;; *) echo "FATAL: LEVEL must be smoke, cycle or full (got '${LEVEL}')" >&2; exit 2 ;; esac
  DATA_MODE=${DATA_MODE:-frozen}
  ci_paths
  LOGDIR="${WORKSPACE:-${PWD}}/ci_logs"
  export NOS_PTMP
}

# Clears the ATL state of earlier cycles from the shared com (every nos/${RUN}.<8 digits>, CI-owned and ATL-only, so the disk does not grow; SECOFS's secofs_ufs.* and any
# other name stay) and the live staging dirs of other PDYs. The com root must be the CI's $NOS_PTMP/$LOGNAME/com; no root, parent or target may be a symlink and every name
# is matched exactly. All targets are validated before the first rm, so a refusal never follows a delete. Then removes the old atl_ci_* roots. MJ (10/15/26)
clear_com() {
  local p c t v live rm=()
  case "${LOGNAME}" in ""|*/*|.|..) echo "FATAL: refusing to clear com: odd LOGNAME '${LOGNAME}'" >&2; exit 1 ;; esac
  p=$(realpath -m -- "${NOS_PTMP}")
  c="${p}/${LOGNAME}/com"
  [ "$(realpath -m -- "${CI_COM}")" = "${c}" ] || { echo "FATAL: refusing to clear ${CI_COM}: it is not ${c} (symlink?)" >&2; exit 1; }
  for t in "${c}" "${c}/nos"; do
    [ ! -L "${t}" ] || { echo "FATAL: refusing to clear under ${t}: it is a symlink" >&2; exit 1; }
  done
  for t in "${c}/nos/${RUN}."*; do
    [[ "${t##*/}" =~ ^${RUN}\.[0-9]{8}$ ]] && { [ -e "${t}" ] || [ -L "${t}" ]; } && rm+=("${t}")
  done
  live="$(realpath -m -- "${RT_DATA_ROOT}")/stofs_3d_atl/live"
  if [ -d "${live}" ]; then
    [ ! -L "${live}" ] || { echo "FATAL: refusing to prune ${live}: it is a symlink" >&2; exit 1; }
    for t in "${live}"/*; do
      [[ "${t##*/}" =~ ^[0-9]{8}12$ ]] && [ "${t##*/}" != "${PDY}${CYC}" ] && { [ -e "${t}" ] || [ -L "${t}" ]; } && rm+=("${t}")
    done
  fi
  for t in ${rm[@]+"${rm[@]}"}; do
    { [ ! -L "${t}" ] && [ -d "${t}" ] && [ "$(realpath -m -- "${t}")" = "${t}" ]; } || { echo "FATAL: refusing to remove ${t}: it is a symlink or not a plain directory" >&2; exit 1; }
  done
  for t in ${rm[@]+"${rm[@]}"}; do rm -rf -- "${t}"; done
  mkdir -p -- "${c}/nos"
  for v in standalone coupled; do
    t="${p}/${LOGNAME}/atl_ci_${v}"
    if [ -L "${t}" ]; then echo "WARN: leaving ${t}: it is a symlink" >&2
    elif [ -d "${t}" ]; then rm -rf -- "${t}"; echo "removed the old per-variant CI root ${t}"
    fi
  done
}

# The cards keep every job's run directory (KEEPDATA=YES, ~150 GB a cycle): $NOS_PTMP/$LOGNAME/work/<cards>/<job>.<jobid>. $1 = job ids to
# remove (none: the whole variant work directory). Only the variant's own directory, at least three levels under NOS_PTMP, is touched. MJ (10/14/26)
clean_work() {
  local w p id
  w=$(realpath -m -- "${NOS_PTMP}/${LOGNAME}/work/${CARDS}")
  p=$(realpath -m -- "${NOS_PTMP}")
  [ "${w##*/}" = "${CARDS}" ] || { echo "FATAL: refusing to clean ${w}: it is not <work>/${CARDS} (symlink?)" >&2; exit 1; }
  case "${w}" in
    "${p}"/?*/?*/?*) ;;
    *) echo "FATAL: refusing to clean ${w}: not at least three levels under NOS_PTMP (${p})" >&2; exit 1 ;;
  esac
  if [ "$#" -eq 0 ]; then
    rm -rf -- "${w}"
  else
    for id in "$@"; do rm -rf -- "${w}"/*."${id}"; done
  fi
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
      if [ "${LEVEL}" != smoke ] && [ "$(dataset_level "${DS}")" = smoke ]; then
        echo "FATAL: dataset ${DS} holds smoke references only; run LEVEL=smoke, or re-seed with SEED_LEVEL=cycle once the source run has forecast and post"
        exit 1
      fi
      local f miss=0 s
      for f in $(com_state_files | sed 's#^#com/#') $(dcom_required | sed 's#^#dcom/#'); do
        [ -s "${DS}/input/${f}" ] || { echo "MISSING: ${DS}/input/${f}" >&2; miss=1; }
      done
      for s in gfs hrrr rtofs nwm; do
        [ -n "$(find "${DS}/input/comin/${s}" -type f -print -quit 2>/dev/null)" ] || { echo "MISSING: ${DS}/input/comin/${s}/ (no files)" >&2; miss=1; }
      done
      compgen -G "${DS}/input/dcom/${PDY}/coops_waterlvlobs/*.xml" >/dev/null || { echo "MISSING: ${DS}/input/dcom/${PDY}/coops_waterlvlobs/*.xml" >&2; miss=1; }
      compgen -G "${DS}/input/dcom/*/can_streamgauge/02OA016_hydrometric.csv" >/dev/null || { echo "MISSING: ${DS}/input/dcom/<day>/can_streamgauge/02OA016_hydrometric.csv" >&2; miss=1; }
      [ "${miss}" = 0 ] || { echo "FATAL: the dataset lacks what the ATL prep card reads (see the header of stofs_3d_atl.sh)"; exit 1; }
      clear_com
      clean_work
      echo "staging ${DS}/input/com -> ${CI_COM} (LEVEL=${LEVEL}, ${VARIANT}); comin and dcom are read in place from ${DS}/input"
      # The cards only read the init state (it is copied into the run directory), so it is hard-linked: 26 GB would not copy quickly. rsync copies instead when the
      # dataset is on another filesystem, so that is said up front. comin and dcom are not linked at all. MJ (10/15/26)
      [ "$(stat -c %d "${DS}/input/com")" = "$(stat -c %d "${CI_COM}")" ] || echo "WARN: ${DS} and ${CI_COM} are on different filesystems: the init state is copied, not linked"
      # Only the two day directories, each linked against itself (an absolute --link-dest, or rsync copies); -a would also copy the dataset's mode onto com/ and nos/. The files stay
      # read-only (shared inodes), the day directories are writable (Du+w). MJ (10/15/26)
      local dsa d
      dsa=$(realpath -- "${DS}")
      for d in "${PDYM1}" "${PDY}"; do
        [ ! -d "${dsa}/input/com/nos/${RUN}.${d}" ] || rsync -a --chmod=Du+w --link-dest="${dsa}/input/com/nos/${RUN}.${d}" "${dsa}/input/com/nos/${RUN}.${d}/" "${CI_COM}/nos/${RUN}.${d}/"
      done
      ;;
    live)
      setup_modules
      : "${DCOM_BUNDLE:?DATA_MODE=live needs DCOM_BUNDLE=<case bundle dir holding dcom/ and seeds/dyn_seed_<PDY-1>/> (run guide section 4.2); otherwise use DATA_MODE=frozen}"
      local b="${DCOM_BUNDLE}" seeds="${DCOM_BUNDLE}/seeds/dyn_seed_${PDYM1}" miss=0 f
      for f in $(dcom_required | sed "s#^#${b}/dcom/#") "${seeds}/staout_1" "${seeds}/${RUN}.t${CYC}z.avg_bias"; do
        [ -s "${f}" ] || { echo "MISSING: ${f}" >&2; miss=1; }
      done
      [ "${miss}" = 0 ] || { echo "FATAL: DCOM_BUNDLE=${b} lacks the files above (before the ~100 GB download)"; exit 1; }
      clear_com
      clean_work
      mkdir -p "${CI_COM}" "${CI_COMIN}"
      echo "staging the public inputs for ${PDY}${CYC} into ${CI_COMIN} (login node)"
      python3 "${HOMEnos}/ush/stage_comin.py" --pdy "${PDY}" --cyc "${CYC}" --comroot "${CI_COMIN}" --profile stofs_3d_atl --jobs 8 \
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

# What run_stage.sh needs to submit this variant's <stage> card, as shell for it to eval (one --export value, so no commas). PDY and CYC come from the environment.
# RPTDIR is the card's own default, read with OFS=${RUN} because the card pins that name (run_stage.sh's OFS is the variant name); the log is
# <RPTDIR>/<prefix>.<jobid>.out, the prefix from its _LOG_PREFIX line so the two cannot drift. MJ (10/15/26)
cmd_card_env() {
  local st=${1:?usage: stofs_3d_atl.sh card-env <stage>} card pfx dcom rpt v
  check_cycle_args
  set_variant "${OFS}"
  ci_paths
  card="${HOMEnos}/slurm/${CARDS}/jnos_${st}_00.sh"
  pfx=$(sed -n 's#^_LOG_PREFIX=.*/\([^/]*\)\.\${_JOBID}.*#\1#p' "${card}" | head -1)
  [ -n "${pfx}" ] || { echo "FATAL: no _LOG_PREFIX in ${card}" >&2; exit 1; }
  rpt=$(unset RPTDIR; OFS=${RUN}; card_value "${card}" RPTDIR) || exit 1
  dcom="${DS}/input/dcom"
  [ "${DATA_MODE:-frozen}" != live ] || dcom="${DCOM_BUNDLE:?DCOM_BUNDLE not set}/dcom"
  for v in "${PACKAGEROOT}" "${HOMEnos}" "${CI_COM}" "${CI_COMIN}" "${dcom}" "${NOS_PTMP}" "${VENV_PATH:-}"; do
    case "${v}" in *,*) echo "FATAL: a comma in '${v}' would split the sbatch --export list" >&2; exit 1 ;; esac
  done
  # Inherited values would bypass what the cards derive; the cards also clear most of these themselves. MJ (10/15/26)
  echo "unset COMOUT COMOUTroot DATA COMIN COMINgfs COMINhrrr COMINrtofs_2d COMINrtofs_3d COMINnwm COMINrerun COMROOT DATAROOT RPTDIR OFS_CONFIG"
  printf 'ATL_RUN=%q\nATL_COMIN=%q\nATL_RPTDIR=%q\nATL_LOGPFX=%q\nATL_EXPORTS=%q\n' "${RUN}" "${CI_COMIN}" "${rpt}" "${rpt}/${pfx}" \
    "OFS=${RUN},PACKAGEROOT=${PACKAGEROOT},${COMVAR}=${CI_COM},EXECnos=${HOMEnos}/exec,DCOMROOT=${dcom},COLDSTART=NO"
}

# After a passing stage: the cards keep the job's run directory (~150 GB a cycle); a failed one is kept for debugging until the next Stage Data. MJ (10/15/26)
cmd_clean_job() {
  set_variant "${OFS}"
  clean_work "${1:?usage: stofs_3d_atl.sh clean-job <jobid>}"
}

cmd_verify() {
  level_setup
  setup_env
  mkdir -p "${LOGDIR}"
  local rc=0 ops_dir cmp="${COMPARE_ATL:-${SCRIPT_DIR}/compare_atl.py}"
  ops_dir="${DS}/ref/ops"
  [ "${DATA_MODE}" != live ] || ops_dir="${LIVE}/ops"
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
      # pass/fail against ops: standalone is the same model and forcing (median 5 mm); coupled differs in the DATM forcing (median 15 mm). MJ (10/22/26)
      local med=5
      [ "${VARIANT}" != coupled ] || med=15
      python3 "${cmp}" ops --ops-dir "${ops_dir}" --out "${CI_COM}" --variant "${VARIANT}" --pdy "${PDY}" --warn-mm "${OPS_WARN_MM:-500}" --fail-median-mm "${OPS_FAIL_MEDIAN_MM:-${med}}" --fail-over-10cm "${OPS_FAIL_OVER_10CM:-10}" || grc=1
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
  local seed_rt
  seed_rt=$(realpath -m -- "${SEED_RT:-/work2/noaa/nos-surge/mjisan/nos-workflow-rt}")   # an absolute path: --link-dest resolves a relative one against the destination. MJ (10/14/26)
  local top="${seed_rt}/stofs_3d_atl" dest="${seed_rt}/stofs_3d_atl/${VARIANT}/${PDY}${CYC}"
  local f s miss=0 refs level=${SEED_LEVEL:-cycle}
  case "${level}" in smoke|cycle) ;; *) echo "FATAL: SEED_LEVEL must be smoke or cycle (got '${level}')" >&2; exit 2 ;; esac
  refs=$(python3 "${cmp}" files --variant "${VARIANT}" --level "${level}" --pdy "${PDY}") || { echo "FATAL: compare_atl.py files failed" >&2; exit 1; }
  for f in $(com_state_files) ${refs}; do
    [ -s "${src_com}/${f}" ] || { echo "MISSING: ${src_com}/${f}" >&2; miss=1; }
  done
  for s in gfs hrrr rtofs nwm; do
    [ -n "$(find "${src_comin}/${s}" -type f -print -quit 2>/dev/null)" ] || { echo "MISSING: ${src_comin}/${s}/ (no files)" >&2; miss=1; }
  done
  for f in $(dcom_required); do
    [ -s "${src_dcom}/${f}" ] || { echo "MISSING: ${src_dcom}/${f}" >&2; miss=1; }
  done
  compgen -G "${src_dcom}/${PDY}/coops_waterlvlobs/*.xml" >/dev/null || { echo "MISSING: ${src_dcom}/${PDY}/coops_waterlvlobs/*.xml" >&2; miss=1; }
  compgen -G "${src_dcom}/*/can_streamgauge/02OA016_hydrometric.csv" >/dev/null || { echo "MISSING: ${src_dcom}/<day>/can_streamgauge/02OA016_hydrometric.csv" >&2; miss=1; }
  # The run's archived param.nml tells the variant apart: nws = 2 (sflux) standalone, nws = 4 (DATM) coupled. A run that has none is not checked. MJ (10/14/26)
  local pn="${src_com}/nos/${RUN}.${PDY}/rerun/${RUN}.t${CYC}z.param.nml" want_nws=2 nws
  [ "${VARIANT}" = standalone ] || want_nws=4
  if [ -s "${pn}" ]; then
    nws=$(sed -n 's/^[[:space:]]*nws[[:space:]]*=[[:space:]]*\(-\{0,1\}[0-9]*\).*/\1/p' "${pn}" | head -1)
    [ "${nws}" = "${want_nws}" ] || { echo "MISSING: ${src_com} is not a ${VARIANT} run (${pn} has nws=${nws:-?}, expected ${want_nws})" >&2; miss=1; }
  else
    echo "WARN: no ${pn}; the variant of ${src_com} is not checked" >&2
  fi
  [ "${miss}" = 0 ] || { echo "FATAL: the sources above are not a finished ${VARIANT} ${PDY}${CYC} run (COMROOT, comin, dcom arguments)" >&2; exit 1; }
  if [ -e "${dest}" ]; then
    if [ "${FORCE:-0}" = 1 ]; then
      rm -rf "${dest}"
    elif [ -f "${dest}/.seeded_ok" ] && [ "${level}" = cycle ] && [ "$(dataset_level "${dest}")" = smoke ]; then
      echo "upgrading the smoke dataset ${dest} to cycle"   # the copies below are idempotent and the marker changes last. MJ (10/14/26)
    else
      echo "FATAL: ${dest} exists; FORCE=1 replaces it (a smoke dataset is upgraded by seeding with the default SEED_LEVEL=cycle, no FORCE)" >&2
      exit 1
    fi
  fi
  mkdir -p "${dest}/input/com" "${dest}/input/comin" "${dest}/input/dcom" "${dest}/ref"
  echo "seeding ${dest} from ${src_com}, ${src_comin}, ${src_dcom}"
  # --files-from turns off the recursion -a implies, so -r is explicit; the fixed modes (read-only files, as the chmod below leaves them) match across the two variants, so the second can hard-link against the first. MJ (10/15/26)
  local lcom=() lcomin=() list PERM=(--chmod=Do+rx,Fo+r,Fa-w)
  if [ -d "${top}/${SIBLING}/${PDY}${CYC}/input" ]; then
    lcom=(--link-dest="${top}/${SIBLING}/${PDY}${CYC}/input/com")
    lcomin=(--link-dest="${top}/${SIBLING}/${PDY}${CYC}/input/comin")
  fi
  list=$(com_state_files)
  [ ! -s "${src_com}/nos/${RUN}.${PDYM1}/rerun/${RUN}.t${CYC}z.param.nml" ] || list+=$'\n'"nos/${RUN}.${PDYM1}/rerun/${RUN}.t${CYC}z.param.nml"
  # -L: the coupled init file is a symlink to the standalone one. MJ (10/14/26)
  echo "${list}" | rsync -arL "${PERM[@]}" --files-from=- ${lcom[@]+"${lcom[@]}"} "${src_com}/" "${dest}/input/com/"
  # only the day directories of PDY-1 and PDY (<source>.<day>), the cycle's whole input window. MJ (10/14/26)
  for s in gfs hrrr rtofs nwm; do
    for f in "${PDYM1}" "${PDY}"; do
      [ ! -d "${src_comin}/${s}/${s}.${f}" ] || echo "${s}/${s}.${f}/"
    done
  done | rsync -ar "${PERM[@]}" --files-from=- ${lcomin[@]+"${lcomin[@]}"} "${src_comin}/" "${dest}/input/comin/"
  for s in gfs hrrr rtofs nwm; do
    [ -d "${dest}/input/comin/${s}" ] || { echo "FATAL: no ${s}.${PDYM1} or ${s}.${PDY} directory under ${src_comin}/${s}" >&2; exit 1; }
  done
  # a trailing slash plus -r makes --files-from copy the directory contents. MJ (10/14/26)
  dcom_groups | while read -r f; do [ ! -e "${src_dcom}/${f}" ] || echo "${f}"; done | rsync -ar "${PERM[@]}" --files-from=- "${src_dcom}/" "${dest}/input/dcom/"
  echo "${refs}" | rsync -arL "${PERM[@]}" --files-from=- "${src_com}/" "${dest}/ref/"
  [ "${level}" = smoke ] || fetch_ops "${dest}/ref/ops"   # the ops products are compared at LEVEL=full only, and a smoke source has no post output. MJ (10/14/26)
  echo "level=${level}" > "${dest}/.seeded_ok"
  find "${dest}/input" -type f -exec chmod a-w {} +   # com shares these inodes; every writer replaces files (new file + rename), none opens one in place. MJ (10/15/26)
  chmod -R o+rX "${dest}" || true
  chmod o+x "${top}" "${top}/${VARIANT}" 2>/dev/null || true
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
  stage|verify|card-env|clean-job)
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/common.sh"
    case "${OFS}" in stofs_3d_atl_ufs_standalone|stofs_3d_atl_ufs) ;; *) echo "FATAL: ${CMD} runs with CI_OFS=stofs_3d_atl_ufs_standalone or stofs_3d_atl_ufs (got ${OFS})" >&2; exit 2 ;; esac
    "cmd_${CMD//-/_}" "$@"
    ;;
  *) usage >&2; exit 2 ;;
esac
