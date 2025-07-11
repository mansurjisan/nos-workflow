#!/bin/bash

#####################################################################################
#  Name: exstofs_3d_atl_post_1.sh                                                     #
#  This script is a postprocessor to create combined hotstart nc file, and          #
#  all the post-model files (that are listed in the STOFS Transition Release        #
#  forms), execpt the 2-D field nc files (which are created exstofs_3d_atl_post_2.sh  #
#                                                                                   #
#  Remarks:                                                                         #
#                                                               September, 2022     #
#####################################################################################

TIMING_LOG="${DATA}/timing_${cycle}.log"
echo "STOFS 3D Atlantic Post Processing Timing Report" > "${TIMING_LOG}"
echo "Started at: $(date)" >> "${TIMING_LOG}"
# Declare global variable for timing
declare -g STEP_START_TIME

time_start() {
    STEP_NAME="$1"
    STEP_START_TIME=$(date +%s)  # Store start time in global variable
    echo "Starting $STEP_NAME at $(date)" >> "${TIMING_LOG}"
}

time_end() {
    local end_time=$(date +%s)
    local duration=$((end_time - STEP_START_TIME))  # Use global start time
    echo "Completed $1 in $((duration/60)) minutes and $((duration%60)) seconds" >> "${TIMING_LOG}"
    echo "----------------------------------------" >> "${TIMING_LOG}"
}


# exstofs_3d_atl_post_processing.sh 

  seton='-xa'
  setoff='+xa'
  set $seton


# ----------------------->

  fn_this_sh="exstofs_3d_atl_post_1"


  echo "module list::"
  module list
  echo; echo


  msg="${fn_this_sh}.sh started "
  echo "$msg"
  postmsg  "$msg"


  pgmout=${fn_this_sh}.$$


# -----------------------> static files
  fn_station_in=$FIXstofs3d/${RUN}_station.in
  
  cd ${DATA}
  cpreq --remove-destination -f ${fn_station_in} station.in


# -----------------------> check & wait for model run complete 
fn_mirror=outputs/mirror.out
str_model_run_status="Run completed successfully"

time_sleep_s=600

flag_run_status=1

cnt=0
while [[ $cnt -le 30 ]]; do

  flag_run_status=`grep "${str_model_run_status}" ${fn_mirror} >/dev/null; echo $?`

    time_elapsed=$(( ${cnt} * ${time_sleep_s} ))

    echo "Elapsed time (sec) =  ${time_elapsed} "
    echo "flag_run_status=${flag_run_status} (0:suceecess)"; echo


    if [[ ${flag_run_status} == 0 ]]; then
        msg="Model run completed. Proceed to post-processing ..."
        echo -e ${msg};  
        echo -e  ${msg} >> $pgmout
        break
    else
        echo "Wait for ${time_sleep_s} more seconds"; echo
        sleep ${time_sleep_s}    # 10min=600s
	cnt=$(( ${cnt} + 1 ))
    fi
done

# ----------------------->

if [[ ${flag_run_status} == 0 ]]; then
    msg=`echo checked mirror.out: SCHISM model run was completed SUCCESSFULLY`
    echo $msg
    echo $msg >> $pgmout


    #sleep 180s     # wait for stofs_3d_atl_create_geopackage.sh


    # ---------------> cp'ed from NCO: prod package (2023/03/16)
    cd ${DATA}
    if [  ! -s done_cp_nc ]; then
        mkdir -p Dir_backup_2d3d
        cpreq -fpa  outputs/{horizontalVelX,horizontalVelY,out2d,salinity,temperature,zCoordinates}*.nc Dir_backup_2d3d

    fi


    # ---------> Update 2d & 3d nc: adding variable attributes
    time_start "POST1/stofs_3d_atl_add_attr_2d_3d_nc"
    
    file_log_attr=log_add_attribute_2d_3d_nc.${cycle}.log
    fn_ush_script_attr=stofs_3d_atl_add_attr_2d_3d_nc.sh

    export pgm="${USHstofs3d}/${fn_ush_script_attr}"

    file_log=add_attribute_2d_3d_nc.${cycle}
    
    rm -f $DATA/mpmdscript_add_attr

    echo "${USHstofs3d}/${fn_ush_script_attr} 1 > $DATA/${file_log}_1 " >> $DATA/mpmdscript_add_attr
    echo "${USHstofs3d}/${fn_ush_script_attr} 2 > $DATA/${file_log}_2 " >> $DATA/mpmdscript_add_attr
    echo "${USHstofs3d}/${fn_ush_script_attr} 3 > $DATA/${file_log}_3 " >> $DATA/mpmdscript_add_attr
#    echo "${USHstofs3d}/${fn_ush_script_attr} 4 > $DATA/${file_log}_4 " >> $DATA/mpmdscript_add_attr
#    echo "${USHstofs3d}/${fn_ush_script_attr} 5 > $DATA/${file_log}_5 " >> $DATA/mpmdscript_add_attr
#    echo "${USHstofs3d}/${fn_ush_script_attr} 6 > $DATA/${file_log}_6 " >> $DATA/mpmdscript_add_attr
#    echo "${USHstofs3d}/${fn_ush_script_attr} 7 > $DATA/${file_log}_7 " >> $DATA/mpmdscript_add_attr
#    echo "${USHstofs3d}/${fn_ush_script_attr} 8 > $DATA/${file_log}_8 " >> $DATA/mpmdscript_add_attr
#    echo "${USHstofs3d}/${fn_ush_script_attr} 9 > $DATA/${file_log}_9 " >> $DATA/mpmdscript_add_attr
#    echo "${USHstofs3d}/${fn_ush_script_attr} 10 > $DATA/${file_log}_10 " >> $DATA/mpmdscript_add_attr

    chmod 775 $DATA/mpmdscript_add_attr
    export MP_PGMMODEL=mpmd
#    mpiexec --oversubscribe -np 10 cfp $DATA/mpmdscript_add_attr
    $DATA/mpmdscript_add_attr


    export err=$?
    if [ $err -ne 0 ];
    then
       msg=" Execution of $pgm did not complete normally, WARNING"
       postmsg  "$msg"
       #err_chk
    else
       msg=" Execution of $pgm completed normally"
       postmsg  "$msg"
    fi

    echo $msg
    echo
    time_end "POST1/stofs_3d_atl_add_attr_2d_3d_nc"
    

    # ---------> create staout 6-min nc & SHEF file
    time_start "POST1/stofs_3d_atl_create_awips_shef"
    file_log_awips=log_create_awips_shef.${cycle}.log
    fn_ush_script_awips=stofs_3d_atl_create_awips_shef.sh
    export pgm="${USHstofs3d}/${fn_ush_script_awips}"
    ${USHstofs3d}/${fn_ush_script_awips} >> ${file_log_awips} 2>&1

    export err=$?
    if [ $err -ne 0 ];
    then
       msg=" Execution of $pgm did not complete normally - WARNING"
       postmsg  "$msg"
       #err_chk
    else
       msg=" Execution of $pgm completed normally"
       postmsg  "$msg"
    fi

    echo $msg
    echo

    time_end "POST1/stofs_3d_atl_create_awips_shef"
exit    
    # ---------> create AWS/EC2 auto nc files
    time_start "POST1/stofs_3d_atl_create_AWS_autoval_nc"
    file_log_autoval=log_stofs_3d_atl_create_AWS_autoval_nc.${cycle}.log
    fn_ush_script_autoval=stofs_3d_atl_create_AWS_autoval_nc.sh
    export pgm="${USHstofs3d}/${fn_ush_script_autoval}"
    ${USHstofs3d}/${fn_ush_script_autoval} >> ${file_log_autoval} 2>&1

    export err=$?
    if [ $err -ne 0 ];
    then
       msg=" Execution of $pgm did not complete normally - WARNING"
       postmsg  "$msg"
       #err_chk
    else
       msg=" Execution of $pgm completed normally"
       postmsg  "$msg"
    fi

    echo $msg
    echo
    time_end "POST1/stofs_3d_atl_create_AWS_autoval_nc"
    

    # ---------> create profile netcdf files
    time_start "POST1/stofs_3d_atl_create_station_profile_nc"
    file_log_prof=log_create_sta_profile.${cycle}.log
    fn_ush_script_prof=stofs_3d_atl_create_station_profile_nc.sh
    #fn_ush_script_prof=stofs_3d_atl_create_station_profile_nc_opt.sh
    export pgm="${USHstofs3d}/${fn_ush_script_prof}"
    ${USHstofs3d}/${fn_ush_script_prof} >> ${file_log_prof} 2>&1

    export err=$?
    if [ $err -ne 0 ];
    then
       msg=" Execution of $pgm did not complete normally - WARNING"
       postmsg  "$msg"
       #err_chk
    else
       msg=" Execution of $pgm completed normally"
       postmsg  "$msg"
    fi

    echo $msg
    echo
    time_end "POST1/stofs_3d_atl_create_station_profile_nc"
    

  #  ---------> Create ADCIRC format water level fields: stofs_3d_atl_create_adcirc_nc.sh
    time_start "POST1/stofs_3d_atl_create_adcirc_nc"
    file_log_adc=log_stofs_3d_atl_create_adcirc_nc.${cycle}.log
    #fn_ush_script_adc=stofs_3d_atl_create_adcirc_nc_opt.sh
    #fn_ush_script_adc=stofs_3d_atl_create_adcirc_nc_py_opt.sh
    fn_ush_script_adc=stofs_3d_atl_create_adcirc_nc.sh
    export pgm="${USHstofs3d}/${fn_ush_script_adc}"
    ${USHstofs3d}/${fn_ush_script_adc} >> ${file_log_adc} 2>&1

    export err=$?
    if [ $err -ne 0 ];
    then
       msg=" Execution of $pgm did not complete normally - WARNING"
       postmsg  "$msg"
       #err_chk
    else
       msg=" Execution of $pgm completed normally"
       postmsg  "$msg"
    fi

    echo $msg
    echo
    time_end "POST1/stofs_3d_atl_create_adcirc_nc"
   
   # ----------> Create AWIPS grib2 files: conus_east_us & puertori masks
    time_start "POST1/stofs_3d_atl_create_awips_grib2"
    file_log_grib2=log_create_awips_grib2_${cycle}.log
    fn_ush_script_grib2=stofs_3d_atl_create_awips_grib2.sh

    export pgm="${USHstofs3d}/${fn_ush_script_grib2}"
    ${USHstofs3d}/${fn_ush_script_grib2} >> ${file_log_grib2} 2>&1

    export err=$?
    if [ $err -ne 0 ];
    then
       msg=" Execution of $pgm did not complete normally - WARNING"
       postmsg  "$msg"
       #err_chk
    else
       msg=" Execution of $pgm completed normally"
       postmsg  "$msg"
    fi

    echo $msg
    echo
    time_end "POST1/stofs_3d_atl_create_awips_grib2"

  # ---------------------------------------> Completed post processing

  msg=" Finished ${fn_this_sh}.sh  SUCCESSFULLY "
  postmsg  "$msg"


  chmod -Rf 755 $COMOUT


  echo
  echo $msg 
  echo


else
    
     msg=`echo SCHISM model run did NOT finish successfully: Not Found \"${str_model_run_status}\" in ${fn_mirror}`
     echo -e $msg
     echo -e $msg >> $pgmout

# if [ -s ${fn_mirror} ] && [ -n "${str_model_run_status}" ]; then
fi




