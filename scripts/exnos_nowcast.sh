#!/bin/bash
###############################################################################
#  exnos_nowcast.sh - NOS-OFS nowcast driver (nos_workflow shim)
#
#  Sources nos_run.sh to populate env vars consumed by Python orchestration,
#  then hands off to nos_workflow.stages.nowcast. MPI launch, combine_hotstart7,
#  and COMOUT archive stay in shell (module-loaded MPI/netCDF/ESMF do not
#  survive a Python subprocess). Set NOS_USE_LEGACY_SHELL=YES to route through
#  the preserved pre-migration shell instead.
###############################################################################

set -x

if [ "${NOS_USE_LEGACY_SHELL:-NO}" = "YES" ]; then
    echo "NOS_USE_LEGACY_SHELL=YES — routing through preserved pre-migration shell"
    exec "${SCRIPTSnos}/legacy/exnos_nowcast.sh.preY-mig"
fi

echo "exnos_nowcast.sh started at $(date)"
echo "  OFS=${RUN}  PDY=${PDY}  cyc=${cyc}"

. ${USHnos}/nos_run.sh ${OFS} nowcast
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: nos_run.sh failed (rc=${err})"
    err_chk
fi

NOS_UTILS_DIR=${NOS_UTILS_DIR:-${USHnos}/python/nos-utils}
NOS_WORKFLOW_DIR=${NOS_WORKFLOW_DIR:-${USHnos}/python}
export PYTHONPATH="${NOS_WORKFLOW_DIR}:${NOS_UTILS_DIR}:${PYTHONPATH:-}"

# LD_PRELOAD must not leak into Python - segfaults numpy/netCDF4
unset LD_PRELOAD

python3 -c "import nos_workflow" || {
    echo "FATAL: nos_workflow not importable from PYTHONPATH=${PYTHONPATH}"
    export err=99; err_chk
}

exec python3 -m nos_workflow run nowcast --ofs "${OFS}"
