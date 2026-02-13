#!/bin/bash
## ============================================================
## head.h - Standard ecFlow header for NOS-OFS unified workflow
##
## This include is sourced at the top of every .ecf script.
## It initializes the ecFlow client, sets up signal traps for
## proper abort handling, and exports standard job variables.
## ============================================================
set -x
date
export PS4='$SECONDS + '

########################################
# ecFlow client communication variables
########################################
export ECF_PORT=%ECF_PORT%
export ECF_HOST=%ECF_HOST%
export ECF_NAME=%ECF_NAME%
export ECF_PASS=%ECF_PASS%
export ECF_TRYNO=%ECF_TRYNO%
export ECF_RID=$$

########################################
# Job identification
########################################
export job=%TASK%
export jobid="${job}.$$"

########################################
# Signal traps for ecFlow error handling
########################################
ERROR() {
    set +ex
    wait
    ecflow_client --abort="${1}"
    trap 0
    exit
}

# Trap fatal signals and errors
trap 'ERROR "trapped signal"' 1 2 3 4 5 6 7 8 10 12 13 15
trap 'ERROR "error exit"' ERR

########################################
# Notify ecFlow server that job has started
########################################
ecflow_client --init="${ECF_RID}"
