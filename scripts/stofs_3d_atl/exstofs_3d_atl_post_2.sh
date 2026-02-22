#!/bin/bash

##############################################################################
#  Name: exstofs_3d_atl_post_2.sh                                              #
#  This script is a postprocessor to create the 2-D field nc files, namely,  #
#  stofs_3d_atl.t12z.????_???.field2d.nc and copies the files to the com     #
#  directory                                                                 #
#                                                                            #
#  Remarks:                                                                  #
#                                                        September, 2022     #
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton


# ----------------------->
  fn_this_script=exstofs_3d_atl_post_2

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }

  msg="${fn_this_script}.sh  started "
  echo "$msg"
  postmsg  "$msg"

  pgmout=${fn_this_script}.$$

  cd ${DATA}


# -----------------------> static files
  fn_station_in=$FIXstofs3d/${RUN}_station.in
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


if [[ ${flag_run_status} == 0 ]]; then    
    msg=`echo checked mirror.out: SCHISM model run was completed SUCCESSFULLY`
    echo $msg
    echo $msg >> $pgmout


  # Combined MPI run: merge hotstart (1 task) + create 2D field files (10 tasks) = 11 tasks
  rm -f $DATA/mpmdscript_hot_slab2d

  #-----------------------------> merge hotstart files
   file_log_create_hotstart=stofs_3d_atl_create_merged_hotstart_nc.${cycle}.log
   fn_ush_script_create_hotstart=stofs_3d_atl_create_merged_hotstart_nc.sh

     echo "${USHstofs3d}/${fn_ush_script_create_hotstart}  > $DATA/${file_log_create_hotstart} " >> $DATA/mpmdscript_hot_slab2d


  # ----------------------------> create 2D field files
    file_log_create_2d=log_create_2d_field_nc.${cycle}.log
    fn_ush_script_create_2d=stofs_3d_atl_create_2d_field_nc.sh

     echo "${USHstofs3d}/${fn_ush_script_create_2d} 1 > $DATA/${file_log_create_2d}_1 " >> $DATA/mpmdscript_hot_slab2d
     echo "${USHstofs3d}/${fn_ush_script_create_2d} 2 > $DATA/${file_log_create_2d}_2 " >> $DATA/mpmdscript_hot_slab2d
     echo "${USHstofs3d}/${fn_ush_script_create_2d} 3 > $DATA/${file_log_create_2d}_3 " >> $DATA/mpmdscript_hot_slab2d
     echo "${USHstofs3d}/${fn_ush_script_create_2d} 4 > $DATA/${file_log_create_2d}_4 " >> $DATA/mpmdscript_hot_slab2d
     echo "${USHstofs3d}/${fn_ush_script_create_2d} 5 > $DATA/${file_log_create_2d}_5 " >> $DATA/mpmdscript_hot_slab2d
     echo "${USHstofs3d}/${fn_ush_script_create_2d} 6 > $DATA/${file_log_create_2d}_6 " >> $DATA/mpmdscript_hot_slab2d
     echo "${USHstofs3d}/${fn_ush_script_create_2d} 7 > $DATA/${file_log_create_2d}_7 " >> $DATA/mpmdscript_hot_slab2d
     echo "${USHstofs3d}/${fn_ush_script_create_2d} 8 > $DATA/${file_log_create_2d}_8 " >> $DATA/mpmdscript_hot_slab2d
     echo "${USHstofs3d}/${fn_ush_script_create_2d} 9 > $DATA/${file_log_create_2d}_9 " >> $DATA/mpmdscript_hot_slab2d
     echo "${USHstofs3d}/${fn_ush_script_create_2d} 10 > $DATA/${file_log_create_2d}_10 " >> $DATA/mpmdscript_hot_slab2d


  # ----------------------------> finalize mpmdscript_hot_slab2d
    chmod 775 $DATA/mpmdscript_hot_slab2d
    export MP_PGMMODEL=mpmd

    N_np_hot_slab2d=11
    mpiexec -l -np ${N_np_hot_slab2d}  --cpu-bind verbose,core cfp $DATA/mpmdscript_hot_slab2d

    export err=$?
    if [ $err -ne 0 ];
    then
       msg=" Execution of creating hotstart.nc, field_2d  did not complete normally - WARNING"
       postmsg "$jlogfile" "$msg"
       err_chk
    else
       msg=" Execution of creating hotstart.nc, field_2d  completed normally"
       postmsg "$jlogfile" "$msg"
    fi

    echo $msg
    echo


 # ---------> create GeoPackage files: 
    file_log_geo=log_geopackage.${cycle}.log
    fn_ush_script_geo=stofs_3d_atl_create_geopackage.sh


    export pgm="${USHstofs3d}/${fn_ush_script_geo}"
    ${USHstofs3d}/${fn_ush_script_geo} >> ${DATA}/${file_log_geo} 2>&1

    export err=$?
    if [ $err -ne 0 ];
    then
       msg=" Execution of $pgm did not complete normally, WARNING"
       postmsg  "$msg"
       cat ${DATA}/${file_log_geo}
       #err_chk
    else
       msg=" Execution of $pgm completed normally"
       postmsg  "$msg"
       cat ${DATA}/${file_log_geo}
    fi

    echo $msg
    echo
 

  # ---------------------------------------> Completed post processing

  msg=" Finished ${fn_this_script}.sh  SUCCESSFULLY "
  postmsg  "$msg"


  chmod -Rf 755 $COMOUT


  echo
  echo $msg 
  echo


else
     msg=`echo SCHISM model run did NOT finish successfully: Not Found \"${str_model_run_status}\" in ${fn_mirror}`
     echo $msg
     echo $msg >> $pgmout

# if [ -s ${fn_mirror} ] && [ -n "${str_model_run_status}" ]; then
fi




