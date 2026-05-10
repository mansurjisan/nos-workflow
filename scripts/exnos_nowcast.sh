#!/bin/bash

##############################################################################
#  Name: exnos_nowcast.sh
#  Purpose: Nowcast-only ex-script for split-job production mode.
#
#  Sources the shared model run library (nos_run.sh) and calls
#  the 4-step interface for the nowcast phase only.
#
#  The nowcast archives a combined hotstart to $COMOUT so the independent
#  forecast job (exnos_forecast.sh) can retrieve it.
#
#  Usage:
#    Called by JNOS_NOWCAST (STOFS): $SCRIstofs3d/exnos_nowcast.sh
#    Called by JNOS_NOWCAST (COMF):  $SCRIPTSnos/exnos_nowcast.sh $OFS
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton

  fn_this_script="exnos_nowcast.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }

  msg="${fn_this_script} started (nowcast-only split-job mode)"
  echo "$msg"
  postmsg "$msg"

  pgmout=pgmout_nowcast.$$

  echo "module list in ${fn_this_script}"
  module list 2>&1 || true
  echo; echo

# -----------------------> Source shared model run library

  source ${USHnos}/nos_run.sh

# -----------------------> Setup working directory

  mkdir -p $DATA
  cd $DATA

# =========================================================================
#  NOWCAST PHASE
# =========================================================================

  echo "========================================="
  echo "=== NOWCAST PHASE (split-job mode) ==="
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

  # Step 3: Run model (SCHISM for STOFS, ROMS/FVCOM/SCHISM for COMF)
  execute_model "nowcast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: execute_model nowcast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 4: Archive nowcast outputs + combined hotstart to $COMOUT
  archive_outputs "nowcast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: archive_outputs nowcast failed"
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
