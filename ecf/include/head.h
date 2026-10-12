#=============================================================================
# head.h - DEVELOPMENT stand-in for the NCO ecFlow header.
# In NCO operations ECF_INCLUDE points at NCO's own head.h, which replaces
# this file. Keep this directory LAST in ECF_INCLUDE on WCOSS2 so the NCO
# versions win wherever both exist.
#=============================================================================
set -e          # stop on the first error
set -u          # fail on undefined variables
set -x          # echo commands
set -o pipefail

export ECF_PORT=%ECF_PORT%
export ECF_HOST=%ECF_HOST%
export ECF_NAME=%ECF_NAME%
export ECF_PASS=%ECF_PASS%
export ECF_TRYNO=%ECF_TRYNO%
export ECF_RID=${PBS_JOBID:-$$}

ecflow_client --init=${ECF_RID}

ERROR() {
  set +e
  wait
  ecflow_client --abort=trap
  trap 0
  exit 0
}
trap ERROR 0
trap '{ echo "Killed by a signal"; ERROR; }' 1 2 3 4 5 6 7 8 10 12 13 15
