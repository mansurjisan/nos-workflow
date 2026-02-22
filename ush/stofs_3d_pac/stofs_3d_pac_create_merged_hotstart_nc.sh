#!/bin/bash

#################################################################################
#  Name: stofs_3d_pac_create_merged_hotstart_nc.sh                              #
#                                                                               #
#  Remarks: this script creates the global domain hotstart.nc through merging   #
#           the sub-domain hotstart nc                                          #
#                                                                               #
#                                                    December 2023; Aug. 2025   #
#  Synced with STOFS operational v3.1.0                                         #
#################################################################################


# ---------------------------> Begin ...
 set -x

  fn_this_sh="stofs_3d_pac_create_merged_hotstart_nc.sh"

  echo " ${fn_this_sh} began"

  pgmout=`pwd`/pgmout_stofs3d_create_merged_hotstart_nc.$$
  rm -f $pgmout

  msg="In ${fn_this_sh}:: begins ... "
  echo $msg >> $pgmout

# ---------------------------> Load YAML Configuration (with fallback to defaults)
if [ -n "${OFS_CONFIG}" ] && [ -f "${OFS_CONFIG}" ]; then
    _yaml_to_env="${USHnos:-${HOMEnos}/ush}/python/nos_ofs/utils/yaml_to_env.py"
    if [ -f "${_yaml_to_env}" ]; then
        echo "Loading merged hotstart config from YAML: ${OFS_CONFIG}"
        _yaml_exports=$(python3 "${_yaml_to_env}" "${OFS_CONFIG}" --framework stofs 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "${_yaml_exports}" ]; then
            eval "${_yaml_exports}"
            echo "YAML config loaded successfully"
        fi
    fi
fi


# ---------------------------> Global Variables


# -------------------------->
  cd ${DATA}/outputs; pwd


    idx_time_step_merge_hotstart=${IDX_HOTSTART_TIMESTEP:-960}
    fn_merged_hotstart_ftn=hotstart_it\=${idx_time_step_merge_hotstart}.nc
    fn_hotstart_stofs3d_merged_std=${RUN}.${cycle}.hotstart.stofs3d.nc

    ${EXECstofs3d}/${RUN:-stofs_3d_pac}_combine_hotstart  -i  ${idx_time_step_merge_hotstart}


    export err=$?
    if [ $err -eq 0 ]; then
       msg=`echo $fn_this_sh completed normally`
       echo $msg; echo $msg >> $pgmout

       if [ -s ${fn_merged_hotstart_ftn} ]; then
          msg=`echo ${fn_merged_hotstart_ftn} has been created`;
          echo $msg; echo $msg >> $pgmout

          fn_merged_hotstart_ftn_time_00=${fn_merged_hotstart_ftn}_time_00
          ncap2 -O -s 'time=0.0' ${fn_merged_hotstart_ftn}  ${fn_merged_hotstart_ftn_time_00}

          echo 'cp: ${fn_merged_hotstart_ftn_time_00} ${COMOUT}/${fn_hotstart_stofs3d_merged_std}'
          echo
          cpreq -pf ${fn_merged_hotstart_ftn_time_00} ${COMOUT}/${fn_hotstart_stofs3d_merged_std}

       else
         msg=`echo ${fn_merged_hotstart_ftn} was not created`
         echo $msg; echo $msg >> $pgmout
       fi

    else
       msg=`echo $fn_this_sh did not complete normally`
       echo $msg; echo $msg >> $pgmout

    fi


echo
echo "${fn_this_sh} completed "
echo
