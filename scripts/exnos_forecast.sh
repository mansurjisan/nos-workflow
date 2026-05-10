#!/bin/bash

##############################################################################
#  Name: exnos_forecast.sh
#  Purpose: Forecast-only ex-script for split-job production mode.
#
#  Sources the shared model run library (nos_run.sh) and calls
#  the 4-step interface for the forecast phase only.
#
#  The forecast retrieves the combined hotstart from $COMOUT (archived by
#  the nowcast job) or falls back to local combine if running in combined
#  mode with shared $DATA.
#
#  Usage:
#    Called by JNOS_FORECAST (STOFS): $SCRIstofs3d/exnos_forecast.sh
#    Called by JNOS_FORECAST (COMF):  $SCRIPTSnos/exnos_forecast.sh $OFS
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton

  fn_this_script="exnos_forecast.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }

  msg="${fn_this_script} started (forecast-only split-job mode)"
  echo "$msg"
  postmsg "$msg"

  pgmout=pgmout_forecast.$$

  echo "module list in ${fn_this_script}"
  module list 2>&1 || true
  echo; echo

# -----------------------> Source shared model run library

  source ${USHnos}/nos_run.sh

# -----------------------> Setup working directory

  mkdir -p $DATA
  cd $DATA

# =========================================================================
#  FORECAST PHASE
# =========================================================================

  echo "========================================="
  echo "=== FORECAST PHASE (split-job mode) ==="
  echo "========================================="
  echo "  RNDAY_FORECAST=${RNDAY_FORECAST:-not set}"
  echo "  PDYHH_FCAST_BEGIN=${PDYHH_FCAST_BEGIN:-not set}"
  echo "========================================="

  # Step 1: Stage static files and forcing to $DATA
  stage_model_files "forecast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: stage_model_files forecast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 2: Retrieve hotstart from $COMOUT (or local combine) and configure restart
  prepare_restart "forecast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: prepare_restart forecast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 3: Run model (SCHISM for STOFS, ROMS/FVCOM/SCHISM for COMF)
  execute_model "forecast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: execute_model forecast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 4: Archive forecast outputs
  archive_outputs "forecast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: archive_outputs forecast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

# =========================================================================
#  Done
# =========================================================================

  msg="Finished ${fn_this_script} SUCCESSFULLY"
  postmsg "$msg"

  echo
  echo "$msg"
  echo "Finished at $(date)"
  echo
