#!/bin/bash

##############################################################################
#  Name: exnos_ofs_post.sh
#  Purpose: Post-processing ex-script for COMF SCHISM models.
#
#  Extracts raw SCHISM outputs from COMOUT tar archive (created by the
#  model job's archive_outputs step), runs the Python combining script
#  to create CO-OPS standard NetCDF products, and archives results.
#
#  Works for both standalone SCHISM (secofs) and UFS-Coastal (secofs_ufs).
#
#  Env vars required:
#    RUNTYPE  — "nowcast" or "forecast"
#    PREFIXNOS, cyc, PDY, FIXofs, COMOUT, DATA, USHnos
#
#  Called by: JNOS_OFS_POST (comf case)
##############################################################################

  seton='-xa'
  setoff='+xa'
  set $seton

  fn_this_script="exnos_ofs_post.sh"

# Fallback if postmsg not provided by prod_util module
  command -v postmsg >/dev/null 2>&1 || postmsg() { echo "[postmsg] $*"; }

  RUNTYPE=${RUNTYPE:-nowcast}

  msg="${fn_this_script} started (RUNTYPE=${RUNTYPE})"
  echo "$msg"
  postmsg "$msg"

  echo "module list in ${fn_this_script}"
  module list 2>&1 || true
  echo; echo

# =========================================================================
#  Setup
# =========================================================================

  mkdir -p $DATA
  cd $DATA

  cycle=t${cyc}z

  echo "========================================="
  echo "=== COMF SCHISM POST-PROCESSING ==="
  echo "========================================="
  echo "  OFS:       ${OFS:-not set}"
  echo "  PREFIXNOS: ${PREFIXNOS:-not set}"
  echo "  RUNTYPE:   ${RUNTYPE}"
  echo "  PDY:       ${PDY:-not set}"
  echo "  cyc:       ${cyc:-not set}"
  echo "  COMOUT:    ${COMOUT:-not set}"
  echo "  FIXofs:    ${FIXofs:-not set}"
  echo "========================================="

# =========================================================================
#  Step 1: Recover time variables from COMOUT (written by prep job)
# =========================================================================

  if [ -s "$COMOUT/time_hotstart.${cycle}" ]; then
      read time_hotstart < "$COMOUT/time_hotstart.${cycle}"
      export time_hotstart
      echo "  time_hotstart: $time_hotstart"
  else
      echo "WARNING: time_hotstart not found in COMOUT"
  fi

  if [ -s "$COMOUT/time_nowcastend.${cycle}" ]; then
      read time_nowcastend < "$COMOUT/time_nowcastend.${cycle}"
      export time_nowcastend
      echo "  time_nowcastend: $time_nowcastend"
  fi

  if [ -s "$COMOUT/time_forecastend.${cycle}" ]; then
      read time_forecastend < "$COMOUT/time_forecastend.${cycle}"
      export time_forecastend
      echo "  time_forecastend: $time_forecastend"
  fi

# =========================================================================
#  Step 2: Extract raw SCHISM outputs from COMOUT tar
# =========================================================================

  RAW_TAR="${COMOUT}/${RUN}.${cycle}.raw_outputs.${RUNTYPE}.tar"

  if [ ! -s "$RAW_TAR" ]; then
      msg="FATAL: Raw output tar not found: $RAW_TAR"
      echo "$msg"
      postmsg "$msg"
      export err=1; err_chk
  fi

  mkdir -p $DATA/outputs
  cd $DATA/outputs

  echo "Extracting raw SCHISM outputs from $RAW_TAR"
  tar xf "$RAW_TAR"
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: Failed to extract $RAW_TAR"
      echo "$msg"; postmsg "$msg"
      err_chk
  fi

  # Verify key files exist
  if [ ! -s "out2d_1.nc" ]; then
      msg="FATAL: out2d_1.nc not found after extraction"
      echo "$msg"; postmsg "$msg"
      export err=1; err_chk
  fi
  echo "  Extracted: $(ls out2d_*.nc 2>/dev/null | wc -l) out2d files"
  echo "  Extracted: $(ls staout_* 2>/dev/null | wc -l) staout files"

# =========================================================================
#  Step 3: Copy FIX files needed by the Python combiner
# =========================================================================

  for fixfile in ${PREFIXNOS}.nv.nc ${PREFIXNOS}.hgrid.gr3 \
                 ${PREFIXNOS}.station.lat.lon ${PREFIXNOS}.sigma.dat; do
      if [ -s "$FIXofs/$fixfile" ]; then
          cp -p "$FIXofs/$fixfile" $DATA/outputs/
          echo "  Copied FIX file: $fixfile"
      else
          msg="FATAL: Required FIX file not found: $FIXofs/$fixfile"
          echo "$msg"; postmsg "$msg"
          export err=1; err_chk
      fi
  done

# =========================================================================
#  Step 4: Create control file for Python combiner
# =========================================================================

  cd $DATA/outputs

  # Determine mode letter and timestart
  if [ "$RUNTYPE" = "nowcast" ]; then
      mode_letter="n"
      # Timestart for nowcast: time_hotstart (YYYYMMDDHH)
      timestart="${time_hotstart:-${PDY}${cyc}}"
  else
      mode_letter="f"
      # Timestart for forecast: time_nowcastend (YYYYMMDDHH)
      timestart="${time_nowcastend:-${PDY}${cyc}}"
  fi

  rm -f schism_standard_output.ctl
  echo "${PREFIXNOS}"   >> schism_standard_output.ctl
  echo "${cyc}"          >> schism_standard_output.ctl
  echo "${PDY}"          >> schism_standard_output.ctl
  echo "${mode_letter}"  >> schism_standard_output.ctl
  echo "${timestart}"    >> schism_standard_output.ctl

  echo "  Control file created:"
  cat schism_standard_output.ctl

# =========================================================================
#  Step 5: Run Python combiner
# =========================================================================

  echo ""
  echo "Running schism_combine_outputs.py..."

  python3 $USHnos/nosofs/schism_combine_outputs.py
  export err=$?
  if [ $err -ne 0 ]; then
      msg="FATAL: schism_combine_outputs.py failed (rc=$err)"
      echo "$msg"; postmsg "$msg"
      err_chk
  fi

# =========================================================================
#  Step 6: Archive products to COMOUT
# =========================================================================

  echo ""
  echo "Archiving post-processing products to COMOUT..."

  # Field files (per-timestep)
  field_count=0
  for f in ${PREFIXNOS}.${cycle}.${PDY}.fields.${mode_letter}*.nc; do
      if [ -s "$f" ]; then
          mv "$f" ${COMOUT}/
          field_count=$((field_count + 1))
      fi
  done
  echo "  Archived $field_count field files"

  # Station timeseries file
  if [ "$RUNTYPE" = "nowcast" ]; then
      sta_file="${PREFIXNOS}.${cycle}.${PDY}.stations.nowcast.nc"
  else
      sta_file="${PREFIXNOS}.${cycle}.${PDY}.stations.forecast.nc"
  fi
  # Handle both naming conventions (t{cyc}z and plain cycle)
  for pattern in "${PREFIXNOS}.t${cyc}z.${PDY}.stations.*.nc" \
                 "${PREFIXNOS}.${cycle}.${PDY}.stations.*.nc"; do
      for f in $pattern; do
          if [ -s "$f" ]; then
              mv "$f" ${COMOUT}/
              echo "  Archived station file: $f"
          fi
      done
  done

  # Renamed raw files (nowcast only: out2d_1.nowcast.nc, etc.)
  for f in ${PREFIXNOS}.t${cyc}z.${PDY}.out2d_*.nc \
           ${PREFIXNOS}.t${cyc}z.${PDY}.zCoordinates_*.nc \
           ${PREFIXNOS}.t${cyc}z.${PDY}.temperature_*.nc \
           ${PREFIXNOS}.t${cyc}z.${PDY}.salinity_*.nc \
           ${PREFIXNOS}.t${cyc}z.${PDY}.horizontalVelX_*.nc \
           ${PREFIXNOS}.t${cyc}z.${PDY}.horizontalVelY_*.nc; do
      if [ -s "$f" ]; then
          mv "$f" ${COMOUT}/
      fi
  done

  # Renamed staout files
  for f in ${PREFIXNOS}.t${cyc}z.${PDY}.*.staout_*; do
      if [ -s "$f" ]; then
          mv "$f" ${COMOUT}/
      fi
  done

  # Model log (mirror.out → named log)
  if [ -s "mirror.out" ]; then
      if [ "$RUNTYPE" = "nowcast" ]; then
          log_name="${PREFIXNOS}.${cycle}.${PDY}.nowcast.log"
      else
          log_name="${PREFIXNOS}.${cycle}.${PDY}.forecast.log"
      fi
      cp -p mirror.out ${COMOUT}/${log_name}
      echo "  Archived model log: ${log_name}"
  fi

# =========================================================================
#  Step 7: DBN alerts (if enabled)
# =========================================================================

  if [ "${SENDDBN:-NO}" = "YES" ]; then
      echo "Sending DBN alerts..."
      DBN_ALERT_TYPE_NETCDF=${DBN_ALERT_TYPE_NETCDF:-NOS_OFS_NETCDF}
      for f in ${COMOUT}/${PREFIXNOS}.t${cyc}z.${PDY}.fields.${mode_letter}*.nc; do
          [ -s "$f" ] && $DBNROOT/bin/dbn_alert MODEL $DBN_ALERT_TYPE_NETCDF $job $f
      done
      for f in ${COMOUT}/${PREFIXNOS}.t${cyc}z.${PDY}.stations.*.nc; do
          [ -s "$f" ] && $DBNROOT/bin/dbn_alert MODEL $DBN_ALERT_TYPE_NETCDF $job $f
      done
  fi

# =========================================================================
#  Done
# =========================================================================

  echo ""
  echo "POST_${RUNTYPE^^} DONE 100" >> ${cormslogfile:-/dev/null} 2>/dev/null || true

  msg="Finished ${fn_this_script} (${RUNTYPE}) SUCCESSFULLY"
  postmsg "$msg"

  echo
  echo "$msg"
  echo "Finished at $(date)"
  echo
