#!/usr/bin/env bash
# Shared helpers for the secofs_ufs Hercules CI pipeline. Sourced, not run.

# systemd-launched agents don't set LOGNAME the way a login shell does, but the cards' RPTDIR/WORKDIR/COMROOT/DATAROOT depend on it, so fall back to the real username here.
export LOGNAME="${LOGNAME:-$(id -un)}"

: "${PACKAGEROOT:?PACKAGEROOT not set}"

expand_path() { eval "echo $1"; }

PACKAGEROOT=$(expand_path "${PACKAGEROOT}")
case "${PACKAGEROOT}" in
  /*) ;;
  *) echo "FATAL: PACKAGEROOT must be an absolute path (got '${PACKAGEROOT}')" >&2; exit 2 ;;
esac
export PACKAGEROOT
export HOMEnos="${PACKAGEROOT}/nos-workflow"
export OFS=secofs_ufs

# Same default the cards fall back to; must be exported before any card_value call since the cards resolve their own ${NOS_PTMP:-...} default against this shell's environment.
export NOS_PTMP=${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}

if [ -n "${VENV_PATH:-}" ]; then
  VENV_PATH=$(expand_path "${VENV_PATH}")
  export VENV_PATH
fi
if [ -n "${RT_DATA_ROOT:-}" ]; then
  RT_DATA_ROOT=$(expand_path "${RT_DATA_ROOT}")
  export RT_DATA_ROOT
fi

# RDHPCS rule: never rely on login-shell module loading -- do it here, explicitly, in every script that sources this file.
setup_modules() {
  local moddir="${HOMEnos}/modulefiles"
  # Bootstrap builds the venv before Deploy has rsynced anything into HOMEnos, so fall back to the checkout's own copy on a fresh NOS_CI_ROOT.
  if [ ! -d "${moddir}" ] && [ -n "${WORKSPACE:-}" ] && [ -d "${WORKSPACE}/modulefiles" ]; then
    moddir="${WORKSPACE}/modulefiles"
  fi
  module purge
  module use "${moddir}"
  module load nos_hercules.intel
}

setup_env() {
  setup_modules
  # Unlike the cards (which silently skip activation if missing), CI must fail loudly here rather than run a stage against the wrong Python.
  if [ -f "${VENV_PATH:-}/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${VENV_PATH}/bin/activate"
  else
    echo "FATAL: no venv at ${VENV_PATH:-} -- create it or set VENV_PATH"
    exit 1
  fi
}

# card_value <card_file> <VAR> -- greps the raw "[export ]VAR=..." line rather than sourcing the whole card, which has #SBATCH directives, mkdir/exit, and exec redirects.
card_value() {
  local card="$1" var="$2" line
  [ -r "${card}" ] || { echo "FATAL: card not readable: ${card}" >&2; return 1; }
  line=$(grep -E "^(export[[:space:]]+)?${var}=" "${card}" | tail -1)
  [ -n "${line}" ] || { echo "FATAL: no ${var}= line in ${card}" >&2; return 1; }
  line=${line#export }
  eval "echo \"${line#*=}\""
}
