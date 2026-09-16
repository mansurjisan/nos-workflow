#!/usr/bin/env bash
# Stage Data stage: frozen -> require a pre-staged dataset; live -> stage it from NODD. Then ensure the first-cycle nowcast init file exists, generating or recovering it if not.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"
setup_env

: "${PDY:?PDY not set}"
: "${CYC:?CYC not set}"
: "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"
DATA_MODE=${DATA_MODE:-frozen}

NOWCAST_CARD="${HOMEnos}/slurm/secofs_ufs/jnos_nowcast_00.sh"
# Local only: run_stage.sh recomputes this same path for the batch-side value, since an export here dies with this sh step.
COMROOT_STAGED="${RT_DATA_ROOT}/comin_${PDY}${CYC}"

case "${DATA_MODE}" in
  frozen)
    [ -f "${COMROOT_STAGED}/.seeded_ok" ] || {
      echo "FATAL: no ${COMROOT_STAGED}/.seeded_ok sentinel -- dataset missing or an interrupted bootstrap.sh/freeze_dataset.sh copy."
      echo "Run freeze_dataset.sh for PDY=${PDY} CYC=${CYC}, or set DATA_MODE=live."
      exit 1
    }
    echo "OK: frozen dataset present at ${COMROOT_STAGED} (sentinel verified)"
    ;;
  live)
    mkdir -p "${COMROOT_STAGED}"
    echo "staging live NODD data into ${COMROOT_STAGED}"
    if ! python3 "${HOMEnos}/ush/stage_comin.py" --pdy "${PDY}" --cyc "${CYC}" --comroot "${COMROOT_STAGED}"; then
      echo "FATAL: stage_comin.py failed -- pick a COMPLETED published cycle (an unpublished/partial cycle exits nonzero on missing files)"
      exit 1
    fi
    ;;
  *)
    echo "FATAL: unknown DATA_MODE '${DATA_MODE}' (expected frozen|live)"
    exit 1
    ;;
esac

COMROOT=$(card_value "${NOWCAST_CARD}" COMROOT)
COMOUT="${COMROOT}/nos/${OFS}.${PDY}"
INIT_FILE="${COMOUT}/${OFS}.t${CYC}z.${PDY}.init.nowcast.nc"

if [ -s "${INIT_FILE}" ]; then
  echo "OK: init file present: ${INIT_FILE}"
  echo "stage_data PASS"
  exit 0
fi

echo "init file missing: ${INIT_FILE}"
mkdir -p "${COMOUT}"

case "${DATA_MODE}" in
  frozen)
    FROZEN_INIT="${COMROOT_STAGED}/init/$(basename "${INIT_FILE}")"
    [ -s "${FROZEN_INIT}" ] || {
      echo "FATAL: frozen dataset has no init file at ${FROZEN_INIT} -- re-run freeze_dataset.sh"
      exit 1
    }
    cp -p "${FROZEN_INIT}" "${INIT_FILE}"
    echo "OK: copied init file from frozen dataset -> ${INIT_FILE}"
    ;;
  live)
    HGRID="${HOMEnos}/fix/${OFS}/${OFS}.hgrid.gr3"
    VGRID="${HOMEnos}/fix/${OFS}/${OFS}.vgrid.in"
    [ -s "${VGRID}" ] || { echo "FATAL: ${VGRID} not found"; exit 1; }
    NVRT=$(awk 'NR==2{print $1; exit}' "${VGRID}")
    [ -n "${NVRT}" ] || { echo "FATAL: could not parse nvrt from line 2 of ${VGRID}"; exit 1; }
    echo "generating cold-start rest state (nvrt=${NVRT}) -> ${INIT_FILE}"
    python3 "${HOMEnos}/tools/make_cold_start_hotstart.py" --hgrid "${HGRID}" --nvrt "${NVRT}" --out "${INIT_FILE}"
    ;;
esac

echo "stage_data PASS"
