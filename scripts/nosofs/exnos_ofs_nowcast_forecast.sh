#!/bin/sh

# ############################################################################
#  Script Name:  exnos_ofs_nowcast_forecast.sh.sms 
#  Purpose:                                                                   #
#  This is the main script is launch both nowcast and forecast simulations    #
# Location:   ~/jobs
# Technical Contact:    Aijun Zhang         Org:  NOS/CO-OPS
#                       Phone: 301-7132890 ext. 127
#                       E-Mail: aijun.zhang@noaa.gov
#
# Usage: 
#
# Input Parameters:
#  OFS 
#
# Modification History:
#     Degui Cao     02/18/2010   
# ##########################################################################

set -x
#PS4=" \${SECONDS} \${0##*/} L\${LINENO} + "

##############################################################################
# CONFIGURATION LOADING
# Priority: 1. OFS_CONFIG env var (YAML), 2. FIXofs YAML, 3. FIXofs .ctl
##############################################################################

CONFIG_LOADED=0

# Find Python package location for YAML support
for search_path in \
    "${HOMEnos}/ush/python" \
    "${HOMEnos}/nos_ofs/ush/python" \
    "$(dirname $0)/../../ush/python"
do
    if [ -d "$search_path/nos_ofs" ]; then
        export PYnos_ofs="$search_path"
        break
    fi
done

# Option 1: Load from OFS_CONFIG environment variable (YAML)
if [ "$CONFIG_LOADED" -eq 0 ] && [ -n "$OFS_CONFIG" ] && [ -f "$OFS_CONFIG" ]; then
    echo "Attempting to load YAML config from OFS_CONFIG: $OFS_CONFIG"
    if [ -n "$PYnos_ofs" ]; then
        export PYTHONPATH="${PYnos_ofs}:${PYTHONPATH}"
        yaml_exports=$(python3 -m nos_ofs.cli export-env --config "$OFS_CONFIG" --framework comf 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "$yaml_exports" ]; then
            eval "$yaml_exports"
            CONFIG_LOADED=1
            echo "Configuration loaded from YAML: $OFS_CONFIG"
        else
            echo "WARNING: Failed to parse YAML config: $OFS_CONFIG"
        fi
    fi
fi

# Option 2: Try to find YAML config in FIXofs
if [ "$CONFIG_LOADED" -eq 0 ] && [ -n "$PYnos_ofs" ] && [ -f "${FIXofs}/${PREFIXNOS}.yaml" ]; then
    echo "Attempting to load YAML config from FIXofs: ${FIXofs}/${PREFIXNOS}.yaml"
    export PYTHONPATH="${PYnos_ofs}:${PYTHONPATH}"
    yaml_exports=$(python3 -m nos_ofs.cli export-env --config "${FIXofs}/${PREFIXNOS}.yaml" --framework comf 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$yaml_exports" ]; then
        eval "$yaml_exports"
        export OFS_CONFIG="${FIXofs}/${PREFIXNOS}.yaml"
        CONFIG_LOADED=1
        echo "Configuration loaded from YAML: ${FIXofs}/${PREFIXNOS}.yaml"
    fi
fi

# Option 3: Fall back to legacy .ctl file
if [ "$CONFIG_LOADED" -eq 0 ]; then
    if [ -s ${FIXofs}/${PREFIXNOS}.ctl ]; then
        . ${FIXofs}/${PREFIXNOS}.ctl
        CONFIG_LOADED=1
        echo "Configuration loaded from legacy .ctl: ${FIXofs}/${PREFIXNOS}.ctl"
    fi
fi

# Verify configuration was loaded
if [ "$CONFIG_LOADED" -eq 0 ]; then
    echo "${RUN} control file is not found, FATAL ERROR!"
    echo "please provide ${RUN} config: ${PREFIXNOS}.yaml or ${PREFIXNOS}.ctl in ${FIXofs}"
    msg="${RUN} control file is not found, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    msg="please provide ${RUN} config: ${PREFIXNOS}.yaml or ${PREFIXNOS}.ctl in ${FIXofs}"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    echo "${RUN} control file is not found, FATAL ERROR!" >> $cormslogfile
    err_chk
fi

# Validate task count if running under LSF
if [ -n "$LSB_DJOB_NUMPROC" ] && [ -n "$TOTAL_TASKS" ] && [ $TOTAL_TASKS -ne $LSB_DJOB_NUMPROC ]; then
    err_exit "Number of tasks/CPUs ($LSB_DJOB_NUMPROC) does not meet job requirements (TOTAL_TASKS=$TOTAL_TASKS)."
fi

##############################################################################
# Source shared model run library
##############################################################################
source ${USHnos}/nos_ofs_model_run.sh

##############################################################################
# NOWCAST PHASE
##############################################################################

# Stage files and configure model (calls nos_ofs_launch.sh internally)
stage_model_files "nowcast"
export err=$?
if [ $err -ne 0 ]; then
    msg="FATAL: stage_model_files nowcast failed"
    echo "$msg"; echo "$msg" >> $cormslogfile
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
fi

# Run nowcast simulation
execute_model "nowcast"
export err=$?
if [ $err -ne 0 ]; then
    msg="FATAL: execute_model nowcast failed"
    echo "$msg"; echo "$msg" >> $cormslogfile
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
fi

# Archive nowcast outputs
archive_outputs "nowcast"
export err=$?
if [ $err -ne 0 ]; then
    msg="FATAL: archive_outputs nowcast failed"
    echo "$msg"; echo "$msg" >> $cormslogfile
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
fi

echo "end of nowcast"

##############################################################################
# FORECAST PHASE
##############################################################################

if [ ${LEN_FORECAST:-0} -gt 0 ]; then

# Run forecast simulation
execute_model "forecast"
export err=$?
if [ $err -ne 0 ]; then
    msg="FATAL: execute_model forecast failed"
    echo "$msg"; echo "$msg" >> $cormslogfile
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
fi

# Archive forecast outputs
archive_outputs "forecast"
export err=$?
if [ $err -ne 0 ]; then
    msg="FATAL: archive_outputs forecast failed"
    echo "$msg"; echo "$msg" >> $cormslogfile
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
fi

if [ $SENDDBN = YES ]; then
  $DBNROOT/bin/dbn_alert MODEL $DBN_ALERT_TYPE_TEXT $job $nosjlogfile
fi
fi

echo "                                    "
echo "END OF NOWCAST/FORECAST SUCCESSFULLY"
echo "                                    "
###############################################################
