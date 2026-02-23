#!/bin/bash

###############################################################################
#  Name: stofs_2d_glo_post_ncdiff.sh
#  Purpose: Compute sub-tidal (anomaly) water level for STOFS-2D-Global.
#
#  Computes: swl = cwl - htp
#    cwl = combined water level (surface run output: wind + tide + pressure)
#    htp = harmonic tide prediction (tide-only run output)
#    swl = sub-tidal / storm surge / anomaly water level
#
#  Input files (from $COMIN):
#    ${RUN}.${cycle}.points.cwl.nc  - Station time series, combined water level
#    ${RUN}.${cycle}.points.htp.nc  - Station time series, tidal prediction
#    ${RUN}.${cycle}.fields.cwl.nc  - Field output, combined water level
#    ${RUN}.${cycle}.fields.htp.nc  - Field output, tidal prediction
#
#  Output files (to $COMOUT):
#    ${RUN}.${cycle}.points.swl.nc  - Station time series, sub-tidal water level
#    ${RUN}.${cycle}.fields.swl.nc  - Field output, sub-tidal water level
#
#  Requires: NCO tools (ncdiff, ncks)
#
#  Remarks:
#    Based on operational exstofs_2d_glo_post_ncdiff.sh
#                                                          February, 2026
###############################################################################

# Start of stofs_2d_glo_post_ncdiff.sh script -------------------------------- #

  set -x

  fn_this_sh="stofs_2d_glo_post_ncdiff.sh"

  echo "${fn_this_sh} began at UTC: $(date -u)"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }
  command -v err_chk  >/dev/null 2>&1 || err_chk()  { if [ ${err:-0} -ne 0 ]; then echo "FATAL ERROR: exit code ${err}"; exit ${err}; fi; }
  command -v err_exit >/dev/null 2>&1 || err_exit() { exit ${err:-1}; }
  command -v cpreq >/dev/null 2>&1 || cpreq() { cp "$@"; }
  command -v cpfs  >/dev/null 2>&1 || cpfs()  { cp "$@"; }

  pgmout=${fn_this_sh}.$$
  rm -f $pgmout

  msg="Starting ${fn_this_sh}: compute sub-tidal water level (swl = cwl - htp)"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# --------------------------------------------------------------------------- #
# 1.  Set times

  export date=$PDY
  export YMDH=${PDY}${cyc}

  lsth=${FCST_LENGTH:-180}

  time_now=$YMDH
  time_end=$(${NDATE:-ndate} $lsth $YMDH)

# --------------------------------------------------------------------------- #
# 2.  Get output files from ${COMIN}

  cd $DATA

  if [ -f $COMIN/${RUN}.${cycle}.points.cwl.nc ]; then
     ln -sf ${COMIN}/${RUN}.${cycle}.points.cwl.nc cwl.fort.61.nc
     ln -sf ${COMIN}/${RUN}.${cycle}.points.htp.nc htp.fort.61.nc
     ln -sf ${COMIN}/${RUN}.${cycle}.fields.cwl.nc cwl.fort.63.nc
     ln -sf ${COMIN}/${RUN}.${cycle}.fields.htp.nc htp.fort.63.nc
  fi

  if [ ! -f cwl.fort.63.nc ] || [ ! -f htp.fort.63.nc ]; then
     msg="FATAL ERROR: cwl.fort.63.nc and/or htp.fort.63.nc do not exist"
     echo "$msg"
     postmsg "${jlogfile:-/dev/null}" "$msg"
     export err=1; err_exit
  else
     echo "cwl.fort.63.nc and htp.fort.63.nc files exist"
  fi

# --------------------------------------------------------------------------- #
# 3.  Execute ncdiff to compute sub-tidal water level
#     Station timeseries (fort.61): full diff of all variables
#     Field output (fort.63): diff only the zeta variable, then append x,y

  echo "Computing ncdiff for station timeseries (fort.61)..."
  ncdiff cwl.fort.61.nc htp.fort.61.nc swl.fort.61.nc
  export err=$?; err_chk

  echo "Computing ncdiff for field output (fort.63, variable: zeta)..."
  ncdiff -v zeta cwl.fort.63.nc htp.fort.63.nc swl.fort.63.nc
  export err=$?; err_chk

  # Append coordinate variables (x, y) that ncdiff does not carry over
  echo "Appending coordinate variables to swl files..."
  ncks -A -v x,y cwl.fort.61.nc swl.fort.61.nc
  export err=$?; err_chk

  ncks -A -v x,y cwl.fort.63.nc swl.fort.63.nc
  export err=$?; err_chk

# --------------------------------------------------------------------------- #
# 4.  Send files to $COMOUT

  if [ "${SENDCOM:-YES}" = YES ]; then
     echo "Copying swl.fort.61.nc to $COMOUT/${RUN}.${cycle}.points.swl.nc"
     cpfs swl.fort.61.nc   $COMOUT/${RUN}.${cycle}.points.swl.nc

     echo "Copying swl.fort.63.nc to $COMOUT/${RUN}.${cycle}.fields.swl.nc"
     cpfs swl.fort.63.nc   $COMOUT/${RUN}.${cycle}.fields.swl.nc
  fi

  if [ "${SENDDBN:-NO}" = YES ]; then
     $DBNROOT/bin/dbn_alert MODEL STOFS_NETCDF $job $COMOUT/${RUN}.${cycle}.points.swl.nc
     $DBNROOT/bin/dbn_alert MODEL STOFS_NETCDF $job $COMOUT/${RUN}.${cycle}.fields.swl.nc
  fi

  msg="Completing ${fn_this_sh}"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# End of stofs_2d_glo_post_ncdiff.sh script ---------------------------------- #
