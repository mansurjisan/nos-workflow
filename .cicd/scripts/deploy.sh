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

echo "deploy PASS: $(date -u +%FT%TZ)"
