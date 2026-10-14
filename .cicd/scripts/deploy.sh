#!/usr/bin/env bash
# Checkout+Deploy stage: rsync the Jenkins workspace checkout into the runtime tree at ${PACKAGEROOT}/nos-workflow, so card/script edits under test actually get run.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

: "${WORKSPACE:?WORKSPACE not set (this script is meant to run under Jenkins)}"

# Fresh logs every build, so verify.sh can never validate a stale log from a reused workspace.
rm -rf "${WORKSPACE}/ci_logs"
mkdir -p "${HOMEnos}" "${WORKSPACE}/ci_logs"

echo "deploying ${WORKSPACE} -> ${HOMEnos}"
rsync -a --delete \
  --exclude='.git/' \
  --exclude='/fix' \
  --exclude='/exec' \
  --exclude='/comin' \
  --exclude='/ush/python/nos-utils' \
  --exclude='/*.out' \
  --exclude='/*.err' \
  "${WORKSPACE}/" "${HOMEnos}/"

# The 2D-Global and STOFS-3D-ATL cards and tools import nos-utils from ${HOMEnos}/ush/python/nos-utils, a directory the rsync above leaves alone; copy the checked-out submodule there, without its .git. MJ (10/13/26)
case "${OFS}" in stofs_3d_atl_ufs_standalone|stofs_3d_atl_ufs) ATL=1 ;; *) ATL=0 ;; esac
if [ "${OFS}" = stofs_2d_glo ] || [ "${ATL}" = 1 ]; then
  NU_SRC="${WORKSPACE}/ush/python/nos-utils"
  NU_SENTINEL=forcing/adcirc_met.py
  [ "${ATL}" != 1 ] || NU_SENTINEL=orchestrator.py
  [ -f "${NU_SRC}/nos_utils/${NU_SENTINEL}" ] || {
    echo "FATAL: ${NU_SRC} is empty -- enable Recursively update submodules in the job config"
    exit 1
  }
  mkdir -p "${HOMEnos}/ush/python/nos-utils"
  rsync -a --delete --exclude='.git' "${NU_SRC}/" "${HOMEnos}/ush/python/nos-utils/"
else
  # scripts/exnos_*.sh put ${USHnos}/python/nos-utils first on PYTHONPATH and the rsync above never deletes it, so a copy left by an earlier 2D-Global deploy would shadow the SECOFS submodule. MJ (10/13/26)
  rm -rf "${HOMEnos}/ush/python/nos-utils"
fi

echo "deploy PASS: $(date -u +%FT%TZ)"
