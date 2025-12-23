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


    # ---------> merge hotstart files
    cd ${DATA}/outputs/

    idx_time_step_merge_hotstart=576
    fn_merged_hotstart_ftn=hotstart_it\=${idx_time_step_merge_hotstart}.nc
    fn_hotstart_stofs3d_merged_std=${RUN}.${cycle}.hotstart.stofs3d.nc

    ${EXECstofs3d}/stofs_3d_atl_combine_hotstart  -i  ${idx_time_step_merge_hotstart}

    export err=$?
    pgm=${EXECstofs3d}/stofs_3d_atl_combine_hotstart

    if [ $err -eq 0 ]; then
       msg=`echo $pgm  completed normally`
       echo $msg; echo $msg >> $pgmout

       # fn_merged_hotstart_ftn=hotstart_it\=${idx_time_step_merge_hotstart}
       if [ -s ${fn_merged_hotstart_ftn} ]; then
          msg=`echo ${fn_merged_hotstart_ftn}} has been created`;
          echo $msg; echo $msg >> $pgmout

          fn_merged_hotstart_ftn_time_00=${fn_merged_hotstart_ftn}_time_00
          ncap2 -O -s 'time=0.0' ${fn_merged_hotstart_ftn}  ${fn_merged_hotstart_ftn_time_00}

          cpreq -pf ${fn_merged_hotstart_ftn_time_00} ${COMOUT}/${fn_hotstart_stofs3d_merged_std}

       else
         msg=`echo ${fn_merged_hotstart_ftn}} was not created`
         echo $msg; echo $msg >> $pgmout
       fi

    else
       msg=`echo $pgm did not complete normally`
       echo $msg; echo $msg >> $pgmout
    fi


    # ---------> create 2D field files
    file_log=log_create_2d_field_nc.${cycle}.log
    fn_ush_script=stofs_3d_atl_create_2d_field_nc.sh
    export pgm="${USHstofs3d}/${fn_ush_script}"

    rm -f $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 1 > $DATA/${file_log}_1 " >> $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 2 > $DATA/${file_log}_2 " >> $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 3 > $DATA/${file_log}_3 " >> $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 4 > $DATA/${file_log}_4 " >> $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 5 > $DATA/${file_log}_5 " >> $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 6 > $DATA/${file_log}_6 " >> $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 7 > $DATA/${file_log}_7 " >> $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 8 > $DATA/${file_log}_8 " >> $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 9 > $DATA/${file_log}_9 " >> $DATA/mpmdscript
    echo "${USHstofs3d}/${fn_ush_script} 10 > $DATA/${file_log}_10 " >> $DATA/mpmdscript

    chmod 775 $DATA/mpmdscript
    export MP_PGMMODEL=mpmd
    mpiexec -l -np 10 --cpu-bind verbose,core cfp $DATA/mpmdscript

    export err=$?
    if [ $err -ne 0 ];
    then
       msg=" Execution of $pgm did not complete normally - WARNING"
       postmsg "$jlogfile" "$msg"
       cat $DATA/${file_log}*
       err_chk
    else
       msg=" Execution of $pgm completed normally"
       postmsg "$jlogfile" "$msg"
       cat $DATA/${file_log}*
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




