#!/bin/bash

##############################################################################
#  Name: exstofs_3d_atl_now_forecast.sh                                      #
#  This script conducts the nowcast and forecast simulations using the       #
#  unified 4-step framework: stage → restart → execute → archive.           #
#                                                                            #
#  The model is run twice:                                                   #
#    1. Nowcast  (rnday=RNDAY_NOWCAST,  start=PDYHH_NCAST_BEGIN)            #
#    2. Forecast (rnday=RNDAY_FORECAST, start=PDYHH_FCAST_BEGIN)            #
#                                                                            #
#  Forcing files are prepared for the full time window by the prep stage     #
#  and shared across both phases. Only param.nml and the initial condition   #
#  (hotstart) change between nowcast and forecast.                           #
#                                                                            #
#  Remarks:                                                                  #
#    Original single-run version: September 2022                             #
#    Split nowcast/forecast using shared library: February 2026              #
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton


# -----------------------> Initialize

  fn_this_script="exstofs_3d_atl_now_forecast.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }

  msg="${fn_this_script} started (unified 2-phase nowcast/forecast)"
  echo "$msg"
  postmsg  "$msg"

  pgmout=pgmout_now_forecast.$$

  echo "module list in ${fn_this_script}"
  module list
  echo; echo


# -----------------------> Source shared model run library

  source ${USHnos}/nos_ofs_model_run.sh


# -----------------------> Setup working directory

  mkdir -p $DATA
  cd $DATA


# =========================================================================
#  NOWCAST PHASE
# =========================================================================

  echo "========================================="
  echo "=== NOWCAST PHASE ==="
  echo "========================================="
  echo "  RNDAY_NOWCAST=${RNDAY_NOWCAST:-not set}"
  echo "  PDYHH_NCAST_BEGIN=${PDYHH_NCAST_BEGIN:-not set}"
  echo "========================================="

  # Step 1: Stage static files and nowcast forcing to $DATA
  stage_model_files "nowcast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: stage_model_files nowcast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 2: Find and stage hotstart from previous cycle
  prepare_restart "nowcast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: prepare_restart nowcast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 3: Run SCHISM nowcast
  execute_model "nowcast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: execute_model nowcast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 4: Archive nowcast outputs
  archive_outputs "nowcast"


# =========================================================================
#  FORECAST PHASE (skip if LEN_FORECAST=0 or RUN_FORECAST=NO)
# =========================================================================

if [ "${RUN_FORECAST:-YES}" = "YES" ] && [ ${LEN_FORECAST:-108} -gt 0 ]; then

  echo "========================================="
  echo "=== FORECAST PHASE ==="
  echo "========================================="
  echo "  RNDAY_FORECAST=${RNDAY_FORECAST:-not set}"
  echo "  PDYHH_FCAST_BEGIN=${PDYHH_FCAST_BEGIN:-not set}"
  echo "========================================="

  # Step 1: Combine nowcast hotstart files, swap to forecast param.nml
  prepare_restart "forecast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: prepare_restart forecast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 2: Run SCHISM forecast
  execute_model "forecast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: execute_model forecast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 3: Archive forecast outputs
  archive_outputs "forecast"

else
  echo "========================================="
  echo "=== FORECAST PHASE SKIPPED ==="
  echo "  RUN_FORECAST=${RUN_FORECAST:-YES}"
  echo "  LEN_FORECAST=${LEN_FORECAST:-108}"
  echo "========================================="
fi


# =========================================================================
#  Done
# =========================================================================

  msg="Finished ${fn_this_script} SUCCESSFULLY"
  postmsg  "$msg"

  echo
  echo "$msg"
  echo "Finished at $(date)"
  echo
