#!/bin/bash

##############################################################################
#  Name: exnos_ofs_forecast.sh
#  Purpose: Forecast-only ex-script for STOFS-2D-Global (ADCIRC framework).
#
#  Sources the shared model run library (nos_ofs_model_run.sh) and calls
#  the 4-step interface for the forecast phase only.
#
#  ADCIRC forecast runs 4 sub-phases internally:
#    1. tide_forecast1  (NWS=0, 0-120h, hourly output)
#    2. surf_forecast1  (NWS=12, 0-120h, hourly output)
#    3. tide_forecast2  (NWS=0, 120-180h, 3-hourly output)
#    4. surf_forecast2  (NWS=12, 120-180h, 3-hourly output)
#
#  The forecast retrieves hotstart/restart and state files from
#  $COMOUT/$COMOUTrerun (archived by the nowcast job).
#
#  Usage:
#    Called by JNOS_OFS_FORECAST: $SCRIstofs3d/exnos_ofs_forecast.sh
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton

  fn_this_script="exnos_ofs_forecast.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }

  msg="${fn_this_script} started (ADCIRC forecast-only split-job mode)"
  echo "$msg"
  postmsg "$msg"

  pgmout=pgmout_forecast.$$

  echo "module list in ${fn_this_script}"
  module list 2>&1 || true
  echo; echo

# -----------------------> Source shared model run library

  source ${USHnos}/nos_ofs_model_run.sh

# -----------------------> Setup working directory

  mkdir -p $DATA
  cd $DATA

# =========================================================================
#  FORECAST PHASE (ADCIRC: tide_fcst1 + surf_fcst1 + tide_fcst2 + surf_fcst2)
# =========================================================================

  echo "==============================================="
  echo "=== FORECAST PHASE (ADCIRC/stofs_2d_glo) ==="
  echo "==============================================="
  echo "  NCPU=${NCPU:-not set}  TOT_NCPU=${TOT_NCPU:-not set}"
  echo "  PPN=${PPN:-not set}    NUM_WRITERS=${NUM_WRITERS:-not set}"
  echo "==============================================="

  # Step 1: Stage static files and forcing to $DATA
  stage_model_files "forecast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: stage_model_files forecast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 2: Retrieve hotstart/restart from $COMOUT/$COMOUTrerun
  prepare_restart "forecast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: prepare_restart forecast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 3: Run ADCIRC model (4 sub-phases: tide_fcst1, surf_fcst1, tide_fcst2, surf_fcst2)
  execute_model "forecast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: execute_model forecast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 4: Archive forecast outputs and send DBN alerts
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
