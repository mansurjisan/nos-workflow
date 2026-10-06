#!/bin/bash
###############################################################################
#  exnos_adcirc.sh <prep|nowcast|forecast> - ADCIRC (STOFS-2D-GLO) ex-script
#
#  Hands off to nos_workflow.stages. Unlike the SCHISM shims it does not source
#  nos_run.sh: the ADCIRC runner builds its own command lines from the machine
#  profile, and the module environment set by the job card is inherited.
###############################################################################

set -x

STAGE=${1:?usage: exnos_adcirc.sh <prep|nowcast|forecast>}
echo "exnos_adcirc.sh ${STAGE} started at $(date)"
echo "  OFS=${OFS}  PDY=${PDY}  cyc=${cyc}"

NOS_UTILS_DIR=${NOS_UTILS_DIR:-${USHnos}/python/nos-utils}
NOS_WORKFLOW_DIR=${NOS_WORKFLOW_DIR:-${USHnos}/python}
export PYTHONPATH="${NOS_WORKFLOW_DIR}:${NOS_UTILS_DIR}:${PYTHONPATH:-}"

unset LD_PRELOAD

python3 -c "import nos_workflow" || {
    echo "FATAL: nos_workflow not importable from PYTHONPATH=${PYTHONPATH}"
    export err=99; err_chk
}

exec python3 -m nos_workflow run "${STAGE}" --ofs "${OFS}"
