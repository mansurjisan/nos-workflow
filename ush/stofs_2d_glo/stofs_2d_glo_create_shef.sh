#!/bin/bash

###############################################################################
#  Name: stofs_2d_glo_create_shef.sh
#  Purpose: Generate SHEF (Standard Hydrological Exchange Format) bulletins
#           for STOFS-2D-Global station water level data.
#
#  SHEF bulletins are the primary dissemination format for NWS water level
#  forecasts.  This script:
#    1. Extracts station timeseries from ADCIRC fort.61.nc files
#    2. Converts to SHEF format using the stofs_2d_glo_netcdf2shef executable
#    3. Adds WMO/NTC headers using make_ntc_file.pl
#    4. Archives and sends alerts for AWIPS distribution
#
#  Three products are generated (for each water level type):
#    cwl (combined water level): WMO header SXUS02 KWBM
#    htp (harmonic tide pred):   WMO header SXUS01 KWBM
#    swl (sub-tidal water level):WMO header SXUS03 KWBM
#
#  Input files:
#    $COMIN/${RUN}.${cycle}.points.cwl.nc  - Station cwl
#    $COMIN/${RUN}.${cycle}.points.htp.nc  - Station htp
#    $COMIN/${RUN}.${cycle}.points.swl.nc  - Station swl
#    $FIXstofs2d/${RUN}_msl2mllw           - MSL to MLLW conversion table
#
#  Output files:
#    $COMOUT/${RUN}.${cycle}.points.{cwl,htp,swl}.shef
#    $COMOUTwmo/shef_${RUN}.${cycle}.points.{cwl,htp,swl}
#
#  Requires:
#    Executables: stofs_2d_glo_netcdf2shef
#    Perl: make_ntc_file.pl
#
#  Remarks:
#    Based on operational exstofs_2d_glo_post_grib2.sh (SHEF section)
#    The SHEF generation is separated into its own script for modularity
#    in the unified framework, though operationally it lives in the
#    grib2 post script.
#                                                          February, 2026
###############################################################################

# Start of stofs_2d_glo_create_shef.sh script -------------------------------- #

  set -x

  fn_this_sh="stofs_2d_glo_create_shef.sh"

  echo "${fn_this_sh} began at UTC: $(date -u)"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }
  command -v err_chk  >/dev/null 2>&1 || err_chk()  { if [ ${err:-0} -ne 0 ]; then echo "FATAL ERROR: exit code ${err}"; exit ${err}; fi; }
  command -v err_exit >/dev/null 2>&1 || err_exit() { exit ${err:-1}; }
  command -v cpreq >/dev/null 2>&1 || cpreq() { cp "$@"; }
  command -v cpfs  >/dev/null 2>&1 || cpfs()  { cp "$@"; }

  pgmout=${fn_this_sh}.$$
  rm -f $pgmout

  msg="Starting ${fn_this_sh}: SHEF bulletin generation"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# --------------------------------------------------------------------------- #
# 1.  Set times and parameters

  export date=$PDY
  export YMDH=${PDY}${cyc}

  lsth=${FCST_LENGTH:-180}

  export COMOUTwmo=${COMOUTwmo:-${COMOUT}/wmo}
  mkdir -p ${COMOUTwmo}

# --------------------------------------------------------------------------- #
# 2.  Get station output files from ${COMIN}

  cd $DATA

  for type in cwl htp swl; do
      if [ -f $COMIN/${RUN}.${cycle}.points.${type}.nc ]; then
          cpreq $COMIN/${RUN}.${cycle}.points.${type}.nc ${type}.fort.61.nc
      fi
  done

  if [ ! -f cwl.fort.61.nc ] || [ ! -f htp.fort.61.nc ]; then
     msg="FATAL ERROR: cwl.fort.61.nc and/or htp.fort.61.nc do not exist"
     echo "$msg"
     postmsg "${jlogfile:-/dev/null}" "$msg"
     export err=1; err_exit
  fi

# --------------------------------------------------------------------------- #
# 3.  Execute netcdf2shef for all water level types

  if [ ! -x ${EXECstofs2d}/${RUN}_netcdf2shef ]; then
      msg="WARNING: ${EXECstofs2d}/${RUN}_netcdf2shef not found, skipping SHEF"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
      exit 0
  fi

  export pgm="stofs_2d_glo_netcdf2shef"
  if command -v prep_step >/dev/null 2>&1; then
      . prep_step
  fi

  for type in cwl htp swl; do
      echo "Generating SHEF for type=${type}..."

      ${EXECstofs2d}/${RUN}_netcdf2shef con ${type} ${YMDH} \
          ${type}.fort.61.nc ${FIXstofs2d}/${RUN}_msl2mllw >> $pgmout 2>errfile
      export err=$?; err_chk

      # Concatenate per-station fort.5xxx files into single SHEF file
      # Station number ranges from operational configuration
      rm -f ${RUN}.${cycle}.points.${type}.shef 2>/dev/null || true

      for sta in $(seq -f "%03g" 1 136) 138 139 $(seq 141 144) $(seq 146 150) 152; do
          if [ -f fort.5${sta} ]; then
              cat fort.5${sta} >> ${RUN}.${cycle}.points.${type}.shef
          fi
      done
      for sta in $(seq 154 156) $(seq 159 161) $(seq 163 177) $(seq 179 208) $(seq 225 229); do
          if [ -f fort.5${sta} ]; then
              cat fort.5${sta} >> ${RUN}.${cycle}.points.${type}.shef
          fi
      done
      for sta in $(seq 559 831); do
          if [ -f fort.5${sta} ]; then
              cat fort.5${sta} >> ${RUN}.${cycle}.points.${type}.shef
          fi
      done
      rm -f fort.5* 2>/dev/null || true
  done

# --------------------------------------------------------------------------- #
# 4.  Create AWIPS SHEF output with WMO/NTC headers

  if [ -f ${USHstofs2d}/make_ntc_file.pl ]; then
      export pgm="makentc"
      if command -v prep_step >/dev/null 2>&1; then
          . prep_step
      fi

      # WMO headers:  cwl -> SXUS02,  htp -> SXUS01,  swl -> SXUS03
      declare -A SHEF_WMO_HEADERS
      SHEF_WMO_HEADERS=( [cwl]=SXUS02 [htp]=SXUS01 [swl]=SXUS03 )

      for type in cwl htp swl; do
          if [ -f ${RUN}.${cycle}.points.${type}.shef ]; then
              sed '1d' ${RUN}.${cycle}.points.${type}.shef > tmp.dat
              ${USHstofs2d}/make_ntc_file.pl \
                  ${SHEF_WMO_HEADERS[$type]} KWBM ${YMDH} NONE \
                  tmp.dat shef_${RUN}.${cycle}.points.${type}
              export err=$?; err_chk
              rm -f tmp.dat
          fi
      done
  else
      echo "WARNING: make_ntc_file.pl not found, skipping WMO headers"
  fi

# --------------------------------------------------------------------------- #
# 5.  Archive SHEF files to $COMOUT and $COMOUTwmo

  for type in cwl htp swl; do
      if [ "${SENDCOM:-YES}" = YES ]; then
          if [ -f ${RUN}.${cycle}.points.${type}.shef ]; then
              cpfs ${RUN}.${cycle}.points.${type}.shef $COMOUT/.
          fi
          if [ -f shef_${RUN}.${cycle}.points.${type} ]; then
              cpfs shef_${RUN}.${cycle}.points.${type} ${COMOUTwmo}/.
          fi
      fi
  done

# --------------------------------------------------------------------------- #
# 6.  Send AWIPS alerts

  if [ "${SENDDBN:-NO}" = YES ]; then
      for type in cwl htp swl; do
          if [ -f $COMOUT/${RUN}.${cycle}.points.${type}.shef ]; then
              $DBNROOT/bin/dbn_alert MODEL STOFS_SHEF $job \
                  $COMOUT/${RUN}.${cycle}.points.${type}.shef
              export err=$?; err_chk
          fi
      done
  fi

  if [ "${SENDDBN_NTC:-NO}" = YES ]; then
      for type in cwl htp swl; do
          if [ -f ${COMOUTwmo}/shef_${RUN}.${cycle}.points.${type} ]; then
              $DBNROOT/bin/dbn_alert NTC_LOW $NET $job \
                  ${COMOUTwmo}/shef_${RUN}.${cycle}.points.${type}
              export err=$?; err_chk
          fi
      done
  fi

  msg="Completing ${fn_this_sh}"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# End of stofs_2d_glo_create_shef.sh script ---------------------------------- #
