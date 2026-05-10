#!/bin/bash
###############################################################################
#  exnos_post.sh — nos_workflow shim
#
#  This file used to drive COMF SCHISM post-processing directly (combine
#  per-phase staout text into station NetCDFs via schism_combine_outputs.py,
#  plus the optional 2D-barotropic ensemble bias correction). The body has
#  migrated to ``nos_workflow.stages.post`` so the same behavior is
#  reachable from the CLI (``nos_uw run post --ofs <name>``) and from any
#  Python caller. The pre-migration shell is preserved at
#  ``scripts/legacy/exnos_post.sh.preY-mig`` so we can revert in one cycle.
#
#  Rollback escape hatch: set NOS_USE_LEGACY_SHELL=YES (e.g. via
#  ``qsub -v NOS_USE_LEGACY_SHELL=YES JNOS_POST``) to short-circuit the
#  Python path and re-route through the preserved legacy shell. Same-cycle
#  revert without editing tracked files.
#
#  Why we still source nos_run.sh: it populates env vars the Python post
#  reads (PREFIXNOS, LEN_NOWCAST, STA_OUT_CTL — plus the standard
#  DBASE_*/time_* set, which post itself doesn't consume but other
#  downstream callers may depend on). Replacing that in Python would
#  mean reimplementing module-load-style env wiring; not worth it.
#
#  Why the two Python sub-tools stay as ``subprocess.run`` instead of
#  imports: schism_combine_outputs.py and ensemble_bias_correct.py are
#  deployed under ``${HOMEnos}/ush/...`` at install time (they are NOT
#  in this repository tree) and have CLI-style argparse glue at module
#  top level, so importing them would execute that glue at import time.
#  Subprocess keeps the contract identical to the legacy shell.
#
#  Rolled out at: <commit migrated-secofs_ufs-post-v1>
###############################################################################

set -x

# ----- Rollback escape hatch ------------------------------------------------
if [ "${NOS_USE_LEGACY_SHELL:-NO}" = "YES" ]; then
    echo "NOS_USE_LEGACY_SHELL=YES — routing through preserved pre-migration shell"
    exec "${SCRIPTSnos}/legacy/exnos_post.sh.preY-mig"
fi

echo "exnos_post.sh (nos_workflow shim) started at $(date)"
echo "  OFS=${RUN}  PDY=${PDY}  cyc=${cyc}"

# ----- STEP 0: env setup via nos_run.sh -------------------------------------
# Sources PREFIXNOS, LEN_NOWCAST, STA_OUT_CTL and the standard
# DBASE_*/time_* set. nos_run.sh tolerates being called with a "post" stage
# tag the same way it tolerates "prep" — it only branches on OFS for the
# fixed-file resolution.
. ${USHnos}/nos_run.sh ${OFS} post
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: nos_run.sh failed (rc=${err})"
    err_chk
fi

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

# ----- STEP 2: run post through nos_workflow --------------------------------
# Invokes nos_workflow.stages.post.run() which:
#   - for each of nowcast/forecast: builds work dir, writes ctl, awk-style
#     station.lat.lon, symlinks staout_{1..9}, runs schism_combine_outputs.py,
#     copies the resulting station NetCDF to $COMOUT
#   - if BAROTROPIC=true: trains bias coefficients and applies them per
#     ensemble member via ensemble_bias_correct.py
# The CLI surfaces a structured FATAL one-liner on failure with full
# traceback in $DATA/nos_uw.post.<ts>.traceback.
exec python3 -m nos_workflow run post --ofs "${OFS}"
