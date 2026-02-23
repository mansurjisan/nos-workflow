#!/bin/bash

###############################################################################
#  Name: stofs_2d_glo_post.sh
#  Purpose: Main post-processing driver for STOFS-2D-Global (ADCIRC).
#
#  Orchestrates the full post-processing pipeline:
#    1. Concatenate nowcast + forecast forcing files (ncrcat)
#    2. Compute sub-tidal water level: swl = cwl - htp  (ncdiff)
#    3. Anomaly correction (observed bias applied to station timeseries)
#    4. Bias correction (spatial field bias correction)
#    5. GRIB2 generation for 8 sub-domains
#    6. SHEF bulletin generation for NWS distribution
#
#  Environment variables expected (set by JNOS_OFS_POST / nos_ofs_config.sh):
#    PDY, cyc, cycle         - Date and cycle
#    RUN                     - stofs_2d_glo
#    DATA                    - Working directory
#    COMIN, COMOUT           - Input/output COM directories
#    COMOUTwmo               - WMO product output directory
#    COMOUTrerun             - Rerun forcing file directory
#    EXECstofs2d             - ADCIRC executables directory
#    FIXstofs2d              - Fix files directory
#    USHstofs2d              - USH scripts directory
#    PARMstofs2d             - Parameter files directory
#    SENDCOM, SENDDBN        - Archive/alert flags
#
#  Remarks:
#                                                          February, 2026
###############################################################################

# Start of stofs_2d_glo_post.sh script --------------------------------------- #

  set -x

  fn_this_sh="stofs_2d_glo_post.sh"

  echo "${fn_this_sh} began at UTC: $(date -u)"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }
# Fallback if err_chk/err_exit not provided
  command -v err_chk  >/dev/null 2>&1 || err_chk()  { if [ ${err:-0} -ne 0 ]; then echo "FATAL ERROR: exit code ${err}"; exit ${err}; fi; }
  command -v err_exit >/dev/null 2>&1 || err_exit() { exit ${err:-1}; }
# Fallback for cpreq/cpfs
  command -v cpreq >/dev/null 2>&1 || cpreq() { cp "$@"; }
  command -v cpfs  >/dev/null 2>&1 || cpfs()  { cp "$@"; }

  pgmout=${fn_this_sh}.$$
  rm -f $pgmout

  msg="Starting ${fn_this_sh}: STOFS-2D-GLO post-processing driver"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# --------------------------------------------------------------------------- #
# 0.  Validate required environment variables

  : ${DATA:?} ${COMIN:?} ${COMOUT:?} ${PDY:?} ${cyc:?}
  : ${RUN:=stofs_2d_glo}
  : ${cycle:=t${cyc}z}

  export SENDCOM=${SENDCOM:-YES}
  export SENDDBN=${SENDDBN:-NO}
  export SENDDBN_NTC=${SENDDBN_NTC:-NO}

  export YMDH=${PDY}${cyc}
  export date=$PDY

  # Time parameters (STOFS-2D-GLO standard)
  wndh=3           # wind interval (hours)
  nowh=6           # nowcast length (hours)
  lsth=180         # total forecast length (hours)

  cd $DATA

# --------------------------------------------------------------------------- #
# 1.  Concatenate forcing files (ncrcat: nowcast + forecast1 + forecast2)
#     Combines the per-phase forcing into single continuous files for archival.

  echo "============================================================="
  echo "=== Step 1: Concatenate forcing files (ncrcat)           ==="
  echo "============================================================="

  file_log_ncrcat=log_post_ncrcat.${cycle}.log
  ${USHstofs2d}/${RUN}_post_ncrcat.sh >> ${file_log_ncrcat} 2>&1
  export err=$?

  if [ $err -ne 0 ]; then
      msg="WARNING: ${RUN}_post_ncrcat.sh did not complete normally (non-fatal)"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
  else
      msg="Step 1 (ncrcat) completed normally"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
  fi

# --------------------------------------------------------------------------- #
# 2.  Compute sub-tidal water level (ncdiff: swl = cwl - htp)

  echo "============================================================="
  echo "=== Step 2: Compute anomaly water level (ncdiff)          ==="
  echo "============================================================="

  file_log_ncdiff=log_post_ncdiff.${cycle}.log
  ${USHstofs2d}/${RUN}_post_ncdiff.sh >> ${file_log_ncdiff} 2>&1
  export err=$?

  if [ $err -ne 0 ]; then
      msg="FATAL: ${RUN}_post_ncdiff.sh failed"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
      err_exit
  else
      msg="Step 2 (ncdiff) completed normally"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
  fi

# --------------------------------------------------------------------------- #
# 3.  Anomaly correction (station-level bias from tide gauge observations)

  echo "============================================================="
  echo "=== Step 3: Anomaly correction (station bias)             ==="
  echo "============================================================="

  file_log_anomaly=log_post_anomaly.${cycle}.log
  ${USHstofs2d}/${RUN}_anomaly_water_level.sh >> ${file_log_anomaly} 2>&1
  export err=$?

  if [ $err -ne 0 ]; then
      msg="WARNING: ${RUN}_anomaly_water_level.sh did not complete normally (non-fatal)"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
  else
      msg="Step 3 (anomaly) completed normally"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
  fi

# --------------------------------------------------------------------------- #
# 4.  SHEF bulletin generation

  echo "============================================================="
  echo "=== Step 4: SHEF bulletin generation                      ==="
  echo "============================================================="

  file_log_shef=log_post_shef.${cycle}.log
  ${USHstofs2d}/${RUN}_create_shef.sh >> ${file_log_shef} 2>&1
  export err=$?

  if [ $err -ne 0 ]; then
      msg="WARNING: ${RUN}_create_shef.sh did not complete normally (non-fatal)"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
  else
      msg="Step 4 (SHEF) completed normally"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
  fi

# --------------------------------------------------------------------------- #
# 5.  GRIB2 generation for 8 sub-domains

  echo "============================================================="
  echo "=== Step 5: GRIB2 generation (8 sub-domains)              ==="
  echo "============================================================="

  file_log_grib2=log_post_grib2.${cycle}.log
  ${USHstofs2d}/${RUN}_create_grib2.sh >> ${file_log_grib2} 2>&1
  export err=$?

  if [ $err -ne 0 ]; then
      msg="WARNING: ${RUN}_create_grib2.sh did not complete normally (non-fatal)"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
  else
      msg="Step 5 (GRIB2) completed normally"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
  fi

# --------------------------------------------------------------------------- #
# 6.  Set permissions on COMOUT

  if [ -d "${COMOUT}" ]; then
      chmod -Rf 755 $COMOUT 2>/dev/null || true
  fi

# --------------------------------------------------------------------------- #
# Done

  msg="Finished ${fn_this_sh} SUCCESSFULLY at $(date -u)"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

  echo
  echo "$msg"
  echo

# End of stofs_2d_glo_post.sh script ---------------------------------------- #
