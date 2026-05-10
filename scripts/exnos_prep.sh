#!/bin/bash
###############################################################################
#  exnos_prep.sh — nos_workflow shim
#
#  This file used to do the prep work directly via heredoc Python; the body
#  has migrated to ``nos_workflow.stages.prep`` so the same behavior is
#  reachable from the CLI (``nos_uw run prep --ofs <name>``) and from any
#  Python caller. The pre-migration shell is preserved at
#  ``scripts/legacy/exnos_prep.sh.preY-mig`` so we can revert in one cycle.
#
#  Rollback escape hatch: set NOS_USE_LEGACY_SHELL=YES (e.g. via
#  ``qsub -v NOS_USE_LEGACY_SHELL=YES JNOS_PREP``) to short-circuit the
#  Python path and re-route through the preserved legacy shell. Same-cycle
#  revert without editing tracked files.
#
#  Why we still source nos_run.sh: it populates env vars Python prep reads
#  (DBASE_MET_NOW, DBASE_TS_NOW, time_hotstart, time_nowcastend,
#  time_forecastend, GRIDFILE, OCEAN_MODEL, …). Replacing that in Python
#  would mean reimplementing module-load-style env wiring; not worth it.
#
#  Rolled out at: <commit migrated-secofs_ufs-prep-v1>
###############################################################################

set -x

# ----- Rollback escape hatch ------------------------------------------------
if [ "${NOS_USE_LEGACY_SHELL:-NO}" = "YES" ]; then
    echo "NOS_USE_LEGACY_SHELL=YES — routing through preserved pre-migration shell"
    exec "${SCRIPTSnos}/legacy/exnos_prep.sh.preY-mig"
fi

echo "exnos_prep.sh (nos_workflow shim) started at $(date)"
echo "  OFS=${RUN}  PDY=${PDY}  cyc=${cyc}"

# ----- STEP 0: env setup via nos_run.sh -------------------------------------
# Sources DBASE_*, time_hotstart, time_nowcastend, time_forecastend, GRIDFILE,
# OCEAN_MODEL, and other vars the Python prep reads.
. ${USHnos}/nos_run.sh ${OFS} prep
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: nos_run.sh failed (rc=${err})"
    err_chk
fi

echo "  time_hotstart=${time_hotstart}"
echo "  time_nowcastend=${time_nowcastend}"
echo "  time_forecastend=${time_forecastend}"

# ----- STEP 1: PYTHONPATH wiring --------------------------------------------
# Convention is git-pull, no pip install. Both nos-utils (forcing library)
# and nos_workflow (driver) live under ush/python; expose both.
NOS_UTILS_DIR=${NOS_UTILS_DIR:-${USHnos}/python/nos-utils}
NOS_WORKFLOW_DIR=${NOS_WORKFLOW_DIR:-${USHnos}/python}
export PYTHONPATH="${NOS_WORKFLOW_DIR}:${NOS_UTILS_DIR}:${PYTHONPATH:-}"

# LD_PRELOAD is scoped on the Python side via bash_compat.preserve_preload
# but we unset here too so the pre-call import probe is clean (lesson #6).
unset LD_PRELOAD

# Quick import probe — fail loudly with a useful message if PYTHONPATH is
# wrong or netCDF4 is missing on the compute node.
python3 -c "import nos_workflow; from nos_utils.nco_bridge import run_prep" || {
    echo "FATAL: nos_workflow / nos_utils not importable from PYTHONPATH=${PYTHONPATH}"
    export err=99; err_chk
}

# ----- STEP 2: run prep through nos_workflow --------------------------------
# Invokes nos_workflow.stages.prep.run() which calls
#   nos_utils.nco_bridge.run_prep(phase="nowcast")
#   nos_utils.nco_bridge.run_prep(phase="forecast")
# The CLI surfaces a structured FATAL one-liner on failure with full
# traceback in $DATA/nos_uw.prep.<ts>.traceback.
exec python3 -m nos_workflow run prep --ofs "${OFS}"
