#!/bin/bash

##############################################################################
#  Name: exnos_ofs_prep.sh
#  Purpose: Unified prep ex-script for STOFS-2D-Global (ADCIRC framework).
#
#  Sources the shared prep library (nos_ofs_prep_run.sh) and calls
#  the 7-step interface to prepare forcing files, model config, and
#  initial conditions for nowcast and forecast.
#
#  Usage:
#    Called by JNOS_OFS_PREP: $SCRIstofs3d/exnos_ofs_prep.sh
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton

  fn_this_script="exnos_ofs_prep.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }
# Fallback if err_chk/err_exit not provided
  command -v err_chk >/dev/null 2>&1 || err_chk() { if [ ${err:-0} -ne 0 ]; then exit ${err}; fi; }
  command -v err_exit >/dev/null 2>&1 || err_exit() { exit ${err:-1}; }

  msg="Starting script: ${fn_this_script} - prepare ADCIRC model control & forcing files"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

  pgmout=pgmout_prep.$$

  echo "module list in ${fn_this_script}"
  module list 2>&1 || true
  echo; echo

# -----------------------> Source shared prep library

  source ${USHnos}/nos_ofs_prep_run.sh

# -----------------------> Setup working directory

  mkdir -p $DATA
  cd $DATA

# =========================================================================
#  PREP PHASE -- 7-step forcing preparation (ADCIRC framework)
# =========================================================================

  echo "========================================="
  echo "=== PREP PHASE (ADCIRC/stofs_2d_glo) ==="
  echo "========================================="
  echo "  OFS_FRAMEWORK=${OFS_FRAMEWORK}"
  echo "  OFS=${OFS:-not set}"
  echo "  PDY=${PDY:-not set} cyc=${cyc:-not set}"
  echo "========================================="

  # Step 1: Stage static files (ADCIRC grid, fort.13/14/24, templates)
  stage_static_files
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: stage_static_files failed"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  fi

  # Step 2: Create model config (nod_equi tidal factors, grid decomposition)
  create_model_config
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: create_model_config failed"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  fi

  # Step 3: Atmospheric forcing (GFS surface forcing via getges.sh)
  create_forcing_atmospheric
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: create_forcing_atmospheric failed"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  fi

  # Step 4: River forcing (not applicable for ADCIRC 2D global)
  create_forcing_river
  export err=$?
  if [ $err -ne 0 ]; then
      msg="WARNING: create_forcing_river failed (non-fatal for ADCIRC 2D)"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
  fi

  # Step 5: Ocean boundary conditions (not applicable for global domain)
  create_forcing_obc
  export err=$?
  if [ $err -ne 0 ]; then
      msg="WARNING: create_forcing_obc failed (non-fatal for global ADCIRC)"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
  fi

  # Step 6: Nudging (not applicable for ADCIRC 2D)
  create_forcing_nudging
  export err=$?
  if [ $err -ne 0 ]; then
      msg="WARNING: create_forcing_nudging failed (non-fatal)"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
  fi

  # Step 7: Initial condition (hotstart/restart file search)
  prepare_initial_condition
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: prepare_initial_condition failed"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  fi

# =========================================================================
#  Done
# =========================================================================

  # Copy jlogfile to COMOUT for monitoring
  [ -s "${jlogfile:-}" ] && [ -d "${COMOUT:-}" ] && cp -p $jlogfile $COMOUT

  msg="Finished ${fn_this_script} SUCCESSFULLY"
  postmsg "${jlogfile:-/dev/null}" "$msg"

  echo
  echo "$msg"
  echo "Finished at $(date)"
  echo
