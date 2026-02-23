#!/bin/bash

##############################################################################
#  Name: exnos_ofs_post.sh
#  Purpose: Unified post-processing ex-script for STOFS-2D-Global (ADCIRC).
#
#  Orchestrates the full ADCIRC post-processing pipeline by calling the
#  main post-processing driver (stofs_2d_glo_post.sh), which in turn
#  dispatches to individual post steps:
#    - ncrcat:  concatenate nowcast + forecast forcing files
#    - ncdiff:  compute sub-tidal water level (swl = cwl - htp)
#    - anomaly: station-level anomaly correction from tide gauges
#    - grib2:   GRIB2 generation for 8 sub-domains
#    - shef:    SHEF bulletin generation for NWS distribution
#
#  Usage:
#    Called by JNOS_OFS_POST: ${SCRIPTSnos}/${RUN}/exnos_ofs_post.sh
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton

  fn_this_script="exnos_ofs_post.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }
# Fallback if err_chk/err_exit not provided
  command -v err_chk  >/dev/null 2>&1 || err_chk()  { if [ ${err:-0} -ne 0 ]; then exit ${err}; fi; }
  command -v err_exit >/dev/null 2>&1 || err_exit() { exit ${err:-1}; }

  msg="Starting script: ${fn_this_script} - STOFS-2D-GLO post-processing"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

  pgmout=pgmout_post.$$

  echo "module list in ${fn_this_script}"
  module list 2>&1 || true
  echo; echo

# -----------------------> Source YAML configuration (if not already loaded)

  if [ "${OFS_CONFIG_LOADED:-0}" != "1" ]; then
      if [ -f "${USHnos:-${HOMEnos}/ush}/nos_ofs_config.sh" ]; then
          source "${USHnos:-${HOMEnos}/ush}/nos_ofs_config.sh"
          load_ofs_config "${OFS_CONFIG:-${PARMnos}/systems/${OFS}.yaml}" "adcirc"
      fi
  fi

# -----------------------> Setup working directory

  mkdir -p $DATA
  cd $DATA

# =========================================================================
#  POST PHASE -- ADCIRC post-processing (STOFS-2D-Global)
# =========================================================================

  echo "============================================="
  echo "=== POST PHASE (ADCIRC/stofs_2d_glo)     ==="
  echo "============================================="
  echo "  OFS_FRAMEWORK=${OFS_FRAMEWORK:-adcirc}"
  echo "  OFS=${OFS:-stofs_2d_glo}"
  echo "  RUN=${RUN:-stofs_2d_glo}"
  echo "  PDY=${PDY:-not set} cyc=${cyc:-not set}"
  echo "  COMIN=${COMIN:-not set}"
  echo "  COMOUT=${COMOUT:-not set}"
  echo "============================================="

# -----------------------> Execute main post-processing driver

  export USHstofs2d=${USHstofs2d:-${HOMEstofs:-${HOMEnos}}/ush/${RUN}}

  if [ -f "${USHstofs2d}/${RUN}_post.sh" ]; then
      ${USHstofs2d}/${RUN}_post.sh
      export err=$?
      if [ $err -ne 0 ]; then
          msg="FATAL: ${RUN}_post.sh failed with exit code ${err}"
          echo "$msg"
          postmsg "${jlogfile:-/dev/null}" "$msg"
          err_exit
      fi
  else
      msg="FATAL: Post driver not found: ${USHstofs2d}/${RUN}_post.sh"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
      export err=1; err_exit
  fi

# =========================================================================
#  Done
# =========================================================================

  # Copy jlogfile to COMOUT for monitoring
  [ -s "${jlogfile:-}" ] && [ -d "${COMOUT:-}" ] && cp -p $jlogfile $COMOUT 2>/dev/null || true

  msg="Finished ${fn_this_script} SUCCESSFULLY"
  postmsg "${jlogfile:-/dev/null}" "$msg"

  echo
  echo "$msg"
  echo "Finished at $(date)"
  echo
