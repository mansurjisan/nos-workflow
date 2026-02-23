#!/bin/bash

##############################################################################
#  Name: exnos_ofs_ensemble_member.sh
#  Purpose: Ensemble member ex-script for ADCIRC-based OFS systems (STOFS-2D-GLO).
#
#  Sources the ensemble run library (nos_ofs_ensemble_run.sh) and calls
#  the 6-step interface to run a single ensemble member:
#    1. Generate parameter perturbations (LHS sampling)
#    2. Stage fix files and forcing (ADCIRC grid, OWI forcing, restart)
#    3. Configure fort.15 (generate from template, apply perturbations)
#    4. Prepare restart (deferred to execute for ADCIRC)
#    5. Run ADCIRC model (adcprep + padcirc for surface forecast)
#    6. Archive member output (fort.61-64.nc, max fields)
#
#  ADCIRC ensemble runs only the surface forecast sub-phase (NWS=12).
#  The tidal component is deterministic (same across members) and is
#  reused from the deterministic tide forecast output. Only the surface
#  forecast (where wind forcing and friction parameters matter) is
#  perturbed.
#
#  Usage:
#    Called by JNOS_OFS_ENSEMBLE_MEMBER:
#      ADCIRC: $SCRIPTSstofs2d/exnos_ofs_ensemble_member.sh
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton

  fn_this_script="exnos_ofs_ensemble_member.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }

# Fallback if cpreq/cpfs not provided by prod_util module
  command -v cpreq >/dev/null 2>&1 || cpreq() { cp -p "$1" "$2"; }
  command -v cpfs >/dev/null 2>&1 || cpfs() { cp -p "$1" "$2"; }

  msg="${fn_this_script} started (ADCIRC ensemble member ${MEMBER_ID})"
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
#  ADCIRC ENSEMBLE MEMBER ${MEMBER_ID}
# =========================================================================

  echo "========================================="
  echo "=== ADCIRC ENSEMBLE MEMBER ${MEMBER_ID} ==="
  echo "  OFS_FRAMEWORK=${OFS_FRAMEWORK}"
  echo "  COMOUT=${COMOUT}"
  echo "  ENSEMBLE_COMOUT=${ENSEMBLE_COMOUT}"
  echo "  NCPU=${NCPU:-not set}  TOT_NCPU=${TOT_NCPU:-not set}"
  echo "  PPN=${PPN:-not set}    NUM_WRITERS=${NUM_WRITERS:-not set}"
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
  # For ADCIRC: links fort.14 (grid), fort.13 (attributes), fort.24 (body tide),
  # fort.rotm, station lists, OWI forcing (fort.221/222), and restart files
  ensemble_stage_files
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_stage_files failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

  # Step 3: Configure fort.15 (generate from template, apply perturbations)
  # For ADCIRC: generates fort.15 from surf.15 template with tidal factors,
  # then applies sed-based parameter perturbations (FFACTOR, ESLM, TAU0)
  ensemble_configure_runtime
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_configure_runtime failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

  # Step 4: Prepare restart
  # For ADCIRC: restart staging is handled in stage_files/execute
  # (fort.67/68 alternation determined at execute time)
  ensemble_prepare_restart
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_prepare_restart failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

  # Step 5: Run ADCIRC model (adcprep + padcirc)
  ensemble_execute_model
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: ensemble_execute_model failed"
      echo "$msg"; postmsg "$msg"
      exit $err
  fi

  # Step 6: Archive member output
  # For ADCIRC: copies fort.61-64.nc, maxele/maxvel/maxwvel.63.nc
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

  msg="Finished ${fn_this_script} ADCIRC member ${MEMBER_ID} SUCCESSFULLY"
  postmsg "$msg"

  echo
  echo "$msg"
  echo "Finished at $(date)"
  echo
