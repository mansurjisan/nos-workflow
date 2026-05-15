#!/bin/bash
#
# WCOSS2 operator drill: run a stage twice (shell-only, then with a
# Python feature flag) against the same inputs and diff the $COMOUT
# artifacts produced by each.
#
# Usage:
#   ./run_wcoss2_drill.sh <stage> <python_flag> <pdy> <cyc>
#
# Examples:
#   ./run_wcoss2_drill.sh nowcast NOS_WORKFLOW_PYTHON_ARCHIVE     20260510 00
#   ./run_wcoss2_drill.sh nowcast NOS_WORKFLOW_PYTHON_STAGE_FILES 20260510 00
#   ./run_wcoss2_drill.sh forecast NOS_WORKFLOW_PYTHON_RUNNER     20260510 06
#
# Outputs to ${DATAROOT:-/tmp}/parity_drill_<sha>/:
#   shell_out/comout    -- $COMOUT artifacts from shell-only run
#   python_out/comout   -- $COMOUT artifacts from Python-flagged run
#   data_diff.txt       -- diff -r between the two
#   summary.txt         -- PASS/FAIL + counts + wall-clock
#
# Prereqs (must be set in the calling shell):
#   - HOMEnos      -- repo install root (so we can locate the PBS script)
#   - OFS          -- the OFS to drill (e.g., secofs_ufs)
#   - LOGNAME      -- read by the standard $COMOUT layout
#
# Exit codes:
#   0  -- PASS (zero diff lines)
#   1  -- FAIL (non-zero diff lines, or argument / qsub error)
#
# PR 7c replaces the PR 1 scaffolding stub with this full drill.  PR 1
# just printed a WARNING and exited 0; the real two-run + diff logic
# was held until enough helpers were ported to make a drill meaningful
# (archive_outputs PR 2 was the first; stage_model_files PR 7c is the
# largest single helper port).

set -euo pipefail

# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------

if [ "$#" -ne 4 ]; then
    cat >&2 <<EOM
usage: $0 <stage> <python_flag> <pdy> <cyc>
  stage       = nowcast | forecast
  python_flag = NOS_WORKFLOW_PYTHON_* env var name
                (e.g., NOS_WORKFLOW_PYTHON_STAGE_FILES,
                 NOS_WORKFLOW_PYTHON_ARCHIVE,
                 NOS_WORKFLOW_PYTHON_RUNNER for "flip everything")
  pdy         = YYYYMMDD
  cyc         = HH (zero-padded)

Examples:
  $0 nowcast  NOS_WORKFLOW_PYTHON_ARCHIVE     20260510 00
  $0 nowcast  NOS_WORKFLOW_PYTHON_STAGE_FILES 20260510 00
  $0 forecast NOS_WORKFLOW_PYTHON_RUNNER      20260510 06
EOM
    exit 1
fi

stage="$1"
python_flag="$2"
pdy="$3"
cyc="$4"

case "${stage}" in
    nowcast|forecast) ;;
    *)
        echo "ERROR: stage must be nowcast or forecast (got '${stage}')" >&2
        exit 1
        ;;
esac

# Sanity: the flag must look like one of the recognized NOS_WORKFLOW_PYTHON_*
# env vars. We don't fail on unknown names (operators may want to test new
# flags before they're in the canonical list), just warn.
case "${python_flag}" in
    NOS_WORKFLOW_PYTHON_STAGE_FILES|\
    NOS_WORKFLOW_PYTHON_PREPARE|\
    NOS_WORKFLOW_PYTHON_EXECUTE|\
    NOS_WORKFLOW_PYTHON_ARCHIVE|\
    NOS_WORKFLOW_PYTHON_RUNNER) ;;
    *)
        echo "WARNING: '${python_flag}' is not a recognized NOS_WORKFLOW_PYTHON_* var" >&2
        echo "         Recognized: NOS_WORKFLOW_PYTHON_{STAGE_FILES,PREPARE,EXECUTE,ARCHIVE,RUNNER}" >&2
        ;;
esac

# ---------------------------------------------------------------------------
# Drill setup
# ---------------------------------------------------------------------------

sha=$(cd "$(dirname "$0")" && git rev-parse --short HEAD 2>/dev/null || echo "nosha")
drill_dir="${DATAROOT:-/tmp}/parity_drill_${sha}"
mkdir -p "${drill_dir}/shell_out" "${drill_dir}/python_out"

# Required environment for path construction
: "${HOMEnos:?HOMEnos must be set (the repo install root)}"
: "${OFS:?OFS must be set (e.g., secofs_ufs)}"
: "${LOGNAME:?LOGNAME must be set (used for \$COMOUT layout)}"

# The standard PBS script naming on WCOSS2.  Operators can override by
# exporting PBS_SCRIPT before invoking the drill.
pbs_script="${PBS_SCRIPT:-${HOMEnos}/pbs/${OFS}/jnos_${stage}_${cyc}.pbs}"
if [ ! -f "${pbs_script}" ]; then
    echo "ERROR: PBS script not found: ${pbs_script}" >&2
    echo "       Override with PBS_SCRIPT=<path> if your layout differs." >&2
    exit 1
fi

# Where the standard ex-script lands its outputs.  Override-able for sites
# that pin a different $COMOUT.
comout_template="${COMOUT_TEMPLATE:-/lfs/h1/nos/ptmp/${LOGNAME}/com/nos/${OFS}.${pdy}}"

cat > "${drill_dir}/summary.txt" <<EOM
======================================================================
Parity drill: ${stage} (flag=${python_flag})
======================================================================
OFS        = ${OFS}
PDY        = ${pdy}
cyc        = ${cyc}
SHA        = ${sha}
PBS script = ${pbs_script}
COMOUT     = ${comout_template}
Started    = $(date -u +%Y-%m-%dT%H:%M:%SZ)

EOM

# ---------------------------------------------------------------------------
# Run 1/2: shell path (no flag)
# ---------------------------------------------------------------------------

echo "Run 1/2: shell path (no flag) ..."
echo "Run 1/2: shell path (no flag)" >> "${drill_dir}/summary.txt"
t0=$(date +%s)
job1=$(qsub -v "PDY=${pdy},cyc=${cyc}" "${pbs_script}")
echo "  job=${job1}"
echo "  job=${job1}" >> "${drill_dir}/summary.txt"

# Wait for job1 to leave the queue.  Some sites have polling intervals
# below 30s; tune via DRILL_POLL_S if needed.
poll_s="${DRILL_POLL_S:-30}"
while qstat "${job1}" >/dev/null 2>&1; do
    sleep "${poll_s}"
done
t1=$(date +%s)
echo "  done ($((t1 - t0))s)."

# Stash the shell-side $COMOUT.  ``cp -rp`` preserves mode/mtime/ownership;
# missing $COMOUT is a hard failure (the shell job is supposed to have
# created it).
if [ ! -d "${comout_template}" ]; then
    echo "ERROR: shell-side \$COMOUT missing: ${comout_template}" >&2
    exit 1
fi
cp -rp "${comout_template}" "${drill_dir}/shell_out/comout"

# ---------------------------------------------------------------------------
# Run 2/2: Python path (flag=1)
# ---------------------------------------------------------------------------

# Clean the $COMOUT before run 2 so the second run starts from the same
# baseline as the first (no leftover from run 1).
echo "  cleaning ${comout_template} before run 2 ..."
rm -rf "${comout_template}"

echo "Run 2/2: Python path (${python_flag}=1) ..."
echo "" >> "${drill_dir}/summary.txt"
echo "Run 2/2: Python path (${python_flag}=1)" >> "${drill_dir}/summary.txt"
t2=$(date +%s)
job2=$(qsub -v "PDY=${pdy},cyc=${cyc},${python_flag}=1" "${pbs_script}")
echo "  job=${job2}"
echo "  job=${job2}" >> "${drill_dir}/summary.txt"

while qstat "${job2}" >/dev/null 2>&1; do
    sleep "${poll_s}"
done
t3=$(date +%s)
echo "  done ($((t3 - t2))s)."

if [ ! -d "${comout_template}" ]; then
    echo "ERROR: python-side \$COMOUT missing: ${comout_template}" >&2
    exit 1
fi
cp -rp "${comout_template}" "${drill_dir}/python_out/comout"

# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

echo "Diffing ${drill_dir}/{shell,python}_out/comout ..."
# ``diff -r`` walks recursively; we redirect both stdout (diff hunks) and
# stderr (``Common subdirectories: ...``) to the same file so the count
# at the bottom reflects the total noise an operator would see.
diff -r "${drill_dir}/shell_out/comout" "${drill_dir}/python_out/comout" \
    > "${drill_dir}/data_diff.txt" 2>&1 || true

n_diffs=$(wc -l < "${drill_dir}/data_diff.txt")
echo "Diff lines: ${n_diffs}"

if [ "${n_diffs}" -eq 0 ]; then
    status="PASS"
else
    status="FAIL"
fi

cat >> "${drill_dir}/summary.txt" <<EOM

----------------------------------------------------------------------
Results
----------------------------------------------------------------------
Run 1 walltime (shell)  : $((t1 - t0))s
Run 2 walltime (python) : $((t3 - t2))s
Diff lines              : ${n_diffs}
Ended                   : $(date -u +%Y-%m-%dT%H:%M:%SZ)
Status                  : ${status}
EOM

echo ""
echo "===== Parity drill ${status} ====="
echo "Output: ${drill_dir}/"
cat "${drill_dir}/summary.txt"

[ "${status}" = "PASS" ]
