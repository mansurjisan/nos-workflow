#!/bin/bash
###############################################################################
#  exnos_forecast.sh — nos_workflow shim
#
#  This file used to drive the SECOFS-UFS forecast directly: source nos_run.sh,
#  then call the 4-step interface (stage_model_files / prepare_restart /
#  execute_model / archive_outputs) inline. The orchestration has migrated
#  to ``nos_workflow.stages.forecast`` so the same behavior is reachable from
#  the CLI (``nos_uw run forecast --ofs <name>``) and from any Python caller.
#  The pre-migration shell is preserved at
#  ``scripts/legacy/exnos_forecast.sh.preY-mig`` so we can revert in one cycle.
#
#  What stayed in shell: the actual ``mpiexec ... fv3_coastalS.exe`` MPI
#  launch, combine_hotstart7, the nccopy NETCDF4_CLASSIC conversion, and
#  the COMOUT archive. They all live inside ``_schism_execute_ufs_coastal``
#  and ``_schism_archive_outputs`` in ``ush/nos_run.sh`` and are invoked
#  from the Python stage via ``bash_compat.run_shell_function``. Reason:
#  ``module load`` (MPI / netCDF / ESMF) doesn't persist into a Python
#  ``subprocess`` re-exec, so MPI launches must stay in shell. The
#  migration philosophy doc (#220) is explicit about this case.
#
#  Forecast-specific delta vs nowcast: ``prepare_restart "forecast"`` in
#  nos_run.sh picks up the combined hotstart from THIS cycle's nowcast
#  (``${COMOUT}/${RUN}.${cycle}.${PDY}.rst.nowcast.nc``), not yesterday's
#  COMOUT init. ``archive_outputs "forecast"`` writes to
#  ``${COMOUT}/${RUN}.${cycle}.${PDY}.forecast_outputs/`` instead of
#  ``.restart_outputs/``. The Python stage doesn't special-case this — the
#  shell helpers branch on the phase arg internally.
#
#  Rollback escape hatch: set NOS_USE_LEGACY_SHELL=YES (e.g. via
#  ``qsub -v NOS_USE_LEGACY_SHELL=YES JNOS_FORECAST``) to short-circuit the
#  Python path and re-route through the preserved legacy shell. Same-cycle
#  revert without editing tracked files.
#
#  Why we still source nos_run.sh: it populates env vars the Python
#  forecast stage reads (and forwards into each shell function call) —
#  PREFIXNOS, GRIDFILE, OCEAN_MODEL, time_hotstart, time_nowcastend,
#  time_forecastend, TOTAL_TASKS, PPN, EXECnos, DATM_INPUT_DIR,
#  RNDAY_FORECAST, PDYHH_FCAST_BEGIN, plus the standard DBASE_*/time_* set.
#  Replacing that in Python would mean reimplementing module-load-style
#  env wiring; not worth it.
#
#  Rolled out at: <commit migrated-secofs_ufs-forecast-v1>
###############################################################################

set -x

# ----- Rollback escape hatch ------------------------------------------------
if [ "${NOS_USE_LEGACY_SHELL:-NO}" = "YES" ]; then
    echo "NOS_USE_LEGACY_SHELL=YES — routing through preserved pre-migration shell"
    exec "${SCRIPTSnos}/legacy/exnos_forecast.sh.preY-mig"
fi

echo "exnos_forecast.sh (nos_workflow shim) started at $(date)"
echo "  OFS=${RUN}  PDY=${PDY}  cyc=${cyc}"

# ----- STEP 0: env setup via nos_run.sh -------------------------------------
# Sources every var nos_run.sh's helpers consult when the Python stage
# invokes them: PREFIXNOS, GRIDFILE, OCEAN_MODEL, time_hotstart,
# time_nowcastend, time_forecastend, TOTAL_TASKS, PPN, EXECnos,
# RNDAY_FORECAST, PDYHH_FCAST_BEGIN, etc.
. ${USHnos}/nos_run.sh ${OFS} forecast
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
# and is also unset inside ``_schism_execute_ufs_coastal`` before the
# mpiexec call (UFS-Coastal links its own hpc-stack libraries via modules,
# not the system netcdf libnetcdff.so the J-job preloads for Fortran
# helpers). We unset here too so the pre-call import probe is clean
# (lesson #6).
unset LD_PRELOAD

# Quick import probe — fail loudly with a useful message if PYTHONPATH is
# wrong or netCDF4 is missing on the compute node. nos_utils import is not
# required for the forecast stage itself (we go directly into nos_run.sh)
# but we keep the probe consistent with the prep/nowcast/post shims.
python3 -c "import nos_workflow" || {
    echo "FATAL: nos_workflow not importable from PYTHONPATH=${PYTHONPATH}"
    export err=99; err_chk
}

# ----- STEP 2: run forecast through nos_workflow ----------------------------
# Invokes nos_workflow.stages.forecast.run() which drives the 4-step contract
# (stage_model_files / prepare_restart / execute_model / archive_outputs)
# against ush/nos_run.sh. The MPI launch + combine_hotstart7 + nccopy
# classic conversion all run inside _schism_execute_ufs_coastal (shell);
# Python only owns orchestration + structured error propagation.
#
# The CLI surfaces a structured FATAL one-liner on failure with full
# traceback in $DATA/nos_uw.forecast.<ts>.traceback.
exec python3 -m nos_workflow run forecast --ofs "${OFS}"
