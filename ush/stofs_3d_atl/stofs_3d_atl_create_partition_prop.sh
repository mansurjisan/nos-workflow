#!/bin/bash

#################################################################################################################
#  Name: stofs_3d_atl_create_partition_prop.sh                                                                #
#                                                                                                               #
#  This script checks whether the default partition.prop matches the PBS resource allocation.                  #
#  If not, it generates a new partition.prop using gpmetis (WCOSS2 system app).                                #
#                                                                                                               #
#  Remarks:                                                                                                     #
#  Synced with STOFS operational v3.1.0                                                      2024              #
#################################################################################################################

  seton='-xa'
  set $seton

# ----------------------->
  fn_this_script=stofs_3d_atl_create_partition_prop.sh

  msg="${fn_this_script} started"
  echo "$msg"
  postmsg  "$msg"

  pgmout=${fn_this_script}.$$

# ---------------------------> Load YAML Configuration (with fallback to defaults)
if [ -n "${OFS_CONFIG}" ] && [ -f "${OFS_CONFIG}" ]; then
    _yaml_to_env="${USHnos:-${HOMEnos}/ush}/python/nos_ofs/utils/yaml_to_env.py"
    if [ -f "${_yaml_to_env}" ]; then
        echo "Loading partition prop config from YAML: ${OFS_CONFIG}"
        _yaml_exports=$(python3 "${_yaml_to_env}" "${OFS_CONFIG}" --framework stofs 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "${_yaml_exports}" ]; then
            eval "${_yaml_exports}"
            echo "YAML config loaded successfully"
        fi
    fi
fi

# -----------------------> check for availability of partition_prop.nc

  mkdir -p ${DATA}/outputs
  cd ${DATA};

  echo "Current dir=`pwd`"; echo

# ----------> check N_partition of the existing partition.prop

  fn_par_prop_default_fix=partition.prop

  nproc_default_fix=$(awk -F' ' "{print \$2 }" partition.prop  | awk 'BEGIN{a=1}{if ($1>0+a) a=$1} END{print a}')

  echo
  echo "nproc_default_fix= ${nproc_default_fix} + 1"
  echo


  # n_scribes: from YAML (resources.nscribes) or default
  let n_scribes=${NSCRIBES:-8}
  let nproc_tgt=${NCPU_PBS}-${n_scribes}
     echo "nproc_tgt=${nproc_tgt}"
     echo


let nproc_default_fix_plus_1=${nproc_default_fix}+1
if [[ ${nproc_default_fix_plus_1} -eq ${nproc_tgt} ]]; then

  echo " In stofs_3d_atl_create_partition_prop.sh: "

  echo "No new partition.prop needs to be generated; continue to use the default in fix"
  echo


else

  echo " In stofs_3d_atl_create_partition_prop.sh: "
  echo "Default partition.prop does not match the need: nproc_default_fix_plus_1=${nproc_default_fix_plus_1}; nproc_tgt=${nproc_tgt}"
  echo

  mv partition.prop partition_prop_nproc_default_fix_${nproc_default_fix};

  # ---------->
    fn_exe_gen_partition=gpmetis      # WCOSS2 system app

    cd ${DATA}


    # ---------> Create new partition.prop
     rm -f graphinfo
     rm -f graphinfo.part.${nproc_tgt}

     # Use system prefix from YAML or default
     _GRAPH_PREFIX=${RUN:-stofs_3d_atl}
     cp -fp ${FIXstofs3d}/${_GRAPH_PREFIX}_graphinfo.txt ./

     ${fn_exe_gen_partition}  ${_GRAPH_PREFIX}_graphinfo.txt  ${nproc_tgt}  -ufactor=1.01  -seed=15


     fn_partition_new=partition.prop_NCPU_PBS_${NCPU_PBS}_nproc_${nproc_tgt}
       rm -f ${fn_partition_new}
       awk '{print NR,$0}' ${_GRAPH_PREFIX}_graphinfo.txt.part.${nproc_tgt} > ${fn_partition_new}

     ln -sf ${fn_partition_new} partition.prop


   # ---------->
    export err=$?

    if [ $err -eq 0 ]; then

      fn_partition_std_name=${_GRAPH_PREFIX}_partition.prop
      cp -pf ${fn_partition_new}  ${COMOUT}/rerun/${fn_partition_std_name}

      msg="Creation/Archiving of ${fn_partition_new} was successfully created"
      echo $msg; echo $msg >> $pgmout

    else
      msg="Creation/Archiving of partition.prop failed"
      echo $msg; echo $msg >> $pgmout

    fi

fi  # if [[ ${nproc_default_fix} -eq ${nproc_tgt} ]]; then


echo
echo "${fn_this_script} completed "
