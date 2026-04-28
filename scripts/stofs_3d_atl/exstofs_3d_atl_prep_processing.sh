#!/bin/bash 

##############################################################################
#  Name: exstofs_3d_atl_prep_processing.sh                                      #
#  This script prepares the files needed by the nowcast and forecast         #
#  simulations, which includes the run control, tidal, river, surface, ope   #
#  ocean boundary, nudging forcings, and the initial condition restart       #
#  files                                                                     #
#                                                                            #
#  Remarks:                                                                  #
#                                                        September, 2022     #
##############################################################################


  seton='-xa'
  setoff='+xa'
  set $setoff
  #set $seton

  fn_this_script="exstofs_3d_atl_prep_processing.sh"

  msg="Starting script: STOFS3D prepare model control & forcing files"
  echo "$msg"
#  postmsg  "$msg"
  postmsg "$jlogfile" "$msg"

# ---------------------------> Load YAML Configuration (with fallback to defaults)
# Try to load from YAML if OFS_CONFIG is set and yaml_to_env.py is available
# This exports config values to environment for use by child scripts
if [ -n "${OFS_CONFIG}" ] && [ -f "${OFS_CONFIG}" ]; then
    _yaml_to_env="${USHnos:-${HOMEnos}/ush}/python/nos_ofs/utils/yaml_to_env.py"
    if [ -f "${_yaml_to_env}" ]; then
        echo "Loading STOFS prep config from YAML: ${OFS_CONFIG}"
        _yaml_exports=$(python3 "${_yaml_to_env}" "${OFS_CONFIG}" --framework stofs 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "${_yaml_exports}" ]; then
            eval "${_yaml_exports}"
            export OFS_CONFIG_LOADED=1
            echo "YAML config loaded successfully"
            # Log key config values
            echo "  LONMIN=${LONMIN:-not set}, LONMAX=${LONMAX:-not set}"
            echo "  LATMIN=${LATMIN:-not set}, LATMAX=${LATMAX:-not set}"
            echo "  N_list_target=${N_list_target:-not set}"
        else
            echo "WARNING: Failed to parse YAML config, using defaults"
        fi
    else
        echo "WARNING: yaml_to_env.py not found at ${_yaml_to_env}"
    fi
else
    echo "INFO: OFS_CONFIG not set or file not found, using script defaults"
fi

  echo "module list in ${fn_this_script}"
  module list
  echo; echo

 
  # flag to control the type of restart file
  # FLAG_RESTART_RTOFS= 0: use stofs3D hotstart.nc; 1: only use RTOFS; 2: combined RTOFS restart & STOFS3D hotstart

  
  mkdir -p ${DATA}
  cd $DATA


# ----------------------------------------> Static files
# copy/ln  model run static filess, e.g., model grid, station output control files, etc. 

ln -sf $FIXstofs3d/${RUN}_windrot_geo2proj.gr3  windrot_geo2proj.gr3
ln -sf $FIXstofs3d/${RUN}_watertype.gr3  watertype.gr3
ln -sf $FIXstofs3d/${RUN}_vgrid.in  vgrid.in
ln -sf $FIXstofs3d/${RUN}_tvd.prop  tvd.prop
ln -sf $FIXstofs3d/${RUN}_tem_nudge.gr3  TEM_nudge.gr3
ln -sf $FIXstofs3d/${RUN}_station.in  station.in
#ln -sf $FIXstofs3d/${RUN}_river_source_sink.in  source_sink.in
ln -sf $FIXstofs3d/${RUN}_shapiro.gr3  shapiro.gr3
ln -sf $FIXstofs3d/${RUN}_sal_nudge.gr3  SAL_nudge.gr3
ln -sf $FIXstofs3d/${RUN}_param.nml_6globaloutput param.nml_template
ln -sf $FIXstofs3d/${RUN}_river_msource.th  msource.th
ln -sf $FIXstofs3d/${RUN}_hgrid.ll  hgrid.ll
ln -sf $FIXstofs3d/${RUN}_hgrid.gr3  hgrid.gr3
ln -sf $FIXstofs3d/${RUN}_estuary.gr3  estuary.gr3
ln -sf $FIXstofs3d/${RUN}_drag.gr3  drag.gr3
ln -sf $FIXstofs3d/${RUN}_diffmin.gr3  diffmin.gr3
ln -sf $FIXstofs3d/${RUN}_diffmax.gr3  diffmax.gr3
ln -sf $FIXstofs3d/${RUN}_bctides.in_template  bctides.in_template
ln -sf $FIXstofs3d/${RUN}_albedo.gr3  albedo.gr3
ln -sf $FIXstofs3d/${RUN}_partition.prop  partition.prop


# ---------------------------------------> create param.nml (nowcast + forecast)
# ---------------------------------------> create param.nml (nowcast + forecast)
file_log=log_create_param_nml.${cycle}.log

# Generate separate param.nml for nowcast and forecast phases
for _phase in nowcast forecast; do
  export pgm="${USHstofs3d}/stofs_3d_atl_create_param_nml.sh ${_phase}"
  ${USHstofs3d}/stofs_3d_atl_create_param_nml.sh ${_phase} >> ${file_log} 2>&1

  export err=$?
  if [ $err -ne 0 ]; then
     msg=" Execution of $pgm (${_phase}) did not complete normally - WARNING"
     postmsg  "$msg"
     cat ${file_log}
  else
     msg=" Execution of $pgm (${_phase}) completed normally"
     postmsg  "$msg"
     cat ${file_log}
  fi
  echo $msg
done

echo

# ---------------------------------------> create bctides.in
# ---------------------------------------> create bctides.in
file_log=log_create_bctides.${cycle}.log

export pgm="${USHstofs3d}/stofs_3d_atl_create_bctides_in.sh"
${USHstofs3d}/stofs_3d_atl_create_bctides_in.sh >> ${file_log} 2>&1  


export err=$?
if [ $err -ne 0 ]
then
   msg=" Execution of $pgm did not complete normally - WARNING"
   postmsg  "$msg"
   # #err_chk
else
   msg=" Execution of $pgm completed normally"
   postmsg  "$msg"
fi

echo $msg
echo


# ---------------------------------------> create nwm/river forcing
# ---------------------------------------> create nwm/river forcing

file_log=log_create_river_forcing_nwm.${cycle}.log

export pgm="${USHstofs3d}/stofs_3d_atl_create_river_forcing_nwm.sh"
${USHstofs3d}/stofs_3d_atl_create_river_forcing_nwm.sh  >> ${file_log} 2>&1

export err=$?
if [ $err -ne 0 ]
then
   msg=" Execution of $pgm did not complete normally - WARNING"
   postmsg  "$msg"
   cat ${file_log}
   err_chk
else
   msg=" Execution of $pgm completed normally"
   postmsg  "$msg"
   cat ${file_log}
fi

echo $msg
echo


# ---------------------------------------> create sflux/GFS forcing
# ---------------------------------------> create sflux/GFS forcing
file_log=log_create_surface_forcing_gfs.${cycle}.log

export pgm="${USHstofs3d}/stofs_3d_atl_create_surface_forcing_gfs.sh"
${USHstofs3d}/stofs_3d_atl_create_surface_forcing_gfs.sh  >> ${file_log} 2>&1

export err=$?
if [ $err -ne 0 ]
then
   msg=" Execution of $pgm did not complete normally - WARNING"
   postmsg  "$msg"
   cat ${file_log}
   err_chk
else
   msg=" Execution of $pgm completed normally"
   postmsg  "$msg"
   cat ${file_log}
fi

echo $msg
echo


# ---------------------------------------> create sflux/HRRR forcing
# ---------------------------------------> create sflux/HRRR forcing
file_log=log_create_surface_forcing_hrrr.${cycle}.log

export pgm="${USHstofs3d}/stofs_3d_atl_create_surface_forcing_hrrr.sh"  
${USHstofs3d}/stofs_3d_atl_create_surface_forcing_hrrr.sh  >> ${file_log} 2>&1

export err=$?
if [ $err -ne 0 ]
then
   msg=" Execution of $pgm did not complete normally - WARNING"
   postmsg  "$msg"
   cat ${file_log}
   err_chk
else
   msg=" Execution of $pgm completed normally"
   postmsg  "$msg"
   cat ${file_log}
fi

echo $msg
echo


# ---------------------------------------> create rtofs/obc_3dth forcing (non-adjust)
# v3.1.1: Split into non_adjust (base) + dynamic_adjust (bias correction)
file_log=log_stofs_3d_atl_create_obc_3d_th_non_adjust.${cycle}.log

export pgm="${USHstofs3d}/stofs_3d_atl_create_obc_3d_th_non_adjust.sh"
${USHstofs3d}/stofs_3d_atl_create_obc_3d_th_non_adjust.sh  >> ${file_log} 2>&1

export err=$?
if [ $err -ne 0 ]
then
   msg=" Execution of $pgm did not complete normally - WARNING"
   postmsg  "$msg"
   cat ${file_log}
   err_chk
else
   msg=" Execution of $pgm completed normally"
   postmsg  "$msg"
   cat ${file_log}
fi

echo $msg
echo


# ---------------------------------------> OBC dynamic bias adjustment
# v3.1.1: Always run dynamic_adjust after non_adjust (applies CO-OPS obs bias correction)
file_log=log_stofs_3d_atl_create_obc_3d_th_dynamic_adjust.${cycle}.log

export pgm="${USHstofs3d}/stofs_3d_atl_create_obc_3d_th_dynamic_adjust.sh"
${USHstofs3d}/stofs_3d_atl_create_obc_3d_th_dynamic_adjust.sh >> ${file_log} 2>&1

export err=$?
if [ $err -ne 0 ]
then
   msg=" Execution of $pgm did not complete normally - WARNING"
   postmsg  "$msg"
   cat ${file_log}
   err_chk
else
   msg=" Execution of $pgm completed normally"
   postmsg  "$msg"
   cat ${file_log}
fi

echo $msg
echo


# ---------------------------------------> create rtofs/obc_nudge forcing
# ---------------------------------------> create rtofs/obc_nudge forcing
file_log=log_stofs_3d_atl_create_obc_nudge.${cycle}.log

export pgm="${USHstofs3d}/stofs_3d_atl_create_obc_nudge.sh"
${USHstofs3d}/stofs_3d_atl_create_obc_nudge.sh  >> ${file_log} 2>&1

export err=$?
if [ $err -ne 0 ]
then
   msg=" Execution of $pgm did not complete normally - WARNING"
   postmsg  "$msg"
   cat ${file_log}
   err_chk
else
   msg=" Execution of $pgm completed normally"
   postmsg  "$msg"
   cat ${file_log}
fi

echo $msg
echo


# ---------------------------------------> create St. Lawrence River forcing (v3.1.1: moved after OBC)
# ---------------------------------------> create St. Lawrence River forcing

file_log=log_create_river_st_lawrence.${cycle}.log

export pgm="${USHstofs3d}/stofs_3d_atl_create_river_st_lawrence.sh"
${USHstofs3d}/stofs_3d_atl_create_river_st_lawrence.sh  >> ${file_log} 2>&1

export err=$?
if [ $err -ne 0 ]
then
   msg=" Execution of $pgm did not complete normally - WARNING"
   postmsg  "$msg"
   cat ${file_log}
   err_chk
else
   msg=" Execution of $pgm completed normally"
   postmsg  "$msg"
   cat ${file_log}
fi

echo $msg
echo


# ---------------------------------------> create restart file 

file_log=log_create_restart.${cycle}.log

fn_restart_coldstart_fix=${FIXstofs3d}/stofs_3d_atl_restart_coldstart.nc
fn_restart_rerun=${COMOUTrerun}/${RUN}.${cycle}.restart.nc

mkdir -p ${COMOUTrerun} 
mkdir -p ${DATA_prep_restart}


if [[ $COLDSTART = YES ]]; then

  # stofs v3.1.1: COLDSTART is forbidden for stofs-3d-atl
  # As a baroclinic 3-D system, using climatological T/S from a cold start file
  # would greatly deteriorate performance skill.
    msg=''
    msg="${msg}\n Attention: COLDSTART=YES is forbidden for stofs-3d-atl."
    msg="${msg}\n stofs-3d-atl is a baroclinic 3-D system. The initial T/S fields"
    msg="${msg}\n must be initialized with conditions close to the current day."
    msg="${msg}\n Please set COLDSTART=NO and provide a valid restart file."

    echo -e "${msg}"; echo -e "${msg}" >> ${file_log}
    err_exit "COLDSTART=YES is forbidden for stofs-3d-atl."


else   # COLDSTART=NO
   msg="COLDSTART=${COLDSTART}"


# ------------------------
# Fast-path: if ${fn_restart_rerun} is already in place (e.g., pre-staged
# from a prev-cycle operational archive for a dev run), accept it and skip
# the hotstart search. Validates with the same >20GB threshold the search
# uses.
  flag_skip_hotstart_search=0
  if [ -s "${fn_restart_rerun}" ]; then
      if [[ $(find "${fn_restart_rerun}" -type f -size +20G 2>/dev/null) ]]; then
          echo "OK: restart already staged at ${fn_restart_rerun} (>20GB); skipping hotstart search"
          echo "OK: restart already staged at ${fn_restart_rerun} (>20GB); skipping hotstart search" >> ${file_log}
          flag_skip_hotstart_search=1
      else
          echo "WARNING: ${fn_restart_rerun} exists but is <20GB; falling through to hotstart search"
      fi
  fi

if [[ ${flag_skip_hotstart_search} -eq 0 ]]; then

  LIST_fn_fnl_hotstart=''
  LIST_fn_fnl_hotstart_all_to_be_searched=''
  days=(0 1 2 3 4)

  cnt_files=0
  for k in ${days[@]}; do
      date_k=`date -d "${PDYHH_NCAST_BEGIN:0:8} ${k} days ago" +%Y%m%d`

      # v3.1.1 operational layout: rerun/restart.nc
      # v3.0 legacy layout: hotstart.stofs3d.nc in the cycle root
      fn_restart_ops="${COMINstofs}/${RUN}.${date_k}/rerun/${RUN}.${cycle}.restart.nc"
      fn_hotstart_oper="${COMINstofs}/${RUN}.${date_k}/${RUN}.${cycle}.hotstart.stofs3d.nc"

      LIST_fn_fnl_hotstart_all_to_be_searched+="${fn_restart_ops} \n ${fn_hotstart_oper} \n "

      for _cand in "${fn_restart_ops}" "${fn_hotstart_oper}"; do
        if [ -s "${_cand}" ]; then
          if [[ $(find "${_cand}" -type f -size +20G 2>/dev/null) ]]; then
             LIST_fn_fnl_hotstart+="${_cand} "
             echo "OK: ${_cand} : filesize (GT 20GB)"
             cnt_files=$((cnt_files+1))
             break 2
          else
             echo "WARNING: ${_cand}: filesize less than 20GB"
          fi
        else
          echo "WARNING: ${_cand} does not exist"
        fi
      done
  done
  echo "cnt_files = " ${cnt_files}

  if [[ $cnt_files -ge 1 ]]; then
     LIST_fn_fnl_hotstart=(${LIST_fn_fnl_hotstart[@]})

     fn_hotstart_oper_prev=${LIST_fn_fnl_hotstart[0]};
     echo "found: fn_hotstart_oper_prev = ${fn_hotstart_oper_prev}"

     cpreq -pf ${fn_hotstart_oper_prev} ${fn_restart_rerun}

  else
     # v3.1.1: Improved error logging with list of all searched files
     msg=" WARNING: The RESTART file is NOT found."
     msg="${msg}\n This script checked for the following files and NONE was found:\n"
     msg="${msg}\n ${LIST_fn_fnl_hotstart_all_to_be_searched}"
     msg="${msg}\n If WCOSS2 recently switched machines, data mirroring may be delayed."
     msg="${msg}\n Please ensure data mirroring is complete before re-running."
     msg="${msg}\n"
     msg="${msg}\n For a dev run, you can pre-stage the restart file at:"
     msg="${msg}\n   ${fn_restart_rerun}"
     msg="${msg}\n (symlink from /lfs/h1/ops/prod/com/stofs/v2.1/stofs_3d_atl.<PDYm1>/rerun/stofs_3d_atl.t12z.restart.nc)"
     msg="${msg}\n"

     echo -e "${msg}"; echo -e "${msg}" >> ${file_log}
     err_exit "RESTART FILE NOT FOUND. See above message for details."
  fi

fi  # flag_skip_hotstart_search
fi  # COLDSTART == YES


# ---------------------------------------> Completed preparing param.nml, bctides, forcing files

msg=" Finished creating  param.nml, bctides, river/gfs/hrrr/rtofs forcing files SUCCESSFULLY "
postmsg  "$msg"



echo 
echo " Finished running - exstofs_3d_atl_prep_processing.sh at " `date`
echo
 


