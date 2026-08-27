#!/usr/bin/env bash
# One-shot helper: freeze the currently-staged live comin tree + nowcast
# init file for one cycle into RT_DATA_ROOT, for reuse by DATA_MODE=frozen
# CI runs. Run this ONCE per cycle you want to pin as a regression dataset.
# Usage: freeze_dataset.sh <PDY> <CYC>
# Override SRC_COMIN to freeze from a comin tree other than the prep
# card's current COMROOT_STAGED default.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

PDY=${1:?usage: freeze_dataset.sh PDY CYC}
CYC=${2:?usage: freeze_dataset.sh PDY CYC}
: "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"

PREP_CARD="${HOMEnos}/slurm/${OFS}/jnos_prep_00.sh"
NOWCAST_CARD="${HOMEnos}/slurm/${OFS}/jnos_nowcast_00.sh"

SRC_COMIN=${SRC_COMIN:-$(card_value "${PREP_CARD}" COMROOT_STAGED)}
COMROOT=$(card_value "${NOWCAST_CARD}" COMROOT)
COMOUT="${COMROOT}/nos/${OFS}.${PDY}"
INIT_FILE="${COMOUT}/${OFS}.t${CYC}z.${PDY}.init.nowcast.nc"
DEST="${RT_DATA_ROOT}/comin_${PDY}${CYC}"

[ -d "${SRC_COMIN}" ] || { echo "FATAL: source comin tree not found: ${SRC_COMIN}"; exit 1; }
[ -s "${INIT_FILE}" ] || { echo "FATAL: nowcast init file not found: ${INIT_FILE}"; exit 1; }

echo "freezing cycle PDY=${PDY} CYC=${CYC}"
echo "  source comin: ${SRC_COMIN}"
echo "  source init:  ${INIT_FILE}"
echo "  dest:         ${DEST}"

mkdir -p "${DEST}/init"
rsync -a "${SRC_COMIN}/" "${DEST}/"
cp -p "${INIT_FILE}" "${DEST}/init/$(basename "${INIT_FILE}")"

echo "=== frozen dataset sizes ==="
du -sh "${DEST}"
du -sh "${DEST}"/* 2>/dev/null || true

echo "freeze_dataset PASS: ${DEST}"
