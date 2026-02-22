#!/bin/bash

#########################################################################
#  Name: stofs_3d_pac_create_param_nml.sh                               #
#  This script creates the model run control file, param.nml, for the   #
#  nowcast and forecast simulations.                                    #
#                                                                       #
#  Usage:                                                               #
#    stofs_3d_pac_create_param_nml.sh [nowcast|forecast]                #
#    - nowcast:  rnday=RNDAY_NOWCAST,  start=PDYHH_NCAST_BEGIN          #
#    - forecast: rnday=RNDAY_FORECAST, start=PDYHH_FCAST_BEGIN          #
#    - (no arg): legacy behavior, rnday=N_DAYS_MODEL_RUN_PERIOD         #
#                                                                       #
#  Remarks:                                                             #
#                                                     September, 2022   #
#########################################################################


# ---------------------------> Begin ...
set -x

  fn_this_script="stofs_3d_pac_create_param_nml.sh"
  phase=${1:-}
  echo "${fn_this_script} started (phase: ${phase:-combined})"

  echo "module list in ${fn_this_script}"
  module list
  echo; echo


# ---------------------------> directory/file names
  dir_wk=${DATA}

  echo dir_wk = ${DATA}

  mkdir -p $dir_wk
  cd $dir_wk

  pgmout=pgmout_nwm.$$
  rm -f $pgmout

  echo `pwd` '/stofs_3d_pac_create_param_nml.sh begin >>> '

# ---------------------------> date/time based on phase
  case "${phase}" in
    nowcast)
      rnday=${RNDAY_NOWCAST:-${N_DAYS_MODEL_RUN_PERIOD}}
      yyyy=${PDYHH_NCAST_BEGIN:0:4}
      mm=${PDYHH_NCAST_BEGIN:4:2}
      dd=${PDYHH_NCAST_BEGIN:6:2}
      start_hour=${PDYHH_NCAST_BEGIN:8:2}
      fn_param_modelRun_date_tag=${RUN}.param.nowcast.${PDYHH_FCAST_BEGIN:0:8}.${cycle}.nml
      fn_param_modelRun_std=${RUN}.${cycle}.param.nowcast.nml
      ;;
    forecast)
      rnday=${RNDAY_FORECAST:-${N_DAYS_MODEL_RUN_PERIOD}}
      yyyy=${PDYHH_FCAST_BEGIN:0:4}
      mm=${PDYHH_FCAST_BEGIN:4:2}
      dd=${PDYHH_FCAST_BEGIN:6:2}
      start_hour=${PDYHH_FCAST_BEGIN:8:2}
      fn_param_modelRun_date_tag=${RUN}.param.forecast.${PDYHH_FCAST_BEGIN:0:8}.${cycle}.nml
      fn_param_modelRun_std=${RUN}.${cycle}.param.forecast.nml
      ;;
    *)
      # Legacy: single combined run
      rnday=$N_DAYS_MODEL_RUN_PERIOD
      yyyy=${PDYHH_NCAST_BEGIN:0:4}
      mm=${PDYHH_NCAST_BEGIN:4:2}
      dd=${PDYHH_NCAST_BEGIN:6:2}
      start_hour=${PDYHH_NCAST_BEGIN:8:2}
      fn_param_modelRun_date_tag=${RUN}.param.nfcast.${PDYHH_FCAST_BEGIN:0:8}.${cycle}.nml
      fn_param_modelRun_std=${RUN}.${cycle}.param.nml
      ;;
  esac

  str_yyyymmdd_cycle=${PDYHH_FCAST_BEGIN:0:8}${cycle}

  fn_param_template='param.nml_template'
  cat $fn_param_template | sed "s/rnday = .*/rnday = $rnday/" | sed "s/start_year = .*/start_year = $yyyy/" | sed "s/start_month = .*/start_month = $mm/" | sed "s/start_day = .*/start_day = $dd/" | sed "s/start_hour = .*/start_hour = $start_hour/" > $fn_param_modelRun_date_tag


  FILESIZE_min=1000
  if [ -f $fn_param_modelRun_date_tag ]; then
     sz_test=`wc -c $fn_param_modelRun_date_tag | awk '{print $1}'`

     if [ $sz_test -ge $FILESIZE_min ]; then
        cp  -pf ${fn_param_modelRun_date_tag}  ${COMOUTrerun}/${fn_param_modelRun_std}
     fi

  else
    echo " ${fn_param_modelRun_date_tag} not created or file size is too small: " $fn_param_modelRun_date_tag
  fi
  export err=$?;


echo
echo "param.nml created (${phase:-combined}): " $fn_param_modelRun_date_tag
echo 'stofs_3d_pac_create_param_nml.sh completed '
echo
