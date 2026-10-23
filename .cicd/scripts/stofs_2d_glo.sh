#!/usr/bin/env bash
# STOFS-2D-Global stages of the Hercules Jenkins pipeline (OFS=stofs_2d_glo; manual and scheduled builds). MJ (10/22/26)
#   stofs_2d_glo.sh stage    Stage Data (called by stage_data.sh): frozen = clear the 2D-Global state of earlier cycles from the shared CI com, then link (hard
#                            links, copy across file systems) the dataset for PDY/CYC from the RT root into it; live = tools/hercules_2d_glo_stage_forcing.sh
#                            --rm-raw on this login/front-end node, which is where the SECOFS live staging (stage_comin.py) runs too, since compute nodes have
#                            no internet
#   stofs_2d_glo.sh card-env <stage>   eval-able shell for run_stage.sh: the card, sbatch flags, timeout, exports and log prefix of the stage's job
#   stofs_2d_glo.sh verify   Verify: compare_2dglo.py against the dataset's reference / ops products
#   stofs_2d_glo.sh seed <PDY> <CYC> [cold]   one-time, by hand: build the frozen dataset from a finished run (see below)
# Env (Jenkinsfile): PDY CYC LEVEL DATA_MODE RT_DATA_ROOT NOS_PTMP PACKAGEROOT VENV_PATH; SLURM_CI_ACCOUNT and SLURM_CI_QOS are read by run_stage.sh;
# optional CMP_TOL (default 1e-3), OPS_WARN_MM (default 500), OPS_STATE_SRC. MJ (10/15/26)
#
# The model stages are the SECOFS Jenkins stages: Prep, Nowcast, Forecast and Post each call run_stage.sh <stage> <PDY> <CYC>, which submits one job of the
# ops chain, waits (timeout = the job's walltime + 1 h), gates on its STAGE_SUMMARY and moves on. Then Verify calls `verify`. The jobs are the ones
# slurm/stofs_2d_glo/launch_stofs_2d_glo.sh queues, with the same sbatch flags and walltimes (card-env repeats them; a test compares the two):
#   Prep      adcprep (COLD=1 only), gfs ncst, gfs fcst   prep card      -N 1 -n 1 --mem=64G   0:50 (3:50 cold)
#   Nowcast   spinup (COLD=1 only), tide ncst, surf ncst  nowcast card   -N 52                 1:20 (2:20 cold)
#   Forecast  tide fcst, surf fcst                        forecast card  -N 52                 2:00
#   Post      ncdiff, ncrcat                              prep card      -N 1 -n 1 --mem=100G  1:15       (the post job logs under the prep card's name)
# LEVEL   Jenkins stages run                       COLD   Verify
#   smoke  Prep Nowcast                              0      regress --level smoke: rerun/stofs_2d_glo_{tide,surf}.61.nc against the reference
#   cycle  Prep Nowcast Forecast Post                0      regress --level cycle: the same plus points.*.nc; ops comparison reported
#   full   Prep Nowcast Forecast Post                1      the same as cycle (a cold start is deterministic); ops comparison reported
# Prep finds the staged ops forcing and skips its GFS steps, so SUBMIT_GFS is not used. smoke and cycle continue from the previous cycle's hotstart/restart, so
# they use the 06z-type dataset; full cold-starts and uses the 00z-type dataset. A job in a bad Slurm state, or without STAGE_SUMMARY status=PASS, fails its
# stage. DATA_MODE=live continues from the state already in the shared com (LEVEL=full first, then cycle at +6 h) and keeps it (live only prunes other days, see below); the smoke/cycle stage
# checks that state before it downloads, and when it has none starts from the public ops state: the .68 hotstart files of the cycle - 126 h from S3, nod_equi regenerated for their base
# date, the decomposition reused from COMGES (stage_ops_state; run guide section 3.4; OPS_STATE_SRC=<PDY><CC> picks another source cycle). frozen clears it and starts from the dataset. live keeps COMGES and the PDY and previous-cycle days but removes the
# other days' 2D dirs and the other ops_s3 cycle dirs, so a daily scheduled cold start never fills the CI storage. MJ (10/22/26)
#
# Layout, the SECOFS one: com/, rpt/ and work/ are the shared $NOS_PTMP/$LOGNAME/{com,rpt,work}, the cards' own defaults; COMROOT_2DGLO is that com (an inherited
# value is ignored). RUN stofs_2d_glo is unique, so the 2D-Global state sits beside SECOFS's and ATL's without touching it: COMGES is com/nos/stofs_2d_glo and a
# cycle is com/nos/stofs_2d_glo.<PDY>. Stage (frozen) removes only those two kinds of names (nos/stofs_2d_glo and nos/stofs_2d_glo.<8 digits>), then the old
# $NOS_PTMP/$LOGNAME/com_2dglo_ci root once. The jobs run with KEEPDATA=NO, so a job removes its own work directory.
# What the jobs write into the linked files: nothing in place. The forcing (rerun/stofs_2d_glo_{ncst,fcst}.{221,222,225}.nc) is only read (symlinked into the
# ADCIRC run directory, read by ncks/ncrcat), but rerun/ also receives the jobs' own products, so it is a real, writable directory in com holding hard links of
# the dataset's forcing. nod_equi and the 4064 tar are replaced by rename, never written. These three kinds are read-only (seed and Bootstrap chmod a-w; com shares
# their inodes). The chain files (hotstart, restart) are copied into the run directory with their mode and ADCIRC rewrites that copy, so a read-only chain file
# would fail the run: they stay writable. The .json beside the tar is rewritten in place when the decomposition is rebuilt, so it is copied, not linked. MJ (10/15/26)
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
RUN=stofs_2d_glo

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

# Everything the stage, card-env and verify commands share. MJ (10/15/26)
level_setup() {
  check_cycle_args
  LEVEL=${LEVEL:-smoke}
  case "${LEVEL}" in
    smoke|cycle) COLD=0 ;;
    full)        COLD=1 ;;
    *) echo "FATAL: LEVEL must be smoke, cycle or full (got '${LEVEL}')" >&2; exit 2 ;;
  esac
  DATA_MODE=${DATA_MODE:-frozen}
  : "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"
  CI_COM="${NOS_PTMP}/${LOGNAME}/com"
  COMROOT_2DGLO="${CI_COM}"
  DS="${RT_DATA_ROOT}/stofs_2d_glo/${PDY}${CYC}"
  LOGDIR="${WORKSPACE:-.}/ci_logs"
  export NOS_PTMP COMROOT_2DGLO
}

# Clears the 2D-Global state of earlier cycles from the shared com: nos/stofs_2d_glo (COMGES) and every nos/stofs_2d_glo.<8 digits>, names matched exactly, so
# SECOFS's and ATL's directories and anything else stay. The com root must be the CI's $NOS_PTMP/$LOGNAME/com; no root, parent or target may be a symlink.
# All targets are validated before the first rm, so a refusal never follows a delete. Then removes the old com_2dglo_ci root once.
# With day arguments (YYYYMMDD, live mode) COMGES and those days' directories are kept and the other days removed. MJ (10/22/26)
clear_com() {
  local p c t n rm=()
  case "${LOGNAME}" in ""|*/*|.|..) echo "FATAL: refusing to clear com: odd LOGNAME '${LOGNAME}'" >&2; exit 1 ;; esac
  p=$(realpath -m -- "${NOS_PTMP}")
  c="${p}/${LOGNAME}/com"
  [ "$(realpath -m -- "${CI_COM}")" = "${c}" ] || { echo "FATAL: refusing to clear ${CI_COM}: it is not ${c} (symlink?)" >&2; exit 1; }
  for t in "${c}" "${c}/nos"; do
    [ ! -L "${t}" ] || { echo "FATAL: refusing to clear under ${t}: it is a symlink" >&2; exit 1; }
  done
  for t in "${c}/nos/${RUN}" "${c}/nos/${RUN}."*; do
    n=${t##*/}
    [[ "${n}" =~ ^${RUN}(\.[0-9]{8})?$ ]] && { [ -e "${t}" ] || [ -L "${t}" ]; } || continue
    [ "$#" = 0 ] || [ "${n}" = "${RUN}" ] || [[ " $* " == *" ${n##*.} "* ]] || rm+=("${t}")
    [ "$#" != 0 ] || rm+=("${t}")
  done
  for t in ${rm[@]+"${rm[@]}"}; do
    { [ ! -L "${t}" ] && [ -d "${t}" ] && [ "$(realpath -m -- "${t}")" = "${t}" ]; } || { echo "FATAL: refusing to remove ${t}: it is a symlink or not a plain directory" >&2; exit 1; }
  done
  for t in ${rm[@]+"${rm[@]}"}; do
    rm -rf -- "${t}"
    [ "$#" = 0 ] || echo "removed ${t}"
  done
  mkdir -p -- "${c}/nos"
  t="${p}/${LOGNAME}/com_2dglo_ci"
  if [ -L "${t}" ]; then echo "WARN: leaving ${t}: it is a symlink" >&2
  elif [ -d "${t}" ]; then rm -rf -- "${t}"; echo "removed the old CI com ${t}"
  fi
}

# Removes the other cycles' ops download dirs (names of exactly 10 digits) under ops_s3, never a symlink; an OPS_WORK in the environment is the caller's own. MJ (10/22/26)
prune_ops_s3() {
  local o="${NOS_PTMP}/${LOGNAME}/ops_s3" t
  [ -z "${OPS_WORK:-}" ] && [ -d "${o}" ] && [ ! -L "${o}" ] || return 0
  for t in "${o}"/*; do
    [[ "${t##*/}" =~ ^[0-9]{10}$ ]] && [ "${t##*/}" != "${PDY}${CYC}" ] && [ -d "${t}" ] && [ ! -L "${t}" ] || continue
    rm -rf -- "${t}"
    echo "removed ${t}"
  done
}

# Live LEVEL=smoke/cycle with no chain state in the CI com: the public ops state (run guide section 3.4). The .68 files of the cycle - 126 h are ops' state at
# cycle + 120 h, so at the chain time PREV (cycle - 6 h). Writes only the two PREV chain files and nod_equi; the decomposition in COMGES must exist (an earlier cold start
# or frozen build). Each file is downloaded to <target>.part and renamed into place only after both pass the time check, so a wrong or partial file is never a chain file. MJ (10/22/26)
stage_ops_state() {
  local ges="${CI_COM}/nos/${RUN}" prevd="${CI_COM}/nos/${RUN}.${PREV:0:8}" b=https://noaa-gestofs-pds.s3.amazonaws.com bytes=1472354116
  local src=${OPS_STATE_SRC:-$(date -u -d "${PDY} ${CYC}:00 126 hours ago" +%Y%m%d%H)} s t f kind use base y m d h line mt
  local -A put=()
  [[ "${src}" =~ ^[0-9]{8}(00|06|12|18)$ ]] || { echo "FATAL: OPS_STATE_SRC must be YYYYMMDDCC (got '${src}')" >&2; exit 1; }
  for t in "${ges}" "${prevd}"; do
    [ ! -L "${t}" ] || { echo "FATAL: refusing to write under ${t}: it is a symlink" >&2; exit 1; }
  done
  for kind in stofs_2d_glo_4064.tar stofs_2d_glo_4064.tar.json; do
    [ -s "${ges}/${kind}" ] || { echo "FATAL: no ${ges}/${kind}: the ops-state start reuses the 4064-rank decomposition; run one DATA_MODE=live LEVEL=full build (cold start) or a frozen 2D-Global build first" >&2; exit 1; }
  done
  mkdir -p "${ges}" "${prevd}"
  setup_env
  for s in tide surf; do
    [ "${s}" = tide ] && kind=hotstart || kind=restart
    t="${prevd}/${RUN}.t${PREV:8:2}z.${kind}"
    for f in "${t}" "${t}.part" "${ges}/${RUN}_nod_equi" "${ges}/${RUN}_nod_equi.new"; do
      [ ! -L "${f}" ] || { echo "FATAL: refusing to write ${f}: it is a symlink" >&2; exit 1; }
    done
    if [ "$(stat -c %s "${t}" 2>/dev/null || echo 0)" = "${bytes}" ]; then use=${t}
    else
      if [ "$(stat -c %s "${t}.part" 2>/dev/null || echo 0)" != "${bytes}" ]; then
        echo "downloading ${b}/${RUN}.${src:0:8}/${src:8:2}/rerun/${RUN}_${s}.68.nc -> ${t}"
        curl -fsSL --retry 3 -C - -o "${t}.part" "${b}/${RUN}.${src:0:8}/${src:8:2}/rerun/${RUN}_${s}.68.nc" || { echo "FATAL: download of the ${s} .68 file failed" >&2; exit 1; }
      fi
      [ "$(stat -c %s "${t}.part" 2>/dev/null || echo 0)" = "${bytes}" ] || { echo "FATAL: ${t}.part is not ${bytes} bytes" >&2; exit 1; }
      use=${t}.part
    fi
    put["${t}"]=${use}
  done
  # time of both files = the chain time minus the units base date; prints the base date as YYYY MM DD HH and the time. MJ (10/22/26)
  base=$(python3 -I - "${PREV}" "${put[${prevd}/${RUN}.t${PREV:8:2}z.hotstart]}" "${put[${prevd}/${RUN}.t${PREV:8:2}z.restart]}" <<'PY'
import re, sys
from datetime import datetime
import netCDF4
chain = datetime.strptime(sys.argv[1], "%Y%m%d%H")
got = []
for f in sys.argv[2:]:
    with netCDF4.Dataset(f) as ds:
        v = ds.variables["time"]
        m = re.match(r"seconds since (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", v.units)
        got.append((datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"), float(v[:].ravel()[0])))
for (b, t), f in zip(got, sys.argv[2:]):
    print(f"{f}: base {b} time {t:.0f} s, expected {(chain - b).total_seconds():.0f} s", file=sys.stderr)
if got[0] != got[1] or any(t != (chain - b).total_seconds() for b, t in got):
    sys.exit(1)
print(got[0][0].strftime("%Y %m %d %H"), int(got[0][1]))
PY
  ) || { rm -f -- "${prevd}"/*.part; echo "FATAL: the ops state files do not hold the model time of ${PREV} (above); nothing was staged" >&2; exit 1; }
  read -r y m d h mt <<<"${base}"
  rm -f "${ges}/${RUN}_nod_equi.new"
  "${HOMEnos}/exec/${RUN}_tide_fac" --length 365 --year "${y}" --month "${m}" --day "${d}" --hour "${h}" --outputformat simple --outputdir "${ges}" --outputname "${RUN}_nod_equi.new" > /dev/null \
    || { rm -f "${ges}/${RUN}_nod_equi.new"; echo "FATAL: ${RUN}_tide_fac failed" >&2; exit 1; }
  read -r line < "${ges}/${RUN}_nod_equi.new" || true
  set -- ${line}
  [ "$#" -ge 4 ] && [ "$((10#$1))" = "$((10#${h}))" ] && [ "$((10#$2))" = "$((10#${d}))" ] && [ "$((10#$3))" = "$((10#${m}))" ] && [ "$((10#$4))" = "$((10#${y}))" ] \
    || { rm -f "${ges}/${RUN}_nod_equi.new"; echo "FATAL: nod_equi line 1 is '${line}', expected '${h} ${d} ${m} ${y}'" >&2; exit 1; }
  for f in "${!put[@]}"; do [ "${put[${f}]}" = "${f}" ] || mv -f -- "${put[${f}]}" "${f}"; done
  mv -f -- "${ges}/${RUN}_nod_equi.new" "${ges}/${RUN}_nod_equi"
  echo "ops state ${src}: base date ${y}-${m}-${d} ${h}z, model time ${mt} s at ${PREV}; chain files ${prevd}/${RUN}.t${PREV:8:2}z.{hotstart,restart}, nod_equi regenerated, decomposition kept"
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
      local with_state=1 f miss=0 files
      [ "${LEVEL}" != full ] || with_state=0
      # prep runs both GFS steps at every level and skips each when its forcing is staged, so ncst and fcst are staged even for smoke. MJ (10/15/26)
      for f in $(input_files "${with_state}" ncst fcst); do
        [ -s "${DS}/input/${f}" ] || { echo "MISSING: ${DS}/input/${f}" >&2; miss=1; }
      done
      [ "${miss}" = 0 ] || { echo "FATAL: the dataset lacks what LEVEL=${LEVEL} needs: the ncst and fcst forcing, and for smoke/cycle COMGES and the previous cycle's chain files (a cold dataset has none; use the dataset of a COLD=0 cycle, or re-seed it)"; exit 1; }
      clear_com
      echo "staging ${DS}/input -> ${CI_COM} (LEVEL=${LEVEL})"
      # The run never writes into these files in place (see the header), so they are hard-linked; the .json is rewritten in place when the decomposition is rebuilt, so it is copied.
      # The directories are made writable (Du+w) whatever the dataset's modes: rerun/ receives the jobs' own products. MJ (10/15/26)
      files=$(input_files "${with_state}" ncst fcst)
      # --no-implied-dirs: the shared com/nos (SECOFS and ATL too) must keep its own mode, mtime and group; missing parents are still created. The json and the chain files
      # (rewritten through their copies) are copied, the rest linked. MJ (10/15/26)
      find "${DS}/input" -type f \( -name '*.2[0-9][0-9].nc' -o -name '*_4064.tar' -o -name '*_nod_equi' \) -exec chmod a-w {} +   # existing datasets too; idempotent. MJ (10/15/26)
      { grep -vE '\.json$|\.t[0-9]{2}z\.(hotstart|restart)$' <<<"${files}" || true; } | rsync -a --no-implied-dirs --chmod=Du+w --files-from=- --link-dest="$(realpath -- "${DS}")/input" "${DS}/input/" "${CI_COM}/"
      { grep -E '\.json$|\.t[0-9]{2}z\.(hotstart|restart)$' <<<"${files}" || true; } | rsync -a --no-implied-dirs --chmod=Du+w --files-from=- "${DS}/input/" "${CI_COM}/"
      du -sh "${CI_COM}/nos/${RUN}"* | sed 's/^/  /'   # MJ (10/15/26)
      ;;
    live)
      local rc=0 f miss=0 ops_state=0
      # Before the 39 GB download: the COLD=0 levels continue from the chain state already in COMROOT_2DGLO, or else start from the public ops state. MJ (10/22/26)
      if [ "${LEVEL}" != full ]; then
        for f in $(input_files 1); do
          [ -s "${CI_COM}/${f}" ] || { echo "MISSING: ${CI_COM}/${f}" >&2; miss=1; }
        done
        [ "${miss}" = 0 ] || { ops_state=1; echo "no chain state in ${CI_COM}: starting from the ops state ${OPS_STATE_SRC:-$(date -u -d "${PDY} ${CYC}:00 126 hours ago" +%Y%m%d%H)} (cycle - 126 h)"; }
      fi
      mkdir -p "${CI_COM}"
      # After the chain-state check, which reads PREV's day (kept). COMGES stays: the chain state (nod_equi, decomposition) a later live LEVEL=cycle continues from; a cold start rebuilds the decomposition itself. PDY stays so a rerun skips the download. MJ (10/22/26)
      clear_com "${PDY}" "${PREV:0:8}"
      prune_ops_s3
      [ "${ops_state}" = 0 ] || stage_ops_state
      du -sh "${CI_COM}/nos/${RUN}"* 2>/dev/null | sed 's/^/  /' || true
      echo "staging the ops forcing for ${PDY}${CYC} into ${CI_COM} (login node; COMGES and the ${PDY}/${PREV:0:8} days stay)"
      bash "${HOMEnos}/tools/hercules_2d_glo_stage_forcing.sh" --rm-raw "${PDY}" "${CYC}" || rc=$?
      case "${rc}" in
        0) ;;
        3) echo "WARN: the ops reference station files were not downloaded; Verify skips the ops comparison" ;;
        *) echo "FATAL: hercules_2d_glo_stage_forcing.sh failed (rc=${rc})"; exit 1 ;;
      esac
      ;;
    *) echo "FATAL: unknown DATA_MODE '${DATA_MODE}' (expected frozen|live)"; exit 1 ;;
  esac
  echo "stage_data PASS"
}

# What run_stage.sh needs to submit this stage's job, as shell for it to eval: the sbatch flags and walltimes are those of launch_stofs_2d_glo.sh (a test
# compares them; the launcher cannot be sourced, it queues the whole chain), the segment and stream lists are space separated and go in the environment of sbatch
# (--export=ALL), as the launcher does, since --export splits at commas, and the timeout is the walltime plus 1 h of headroom (run_stage.sh counts it from the job's start). Post runs on the prep card. The
# log is <RPTDIR>/<prefix>.<jobid>.out with RPTDIR and the prefix read from the card, so the post job logs under the prep name. MJ (10/19/26)
cmd_card_env() {
  local st=${1:?usage: stofs_2d_glo.sh card-env <stage>} card seg stream="" flags wall pfx rpt v h m s
  level_setup
  case "${st}" in
    prep)     card=prep;     seg="ncst fcst"; flags="-N 1 -n 1 --mem=64G"; wall=0:50:00
              [ "${COLD}" != 1 ] || { seg="adcprep ${seg}"; wall=3:50:00; } ;;
    nowcast)  card=nowcast;  seg=ncst; stream="tide surf"; flags="-N 52"; wall=1:20:00
              [ "${COLD}" != 1 ] || { seg="spinup ${seg}"; wall=2:20:00; } ;;
    forecast) card=forecast; seg=fcst; stream="tide surf"; flags="-N 52"; wall=2:00:00 ;;
    post)     card=prep;     seg="ncdiff ncrcat"; flags="-N 1 -n 1 --mem=100G"; wall=1:15:00 ;;
    *) echo "FATAL: unknown stage '${st}' (expected prep|nowcast|forecast|post)" >&2; exit 2 ;;
  esac
  card="${HOMEnos}/slurm/${RUN}/jnos_${card}_00.sh"
  [ -r "${card}" ] || { echo "FATAL: card not found: ${card}" >&2; exit 2; }
  pfx=$(sed -n 's#^_LOG_PREFIX=.*/\([^/]*\)\.\${_JOBID}.*#\1#p' "${card}" | head -1)
  [ -n "${pfx}" ] || { echo "FATAL: no _LOG_PREFIX in ${card}" >&2; exit 1; }
  rpt=$(unset RPTDIR; card_value "${card}" RPTDIR) || exit 1
  for v in "${PACKAGEROOT}" "${CI_COM}" "${NOS_PTMP}" "${VENV_PATH:-}"; do
    case "${v}" in *,*) echo "FATAL: a comma in '${v}' would split the sbatch --export list" >&2; exit 1 ;; esac
  done
  IFS=: read -r h m s <<<"${wall}"
  # The launcher's own unset list (inherited values would bypass what the cards derive), without HOMEnos, which run_stage.sh still uses and the card sets itself. MJ (10/15/26)
  echo "unset HOMEstofs EXECnos FIXnos FIXofs NOS_WORKFLOW_DIR NOS_UTILS_DIR PYTHONPATH OFS_CONFIG COMROOT DATAROOT COMIN COMINgfs COMOUT COMOUTroot COMGES DATA ADCIRC_MODE COLDSTART NCPU NUM_WRITERS TOT_NCPU NOWCAST_HOURS COLDSTART_SPINUP_DAYS ATMOSPHERIC_FORCING RPTDIR"
  printf 'export ADCIRC_SEGMENT=%q ADCIRC_STREAM=%q\n' "${seg}" "${stream}"
  # the ATL_ names of the hook variables are historical; this hook fills the same ones. MJ (10/15/26)
  printf 'ATL_RUN=%q\nATL_COMIN=%q\nATL_RPTDIR=%q\nATL_LOGPFX=%q\nATL_EXPORTS=%q\nSTAGE_CARD=%q\nSTAGE_SBATCH=%q\nTIMEOUT_S=%q\n' \
    "${RUN}" "${NOS_PTMP}/${LOGNAME}/comin_2dglo" "${rpt}" "${rpt}/${pfx}" \
    "ADCIRC_MODE=ops,KEEPDATA=NO,COMROOT_2DGLO=${CI_COM},ADCIRC_EXEC_DIR=${PACKAGEROOT}/adcirc_v56.1.0_exec,PACKAGEROOT=${PACKAGEROOT}" \
    "${card}" "-J ${RUN}_${st} -t ${wall} ${flags}" "$(( 10#${h} * 3600 + 10#${m} * 60 + 10#${s} + 3600 ))"
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
    # full compares the same files as cycle, against the ref/ the cold seed stored: tide_fac, adcprep and ADCIRC on the same inputs reproduce. MJ (10/13/26)
    if [ -d "${DS}/ref" ]; then
      python3 "${cmp}" regress --ref "${DS}/ref" --out "${CI_COM}" --pdy "${PDY}" --cyc "${CYC}" --level "${LEVEL/full/cycle}" --tol "${CMP_TOL:-1e-3}" || grc=1
    elif [ "${DATA_MODE}" = frozen ]; then
      echo "FAIL: ${DS}/ref is missing; the frozen dataset has no reference outputs"
      grc=1
    else
      echo "no frozen reference for ${PDY}${CYC} (live mode): regression comparison skipped"
    fi
    if [ "${LEVEL}" != smoke ]; then
      python3 "${cmp}" ops --out "${CI_COM}" --ops-dir "${ops_dir}" --pdy "${PDY}" --cyc "${CYC}" --warn-mm "${OPS_WARN_MM:-500}" || grc=1
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
  local src=${COMROOT_2DGLO:-${ptmp}/${user}/com}
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
  touch "${dest}/.seeded_ok"
  find "${dest}/input" -type f \( -name '*.2[0-9][0-9].nc' -o -name '*_4064.tar' -o -name '*_nod_equi' \) -exec chmod a-w {} +   # com shares these inodes; none is written in place, the chain files and the .json must stay writable (see the header). MJ (10/15/26)
  chmod -R o+rX "${dest}" || true
  du -sh "${dest}"/* | sed 's/^/  /'
  echo "seed PASS: ${dest}"
  echo "the CI account reads it only if the parent directories are traversable: chmod o+x ${seed_rt} ${seed_rt}/stofs_2d_glo"
}

CMD=${1:-}
[ "$#" -eq 0 ] || shift
case "${CMD}" in
  seed) cmd_seed "$@" ;;
  stage|verify|card-env)
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/common.sh"
    [ "${OFS}" = stofs_2d_glo ] || { echo "FATAL: ${CMD} runs with CI_OFS=stofs_2d_glo (got ${OFS})" >&2; exit 2; }
    "cmd_${CMD//-/_}" "$@"
    ;;
  *) usage >&2; exit 2 ;;
esac
