#!/usr/bin/env bash
# One-shot helper: freeze the currently-staged live comin tree + nowcast init file for one cycle into RT_DATA_ROOT, for reuse by DATA_MODE=frozen CI runs.
# Usage: freeze_dataset.sh <PDY> <CYC>
# Override SRC_COMIN to freeze from a tree other than the pipeline's live-staged default.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

PDY=${1:?usage: freeze_dataset.sh PDY CYC}
CYC=${2:?usage: freeze_dataset.sh PDY CYC}
: "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"

NOWCAST_CARD="${HOMEnos}/slurm/${OFS}/jnos_nowcast_00.sh"

# card_value would return the cards' own COMROOT_STAGED=/work/PLACEHOLDER default, not a real tree, so default SRC_COMIN to the live-staged tree instead (see run_stage.sh).
if [ -z "${SRC_COMIN:-}" ]; then
  if [ -n "${COMROOT_STAGED:-}" ]; then
    SRC_COMIN="${COMROOT_STAGED}"
  else
    echo "FATAL: SRC_COMIN not set. Set SRC_COMIN=<comin tree to freeze>, or" \
         "run with COMROOT_STAGED=<tree> (e.g. \${RT_DATA_ROOT}/comin_${PDY}${CYC}" \
         "if that is what the live pipeline staged)."
    exit 1
  fi
fi
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
if [ "${SRC_COMIN}" = "${DEST}" ]; then
  echo "source is already the frozen dest; skipping comin copy"
else
  rsync -a "${SRC_COMIN}/" "${DEST}/"
fi
cp -p "${INIT_FILE}" "${DEST}/init/$(basename "${INIT_FILE}")"
touch "${DEST}/.seeded_ok"

echo "=== frozen dataset sizes ==="
du -sh "${DEST}"
du -sh "${DEST}"/* 2>/dev/null || true

echo "freeze_dataset PASS: ${DEST}"
