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

echo "run the launch script to set the NOS configuration"
. $USHnos/nos_ofs_launch.sh $OFS nowcast
export pgm="$USHnos/nos_ofs_launch.sh $OFS nowcast"
export err=$?
if [ $err -ne 0 ]
then
   echo "Execution of $pgm did not complete normally, FATAL ERROR!"
   echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
   msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
   err_chk
else
   echo "Execution of $pgm completed normally" >> $cormslogfile
   echo "Execution of $pgm completed normally"
   msg=" Execution of $pgm completed normally"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
fi

#####     Run nowcast simulation
runtype='nowcast'
echo "     " >> $jlogfile 
echo "     " >> $nosjlogfile 
echo " Start $runtype " >> $jlogfile
echo " Start $runtype " >> $nosjlogfile
echo "Making $runtype at : `date`" >> $jlogfile
echo "Making $runtype at : `date`" >> $nosjlogfile
echo "Making $runtype at : `date`"
export pgm="$USHnos/nos_ofs_nowcast_forecast.sh $runtype"
$USHnos/nos_ofs_nowcast_forecast.sh $runtype 
export err=$?
if [ $err -ne 0 ]
then
   echo "Execution of $pgm did not complete normally, FATAL ERROR!"
   echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
   msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
   err_chk
else
   echo "Execution of $pgm completed normally" >> $cormslogfile
   echo "Execution of $pgm completed normally"
   msg=" Execution of $pgm completed normally"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
fi

###  archive nowcast outputs
export pgm="$USHnos/nos_ofs_archive.sh $runtype"
$USHnos/nos_ofs_archive.sh $runtype
export err=$?
if [ $err -ne 0 ]
then
   echo "Execution of $pgm did not complete normally, FATAL ERROR!"
   echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
   msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
   err_chk
else
   echo "Execution of $pgm completed normally" >> $cormslogfile
   echo "Execution of $pgm completed normally"
   msg=" Execution of $pgm completed normally"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
fi

# if [ $envir = "dev" ]; then
#   $USHnos/nos_ofs_sftp.sh $runtype
# fi
 echo "end of $runtype"

if [ $LEN_FORECAST -gt 0 ] 
then
#####    Run forecast simulation
runtype='forecast'

echo "     " >> $jlogfile 
echo "     " >> $nosjlogfile 
echo " Start nos_ofs_nowcast_forecast.sh $runtype at : `date`" >> $jlogfile
echo " Start nos_ofs_nowcast_forecast.sh $runtype at : `date`" >> $nosjlogfile
echo "Running nos_ofs_nowcast_forecast.sh $runtype at : `date`" >> $jlogfile
echo "Running nos_ofs_nowcast_forecast.sh $runtype at : `date`" >> $nosjlogfile
echo " Start nos_ofs_nowcast_forecast.sh $runtype at : `date`" 
export pgm="$USHnos/nos_ofs_nowcast_forecast.sh $runtype"
$USHnos/nos_ofs_nowcast_forecast.sh $runtype 
export err=$?
if [ $err -ne 0 ]
then
   echo "Execution of $pgm did not complete normally, FATAL ERROR!"
   echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
   msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
   err_chk
else
   echo "Execution of $pgm completed normally" >> $cormslogfile
   echo "Execution of $pgm completed normally"
   msg=" Execution of $pgm completed normally"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
fi
echo "end of nos_ofs_nowcast_forecast.sh $runtype"

##  archive forecast outputs 
export pgm="$USHnos/nos_ofs_archive.sh $runtype"
$USHnos/nos_ofs_archive.sh $runtype 
export err=$?
if [ $err -ne 0 ]
then
   echo "Execution of $pgm did not complete normally, FATAL ERROR!"
   echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
   msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
   err_chk
else
   echo "Execution of $pgm completed normally" >> $cormslogfile
   echo "Execution of $pgm completed normally"
   msg=" Execution of $pgm completed normally"
   postmsg "$jlogfile" "$msg"
   postmsg "$nosjlogfile" "$msg"
fi

# if [ $envir = "dev" ]; then
#  # for development copy outputs to CO-OPS via sftp push 
#   $USHnos/nos_ofs_sftp.sh $runtype
# fi
if [ $SENDDBN = YES ]; then
  $DBNROOT/bin/dbn_alert MODEL $DBN_ALERT_TYPE_TEXT $job $nosjlogfile
fi
fi
          echo "                                    "
          echo "END OF NOWCAST/FORECAST SUCCESSFULLY"
          echo "                                    "
###############################################################
