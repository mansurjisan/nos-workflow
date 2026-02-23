#!/bin/bash

###############################################################################
#  Name: stofs_2d_glo_create_grib2.sh
#  Purpose: Generate GRIB2 products for STOFS-2D-Global sub-domains.
#
#  Interpolates ADCIRC unstructured grid output (fort.63.nc) to regular
#  lat/lon grids for 8 sub-domains using the stofs_2d_glo_netcdf2grib
#  Fortran executable, then processes with tocgrib2 for WMO headers.
#
#  Sub-domains (read from YAML config output.grib2_domains):
#    conus.east, conus.west, alaska, hawaii,
#    puertori, guam, micronesia, northpacific
#
#  For each domain and each water level type (cwl, htp, swl):
#    - Per-hour GRIB2: ${RUN}.${cycle}.${domain}.f{000..180}.grib2
#    - Combined GRIB2: ${RUN}.${cycle}.${domain}.${type}.grib2
#    - WMO-headered:   grib2_${RUN}.${cycle}.${domain}.${type}
#
#  Input files:
#    $COMIN/${RUN}.${cycle}.fields.cwl.nc  - Combined water level fields
#    $COMIN/${RUN}.${cycle}.fields.htp.nc  - Tidal prediction fields
#    $COMIN/${RUN}.${cycle}.fields.swl.nc  - Sub-tidal water level fields
#    $FIXstofs2d/${RUN}_${domain}.mask     - Domain mask files
#
#  Requires:
#    Executables: stofs_2d_glo_netcdf2grib, tocgrib2
#    Parameter files: $PARMstofs2d/grib2_${RUN}_${domain}_${type}
#
#  Remarks:
#    Based on operational exstofs_2d_glo_post_grib2.sh
#    Uses MPI cfp for parallel domain processing
#                                                          February, 2026
###############################################################################

# Start of stofs_2d_glo_create_grib2.sh script ------------------------------- #

  set -x

  fn_this_sh="stofs_2d_glo_create_grib2.sh"

  echo "${fn_this_sh} began at UTC: $(date -u)"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }
  command -v err_chk  >/dev/null 2>&1 || err_chk()  { if [ ${err:-0} -ne 0 ]; then echo "FATAL ERROR: exit code ${err}"; exit ${err}; fi; }
  command -v err_exit >/dev/null 2>&1 || err_exit() { exit ${err:-1}; }
  command -v cpreq >/dev/null 2>&1 || cpreq() { cp "$@"; }
  command -v cpfs  >/dev/null 2>&1 || cpfs()  { cp "$@"; }

  pgmout=${fn_this_sh}.$$
  rm -f $pgmout

  msg="Starting ${fn_this_sh}: GRIB2 generation for sub-domains"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# --------------------------------------------------------------------------- #
# 1.  Set times and parameters

  export date=$PDY
  export YMDH=${PDY}${cyc}

  lsth=${FCST_LENGTH:-180}

  time_now=$YMDH
  time_end=$(${NDATE:-ndate} $lsth $YMDH)

  # GRIB2 sub-domains and their fort unit base numbers
  # Domain mask files are: ${FIXstofs2d}/${RUN}_${domain}.mask
  # Fort unit offsets:  conus.east=3000, conus.west=4000, puertori=5000,
  #                     alaska=6000, hawaii=7000, guam=8000, northpacific=9000
  declare -A DOMAIN_UNITS
  DOMAIN_UNITS=(
      [conus.east]=3000
      [conus.west]=4000
      [puertori]=5000
      [alaska]=6000
      [hawaii]=7000
      [guam]=8000
      [northpacific]=9000
  )

  # All GRIB2 domains (micronesia not in operational netcdf2grib, but in YAML)
  GRIB2_DOMAINS="conus.east conus.west puertori alaska hawaii guam northpacific"

  # Number of CPUs for parallel processing (7 domains)
  export NCPU=${NCPU:-7}
  export PPN=${PPN:-7}

# --------------------------------------------------------------------------- #
# 2.  Get output files from ${COMIN}

  cd $DATA

  if [ -f $COMIN/${RUN}.${cycle}.fields.cwl.nc ]; then
     cpreq $COMIN/${RUN}.${cycle}.points.cwl.nc cwl.fort.61.nc
     cpreq $COMIN/${RUN}.${cycle}.points.htp.nc htp.fort.61.nc
     cpreq $COMIN/${RUN}.${cycle}.points.swl.nc swl.fort.61.nc
     cpreq $COMIN/${RUN}.${cycle}.fields.cwl.nc cwl.fort.63.nc
     cpreq $COMIN/${RUN}.${cycle}.fields.htp.nc htp.fort.63.nc
     cpreq $COMIN/${RUN}.${cycle}.fields.swl.nc swl.fort.63.nc
  fi

  if [ ! -f cwl.fort.63.nc ] || [ ! -f htp.fort.63.nc ]; then
     msg="FATAL ERROR: cwl.fort.63.nc and/or htp.fort.63.nc do not exist"
     echo "$msg"
     postmsg "${jlogfile:-/dev/null}" "$msg"
     export err=1; err_exit
  else
     echo "Field output files (cwl, htp, swl) exist"
  fi

# --------------------------------------------------------------------------- #
# 3.  Generate SHEF from station data (netcdf2shef)
#     This is done first because it processes fort.61.nc (station) files

  if [ -x ${EXECstofs2d}/${RUN}_netcdf2shef ]; then
      export pgm="stofs_2d_glo_netcdf2shef"
      if command -v prep_step >/dev/null 2>&1; then
          . prep_step
      fi

      for type in cwl htp swl; do
          ${EXECstofs2d}/${RUN}_netcdf2shef con $type $YMDH \
              ${type}.fort.61.nc ${FIXstofs2d}/${RUN}_msl2mllw >> $pgmout 2>errfile
          export err=$?; err_chk

          # Concatenate per-station SHEF files into single file
          # Station ranges match operational configuration
          for sta in $(seq -f "%03g" 1 136) 138 139 $(seq 141 144) $(seq 146 150) 152; do
              cat fort.5${sta} >> ${RUN}.${cycle}.points.${type}.shef 2>/dev/null || true
          done
          for sta in $(seq 154 156) $(seq 159 161) $(seq 163 177) $(seq 179 208) $(seq 225 229); do
              cat fort.5${sta} >> ${RUN}.${cycle}.points.${type}.shef 2>/dev/null || true
          done
          for sta in $(seq 559 831); do
              cat fort.5${sta} >> ${RUN}.${cycle}.points.${type}.shef 2>/dev/null || true
          done
          rm -f fort.5* 2>/dev/null || true
      done

      # Create AWIPS SHEF output with NTC headers
      if [ -f ${USHstofs2d}/make_ntc_file.pl ]; then
          export pgm="makentc"
          if command -v prep_step >/dev/null 2>&1; then
              . prep_step
          fi

          for type in cwl htp swl; do
              sed '1d' ${RUN}.${cycle}.points.${type}.shef > tmp.dat
              if [ "${type}" = "cwl" ]; then
                  ${USHstofs2d}/make_ntc_file.pl SXUS02 KWBM ${YMDH} NONE tmp.dat shef_${RUN}.${cycle}.points.${type}
              elif [ "${type}" = "htp" ]; then
                  ${USHstofs2d}/make_ntc_file.pl SXUS01 KWBM ${YMDH} NONE tmp.dat shef_${RUN}.${cycle}.points.${type}
              else
                  ${USHstofs2d}/make_ntc_file.pl SXUS03 KWBM ${YMDH} NONE tmp.dat shef_${RUN}.${cycle}.points.${type}
              fi
              export err=$?; err_chk
              rm -f tmp.dat
          done
      fi

      # Archive SHEF files
      for type in cwl htp swl; do
          if [ "${SENDCOM:-YES}" = YES ]; then
              cpfs ${RUN}.${cycle}.points.${type}.shef $COMOUT/.
          fi
          if [ "${SENDDBN:-NO}" = YES ]; then
              mkdir -p ${COMOUTwmo:-${COMOUT}/wmo}
              cpfs shef_${RUN}.${cycle}.points.${type} ${COMOUTwmo:-${COMOUT}/wmo}/.
          fi
      done

      # Send SHEF alerts
      if [ "${SENDDBN:-NO}" = YES ]; then
          for type in cwl htp swl; do
              $DBNROOT/bin/dbn_alert MODEL STOFS_SHEF $job $COMOUT/${RUN}.${cycle}.points.${type}.shef
              export err=$?; err_chk
          done
      fi
      if [ "${SENDDBN_NTC:-NO}" = YES ]; then
          for type in cwl htp swl; do
              $DBNROOT/bin/dbn_alert NTC_LOW $NET $job ${COMOUTwmo:-${COMOUT}/wmo}/shef_${RUN}.${cycle}.points.${type}
              export err=$?; err_chk
          done
      fi
  else
      echo "WARNING: ${EXECstofs2d}/${RUN}_netcdf2shef not found, skipping SHEF"
  fi

# --------------------------------------------------------------------------- #
# 4.  Generate GRIB2 for all domains (netcdf2grib)
#     Uses MPI cfp for parallel processing across domains

  if [ -x ${EXECstofs2d}/${RUN}_netcdf2grib ]; then
      export pgm="stofs_2d_glo_netcdf2grib"
      if command -v prep_step >/dev/null 2>&1; then
          . prep_step
      fi

      for type in cwl htp swl; do
          rm -f poescript 2>/dev/null || true

          # Build parallel task list (one domain per MPI rank)
          pgm_idx=1
          for domain in ${GRIB2_DOMAINS}; do
              unit=${DOMAIN_UNITS[$domain]}
              echo "${EXECstofs2d}/${RUN}_netcdf2grib ${domain%%.*} ${type} ${YMDH} ${FIXstofs2d}/${RUN}_${domain}.mask ${type}.fort.63.nc ${unit} >> ${pgmout}.${pgm_idx} 2>errfile" >> poescript
              pgm_idx=$((pgm_idx + 1))
          done

          chmod 775 poescript

          if command -v cfp >/dev/null 2>&1; then
              mpiexec -n ${NCPU} -ppn ${PPN} --cpu-bind core cfp poescript
          else
              # Sequential fallback when MPI/cfp not available
              echo "WARNING: cfp not available, running domains sequentially"
              for domain in ${GRIB2_DOMAINS}; do
                  unit=${DOMAIN_UNITS[$domain]}
                  ${EXECstofs2d}/${RUN}_netcdf2grib ${domain%%.*} ${type} ${YMDH} \
                      ${FIXstofs2d}/${RUN}_${domain}.mask ${type}.fort.63.nc ${unit} >> $pgmout 2>errfile
              done
          fi
          export err=$?; err_chk
          cat ${pgmout}.* >> $pgmout 2>/dev/null || true

          # Assemble per-hour and per-type GRIB2 files from fort units
          for fhr in $(seq -f "%03g" 0 ${lsth}); do
              for domain in ${GRIB2_DOMAINS}; do
                  unit_prefix=$(echo ${DOMAIN_UNITS[$domain]} | cut -c1)
                  if [ -f fort.${unit_prefix}${fhr} ]; then
                      cat fort.${unit_prefix}${fhr} >> ${RUN}.${cycle}.${domain}.f${fhr}.grib2
                      cat fort.${unit_prefix}${fhr} >> ${RUN}.${cycle}.${domain}.${type}.grib2
                  fi
              done
          done

          # Clean up fort files
          rm -f fort.3* fort.4* fort.5* fort.6* fort.7* fort.8* fort.9* 2>/dev/null || true
      done
  else
      echo "WARNING: ${EXECstofs2d}/${RUN}_netcdf2grib not found, skipping GRIB2 generation"
      msg="Completing ${fn_this_sh} (no GRIB2 executable)"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
      exit 0
  fi

# --------------------------------------------------------------------------- #
# 5.  Send GRIB2 output to $COMOUT

  if [ "${SENDCOM:-YES}" = YES ]; then
     for domain in ${GRIB2_DOMAINS}; do
         for fhr in $(seq -f "%03g" 0 ${lsth}); do
             if [ -f ${RUN}.${cycle}.${domain}.f${fhr}.grib2 ]; then
                 cpfs ${RUN}.${cycle}.${domain}.f${fhr}.grib2 $COMOUT/.
             fi
         done
     done

     # Send per-hour alerts
     if [ "${SENDDBN:-NO}" = YES ]; then
         for domain in ${GRIB2_DOMAINS}; do
             for fhr in $(seq -f "%03g" 0 ${lsth}); do
                 if [ -f $COMOUT/${RUN}.${cycle}.${domain}.f${fhr}.grib2 ]; then
                     $DBNROOT/bin/dbn_alert MODEL ${DBN_ALERT_TYPE:-STOFS_GB2} $job \
                         $COMOUT/${RUN}.${cycle}.${domain}.f${fhr}.grib2
                     export err=$?; err_chk
                 fi
             done
         done
     fi
  fi

# --------------------------------------------------------------------------- #
# 6.  Process GRIB2 products with WMO headers (tocgrib2)

  if command -v tocgrib2 >/dev/null 2>&1; then
      export pgm="tocgrib2"
      if command -v prep_step >/dev/null 2>&1; then
          . prep_step
      fi

      export PARMstofs2d=${PARMstofs2d:-${HOMEnos:-${HOMEstofs}}/parm/${RUN}}

      for domain in ${GRIB2_DOMAINS}; do
          for type in cwl htp swl; do
              if [ -f ${RUN}.${cycle}.${domain}.${type}.grib2 ]; then
                  export FORT11=${RUN}.${cycle}.${domain}.${type}.grib2
                  export FORT31=" "
                  export FORT51=grib2_${RUN}.${cycle}.${domain}.${type}

                  if [ -f ${PARMstofs2d}/grib2_${RUN}_${domain}_${type} ]; then
                      tocgrib2 < ${PARMstofs2d}/grib2_${RUN}_${domain}_${type} >> $pgmout 2>errfile
                      err=$?; export err; err_chk
                  else
                      echo "WARNING: Parameter file grib2_${RUN}_${domain}_${type} not found"
                  fi
              fi
          done
      done
  else
      echo "WARNING: tocgrib2 not available, skipping WMO header processing"
  fi

# --------------------------------------------------------------------------- #
# 7.  Send WMO-headered GRIB2 files to $COMOUT

  if [ "${SENDCOM:-YES}" = YES ]; then
     mkdir -p ${COMOUTwmo:-${COMOUT}/wmo}
     for domain in ${GRIB2_DOMAINS}; do
         for type in cwl htp swl; do
             if [ -f ${RUN}.${cycle}.${domain}.${type}.grib2 ]; then
                 cpfs ${RUN}.${cycle}.${domain}.${type}.grib2  $COMOUT/.
             fi
             if [ -f grib2_${RUN}.${cycle}.${domain}.${type} ]; then
                 cpfs grib2_${RUN}.${cycle}.${domain}.${type}  ${COMOUTwmo:-${COMOUT}/wmo}/.
             fi
         done
     done
  fi

  # AWIPS distribution
  if [ "${SENDDBN_NTC:-NO}" = YES ]; then
      for domain in ${GRIB2_DOMAINS}; do
          for type in cwl htp swl; do
              if [ -f ${COMOUTwmo:-${COMOUT}/wmo}/grib2_${RUN}.${cycle}.${domain}.${type} ]; then
                  $DBNROOT/bin/dbn_alert NTC_LOW $NET $job \
                      ${COMOUTwmo:-${COMOUT}/wmo}/grib2_${RUN}.${cycle}.${domain}.${type}
                  export err=$?; err_chk
              fi
              if [ -f $COMOUT/${RUN}.${cycle}.${domain}.${type}.grib2 ]; then
                  $DBNROOT/bin/dbn_alert MODEL ${DBN_ALERT_TYPE:-STOFS_GB2} $job \
                      $COMOUT/${RUN}.${cycle}.${domain}.${type}.grib2
                  export err=$?; err_chk
              fi
          done
      done
  fi

  msg="Completing ${fn_this_sh}"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# End of stofs_2d_glo_create_grib2.sh script --------------------------------- #
