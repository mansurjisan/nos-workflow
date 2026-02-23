#!/bin/bash

###############################################################################
#  Name: stofs_2d_glo_post_ncrcat.sh
#  Purpose: Concatenate nowcast + forecast forcing files for STOFS-2D-Global.
#
#  STOFS-2D-GLO runs ADCIRC in 3 phases (nowcast, forecast1, forecast2),
#  each producing separate GFS forcing NetCDF files (fort.221, fort.222,
#  fort.225).  This script concatenates them into single continuous files
#  for archival and downstream use.
#
#  Input files (from $COMOUTrerun):
#    ${RUN}_ncst.221.nc, ${RUN}_fcst1.221.nc, ${RUN}_fcst2.221.nc  (pressfc)
#    ${RUN}_ncst.222.nc, ${RUN}_fcst1.222.nc, ${RUN}_fcst2.222.nc  (uvgrd10m)
#    ${RUN}_ncst.225.nc, ${RUN}_fcst1.225.nc, ${RUN}_fcst2.225.nc  (icec)
#
#  Output files (to $COMOUT):
#    ${RUN}.${cycle}.pressfc.nc    - Surface pressure (full run)
#    ${RUN}.${cycle}.uvgrd10m.nc   - 10m wind components (full run)
#    ${RUN}.${cycle}.icec.nc       - Sea ice concentration (full run)
#
#  Requires: NCO tools (ncrcat)
#
#  Remarks:
#    Based on operational exstofs_2d_glo_post_ncrcat.sh
#                                                          February, 2026
###############################################################################

# Start of stofs_2d_glo_post_ncrcat.sh script -------------------------------- #

  set -x

  fn_this_sh="stofs_2d_glo_post_ncrcat.sh"

  echo "${fn_this_sh} began at UTC: $(date -u)"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }
  command -v err_chk  >/dev/null 2>&1 || err_chk()  { if [ ${err:-0} -ne 0 ]; then echo "FATAL ERROR: exit code ${err}"; exit ${err}; fi; }
  command -v err_exit >/dev/null 2>&1 || err_exit() { exit ${err:-1}; }
  command -v cpfs  >/dev/null 2>&1 || cpfs()  { cp "$@"; }

  pgmout=${fn_this_sh}.$$
  rm -f $pgmout

  msg="Starting ${fn_this_sh}: concatenate forcing files"
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
# 2.  Get output files from ${COMOUTrerun}

  cd $DATA

  export COMOUTrerun=${COMOUTrerun:-${COMOUT}/rerun}

  if [ -f ${COMOUTrerun}/${RUN}_ncst.221.nc ]; then
     ln -sf ${COMOUTrerun}/${RUN}_ncst.221.nc  ncst.221.nc
     ln -sf ${COMOUTrerun}/${RUN}_ncst.222.nc  ncst.222.nc
     ln -sf ${COMOUTrerun}/${RUN}_ncst.225.nc  ncst.225.nc
     ln -sf ${COMOUTrerun}/${RUN}_fcst1.221.nc fcst1.221.nc
     ln -sf ${COMOUTrerun}/${RUN}_fcst1.222.nc fcst1.222.nc
     ln -sf ${COMOUTrerun}/${RUN}_fcst1.225.nc fcst1.225.nc
     ln -sf ${COMOUTrerun}/${RUN}_fcst2.221.nc fcst2.221.nc
     ln -sf ${COMOUTrerun}/${RUN}_fcst2.222.nc fcst2.222.nc
     ln -sf ${COMOUTrerun}/${RUN}_fcst2.225.nc fcst2.225.nc
  else
     msg="FATAL ERROR: Forcing files not found in ${COMOUTrerun}"
     echo "$msg"
     postmsg "${jlogfile:-/dev/null}" "$msg"
     export err=1; err_exit
  fi

# --------------------------------------------------------------------------- #
# 3.  Execute ncrcat to combine all forcing files

  echo "Concatenating pressure surface forcing (fort.221)..."
  ncrcat ncst.221.nc fcst1.221.nc fcst2.221.nc fort.221.nc
  export err=$?; err_chk

  echo "Concatenating wind forcing (fort.222)..."
  ncrcat ncst.222.nc fcst1.222.nc fcst2.222.nc fort.222.nc
  export err=$?; err_chk

  echo "Concatenating ice concentration (fort.225)..."
  ncrcat ncst.225.nc fcst1.225.nc fcst2.225.nc fort.225.nc
  export err=$?; err_chk

# --------------------------------------------------------------------------- #
# 4.  Send files to $COMOUT

  if [ "${SENDCOM:-YES}" = YES ]; then
     echo "Copying fort.221.nc to $COMOUT/${RUN}.${cycle}.pressfc.nc"
     cpfs fort.221.nc   $COMOUT/${RUN}.${cycle}.pressfc.nc

     echo "Copying fort.222.nc to $COMOUT/${RUN}.${cycle}.uvgrd10m.nc"
     cpfs fort.222.nc   $COMOUT/${RUN}.${cycle}.uvgrd10m.nc

     echo "Copying fort.225.nc to $COMOUT/${RUN}.${cycle}.icec.nc"
     cpfs fort.225.nc   $COMOUT/${RUN}.${cycle}.icec.nc
  fi

  msg="Completing ${fn_this_sh}"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# End of stofs_2d_glo_post_ncrcat.sh script ---------------------------------- #
