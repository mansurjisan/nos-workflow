#!/usr/bin/env bash
# Bootstrap stage: seed the CI-owned NOS_CI_ROOT tree (fix/, exec/, venv,
# and -- in frozen mode -- the regression dataset) from the user's tree the
# first time a build runs against a given root. role-epic cannot write (and,
# pre-chmod, cannot even read) /work2/noaa/nos-surge/mjisan directly, so this
# is a one-time, one-directional copy; idempotent, a fast no-op once
# everything already exists under PACKAGEROOT/VENV_PATH/RT_DATA_ROOT.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

: "${WORKSPACE:?WORKSPACE not set (this script is meant to run under Jenkins)}"
: "${SEED_SRC:?SEED_SRC not set}"
: "${SEED_RT:?SEED_RT not set}"
DATA_MODE=${DATA_MODE:-live}

FIX_DEST="${HOMEnos}/fix/${OFS}"
EXEC_DEST="${HOMEnos}/exec"

need_fix=0
[ -d "${FIX_DEST}" ] || need_fix=1
need_exec=0
[ -x "${EXEC_DEST}/fv3_coastalS.exe" ] || need_exec=1

need_rt=0
if [ "${DATA_MODE}" = "frozen" ]; then
  : "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"
  : "${PDY:?PDY not set}"
  : "${CYC:?CYC not set}"
  COMROOT_STAGED="${RT_DATA_ROOT}/comin_${PDY}${CYC}"
  [ -d "${COMROOT_STAGED}" ] || need_rt=1
fi

# Readability preflight: fail with an actionable chmod before touching
# rsync, rather than mid-copy. o+ (not g+), since role-epic is not a member
# of the nos-surge group.
if [ "${need_fix}" -eq 1 ] || [ "${need_exec}" -eq 1 ]; then
  ls "${SEED_SRC}" >/dev/null 2>&1 || {
    echo "FATAL: ${SEED_SRC} not readable as $(whoami)."
    echo "Ask the tree owner to run: chmod -R o+rX ${SEED_SRC}"
    echo "(and o+x on every parent directory above it, e.g. chmod o+x /work2/noaa/nos-surge/mjisan)"
    exit 1
  }
fi
if [ "${need_rt}" -eq 1 ]; then
  ls "${SEED_RT}" >/dev/null 2>&1 || {
    echo "FATAL: ${SEED_RT} not readable as $(whoami)."
    echo "Ask the tree owner to run: chmod -R o+rX ${SEED_RT}"
    echo "(and o+x on every parent directory above it, e.g. chmod o+x /work2/noaa/nos-surge/mjisan)"
    exit 1
  }
fi

# a. CI root
mkdir -p "${PACKAGEROOT}"

# b. fix/ -- deploy.sh's own --exclude='/fix' means it never touches this
# dir once seeded, regardless of whether Bootstrap or Deploy runs first.
if [ "${need_fix}" -eq 1 ]; then
  echo "bootstrap: seeding fix/ from ${SEED_SRC}/fix/"
  mkdir -p "${HOMEnos}/fix"
  rsync -a "${SEED_SRC}/fix/" "${HOMEnos}/fix/"
else
  echo "bootstrap: ${FIX_DEST} already present, skipping fix/ seed"
fi

# c. exec/ -- same anchored-exclude protection as fix/ above.
if [ "${need_exec}" -eq 1 ]; then
  echo "bootstrap: seeding exec/ from ${SEED_SRC}/exec/"
  mkdir -p "${EXEC_DEST}"
  rsync -a "${SEED_SRC}/exec/" "${EXEC_DEST}/"
else
  echo "bootstrap: ${EXEC_DEST}/fv3_coastalS.exe already present, skipping exec/ seed"
fi
[ -x "${EXEC_DEST}/fv3_coastalS.exe" ] || {
  echo "FATAL: ${EXEC_DEST}/fv3_coastalS.exe still missing after seeding from ${SEED_SRC}/exec/"
  exit 1
}

# d. venv
if [ -f "${VENV_PATH:-}/bin/activate" ]; then
  echo "bootstrap: venv already present at ${VENV_PATH}, skipping"
else
  NOS_UTILS="${WORKSPACE}/ush/python/nos-utils"
  if [ ! -f "${NOS_UTILS}/setup.py" ] && [ ! -f "${NOS_UTILS}/pyproject.toml" ]; then
    echo "FATAL: ${NOS_UTILS} has no setup.py/pyproject.toml -- the nos-utils submodule was not checked out."
    echo "enable Git > Additional Behaviours > Advanced sub-modules behaviours > Recursively update submodules in the job config"
    exit 1
  fi
  echo "bootstrap: creating venv at ${VENV_PATH}"
  setup_modules
  python3 -m venv --system-site-packages "${VENV_PATH}"
  "${VENV_PATH}/bin/pip" install scipy
  # Editable install binds this venv to ${WORKSPACE}'s submodule checkout;
  # fine for CI, since the workspace path is stable for the life of the job.
  "${VENV_PATH}/bin/pip" install -e "${NOS_UTILS}"
fi

# e. frozen dataset
if [ "${DATA_MODE}" = "frozen" ]; then
  if [ "${need_rt}" -eq 1 ]; then
    if [ -d "${SEED_RT}/comin_${PDY}${CYC}" ]; then
      echo "bootstrap: seeding frozen dataset (~80GB) from ${SEED_RT}/comin_${PDY}${CYC}"
      mkdir -p "${COMROOT_STAGED}"
      rsync -a --info=progress2 "${SEED_RT}/comin_${PDY}${CYC}/" "${COMROOT_STAGED}/"
    else
      echo "FATAL: no frozen dataset at ${COMROOT_STAGED} or ${SEED_RT}/comin_${PDY}${CYC}."
      echo "Run freeze_dataset.sh for PDY=${PDY} CYC=${CYC}, or switch DATA_MODE=live."
      exit 1
    fi
  else
    echo "bootstrap: frozen dataset already present at ${COMROOT_STAGED}, skipping"
  fi
fi

echo "bootstrap PASS"
