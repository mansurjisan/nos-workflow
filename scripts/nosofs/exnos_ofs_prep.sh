#!/bin/sh
# #########################################################################
#  Script Name: exnos_ofs_prep.sh
#  Purpose:                                                                #
#  This is the main script is launch sripts to generating forcing files    #
# Location:   ~/jobs
# Technical Contact:    Aijun Zhang         Org:  NOS/CO-OPS
#                       Phone: 240-533-0591 
#                       E-Mail: aijun.zhang@noaa.gov
#
#  Usage: 
#
# Input Parameters:
#   OFS 
#
# Modification History:
#     Degui Cao     02/18/2010   
# #########################################################################

set -x
#PS4=" \${SECONDS} \${0##*/} L\${LINENO} + "

echo "Start ${RUN} Preparation " > $cormslogfile

# ============================================================================
# YAML Configuration Loading (Phase 1 Integration)
# ============================================================================
# Try loading YAML config first, fall back to legacy .ctl file
# Priority: OFS_CONFIG env var -> FIXofs YAML -> FIXofs .ctl

CONFIG_SOURCE="none"

# Option 1: Load from OFS_CONFIG environment variable (YAML)
if [ -n "$OFS_CONFIG" ] && [ -f "$OFS_CONFIG" ]; then
    echo "Loading configuration from YAML: $OFS_CONFIG"
    if [ -f "${USHnos}/nos_ofs_config.sh" ]; then
        . ${USHnos}/nos_ofs_config.sh
        if [ "${OFS_CONFIG_LOADED:-0}" -eq 1 ]; then
            CONFIG_SOURCE="yaml"
            echo "Successfully loaded YAML config from $OFS_CONFIG" >> $cormslogfile
        fi
    fi
fi

# Option 2: Check for YAML config in FIXofs
if [ "$CONFIG_SOURCE" = "none" ] && [ -f "${FIXofs}/${PREFIXNOS}.yaml" ]; then
    echo "Loading configuration from YAML: ${FIXofs}/${PREFIXNOS}.yaml"
    export OFS_CONFIG="${FIXofs}/${PREFIXNOS}.yaml"
    if [ -f "${USHnos}/nos_ofs_config.sh" ]; then
        . ${USHnos}/nos_ofs_config.sh
        if [ "${OFS_CONFIG_LOADED:-0}" -eq 1 ]; then
            CONFIG_SOURCE="yaml"
            echo "Successfully loaded YAML config from ${FIXofs}/${PREFIXNOS}.yaml" >> $cormslogfile
        fi
    fi
fi

# Option 3: Fall back to legacy .ctl file
if [ "$CONFIG_SOURCE" = "none" ]; then
    if [ -s ${FIXofs}/${PREFIXNOS}.ctl ]; then
        . ${FIXofs}/${PREFIXNOS}.ctl
        CONFIG_SOURCE="ctl"
        echo "Loaded legacy .ctl config from ${FIXofs}/${PREFIXNOS}.ctl" >> $cormslogfile
    else
        echo "${RUN} control file is not found"
        echo "please provide ${RUN} control file: ${PREFIXNOS}.yaml or ${PREFIXNOS}.ctl in ${FIXofs}"
        msg="${RUN} control file is not found"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
        echo "${RUN} control file is not found" >> $cormslogfile
        err_chk
    fi
fi

echo "Configuration loaded from: $CONFIG_SOURCE"
# ============================================================================

export pgm="$USHnos/nos_ofs_launch.sh $OFS prep"
echo "run the launch script to set the NOS configuration"
. $USHnos/nos_ofs_launch.sh $OFS prep
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

# =============================================================================
# Meteorological Forcing (sflux) Generation — Nowcast
# Skip for UFS-Coastal (USE_DATM): atmospheric forcing is handled by DATM
# via the DATM forcing generation step below.
# =============================================================================
if [ "${USE_DATM:-false}" != "true" ] && [ "${USE_DATM:-0}" != "1" ]; then

export metnum=1


echo "The script nos_ofs_create_forcing_met.sh nowcast  starts at time: " `date `
. prep_step
echo "Generating the meteorological forcing for nowcast"
export pgm=nos_ofs_create_forcing_met.sh
DBASE=$DBASE_MET_NOW
TIME_START_TMP=${time_hotstart}
TIME_END_TMP=$time_nowcastend
export pgm=nos_ofs_create_forcing_met.sh
$USHnos/nos_ofs_create_forcing_met.sh nowcast $DBASE $TIME_START_TMP $TIME_END_TMP
#$USHnos/nos_ofs_create_forcing_met.sh nowcast
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
if [ -s MET_DBASE.NOWCAST ]; then
  read DBASE < MET_DBASE.NOWCAST
  echo 'DBASE=' $DBASE 'DBASE_MET_NOW='  $DBASE_MET_NOW
  if [ $DBASE != $DBASE_MET_NOW ]; then
    DBASE_MET_NOW=$DBASE
    export DBASE_MET_NOW
  fi
fi

if [ $MET_NUM -eq 2 ]
then
export metnum=2

export pgm=nos_ofs_create_forcing_met.sh
DBASE=$DBASE_MET_NOW2
TIME_START_TMP=${time_hotstart}
TIME_END_TMP=$time_nowcastend
#TIME_START_TMP=` $NDATE -3 ${time_hotstart} `
#TIME_END_TMP=` $NDATE +6 ${time_nowcastend} `
export pgm=nos_ofs_create_forcing_met.sh
$USHnos/nos_ofs_create_forcing_met.sh nowcast $DBASE $TIME_START_TMP $TIME_END_TMP
#$USHnos/nos_ofs_create_forcing_met.sh nowcast
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
if [ -s MET_DBASE.NOWCAST ]; then
  read DBASE < MET_DBASE.NOWCAST
  echo 'DBASE=' $DBASE 'DBASE_MET_NOW='  $DBASE_MET_NOW
  if [ $DBASE != $DBASE_MET_NOW ]; then
    DBASE_MET_NOW=$DBASE
    export DBASE_MET_NOW
  fi
fi

fi

else
  echo "Skipping sflux nowcast generation (USE_DATM=true, atmospheric forcing via DATM)"
  echo "Skipping sflux nowcast generation (USE_DATM=true)" >> $cormslogfile
fi

# =============================================================================
# UFS-Coastal DATM Forcing Generation (run early, before OBC/river)
# When USE_DATM is enabled, generate DATM blended HRRR+GFS forcing,
# ESMF meshes, and UFS config files (model_configure, datm_in,
# datm.streams, ufs.configure).
# No dependency on river, OBC, or model config steps.
# =============================================================================
if [ "${USE_DATM:-false}" == "true" ] || [ "${USE_DATM:-0}" == "1" ]; then
    echo "============================================"
    echo "Generating UFS-Coastal DATM forcing..."
    echo "============================================"

    # Export variables needed by DATM scripts
    export DATM_BLEND_HRRR_GFS=${DATM_BLEND_HRRR_GFS:-true}
    export DATM_DOMAIN=${DATM_DOMAIN:-SECOFS}
    export BLEND_RESOLUTION=${BLEND_RESOLUTION:-0.025}
    export BLEND_BUFFER_DEG=${BLEND_BUFFER_DEG:-0.5}
    export NHOURS_FCST=${LEN_FORECAST:-48}
    export DT_ATMOS=${DT_ATMOS:-720}
    export NHOUR=${NHOUR:-nhour}
    # DATM input directory and file naming
    export DATM_INPUT_DIR=${DATM_INPUT_DIR:-INPUT}
    export DATM_MESH_FILE=${DATM_MESH_FILE:-datm_esmf_mesh.nc}
    export DATM_FORCING_FILE=${DATM_FORCING_FILE:-datm_forcing.nc}

    # Run blended forcing orchestrator
    ${USHnos}/nosofs/nos_ofs_create_datm_forcing_blended.sh ${DATM_DOMAIN}
    export err=$?
    if [ $err -ne 0 ]; then
        echo "DATM forcing generation failed, FATAL ERROR!"
        echo "DATM forcing generation failed, FATAL ERROR!" >> $cormslogfile
        msg="DATM forcing generation failed, FATAL ERROR!"
        postmsg "$jlogfile" "$msg"
        err_chk
    else
        echo "DATM forcing generation completed normally"
        echo "DATM forcing generation completed normally" >> $cormslogfile
        msg="DATM forcing generation completed normally"
        postmsg "$jlogfile" "$msg"
    fi

    # Archive DATM artifacts to COMOUT
    DATM_DIR=${DATM_INPUT_DIR:-INPUT}
    mkdir -p $COMOUT/${RUN}.${cycle}.datm_input
    if [ -d ${DATA}/${DATM_DIR} ]; then
        cp -p ${DATA}/${DATM_DIR}/*.nc $COMOUT/${RUN}.${cycle}.datm_input/ 2>/dev/null || true
    fi
    for f in model_configure datm_in datm.streams ufs.configure fd_ufs.yaml noahmptable.tbl; do
        [ -s "${DATA}/${f}" ] && cp -p "${DATA}/${f}" "$COMOUT/${RUN}.${cycle}.${f}"
    done
    echo "DATM artifacts archived to $COMOUT"
fi

echo "The script nos_ofs_create_forcing_river.sh starts at time: " `date `
echo "Generating the river forcing"
export pgm=nos_ofs_create_forcing_river.sh
. prep_step
$USHnos/nos_ofs_create_forcing_river.sh
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
  echo "Execution of $pgm completed normally"
  echo "Execution of $pgm completed normally" >> $cormslogfile
  msg=" Execution of $pgm completed normally"
  postmsg "$jlogfile" "$msg"
  postmsg "$nosjlogfile" "$msg"
fi



if [ "${OFS,,}" != "lsofs" -a "${OFS,,}" != "loofs" ]; then
  echo "The script nos_ofs_create_forcing_obc.sh starts at time: " `date `
  echo "Generating the open boundary forcing"
  export pgm=nos_ofs_create_forcing_obc.sh
  . prep_step
  $USHnos/nos_ofs_create_forcing_obc.sh
  export err=$?
  if [ $err -ne 0 ];  then
    echo "Execution of $pgm did not complete normally, FATAL ERROR!"
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
    msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
  fi
fi
TS_NUDGING=${TS_NUDGING:-0}
if [ $TS_NUDGING -eq 1 ]; then
  echo "Generating the forcing for T/S nudging fields"
  export pgm=nos_ofs_create_forcing_nudg.sh
  . prep_step
  $USHnos/nos_ofs_create_forcing_nudg.sh
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
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
  fi
fi




# =============================================================================
# Meteorological Forcing (sflux) Generation — Forecast
# Skip for UFS-Coastal (USE_DATM): atmospheric forcing is handled by DATM.
# =============================================================================
if [ "${USE_DATM:-false}" != "true" ] && [ "${USE_DATM:-0}" != "1" ]; then

export metnum=1

if [ $LEN_FORECAST -gt 0 ]; then
  echo "The script nos_ofs_create_forcing_met.sh forecast starts at time: " `date `
  echo "Generating the meteorological forcing for forecst"
# added for blended met forcing source, e.g. HRRR:NDFD
  res="${DBASE_MET_FOR//[^:]}"
  nnn=${#res}
  export nfore=$((nnn + 1))

#export DBASE_MET_FOR1=${DBASE_MET_FOR%:*}
#export DBASE_MET_FOR2=${DBASE_MET_FOR#*:}

 if [ $nfore -eq 1 ]; then
  DBASE=${DBASE_MET_FOR%:*}
  TIME_START_TMP=${time_nowcastend}
  TIME_END_TMP=$time_forecastend
  export pgm=nos_ofs_create_forcing_met.sh
  $USHnos/nos_ofs_create_forcing_met.sh forecast  $DBASE $TIME_START_TMP $TIME_END_TMP
  export err=$?
  if [ $err -ne 0 ]; then
    echo "Execution of $pgm did not complete normally, FATAL ERROR!"
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
    msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"

  fi
 elif  [ $nfore -eq 2 ]; then
  DBASE=${DBASE_MET_FOR%:*}
  TIME_START_TMP=${time_nowcastend}
  TIME_END_TMP=` $NDATE +48 $TIME_START_TMP `
  export pgm=nos_ofs_create_forcing_met.sh
  export met_fore_round=1
  $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
  export err=$?
  if [ $err -ne 0 ]; then
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" 
    echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
    msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
    err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
## read in DBASE used in actual  met forcing generating
    if [ -s MET_DBASE.FORECAST ]; then
       read DBASE < MET_DBASE.FORECAST
       echo 'DBASE=' $DBASE 'DBASE_MET_FOR='  $DBASE_MET_FOR
    fi
#    cp -p $MET_NETCDF_1_FORECAST ${MET_NETCDF_1_FORECAST}.$DBASE
#    cp -p $MET_NETCDF_2_FORECAST ${MET_NETCDF_2_FORECAST}.$DBASE 
     cp -p $MET_NETCDF_1_FORECAST"1" ${MET_NETCDF_1_FORECAST}.$DBASE
     cp -p $MET_NETCDF_2_FORECAST"1" ${MET_NETCDF_2_FORECAST}.$DBASE
  fi

  DBASE=${DBASE_MET_FOR#*:}
#  TIME_START_TMP=$TIME_END_TMP
  TIME_START_TMP=${time_nowcastend}
  TIME_END_TMP=${time_forecastend}
  export pgm=nos_ofs_create_forcing_met.sh
  export met_fore_round=2
  $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
  export err=$?
  if [ $err -ne 0 ]; then
     echo "Execution of $pgm did not complete normally, FATAL ERROR!"
     echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
     msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
     postmsg "$jlogfile" "$msg"
     postmsg "$nosjlogfile" "$msg"
     err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
## read in DBASE used in actual  met forcing generating
    if [ -s MET_DBASE.FORECAST ]; then
      read DBASE < MET_DBASE.FORECAST
      echo 'DBASE=' $DBASE 'DBASE_MET_FOR='  $DBASE_MET_FOR
    fi
#    cp -p $MET_NETCDF_1_FORECAST ${MET_NETCDF_1_FORECAST}.$DBASE
#    cp -p $MET_NETCDF_2_FORECAST ${MET_NETCDF_2_FORECAST}.$DBASE   
     mv $MET_NETCDF_1_FORECAST"2" ${MET_NETCDF_1_FORECAST}.$DBASE
     mv $MET_NETCDF_2_FORECAST"2" ${MET_NETCDF_2_FORECAST}.$DBASE
     rm  $MET_NETCDF_1_FORECAST"1"
     rm  $MET_NETCDF_2_FORECAST"1"
  fi
 fi

#############################################################   machuan

if [ $MET_NUM -eq 2 ]
then
export metnum=2
DBASE=$DBASE_MET_FOR2

  TIME_START_TMP=${time_nowcastend}
  TIME_END_TMP=${time_forecastend}
  export pgm=nos_ofs_create_forcing_met.sh
  $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
  export err=$?
  if [ $err -ne 0 ]; then
     echo "Execution of $pgm did not complete normally, FATAL ERROR!"
     echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
     msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
     postmsg "$jlogfile" "$msg"
     postmsg "$nosjlogfile" "$msg"
     err_chk
  else
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
## read in DBASE used in actual  met forcing generating
    if [ -s MET_DBASE.FORECAST ]; then
      read DBASE < MET_DBASE.FORECAST
      echo 'DBASE=' $DBASE 'DBASE_MET_FOR='  $DBASE_MET_FOR
    fi
#    cp -p $MET_NETCDF_1_FORECAST ${MET_NETCDF_1_FORECAST}.$DBASE
#    cp -p $MET_NETCDF_2_FORECAST ${MET_NETCDF_2_FORECAST}.$DBASE
     mv $MET_NETCDF_1_FORECAST"2" ${MET_NETCDF_1_FORECAST}.$DBASE
     mv $MET_NETCDF_2_FORECAST"2" ${MET_NETCDF_2_FORECAST}.$DBASE
     rm  $MET_NETCDF_1_FORECAST"1"
     rm  $MET_NETCDF_2_FORECAST"1"
  fi
fi 

##################################


## read in DBASE used in actual  met forcing generating
 if [ -s MET_DBASE.FORECAST ]; then
  read DBASE < MET_DBASE.FORECAST
  echo 'DBASE=' $DBASE 'DBASE_MET_FOR='  $DBASE_MET_FOR
  if [ $DBASE != $DBASE_MET_FOR ]; then
    DBASE_MET_FOR=$DBASE
    export DBASE_MET_FOR
  fi
 fi
 echo "The script nos_ofs_create_forcing_met.sh forecast ended at time: " `date `
fi

else
  echo "Skipping sflux forecast generation (USE_DATM=true, atmospheric forcing via DATM)"
  echo "Skipping sflux forecast generation (USE_DATM=true)" >> $cormslogfile
fi

if [ ${OCEAN_MODEL} == "FVCOM" -o ${OCEAN_MODEL} == "fvcom" ]
then

 echo "Preparing FVCOM Control File for nowcast"
 export pgm="nos_ofs_prep_fvcom_ctl.sh  $OFS nowcast"
 $USHnos/nos_ofs_prep_fvcom_ctl.sh  $OFS nowcast
 export err=$?
 if [ $err -ne 0 ]
 then
   echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!"
   echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!" >> $cormslogfile
   msg=" Execution of nowcast ctl did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   err_chk
 else
   echo "Execution of nowcast ctl completed normally"
   echo "Execution of nowcast ctl completed normally" >> $cormslogfile
   msg=" Execution of nowcast ctl completed normally"
   postmsg "$jlogfile" "$msg"
 fi

 if [ $LEN_FORECAST -gt 0 ]; then
 echo "Preparing FVCOM Control File for forecast"
 $USHnos/nos_ofs_prep_fvcom_ctl.sh  $OFS forecast
 export err=$?
 if [ $err -ne 0 ]
 then
   echo "Execution of forecast ctl did not complete normally, FATAL ERROR! "
   echo "Execution of forecast ctl did not complete normally, FATAL ERROR! " >> $cormslogfile
   msg=" Execution of forecast ctl did not complete normally, FATAL ERROR! "
   postmsg "$jlogfile" "$msg"
   err_chk
 else
  echo "Execution of forecast ctl completed normally"
  echo "Execution of forecast ctl completed normally" >> $cormslogfile
  msg=" Execution of forecast ctl completed normally"
  postmsg "$jlogfile" "$msg"
 fi
 fi
elif [ ${OCEAN_MODEL} == "ROMS" -o ${OCEAN_MODEL} == "roms" ]
then
  echo "Preparing ROMS Control File for nowcast"
  export pgm=nos_ofs_prep_roms_ctl.sh
  . prep_step
  $USHnos/nos_ofs_prep_roms_ctl.sh  $OFS nowcast
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
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
  fi
  if [ $LEN_FORECAST -gt 0 ]; then
  echo "Preparing ROMS Control File for forecast"
  export pgm=nos_ofs_prep_roms_ctl.sh
  . prep_step
  $USHnos/nos_ofs_prep_roms_ctl.sh  $OFS forecast
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
    echo "Execution of $pgm completed normally"
    echo "Execution of $pgm completed normally" >> $cormslogfile
    msg=" Execution of $pgm completed normally"
    postmsg "$jlogfile" "$msg"
    postmsg "$nosjlogfile" "$msg"
  fi
  fi
elif [ ${OCEAN_MODEL} == "SELFE" -o ${OCEAN_MODEL} == "selfe" -o ${OCEAN_MODEL} == "SCHISM" -o ${OCEAN_MODEL} == "schism" ]
#elif [ ${OCEAN_MODEL} == "SCHISM" -o ${OCEAN_MODEL} == "schism" ]


then

# echo "Preparing SELFE Control File for nowcast"
 echo "Preparing SCHISM Control File for nowcast"

 export pgm="nos_ofs_prep_schism_ctl.sh  $OFS nowcast"
 $USHnos/nos_ofs_prep_schism_ctl.sh  $OFS nowcast
 export err=$?
 if [ $err -ne 0 ]
 then
   echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!"
   echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!" >> $cormslogfile
   msg=" Execution of nowcast ctl did not complete normally, FATAL ERROR!"
   postmsg "$jlogfile" "$msg"
   err_chk
 else
   echo "Execution of nowcast ctl completed normally"
   echo "Execution of nowcast ctl completed normally" >> $cormslogfile
   msg=" Execution of nowcast ctl completed normally"
   postmsg "$jlogfile" "$msg"
 fi

#############

tar -cvf ${NWM_SOURCE_SINK_NOW} -C ./data/ .

cp ${NWM_SOURCE_SINK_NOW} ${COMOUT}/${NWM_SOURCE_SINK_NOW}

read rnday < "nowcast_running_day"
ns=$(echo "scale=0; $rnday * 3600 *24" | bc)
nsecond=$(printf "%.0f\n" "$ns")

cd ./data

for i in vsink.th vsource.th  msource.th;
do
        awk -v  awk_var=$nsecond '{ $1 = $1 - awk_var ; print }' $i  >  $i.new
        awk '$1 >= 0'  $i.new >  $i.new.new
        mv $i.new.new $i
done
rm *.new
cd ..

tar -cvf ${NWM_SOURCE_SINK_FORE} -C ./data/ .
cp ${NWM_SOURCE_SINK_FORE} ${COMOUT}/${NWM_SOURCE_SINK_FORE}


#############



 if [ $LEN_FORECAST -gt 0 ]; then
# echo "Preparing SELFE Control File for forecast"
 echo "Preparing SCHISM Control File for forecast"

 $USHnos/nos_ofs_prep_schism_ctl.sh  $OFS forecast
 export err=$?
 if [ $err -ne 0 ]
 then
   echo "Execution of forecast ctl did not complete normally, FATAL ERROR! "
   echo "Execution of forecast ctl did not complete normally, FATAL ERROR! " >> $cormslogfile
   msg=" Execution of forecast ctl did not complete normally, FATAL ERROR! "
   postmsg "$jlogfile" "$msg"
   err_chk
 else
  echo "Execution of forecast ctl completed normally"
  echo "Execution of forecast ctl completed normally" >> $cormslogfile
  msg=" Execution of forecast ctl completed normally"
  postmsg "$jlogfile" "$msg"
 fi
 fi
fi

cp -p $jlogfile $COMOUT
	   echo "			  "
	   echo "END OF PREP SUCCESSFULLY "
	   echo "			  "

#exit
