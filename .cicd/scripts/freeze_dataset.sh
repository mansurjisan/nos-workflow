#!/usr/bin/env bash
# One-shot helper: freeze the currently-staged live comin tree + nowcast
# init file for one cycle into RT_DATA_ROOT, for reuse by DATA_MODE=frozen
# CI runs. Run this ONCE per cycle you want to pin as a regression dataset.
# Usage: freeze_dataset.sh <PDY> <CYC>
# Override SRC_COMIN to freeze from a comin tree other than the default
# (the live-staged tree the pipeline itself used for this PDY/CYC).
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

PDY=${1:?usage: freeze_dataset.sh PDY CYC}
CYC=${2:?usage: freeze_dataset.sh PDY CYC}
: "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"

NOWCAST_CARD="${HOMEnos}/slurm/${OFS}/jnos_nowcast_00.sh"

# The prep/nowcast cards' own COMROOT_STAGED= line is a /work/PLACEHOLDER
# default (COMROOT_STAGED is normally supplied by the caller at sbatch
# time), so card_value would silently return that placeholder rather than
# a real tree. Default instead to the live-staged tree this pipeline uses
# (see run_stage.sh); if that is not set either, this must be told where
# to freeze from.
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
