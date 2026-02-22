#!/bin/bash

##############################################################################
#  Name: exnos_ofs_prep.sh
#  Purpose: Unified prep ex-script for both STOFS and COMF frameworks.
#
#  Sources the shared prep library (nos_ofs_prep_run.sh) and calls
#  the 7-step interface to prepare forcing files, model config, and
#  initial conditions for nowcast and forecast.
#
#  Usage:
#    Called by JNOS_OFS_PREP (STOFS): $SCRIstofs3d/exnos_ofs_prep.sh
#    Called by JNOS_OFS_PREP (COMF):  $SCRIPTSnos/exnos_ofs_prep.sh $OFS
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

  msg="Starting script: ${fn_this_script} - prepare model control & forcing files"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

  pgmout=pgmout_prep.$$

  echo "module list in ${fn_this_script}"
  module list 2>&1 || true
  echo; echo

# ---------------------------> Load YAML Configuration (STOFS only, with fallback)
# For STOFS, try to load YAML config if OFS_CONFIG is set.
# COMF config loading is handled inside _comf_stage_static_files.
if [ "${OFS_FRAMEWORK}" = "stofs" ]; then
    if [ -n "${OFS_CONFIG:-}" ] && [ -f "${OFS_CONFIG:-}" ]; then
        _yaml_to_env="${USHnos:-${HOMEnos}/ush}/python/nos_ofs/utils/yaml_to_env.py"
        if [ -f "${_yaml_to_env}" ]; then
            echo "Loading STOFS prep config from YAML: ${OFS_CONFIG}"
            _yaml_exports=$(python3 "${_yaml_to_env}" "${OFS_CONFIG}" --framework stofs 2>/dev/null)
            if [ $? -eq 0 ] && [ -n "${_yaml_exports}" ]; then
                eval "${_yaml_exports}"
                export OFS_CONFIG_LOADED=1
                echo "YAML config loaded successfully"
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
fi

# -----------------------> Source shared prep library

  source ${USHnos}/nos_ofs_prep_run.sh

# -----------------------> Setup working directory

  mkdir -p $DATA
  cd $DATA

# =========================================================================
#  PREP PHASE — 7-step forcing preparation
# =========================================================================

  echo "========================================="
  echo "=== PREP PHASE (unified) ==="
  echo "========================================="
  echo "  OFS_FRAMEWORK=${OFS_FRAMEWORK}"
  echo "  OFS=${OFS:-not set}"
  echo "  PDY=${PDY:-not set} cyc=${cyc:-not set}"
  echo "========================================="

  # Step 1: Stage static files (grid, control files)
  stage_static_files
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: stage_static_files failed"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  fi

  # Step 2: Create model config (param.nml, bctides.in, runtime ctl)
  create_model_config
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: create_model_config failed"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  fi

  # Step 3: Atmospheric forcing (GFS/HRRR or NAM/GFS/RTMA)
  create_forcing_atmospheric
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: create_forcing_atmospheric failed"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  fi

  # Step 4: River forcing (NWM/USGS)
  create_forcing_river
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: create_forcing_river failed"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  fi

  # Step 5: Ocean boundary conditions (RTOFS/HYCOM)
  create_forcing_obc
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: create_forcing_obc failed"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  fi

  # Step 6: Nudging (optional, T/S interior — non-fatal)
  create_forcing_nudging
  export err=$?
  if [ $err -ne 0 ]; then
      msg="WARNING: create_forcing_nudging failed (non-fatal)"
      echo "$msg"; postmsg "${jlogfile:-/dev/null}" "$msg"
  fi

  # Step 7: Initial condition (restart/hotstart)
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
