#!/usr/bin/env bash
# Checkout+Deploy stage: rsync the Jenkins workspace checkout into the
# runtime tree at ${PACKAGEROOT}/nos-workflow, so card/script edits under
# test actually get run. Big static dirs (fix/, exec/) and staged input
# data (comin/) persist machine-side, and the ush/python/nos-utils
# submodule is never touched by CI.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

: "${WORKSPACE:?WORKSPACE not set (this script is meant to run under Jenkins)}"

mkdir -p "${HOMEnos}" "${WORKSPACE}/ci_logs"

echo "deploying ${WORKSPACE} -> ${HOMEnos}"
rsync -a --delete \
  --exclude='.git/' \
  --exclude='fix/' \
  --exclude='exec/' \
  --exclude='comin/' \
  --exclude='ush/python/nos-utils/' \
  "${WORKSPACE}/" "${HOMEnos}/"

echo "deploy PASS: $(date -u +%FT%TZ)"
