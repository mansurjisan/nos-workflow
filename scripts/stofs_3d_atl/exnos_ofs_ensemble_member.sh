#!/bin/bash

##############################################################################
#  Name: exnos_ofs_ensemble_member.sh
#  Purpose: Ensemble member ex-script for SCHISM-based OFS systems.
#
#  Sources the ensemble run library (nos_ofs_ensemble_run.sh) and calls
#  the 6-step interface to run a single ensemble member:
#    1. Generate parameter perturbations
#    2. Stage fix files and forcing
#    3. Configure param.nml (ihot, start time, perturbations)
#    4. Prepare restart (hotstart + output state files)
#    5. Run SCHISM model
#    6. Archive member output
#
#  Usage:
#    Called by JNOS_OFS_ENSEMBLE_MEMBER:
#      STOFS: $SCRIstofs3d/exnos_ofs_ensemble_member.sh
#      COMF:  $SCRIPTSnos/exnos_ofs_ensemble_member.sh $OFS
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton

  fn_this_script="exnos_ofs_ensemble_member.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }

  msg="${fn_this_script} started (member ${MEMBER_ID})"
  echo "$msg"
  postmsg "$msg"

  pgmout=pgmout_ensemble.$$

  echo "module list in ${fn_this_script}"
  module list 2>&1 || true
  echo; echo

# -----------------------> Source ensemble run library

  source ${USHnos}/nos_ofs_ensemble_run.sh

# -----------------------> Working directory

  mkdir -p $MEMBER_DATA
  cd $MEMBER_DATA

# =========================================================================
#  ENSEMBLE MEMBER ${MEMBER_ID}
# =========================================================================

  echo "========================================="
  echo "=== ENSEMBLE MEMBER ${MEMBER_ID} ==="
  echo "  OFS_FRAMEWORK=${OFS_FRAMEWORK}"
  echo "  COMOUT=${COMOUT}"
  echo "  ENSEMBLE_COMOUT=${ENSEMBLE_COMOUT}"
  echo "========================================="

  # Step 1: Generate parameter perturbations
  ensemble_generate_params
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_generate_params failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

  # Step 2: Stage static files and forcing
  ensemble_stage_files
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_stage_files failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

  # Step 3: Configure param.nml (copy, ihot, start time, perturbations)
  ensemble_configure_runtime
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_configure_runtime failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

  # Step 4: Prepare restart (hotstart + output state files)
  ensemble_prepare_restart
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_prepare_restart failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

  # Step 5: Run SCHISM model
  ensemble_execute_model
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_execute_model failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

  # Step 6: Archive member output
  ensemble_archive_outputs
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_archive_outputs failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

# =========================================================================
#  Done
# =========================================================================

  msg="Finished ${fn_this_script} member ${MEMBER_ID} SUCCESSFULLY"
  postmsg "$msg"

  echo
  echo "$msg"
  echo "Finished at $(date)"
  echo
