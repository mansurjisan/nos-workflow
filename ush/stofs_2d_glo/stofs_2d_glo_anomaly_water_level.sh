#!/bin/bash

###############################################################################
#  Name: stofs_2d_glo_anomaly_water_level.sh
#  Purpose: Compute anomaly-corrected water level for STOFS-2D-Global.
#
#  The anomaly correction adjusts model water levels using observed bias
#  from CO-OPS tide gauge stations.  The correction is:
#    acwl = cwl + anomaly   (anomaly = obs - model at station locations)
#
#  Steps:
#    1. Extract per-station timeseries from cwl and htp fort.61.nc files
#       using the stofs_2d_glo_anomaly Fortran executable
#    2. Compute observed anomaly from CO-OPS water level observations
#       (via etweb_database.py and etweb_extract.py)
#    3. Apply anomaly correction to each station timeseries
#    4. Rebuild the corrected station NetCDF file
#
#  Input files:
#    $COMIN/${RUN}.${cycle}.points.cwl.nc  - Combined water level stations
#    $COMIN/${RUN}.${cycle}.points.htp.nc  - Tidal prediction stations
#    $FIXstofs2d/${RUN}_station.ctl        - Station control file
#    $FIXstofs2d/${RUN}_cron.bnt           - Cron control file
#    $FIXstofs2d/${RUN}_ft03.dta           - Harmonic constants
#    $FIXstofs2d/${RUN}_ft07.dta           - Harmonic constants
#
#  Output files:
#    $COMOUT/${RUN}.${cycle}.points.cwl.nc  - Anomaly-corrected station cwl
#    $COMOUT/database.tar.gz                - Updated observation database
#
#  Requires:
#    Executables: stofs_2d_glo_anomaly
#    Python: etweb_database.py, etweb_extract.py
#    NCO tools: ncdump, ncgen
#
#  Remarks:
#    Based on operational exstofs_2d_glo_post_anomaly.sh
#                                                          February, 2026
###############################################################################

# Start of stofs_2d_glo_anomaly_water_level.sh script ------------------------ #

  set -x

  fn_this_sh="stofs_2d_glo_anomaly_water_level.sh"

  echo "${fn_this_sh} began at UTC: $(date -u)"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }
  command -v err_chk  >/dev/null 2>&1 || err_chk()  { if [ ${err:-0} -ne 0 ]; then echo "FATAL ERROR: exit code ${err}"; exit ${err}; fi; }
  command -v err_exit >/dev/null 2>&1 || err_exit() { exit ${err:-1}; }
  command -v cpreq >/dev/null 2>&1 || cpreq() { cp "$@"; }
  command -v cpfs  >/dev/null 2>&1 || cpfs()  { cp "$@"; }

  pgmout=${fn_this_sh}.$$
  rm -f $pgmout

  msg="Starting ${fn_this_sh}: anomaly water level correction"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# --------------------------------------------------------------------------- #
# 1.  Set times

  export date=$PDY
  export YMDH=${PDY}${cyc}

  wndh=3
  nowh=6
  lsth=${FCST_LENGTH:-180}

  time_beg=$(${NDATE:-ndate} -${nowh} $YMDH)
  time_now=$YMDH
  time_end=$(${NDATE:-ndate} $lsth $YMDH)

  # Build time-minute file (6-minute intervals for station output)
  cd $DATA
  rm -f ymdhm.txt

  ymdh=$time_beg
  while [ $ymdh -lt $time_end ]; do
      for mins in $(seq -f "%02g" 6 6 54); do
          echo ${ymdh}${mins} >> ymdhm.txt
      done
      ymdh=$(${NDATE:-ndate} 1 $ymdh)
      echo ${ymdh}00 >> ymdhm.txt
  done

# --------------------------------------------------------------------------- #
# 2.  Copy output files from $COMIN

  # Handle previous-cycle database for 00z cycle
  if [ "${cyc}" = "00" ]; then
     if [ -f ${COM:-${COMOUT}/..}/${RUN}.${PDYm1:-}/database.tar.gz ]; then
        cpreq ${COM:-${COMOUT}/..}/${RUN}.${PDYm1:-}/database.tar.gz ${COMIN}/. 2>/dev/null || true
     fi
  fi

  if [ -f $COMIN/${RUN}.${cycle}.points.cwl.nc ]; then
     ln -sf $COMIN/${RUN}.${cycle}.points.cwl.nc cwl.fort.61.nc
     ln -sf $COMIN/${RUN}.${cycle}.points.htp.nc htp.fort.61.nc
     cpreq $COMIN/${RUN}.${cycle}.points.cwl.nc ${RUN}.${cycle}.points.cwl.noanomaly.nc 2>/dev/null || true
  else
     msg="FATAL ERROR: ${RUN}.${cycle}.points.cwl.nc not found in ${COMIN}"
     echo "$msg"
     postmsg "${jlogfile:-/dev/null}" "$msg"
     export err=1; err_exit
  fi

  # Extract metadata from cwl NetCDF file
  ncdump -f f cwl.fort.61.nc > tmp.cdl
  export err=$?; err_chk

  time_number=$(grep -P "time = UNLIMITED" tmp.cdl | grep -o '[0-9]\+')
  station_number=$(grep -P "station =" tmp.cdl | grep -o '[0-9]\+')
  sed -i '31d' tmp.cdl
  sed -i '1,/zeta =/!d' tmp.cdl

  echo "time_number=${time_number}, station_number=${station_number}"

# --------------------------------------------------------------------------- #
# 3.  Extract per-station water level timeseries using Fortran executable

  export pgm="stofs_2d_glo_anomaly"
  if command -v prep_step >/dev/null 2>&1; then
      . prep_step
  fi

  extract_year=$(echo $time_now | cut -c1-4)
  extract_year2=$(echo $time_now | cut -c3-4)
  extract_month=$(echo $time_now | cut -c5-6)
  extract_day=$(echo $time_now | cut -c7-8)

  if [ -x ${EXECstofs2d}/${RUN}_anomaly ]; then
      mpiexec -n 1 -ppn 1 ${EXECstofs2d}/${RUN}_anomaly \
          "cwl.fort.61.nc" "htp.fort.61.nc" \
          "${extract_day}" "${cyc}" \
          "${FIXstofs2d}/${RUN}_station.ctl" \
          "ymdhm.txt" "mdl.t${cyc}z.txt" >> $pgmout 2>errfile
      export err=$?; err_chk
  else
      msg="WARNING: ${EXECstofs2d}/${RUN}_anomaly not found, skipping station extraction"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
      # Archive no-anomaly version and exit gracefully
      if [ "${SENDCOM:-YES}" = YES ]; then
          cpfs ${RUN}.${cycle}.points.cwl.noanomaly.nc $COMOUT/${RUN}.${cycle}.points.cwl.noanomaly.nc 2>/dev/null || true
      fi
      msg="Completing ${fn_this_sh} (no anomaly executable)"
      echo "$msg"
      postmsg "${jlogfile:-/dev/null}" "$msg"
      exit 0
  fi

  mkdir -p $DATA/model
  mv *.cwl $DATA/model/. 2>/dev/null || true
  cpreq mdl.${cycle}.txt $DATA/model/${RUN}_1hcwl.txt 2>/dev/null || true

# --------------------------------------------------------------------------- #
# 4.  Compute anomaly from CO-OPS tide gauge observations

  mkdir -p $DATA/data $DATA/database $DATA/log $DATA/msl $DATA/msl/plots $DATA/msl/maps

  cpreq ${FIXstofs2d}/${RUN}_station.ctl $DATA/data/.
  ln -sf ${FIXstofs2d}/${RUN}_cron.bnt   $DATA/data/cron.bnt
  ln -sf ${FIXstofs2d}/${RUN}_ft03.dta   $DATA/data/ft03.dta
  ln -sf ${FIXstofs2d}/${RUN}_ft07.dta   $DATA/data/ft07.dta

  # Unpack previous observation database
  if [ -f $COMIN/database.tar.gz ]; then
      cpreq $COMIN/database.tar.gz $DATA/.
      tar xvzf database.tar.gz
      export err=$?; err_chk
  else
      mkdir -p $DATA/database
  fi

  # Download CO-OPS observations
  export DCOMIN=${DCOMIN:-${DCOMROOT:-/lfs/h1/ops/prod/dcom}/${PDY}/coops_waterlvlobs}

  if [ ! -d $DCOMIN ]; then
     echo "WARNING: ${DCOMIN} not available, trying previous date"
     export DCOMIN=${DCOMROOT:-/lfs/h1/ops/prod/dcom}/${PDYm1:-$(date -d "$PDY -1 day" +%Y%m%d)}/coops_waterlvlobs
  fi

  # Extract station observation data
  sed -i '1d' $DATA/data/${RUN}_station.ctl 2>/dev/null || true
  while read obs; do
      nosid=$(echo $obs | awk '{print $2}')
      msl2mllw=$(echo $obs | awk '{print $3}')
      echo "$nosid $msl2mllw"
      if [ -f $DCOMIN/${nosid}.xml ]; then
          awk -v m=$msl2mllw '{print $4,$5",",($ 6+m)*3.2808","}' $DCOMIN/${nosid}.xml > $DATA/database/${nosid}.csv
      else
          echo "NULL" > $DATA/database/${nosid}.csv
      fi
  done < $DATA/data/${RUN}_station.ctl

  # Run Python anomaly processing
  if [ -f ${USHstofs2d}/etweb_database.py ]; then
      mpiexec -n 1 -ppn 1 python ${USHstofs2d}/etweb_database.py >> $pgmout 2>errfile
      export err=$?; err_chk
  fi

  extract_now="${extract_month}/${extract_day}/${extract_year} ${cyc}:00:00"
  if [ -f ${USHstofs2d}/etweb_extract.py ]; then
      mpiexec -n 1 -ppn 1 python ${USHstofs2d}/etweb_extract.py --all --date "${extract_now}" >> $pgmout 2>errfile
      export err=$?; err_chk
  fi

  # Archive updated database
  rm -f $DATA/database/*.csv 2>/dev/null || true
  if [ -d $DATA/database ]; then
      tar cvzf database.tar.gz database/
      export err=$?; err_chk
      if [ "${SENDCOM:-YES}" = YES ]; then
          cpfs database.tar.gz $COMOUT/.
      fi
  fi

# --------------------------------------------------------------------------- #
# 5.  Combine water level and anomaly for each station

  mkdir -p $DATA/tmp

  extract_date="${extract_year2}${extract_month}${extract_day}"
  while read line; do
      abbr=$(echo $line | awk '{print $1}')
      if [ -f $DATA/msl/plots/${abbr}_${extract_date}.anom ]; then
          anom=$(tail -n 1 $DATA/msl/plots/${abbr}_${extract_date}.anom | awk '{print $2}')
          if [ "${anom}" != "0.00" ]; then
              while read line1; do
                  awk -f ${USHstofs2d}/inter.awk $DATA/msl/plots/${abbr}_${extract_date}.anom > tmp.txt
                  export err=$?; err_chk
              done < $DATA/msl/plots/${abbr}_${extract_date}.anom

              grep -e ${time_beg} -A 4000 tmp.txt > $DATA/tmp/anom.tmp
              sed -i '1d' $DATA/tmp/anom.tmp
              cons_anom=$(tail -n 1 tmp.txt | awk '{print $2}')
              cut -f2 -d' ' $DATA/tmp/anom.tmp > $DATA/tmp/${abbr}.6manom
              line_number=$(wc -l < $DATA/tmp/${abbr}.6manom)
              line_filt=$((${time_number}-${line_number}))
              for i in $(seq 1 ${line_filt}); do
                  echo $cons_anom >> $DATA/tmp/${abbr}.6manom
              done

              paste $DATA/model/${abbr}.cwl $DATA/tmp/${abbr}.6manom | awk '{print $2 + $3}' > $DATA/tmp/${abbr}.acwl
              export err=$?; err_chk
              awk -f ${USHstofs2d}/transpose.awk $DATA/tmp/${abbr}.acwl >> ${station_number}_stations.csv
              export err=$?; err_chk
              rm -f tmp.txt $DATA/tmp/anom.tmp
          else
              awk '{print $2}' $DATA/model/${abbr}.cwl > $DATA/tmp/${abbr}.acwl
              export err=$?; err_chk
              awk -f ${USHstofs2d}/transpose.awk $DATA/tmp/${abbr}.acwl >> ${station_number}_stations.csv
              export err=$?; err_chk
          fi
      else
          awk '{print $2}' $DATA/model/${abbr}.cwl > $DATA/tmp/${abbr}.acwl
          export err=$?; err_chk
          awk -f ${USHstofs2d}/transpose.awk $DATA/tmp/${abbr}.acwl >> ${station_number}_stations.csv
          export err=$?; err_chk
      fi
  done < $DATA/data/${RUN}_station.ctl

# --------------------------------------------------------------------------- #
# 6.  Generate NetCDF file for anomaly-corrected water level

  for i in $(seq 1 ${time_number}); do
      awk -v i=${i} '{print $i","}' ${station_number}_stations.csv >> tmp2.txt
      export err=$?; err_chk
  done
  sed -i '$ s/,/;/g' tmp2.txt
  echo '}' >> tmp2.txt
  cat tmp.cdl tmp2.txt > cwl.fort.61.cdl
  ncgen -o acwl.fort.61.nc cwl.fort.61.cdl
  export err=$?; err_chk
  rm -f *.cdl *.csv tmp.txt tmp2.txt 2>/dev/null || true

# --------------------------------------------------------------------------- #
# 7.  Send files to $COMOUT

  if [ "${SENDCOM:-YES}" = YES ]; then
     echo "Copying anomaly-corrected fort.61.nc to $COMOUT/${RUN}.${cycle}.points.cwl.nc"
     cpfs acwl.fort.61.nc $COMOUT/${RUN}.${cycle}.points.cwl.nc

     if [ "${SENDDBN:-NO}" = YES ]; then
        $DBNROOT/bin/dbn_alert MODEL ${DBN_ALERT_TYPE:-STOFS_NETCDF} $job $COMOUT/${RUN}.${cycle}.points.cwl.nc
        $DBNROOT/bin/dbn_alert MODEL ${DBN_ALERT_TYPE:-STOFS_NETCDF} $job $COMOUT/${RUN}.${cycle}.points.cwl.noanomaly.nc 2>/dev/null || true
     fi
  fi

  msg="Completing ${fn_this_sh}"
  echo "$msg"
  postmsg "${jlogfile:-/dev/null}" "$msg"

# End of stofs_2d_glo_anomaly_water_level.sh script -------------------------- #
