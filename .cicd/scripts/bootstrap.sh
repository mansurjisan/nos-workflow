#!/usr/bin/env bash
# Bootstrap stage: seed the CI-owned NOS_CI_ROOT tree (fix/, exec/, venv, and -- in frozen mode -- the regression dataset) from the user's tree; idempotent no-op once already seeded.
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
# SECOFS keeps its sentinel and executable; STOFS-2D-Global has its own exec sentinel (exec/ is shared) and also needs the ADCIRC build, which lives beside the clone. MJ (10/13/26)
EXEC_SENTINEL="${EXEC_DEST}/.seeded_ok"
EXEC_NEED=(fv3_coastalS.exe)
if [ "${OFS}" = stofs_2d_glo ]; then
  EXEC_SENTINEL="${EXEC_DEST}/.seeded_ok.${OFS}"
  EXEC_NEED=(stofs_2d_glo_tide_fac)
  ADCIRC_SRC="${SEED_ADCIRC:-$(dirname "${SEED_SRC}")/adcirc_v56.1.0_exec}"
  ADCIRC_DEST="${PACKAGEROOT}/adcirc_v56.1.0_exec"
fi

# Sentinel-gated, not existence-of-directory: an interrupted rsync could leave a partially-populated destination that [ -d ]/[ -x ] would mistake for a complete seed.
need_fix=0
[ -f "${FIX_DEST}/.seeded_ok" ] || need_fix=1
need_exec=0
[ -f "${EXEC_SENTINEL}" ] || need_exec=1
need_adcirc=0
if [ "${OFS}" = stofs_2d_glo ]; then
  [ -f "${ADCIRC_DEST}/.seeded_ok" ] || need_adcirc=1
fi

need_rt=0
if [ "${DATA_MODE}" = "frozen" ]; then
  : "${RT_DATA_ROOT:?RT_DATA_ROOT not set}"
  : "${PDY:?PDY not set}"
  : "${CYC:?CYC not set}"
  RT_REL="comin_${PDY}${CYC}"
  RT_SIZE="~80GB"
  if [ "${OFS}" = stofs_2d_glo ]; then
    RT_REL="stofs_2d_glo/${PDY}${CYC}"
    RT_SIZE="tens of GB"
  fi
  COMROOT_STAGED="${RT_DATA_ROOT}/${RT_REL}"
  [ -f "${COMROOT_STAGED}/.seeded_ok" ] || need_rt=1
fi

# Preflight: fail with an actionable chmod message before touching rsync, rather than mid-copy.
if [ "${need_fix}" -eq 1 ]; then
  ls "${SEED_SRC}/fix" >/dev/null 2>&1 || {
    echo "FATAL: ${SEED_SRC}/fix not readable as $(whoami)."
    echo "Ask the tree owner to run: chmod -R o+rX ${SEED_SRC}/fix"
    echo "and chmod o+x (not -R) on every parent directory above it, e.g.:"
    echo "  chmod o+x ${SEED_SRC} /work2/noaa/nos-surge/mjisan"
    exit 1
  }
fi
if [ "${need_exec}" -eq 1 ]; then
  ls "${SEED_SRC}/exec" >/dev/null 2>&1 || {
    echo "FATAL: ${SEED_SRC}/exec not readable as $(whoami)."
    echo "Ask the tree owner to run: chmod -R o+rX ${SEED_SRC}/exec"
    echo "and chmod o+x (not -R) on every parent directory above it, e.g.:"
    echo "  chmod o+x ${SEED_SRC} /work2/noaa/nos-surge/mjisan"
    exit 1
  }
fi
if [ "${need_adcirc}" -eq 1 ]; then
  ls "${ADCIRC_SRC}" >/dev/null 2>&1 || {
    echo "FATAL: ${ADCIRC_SRC} not readable as $(whoami) (the ADCIRC build: tools/build_stofs_2d_glo_adcirc_hercules.sh; SEED_ADCIRC overrides the path)."
    echo "Ask the tree owner to run: chmod -R o+rX ${ADCIRC_SRC}"
    exit 1
  }
fi
if [ "${DATA_MODE}" = "frozen" ] && [ "${need_rt}" -eq 1 ]; then
  ls "${SEED_RT}/${RT_REL}" >/dev/null 2>&1 || {
    echo "FATAL: ${SEED_RT}/${RT_REL} not readable as $(whoami)."
    echo "Ask the tree owner to run: chmod -R o+rX ${SEED_RT}/${RT_REL}"
    echo "and chmod o+x (not -R) on every parent directory above it, e.g.:"
    echo "  chmod o+x ${SEED_RT} /work2/noaa/nos-surge/mjisan"
    [ "${OFS}" != stofs_2d_glo ] || echo "If the dataset does not exist yet, seed it once: bash .cicd/scripts/stofs_2d_glo.sh seed ${PDY} ${CYC} (see its header)"
    exit 1
  }
fi

mkdir -p "${PACKAGEROOT}"

# deploy.sh's own --exclude='/fix' means it never touches this dir once seeded, regardless of whether Bootstrap or Deploy runs first.
if [ "${need_fix}" -eq 1 ]; then
  echo "bootstrap: seeding fix/ from ${SEED_SRC}/fix/"
  mkdir -p "${HOMEnos}/fix"
  rsync -a "${SEED_SRC}/fix/" "${HOMEnos}/fix/"
  touch "${FIX_DEST}/.seeded_ok"
else
  echo "bootstrap: ${FIX_DEST}/.seeded_ok already present, skipping fix/ seed"
fi

# Same anchored-exclude protection as fix/ above.
if [ "${need_exec}" -eq 1 ]; then
  echo "bootstrap: seeding exec/ from ${SEED_SRC}/exec/"
  mkdir -p "${EXEC_DEST}"
  rsync -a "${SEED_SRC}/exec/" "${EXEC_DEST}/"
  touch "${EXEC_SENTINEL}"
else
  echo "bootstrap: ${EXEC_SENTINEL} already present, skipping exec/ seed"
fi
for exe in "${EXEC_NEED[@]}"; do
  [ -x "${EXEC_DEST}/${exe}" ] || {
    echo "FATAL: ${EXEC_DEST}/${exe} still missing after seeding from ${SEED_SRC}/exec/"
    exit 1
  }
done

if [ "${OFS}" = stofs_2d_glo ]; then
  if [ "${need_adcirc}" -eq 1 ]; then
    echo "bootstrap: seeding the ADCIRC executables from ${ADCIRC_SRC}/"
    mkdir -p "${ADCIRC_DEST}"
    rsync -a "${ADCIRC_SRC}/" "${ADCIRC_DEST}/"
    touch "${ADCIRC_DEST}/.seeded_ok"
  else
    echo "bootstrap: ${ADCIRC_DEST}/.seeded_ok already present, skipping the ADCIRC seed"
  fi
  for exe in padcirc adcprep; do
    [ -x "${ADCIRC_DEST}/${exe}" ] || {
      echo "FATAL: ${ADCIRC_DEST}/${exe} still missing after seeding from ${ADCIRC_SRC}/"
      exit 1
    }
  done
fi

# Gated on the actual payload (scipy + editable nos-utils importable), not just bin/activate existing, which a half-built venv would also satisfy.
if [ -x "${VENV_PATH:-}/bin/python" ] && "${VENV_PATH}/bin/python" -c 'import scipy, nos_utils' >/dev/null 2>&1; then
  echo "bootstrap: venv already present at ${VENV_PATH} with scipy+nos_utils importable, skipping"
else
  if [ -d "${VENV_PATH:-}" ]; then
    echo "bootstrap: partial venv at ${VENV_PATH} (scipy/nos_utils not importable) -- rebuilding"
    rm -rf "${VENV_PATH}"
  fi
  NOS_UTILS="${WORKSPACE}/ush/python/nos-utils"
  if [ ! -f "${NOS_UTILS}/setup.py" ] && [ ! -f "${NOS_UTILS}/pyproject.toml" ]; then
    echo "FATAL: ${NOS_UTILS} has no setup.py/pyproject.toml -- the nos-utils submodule was not checked out."
    echo "enable Git > Additional Behaviours > Advanced sub-modules behaviours > Recursively update submodules in the job config"
    exit 1
  fi
  echo "bootstrap: creating venv at ${VENV_PATH}"
  setup_modules
  command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 not found on PATH after setup_modules -- check that modulefiles/nos_hercules.intel.lua loads a python module"; exit 1; }
  python3 -m venv --system-site-packages "${VENV_PATH}"
  "${VENV_PATH}/bin/pip" install scipy==1.17.1
  # Editable install binds this venv to ${WORKSPACE}'s submodule checkout; fine for CI, since the workspace path is stable for the life of the job.
  "${VENV_PATH}/bin/pip" install -e "${NOS_UTILS}"
fi

if [ "${DATA_MODE}" = "frozen" ]; then
  if [ "${need_rt}" -eq 1 ]; then
    if [ -d "${SEED_RT}/${RT_REL}" ]; then
      echo "bootstrap: seeding frozen dataset (${RT_SIZE}) from ${SEED_RT}/${RT_REL}"
      mkdir -p "${COMROOT_STAGED}"
      rsync -a --info=progress2 "${SEED_RT}/${RT_REL}/" "${COMROOT_STAGED}/"
      touch "${COMROOT_STAGED}/.seeded_ok"
    else
      echo "FATAL: no frozen dataset at ${COMROOT_STAGED} or ${SEED_RT}/${RT_REL}."
      if [ "${OFS}" = stofs_2d_glo ]; then
        echo "Seed it with: bash .cicd/scripts/stofs_2d_glo.sh seed ${PDY} ${CYC} (see its header), or switch DATA_MODE=live."
      else
        echo "Run freeze_dataset.sh for PDY=${PDY} CYC=${CYC}, or switch DATA_MODE=live."
      fi
      exit 1
    fi
  else
    echo "bootstrap: frozen dataset already present at ${COMROOT_STAGED} (sentinel verified), skipping"
  fi
fi

echo "bootstrap PASS"
