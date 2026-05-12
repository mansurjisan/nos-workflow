#!/bin/bash
#
# WCOSS2 operator drill: run a stage twice (shell-only, then with a
# Python feature flag) against the same inputs and diff every output
# file produced into $DATA and $COMOUT.
#
# Usage:
#   ./run_wcoss2_drill.sh <stage> <python_flag>
#
# Examples:
#   ./run_wcoss2_drill.sh nowcast NOS_WORKFLOW_PYTHON_ARCHIVE
#   ./run_wcoss2_drill.sh forecast NOS_WORKFLOW_PYTHON_RUNNER
#
# Outputs:
#   ${DATAROOT}/parity_drill_<sha>/
#     shell_files.txt     # find $DATA $COMOUT -type f, sorted
#     python_files.txt
#     file_list_diff.txt  # diff of the two file lists
#     content_diff/        # per-file byte-diff for files in both
#     summary.txt         # PASS/FAIL + counts
#
# PR 1 ships this as scaffolding only — the two-run + diff logic lands
# in PR 2 (the first helper to be ported, archive_outputs). Until then,
# the script prints a warning and exits 0.

set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: $0 <stage> <python_flag>" >&2
    echo "  stage = nowcast | forecast" >&2
    echo "  python_flag = env var name (e.g., NOS_WORKFLOW_PYTHON_ARCHIVE)" >&2
    exit 1
fi

stage="$1"
python_flag="$2"
sha=$(cd "$(dirname "$0")" && git rev-parse --short HEAD 2>/dev/null || echo "nosha")
drill_dir="${DATAROOT:-/tmp}/parity_drill_${sha}"

mkdir -p "${drill_dir}"
echo "Parity drill dir: ${drill_dir}"
echo "Stage: ${stage}"
echo "Python flag: ${python_flag}"

echo "WARNING: PR 1 scaffolding only — no helpers ported yet." >&2
echo "         Two-run + diff logic lands in PR 2." >&2
exit 0
