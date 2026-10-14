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

# The 2D-Global cards and tools import nos-utils from ${HOMEnos}/ush/python/nos-utils, a directory the rsync above leaves alone; copy the checked-out submodule there, without its .git. MJ (10/13/26)
if [ "${OFS}" = stofs_2d_glo ]; then
  NU_SRC="${WORKSPACE}/ush/python/nos-utils"
  [ -f "${NU_SRC}/nos_utils/forcing/adcirc_met.py" ] || {
    echo "FATAL: ${NU_SRC} is empty -- enable Recursively update submodules in the job config"
    exit 1
  }
  mkdir -p "${HOMEnos}/ush/python/nos-utils"
  rsync -a --delete --exclude='.git' "${NU_SRC}/" "${HOMEnos}/ush/python/nos-utils/"
fi

echo "deploy PASS: $(date -u +%FT%TZ)"
