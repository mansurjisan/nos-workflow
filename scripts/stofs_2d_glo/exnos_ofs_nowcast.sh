#!/bin/bash

##############################################################################
#  Name: exnos_ofs_nowcast.sh
#  Purpose: Nowcast-only ex-script for STOFS-2D-Global (ADCIRC framework).
#
#  Sources the shared model run library (nos_ofs_model_run.sh) and calls
#  the 4-step interface for the nowcast phase only.
#
#  ADCIRC nowcast runs 2 sub-phases internally:
#    1. tide_nowcast  (NWS=0, tidal-only)
#    2. surf_nowcast  (NWS=12, tide+surface forcing)
#
#  The nowcast archives hotstart/restart files and state to $COMOUT/$COMOUTrerun
#  so the independent forecast job can retrieve them.
#
#  Usage:
#    Called by JNOS_OFS_NOWCAST: $SCRIstofs3d/exnos_ofs_nowcast.sh
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton

  fn_this_script="exnos_ofs_nowcast.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }

  msg="${fn_this_script} started (ADCIRC nowcast-only split-job mode)"
  echo "$msg"
  postmsg "$msg"

  pgmout=pgmout_nowcast.$$

  echo "module list in ${fn_this_script}"
  module list 2>&1 || true
  echo; echo

# -----------------------> Source shared model run library

  source ${USHnos}/nos_ofs_model_run.sh

# -----------------------> Setup working directory

  mkdir -p $DATA
  cd $DATA

# =========================================================================
#  NOWCAST PHASE (ADCIRC: tide_nowcast + surf_nowcast)
# =========================================================================

  echo "============================================="
  echo "=== NOWCAST PHASE (ADCIRC/stofs_2d_glo) ==="
  echo "============================================="
  echo "  NCPU=${NCPU:-not set}  TOT_NCPU=${TOT_NCPU:-not set}"
  echo "  PPN=${PPN:-not set}    NUM_WRITERS=${NUM_WRITERS:-not set}"
  echo "  COLDSTART=${COLDSTART:-not set}"
  echo "============================================="

  # Step 1: Stage static files (ADCIRC grid, templates, met control)
  stage_model_files "nowcast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: stage_model_files nowcast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 2: Find and verify hotstart from previous cycle
  prepare_restart "nowcast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: prepare_restart nowcast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 3: Run ADCIRC model (tide_nowcast then surf_nowcast)
  execute_model "nowcast"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: execute_model nowcast failed"
      echo "$msg"; postmsg "$msg"
      err_exit
  fi

  # Step 4: Archive nowcast outputs to $COMOUT
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
