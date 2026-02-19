#!/bin/bash

############################################################################
#  Name: stofs_3d_atl_create_surface_forcing_rrfs.sh                       #
#  This script reads NCEP/RRFS data to create RRFS-based surface forcing   #
#  files for STOFS-3D-ATL/SECOFS ensemble members.                         #
#                                                                          #
#  RRFS (Rapid Refresh Forecast System) is a 3km convection-allowing       #
#  model over North America. It runs hourly, but only the synoptic         #
#  cycles (00/06/12/18Z) provide extended 84-hour forecasts; all other     #
#  cycles provide only 18-hour forecasts.                                  #
#                                                                          #
#  Output: ${RUN}.${cycle}.rrfs.{air,prc,rad}.nc                           #
#                                                                          #
#  Key differences from GFS/GEFS:                                          #
#    - 3km native resolution (files ~6GB each, MUST subset to domain)      #
#    - Hourly temporal resolution (same as GFS, unlike 3-hourly GEFS)      #
#    - Has SPFH directly (no RH->SPFH conversion needed, unlike GEFS)     #
#    - Has MSLET instead of PRMSL (requires ncrename to PRMSL for SCHISM) #
#    - Has PRATE directly (no APCP->PRATE conversion needed)              #
#    - Maximum forecast length: 84h (00/06/12/18Z cycles only)            #
#    - Coverage limitation: 84h max means GFS backfill needed for STOFS   #
#      108h forecasts (last 24h). SECOFS 48h forecasts fully covered.     #
#                                                                          #
#  Environment variables:                                                  #
#    COMINrrfs        - RRFS input data root directory                     #
#    RRFS_RESOLUTION  - Grid resolution label (default: "3km")             #
#    DATA_prep_rrfs   - Working directory for this script                  #
#    PDY, cyc         - Current cycle date and hour                        #
#    LONMIN/LONMAX/LATMIN/LATMAX - Domain bounds (STOFS convention)        #
#    MINLON/MAXLON/MINLAT/MAXLAT - Domain bounds (COMF convention)        #
#    PDYHH_FCAST_BEGIN, PDYHH_NCAST_BEGIN - Nowcast/forecast timestamps    #
#                                                                          #
#  Data path on WCOSS2:                                                    #
#    /lfs/h1/ops/para/com/rrfs/v1.0/rrfs.YYYYMMDD/HH/                     #
#        rrfs.tHHz.prslev.3km.fFFF.na.grib2                               #
#                                                                          #
#  Adapted from stofs_3d_atl_create_surface_forcing_gefs.sh                #
#                                                        February, 2026    #
############################################################################


# ---------------------------> Begin ...
set -x

echo 'stofs_3d_atl_create_surface_forcing_rrfs.sh started'

# ---------------------------> Load YAML Configuration (with fallback to defaults)
# Try to load from YAML if OFS_CONFIG is set and yaml_to_env.py is available
if [ -n "${OFS_CONFIG}" ] && [ -f "${OFS_CONFIG}" ]; then
    _yaml_to_env="${USHnos:-${HOMEnos}/ush}/python/nos_ofs/utils/yaml_to_env.py"
    if [ -f "${_yaml_to_env}" ]; then
        echo "Loading RRFS config from YAML: ${OFS_CONFIG}"
        _yaml_exports=$(python3 "${_yaml_to_env}" "${OFS_CONFIG}" --framework stofs 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "${_yaml_exports}" ]; then
            eval "${_yaml_exports}"
            echo "YAML config loaded successfully"
        fi
    fi
fi


# ---------------------------> RRFS Configuration
RRFS_RESOLUTION=${RRFS_RESOLUTION:-3km}

echo "RRFS resolution: ${RRFS_RESOLUTION}"


# ---------------------------> SAFETY CHECK: Validate required environment variables
# This prevents catastrophic deletion if variables are not set
if [ -z "${DATA_prep_rrfs}" ]; then
    echo "FATAL ERROR: DATA_prep_rrfs is not set. Exiting to prevent accidental file deletion."
    echo "Please set DATA_prep_rrfs to a valid working directory path before running this script."
    exit 1
fi

# Additional safety: ensure path is not root or system directory
case "${DATA_prep_rrfs}" in
    /|/bin|/boot|/dev|/etc|/home|/lib*|/opt|/proc|/root|/run|/sbin|/sys|/tmp|/usr|/var|/mnt|/media)
        echo "FATAL ERROR: DATA_prep_rrfs='${DATA_prep_rrfs}' appears to be a system directory."
        echo "Refusing to delete contents of system directories. Exiting."
        exit 1
        ;;
esac

# ---------------------------> directory/file names

  dir_wk=${DATA_prep_rrfs}/

  mkdir -p $dir_wk
  cd $dir_wk || { echo "ERROR: Cannot cd to $dir_wk"; exit 1; }
  rm -fr $dir_wk/*

  mkdir -p ${COMOUTrerun}


  pgmout=pgmout_rrfs.$$


# ---------------------------> Global Variables
  # NCO update script: RRFS-specific version that documents the MSLET->PRMSL rename.
  # After ncrename in the processing loop, variable names match the GFS convention,
  # so the NCO script is structurally identical to the GFS version.
  fn_nco_update_time_varName=${FIXstofs3d}/stofs_3d_atl_rrfs_input_nco_update_var.nco

  # Fallback: if RRFS-specific NCO script does not exist, use the GFS one (same variable names
  # after our ncrename step converts MSLET_meansealevel -> PRMSL_meansealevel)
  if [ ! -f "${fn_nco_update_time_varName}" ]; then
      fn_nco_update_time_varName=${FIXstofs3d}/stofs_3d_atl_gfs_input_nco_update_var.nco
      echo "INFO: Using GFS NCO update script as fallback: ${fn_nco_update_time_varName}"
  fi

  if [ ! -f "${fn_nco_update_time_varName}" ]; then
      fn_nco_update_time_varName=${FIXstofs3d}/stofs_3d_atl_nam_input_nco_update_var.nco
      echo "INFO: Using NAM NCO update script as second fallback: ${fn_nco_update_time_varName}"
  fi

  fn_rrfs_rad_schism=sflux_rad_1.0001.nc
  fn_rrfs_rad_std=${RUN}.${cycle}.rrfs.rad.nc

  fn_rrfs_prc_schism=sflux_prc_1.0001.nc
  fn_rrfs_prc_std=${RUN}.${cycle}.rrfs.prc.nc

  fn_rrfs_air_schism=sflux_air_1.0001.nc
  fn_rrfs_air_std=${RUN}.${cycle}.rrfs.air.nc


# ---------------> Region of interest
# RRFS files are ~6GB at native 3km resolution -- subsetting is CRITICAL for performance.
# Support both STOFS convention (LONMIN/LONMAX) and COMF/nosofs convention (MINLON/MAXLON).
# STOFS takes priority if both are set.
    LONMIN=${LONMIN:-${MINLON:--98.5035}}
    LONMAX=${LONMAX:-${MAXLON:--52.4867}}
    LATMIN=${LATMIN:-${MINLAT:-7.347}}
    LATMAX=${LATMAX:-${MAXLAT:-52.5904}}
    echo "Domain bounds: LONMIN=$LONMIN LONMAX=$LONMAX LATMIN=$LATMIN LATMAX=$LATMAX"



# ---------------> Dates
   yyyymmdd_today=${PDYHH_FCAST_BEGIN:0:8}
   yyyymmdd_prev=${PDYHH_NCAST_BEGIN:0:8}

   echo yyyymmdd_today=$yyyymmdd_today
   echo yyyymmdd_prev=$yyyymmdd_prev

    iyr=`echo ${yyyymmdd_prev} | cut -c1-4`
    imon=`echo ${yyyymmdd_prev} | cut  -c5-6`
    iday=`echo ${yyyymmdd_prev} | cut -c7-8`


# --------------------------> Create file lists
# RRFS file naming: rrfs.tHHz.prslev.3km.fFFF.na.grib2
#
# RRFS cycle structure:
#   - 00Z, 06Z, 12Z, 18Z: extended runs with forecasts out to f084 (84 hours)
#   - All other hours: short runs, f001-f018 only
#
# Strategy: Cycle-aware file collection
#   Each file's ACTUAL valid time is computed from its cycle date + hour + forecast hour.
#   This avoids time ordering issues when stitching files from multiple cycles.
#
#   For 00Z: prev_day 00Z extended (f001-f024) + today 00Z extended (f001-f084)
#   For 06Z: prev_day 06Z extended (f001-f024) + today 06Z extended (f001-f084)
#   For 12Z: prev_day 12Z f006 + short cycles + today 12Z extended (f001-f084)
#   For 18Z: prev_day 18Z extended (f001-f024) + today 18Z extended (f001-f084)
#
# Each file entry is stored as "VALID_HOUR|FILEPATH" so we can sort by valid time.

    # Compute day offset between yyyymmdd_prev and yyyymmdd_today (in days)
    # Used for valid-time calculation: valid_hour = day_offset*24 + cycle_hour + forecast_hour
    _today_day_off=$(( ($(date -d "${yyyymmdd_today}" +%s) - $(date -d "${yyyymmdd_prev}" +%s)) / 86400 ))
    echo "Day offset (prev→today): ${_today_day_off}"

    # Helper: add a file with its valid time to the collection
    # Usage: _add_rrfs_file YYYYMMDD CYC_HOUR FCAST_HOUR
    # Stores: "VALID_HOURS_FROM_BASE|FILEPATH" in _RRFS_FILE_LIST
    # Valid hour = (file_date - base_date)*24 + cycle_hour + forecast_hour
    _RRFS_FILE_LIST=()
    _add_rrfs_file() {
        local _fdate=$1 _fcyc=$2 _fhr=$3
        local _fstr=$(printf "%03d" ${_fhr})
        local _cstr=$(printf "%02d" ${_fcyc})
        local _fpath=${COMINrrfs}/rrfs.${_fdate}/${_cstr}/rrfs.t${_cstr}z.prslev.${RRFS_RESOLUTION}.f${_fstr}.na.grib2
        # Valid time in hours from base (yyyymmdd_prev 00Z)
        local _day_off=0
        [ "${_fdate}" = "${yyyymmdd_today}" ] && _day_off=${_today_day_off}
        local _fepoch=$(( _day_off * 24 + 10#${_fcyc} + _fhr ))
        _RRFS_FILE_LIST+=("${_fepoch}|${_fpath}")
    }

    echo "Cycle hour: ${cyc:-00}"
    _cyc_hr=$((10#${cyc:-0}))

    # ------ Build file list based on cycle ------
    # Strategy: use the latest available extended cycle for each time window.
    # Extended cycles (00/06/12/18Z) go to f084; we stitch 2-3 of them.

    if [ ${_cyc_hr} -eq 0 ] || [ ${_cyc_hr} -eq 6 ]; then
        # 00Z or 06Z cycle: nowcast coverage from prev extended cycles

        # Previous day's matching extended cycle for nowcast (f001-f024)
        _prev_ext_cyc=${_cyc_hr}
        for _fhr in $(seq 1 24); do
            _add_rrfs_file ${yyyymmdd_prev} ${_prev_ext_cyc} ${_fhr}
        done

        # Today's matching extended cycle for forecast (f001-f084)
        for _fhr in $(seq 1 84); do
            _add_rrfs_file ${yyyymmdd_today} ${_cyc_hr} ${_fhr}
        done

    elif [ ${_cyc_hr} -eq 12 ]; then
        # 12Z cycle (STOFS-3D-ATL): nowcast from short cycles, forecast from 12Z extended

        # Previous day 06Z f006 (1 file)
        _add_rrfs_file ${yyyymmdd_prev} 6 6
        # Previous day 12Z f001-f006
        for _fhr in $(seq 1 6); do
            _add_rrfs_file ${yyyymmdd_prev} 12 ${_fhr}
        done
        # Previous day 18Z f001-f006
        for _fhr in $(seq 1 6); do
            _add_rrfs_file ${yyyymmdd_prev} 18 ${_fhr}
        done
        # Today 00Z f001-f006
        for _fhr in $(seq 1 6); do
            _add_rrfs_file ${yyyymmdd_today} 0 ${_fhr}
        done
        # Today 06Z f001-f006
        for _fhr in $(seq 1 6); do
            _add_rrfs_file ${yyyymmdd_today} 6 ${_fhr}
        done
        # Today 12Z extended: f001-f084
        for _fhr in $(seq 1 84); do
            _add_rrfs_file ${yyyymmdd_today} 12 ${_fhr}
        done

    elif [ ${_cyc_hr} -eq 18 ]; then
        # 18Z cycle: nowcast from earlier cycles, forecast from 18Z extended
        _add_rrfs_file ${yyyymmdd_prev} 12 6
        for _fhr in $(seq 1 6); do
            _add_rrfs_file ${yyyymmdd_prev} 18 ${_fhr}
        done
        for _fhr in $(seq 1 6); do
            _add_rrfs_file ${yyyymmdd_today} 0 ${_fhr}
        done
        for _fhr in $(seq 1 6); do
            _add_rrfs_file ${yyyymmdd_today} 6 ${_fhr}
        done
        for _fhr in $(seq 1 6); do
            _add_rrfs_file ${yyyymmdd_today} 12 ${_fhr}
        done
        # Today 18Z extended: f001-f084
        for _fhr in $(seq 1 84); do
            _add_rrfs_file ${yyyymmdd_today} 18 ${_fhr}
        done

    else
        echo "WARNING: Non-standard cycle hour ${_cyc_hr}, using 00Z strategy"
        for _fhr in $(seq 1 24); do
            _add_rrfs_file ${yyyymmdd_prev} 0 ${_fhr}
        done
        for _fhr in $(seq 1 84); do
            _add_rrfs_file ${yyyymmdd_today} 0 ${_fhr}
        done
    fi

    echo "Total candidate RRFS files: ${#_RRFS_FILE_LIST[@]}"

    # ------ Backup list: previous day's latest extended cycle ------
    # Fall back to previous day's cycle that matches or precedes ours
    _RRFS_BACKUP_LIST=()
    _bk_cyc=${_cyc_hr}
    _bk_cstr=$(printf "%02d" ${_bk_cyc})
    for _fhr in $(seq 1 84); do
        _bk_fstr=$(printf "%03d" ${_fhr})
        _fpath=${COMINrrfs}/rrfs.${yyyymmdd_prev}/${_bk_cstr}/rrfs.t${_bk_cstr}z.prslev.${RRFS_RESOLUTION}.f${_bk_fstr}.na.grib2
        # day_offset = 0 since all backup files are from yyyymmdd_prev
        _fepoch=$(( _bk_cyc + _fhr ))
        _RRFS_BACKUP_LIST+=("${_fepoch}|${_fpath}")
    done

    echo; echo "Primary list (first 10):"
    for _entry in "${_RRFS_FILE_LIST[@]:0:10}"; do echo "  $_entry"; done
    echo "  ..."

    echo; echo "Backup list (first 10):"
    for _entry in "${_RRFS_BACKUP_LIST[@]:0:10}"; do echo "  $_entry"; done
    echo "  ..."


# ------------------------> Check file sizes and filter
# RRFS native 3km files are ~6GB each. Set minimum threshold at 500 MB.
FILESIZE=500000000

_filter_rrfs_list() {
    local -n _input_list=$1
    local -n _output_list=$2
    _output_list=()
    for _entry in "${_input_list[@]}"; do
        local _vhour=${_entry%%|*}
        local _fpath=${_entry##*|}
        if [ -s "${_fpath}" ]; then
            local _fsz=$(wc -c < "${_fpath}")
            if [ ${_fsz} -ge ${FILESIZE} ]; then
                _output_list+=("${_entry}")
                echo "OK [vh=${_vhour}h]: ${_fpath} (${_fsz} bytes)"
            else
                echo "SMALL [vh=${_vhour}h]: ${_fpath} (${_fsz} < ${FILESIZE})"
            fi
        else
            echo "MISS [vh=${_vhour}h]: ${_fpath}"
        fi
    done
}

echo; echo "=== Checking primary file list ==="
_RRFS_PRIMARY_VALID=()
_filter_rrfs_list _RRFS_FILE_LIST _RRFS_PRIMARY_VALID

echo; echo "=== Checking backup file list ==="
_RRFS_BACKUP_VALID=()
_filter_rrfs_list _RRFS_BACKUP_LIST _RRFS_BACKUP_VALID

N_primary=${#_RRFS_PRIMARY_VALID[@]}
N_backup=${#_RRFS_BACKUP_VALID[@]}
echo; echo "Primary valid: ${N_primary} files"
echo "Backup valid:  ${N_backup} files"

# Use primary if sufficient (>30), otherwise try backup, otherwise combine
N_dim_cr_min_cntList=30
if [ ${N_primary} -ge ${N_dim_cr_min_cntList} ]; then
    LIST_fn_final_qa_sz=("${_RRFS_PRIMARY_VALID[@]}")
    echo "Using primary list (${N_primary} files)"
elif [ ${N_backup} -ge ${N_dim_cr_min_cntList} ]; then
    LIST_fn_final_qa_sz=("${_RRFS_BACKUP_VALID[@]}")
    echo "Using backup list (${N_backup} files)"
elif [ ${N_primary} -gt 0 ]; then
    # Combine: primary + any backup files with valid hours beyond primary's range
    LIST_fn_final_qa_sz=("${_RRFS_PRIMARY_VALID[@]}" "${_RRFS_BACKUP_VALID[@]}")
    echo "Using combined list (${N_primary} + ${N_backup} files)"
else
    LIST_fn_final_qa_sz=()
    echo "WARNING: No valid RRFS files found"
fi

# Sort by valid hour and deduplicate (keep first occurrence for each valid hour)
if [ ${#LIST_fn_final_qa_sz[@]} -gt 0 ]; then
    _SORTED_UNIQUE=()
    _seen_hours=""
    while IFS= read -r _entry; do
        _vh=${_entry%%|*}
        if [[ ! " ${_seen_hours} " =~ " ${_vh} " ]]; then
            _SORTED_UNIQUE+=("${_entry}")
            _seen_hours="${_seen_hours} ${_vh}"
        fi
    done < <(printf '%s\n' "${LIST_fn_final_qa_sz[@]}" | sort -t'|' -k1 -n)
    LIST_fn_final_qa_sz=("${_SORTED_UNIQUE[@]}")
    echo "After sort+dedup: ${#LIST_fn_final_qa_sz[@]} files"
    echo "Valid hour range: ${LIST_fn_final_qa_sz[0]%%|*}h to ${LIST_fn_final_qa_sz[-1]%%|*}h"
fi


# ---------------------> Process data
# RRFS variables to extract via wgrib2:
#   - TMP:2 m above ground        (surface temperature)
#   - SPFH:2 m above ground       (specific humidity -- RRFS has SPFH directly)
#   - UGRD:10 m above ground      (10m u-wind)
#   - VGRD:10 m above ground      (10m v-wind)
#   - MSLET:mean sea level         (mean sea level pressure, ETA reduction)
#     *** KEY DIFFERENCE: RRFS uses MSLET, not PRMSL ***
#     After wgrib2 -netcdf: becomes MSLET_meansealevel
#     We ncrename it to PRMSL_meansealevel for compatibility with the NCO script
#   - PRATE:surface:1 hour fcst   (precipitation rate, instantaneous)
#   - DSWRF:surface                (downward shortwave radiation)
#   - DLWRF:surface                (downward longwave radiation)
#
# Variables NOT extracted (not needed for SCHISM sflux, but listed for reference):
#   - ALBDO:surface, USWRF:surface, ULWRF:surface (available but unused)

 list_var_oi='TMP:2 m above|SPFH:2 m above|UGRD:10 m above|VGRD:10 m above|MSLET|PRATE:surface:.*1 hour fcst|DSWRF:surface|DLWRF:surface'

 rm -f *_voi*.
 rm -f *_sflux.nc

# Minimum number of time steps for a valid merged file
N_dim_cr_min_cntList=30
N_LIST_fn_final_qa_sz=${#LIST_fn_final_qa_sz[@]}

fn_merged_sflux=rrfs_merge_v1.nc

echo; echo "N_LIST_fn_final_qa_sz = ${N_LIST_fn_final_qa_sz}"; echo

if [[ ${N_LIST_fn_final_qa_sz} -gt ${N_dim_cr_min_cntList} ]]; then

  echo "N_LIST_fn_final_qa_sz = ${N_LIST_fn_final_qa_sz}"
  echo

  # Process each file using its ACTUAL valid hour from the sorted list.
  # Each entry is "VALID_HOUR|FILEPATH" — the valid hour is hours from base
  # (yyyymmdd_prev 00Z), which maps directly to the SCHISM time variable.
  cnt=0
  for _entry in "${LIST_fn_final_qa_sz[@]}"
  do
   # Parse valid hour and filepath from the entry
   _valid_hour=${_entry%%|*}
   fn_rrfs_k=${_entry##*|}

   str_xxx_cnt=$(printf "%03d" $cnt)
   echo "Processing(${str_xxx_cnt}, vh=${_valid_hour}h): ${fn_rrfs_k}"

   # Step 1: Extract variables of interest from GRIB2
   fn_varOI=RRFS_voi_${str_xxx_cnt}.grb2
      $WGRIB2  -s  $fn_rrfs_k  | egrep "$list_var_oi" | $WGRIB2  -i  $fn_rrfs_k  -grib  $fn_varOI  >> $pgmout 2> errfile
      export err=$?;

   # Step 2: Subset to region of interest (CRITICAL -- RRFS files are ~6GB at native 3km)
   fn_roi=iRRFS_voi_rio_${str_xxx_cnt}.grb2
      $WGRIB2  $fn_varOI  -small_grib ${LONMIN}:${LONMAX} ${LATMIN}:${LATMAX} $fn_roi   >> $pgmout 2> errfile
      export err=$?;

   # Step 3: Convert GRIB2 to NetCDF
   # RRFS is Lambert Conformal — wgrib2 -netcdf produces y,x dimensions
   # (not latitude,longitude like GFS/GEFS). Remove y,x variables with ncks
   # so ncap2 NCO script can reference the y,x dimensions cleanly.
   fn_0_rnVar_with_xy=RRFS_voi_rio_0rename_with_xy_${str_xxx_cnt}.nc
      $WGRIB2  $fn_roi -netcdf $fn_0_rnVar_with_xy  >> $pgmout 2> errfile
      export err=$?;

   fn_0_rnVar_raw=RRFS_voi_rio_0rename_raw_${str_xxx_cnt}.nc
      ncks -CO -x -v y,x $fn_0_rnVar_with_xy $fn_0_rnVar_raw  >> $pgmout 2> errfile
      export err=$?;

   # Step 4: Rename MSLET -> PRMSL for SCHISM compatibility
   fn_0_rnVar=RRFS_voi_rio_0rename_${str_xxx_cnt}.nc
      cp ${fn_0_rnVar_raw} ${fn_0_rnVar}
      ncrename -O -v MSLET_meansealevel,PRMSL_meansealevel ${fn_0_rnVar}  >> $pgmout 2> errfile
      export err=$?;

      if [ $err -ne 0 ]; then
          echo "WARNING: ncrename MSLET->PRMSL failed for ${str_xxx_cnt}, checking if PRMSL already exists"
          ncdump -h ${fn_0_rnVar_raw} | grep -q "PRMSL_meansealevel"
          if [ $? -eq 0 ]; then
              echo "INFO: PRMSL_meansealevel already present, using as-is"
              cp ${fn_0_rnVar_raw} ${fn_0_rnVar}
          else
              echo "ERROR: Neither MSLET nor PRMSL found in ${fn_rrfs_k}"
              echo "ERROR: Skipping file ${str_xxx_cnt}"  >> $pgmout
              rm -f ${fn_0_rnVar}
              cnt=$((cnt + 1))
              continue
          fi
      fi

   # Step 5: Check for missing variables and fill with zeros if absent.
   # Some RRFS forecast hours encode PRATE differently (e.g., avg vs instantaneous),
   # so the wgrib2 extraction pattern may not match at all hours.
   if ! ncdump -h ${fn_0_rnVar} 2>/dev/null | grep -q "PRATE_surface"; then
       echo "WARNING: PRATE_surface missing in ${str_xxx_cnt}, filling with zero"
       ncap2 -Oh -s 'PRATE_surface[$time,$y,$x]=0.0f' ${fn_0_rnVar} ${fn_0_rnVar}
   fi

   # Step 6: Update time variable using ACTUAL valid hour (not sequential counter)
   # _valid_hour is hours from base (yyyymmdd_prev 00Z). The NCO script converts
   # tin (hours) to fractional days: time[time] = float(tin/24.)
   fn_out=RRFS_sflux_no_${str_xxx_cnt}.nc

   str_time=`echo '"'days since $iyr-$imon-$iday 00:00:00'"'`

     ncap2 -Oh -s "tin=${_valid_hour}"  -s "time@units=$str_time"  -s "time@base_date ={ $iyr, $imon, $iday, 0}" -S $fn_nco_update_time_varName -v ${fn_0_rnVar}  $fn_out   >> $pgmout 2> errfile
     export err=$?;

   cnt=$((cnt + 1))
 done

# Merge all time steps into a single file
 rm -f ${fn_merged_sflux};

 echo fn_merged_sflux= $fn_merged_sflux

    rm -f $fn_merged_sflux
    find . -size 0  -exec rm -f {} \;

    list_RRFS_sflux_no=`ls RRFS_sflux_no_*.nc 2>/dev/null`
    if [ ! -z "$list_RRFS_sflux_no" ]; then
      ncrcat -O  RRFS_sflux_no_*.nc  $fn_merged_sflux
    fi

fi   # if [[ ${N_LIST_fn_final_qa_sz} -gt ${N_dim_cr_min_cntList} ]]



# ---------------------------------> QC & archive
# RRFS hourly QC thresholds:
#   - N_dim_cr_min: minimum number of time steps (70 = ~2.9 days)
#   - N_dim_cr_max: expected full time steps (100 = ~4.2 days including nowcast)
#   - File size: RRFS subsetted merged sflux depends on domain; ~2 GB for STOFS-ATL
#   - time_end_step: end time in fractional days from reference date
#
# For hourly data: ~109 files total from primary list
# 84h forecast / 24 = 3.5 days of forecast from today 12Z
# Plus ~24h nowcast coverage = ~4.5 days total
# End time: about 8.0 fractional days from reference date (yyyymmdd_prev 00Z)
# For STOFS-3D-ATL which needs 10.0 days, GFS must fill the gap beyond 84h.
N_dim_cr_min=70
N_dim_cr_max=100
list_fn_sz_cr=(2000000)
list_end_time_step=(10.0)
list_offset_time=(1.0)



# RRFS radiation variables (DSWRF/DLWRF) have inconsistent wgrib2 -netcdf
# naming (averaged fields get suffixes). Archive only air and prc.
# Radiation must come from a secondary source (GFS/HRRR sflux_*_2).
fn_ori=${fn_merged_sflux}

fn_std=${fn_rrfs_air_std}
rm -f ${fn_std}

k=0
   if [[ -s ${fn_ori} ]]; then
       sz_k=$((`wc -c ${fn_ori} | awk '{print $1}'`))

       if [[ ${sz_k} -gt ${list_fn_sz_cr[$k]} ]]; then
            dim_k=`ncdump -h  ${fn_ori}  | grep "time = UNLIMITED" | awk -F'(' '{print $2}' | awk -F' ' '{print $1}'`;
       else
            sz_k=$((0))
            dim_k=$((0))
       fi
   else
            sz_k=$((0))
            dim_k=$((0))
   fi
   echo "dim=${dim_k}, sz_k-bytes=${sz_k}, sz_cr=${list_fn_sz_cr[$k]}"


   time_end_step=${list_end_time_step[$k]}
   time_offset=${list_offset_time[$k]}

   if [[ ${dim_k} -ge ${N_dim_cr_max} ]]; then
      ln -sf ${fn_ori} ${fn_std}_for_noting

      ncap2 -s "time(0)=float(0.499999);time(-1)=float(${time_end_step})" ${fn_ori} -O ${fn_std}

      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_rrfs_air_std}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_rrfs_prc_std}
      echo "done: method - non-backup (RRFS, air+prc only, no rad)"

   elif [[ ${dim_k} -ge ${N_dim_cr_min} ]]; then
      ncap2 -s "time(0)=float(0.499999);time(-1)=${time_end_step}" ${fn_ori} -O ${fn_std}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_rrfs_air_std}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_rrfs_prc_std}
      echo "done: method - backup 1 (RRFS, air+prc only, no rad)"

   else
      if [[ -f  ${COMOUT_PREV}/rerun/${fn_std} ]]; then

        fn_prev=prev_${fn_std}
        cpreq -pf ${COMOUT_PREV}/rerun/${fn_std} ${fn_prev}

        ncap2 -s "time(-1)=float(${time_end_step})" ${fn_prev} -O ${fn_std}

         cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_rrfs_air_std}
         cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_rrfs_prc_std}
         echo "done: method - backup 2 (RRFS, from previous cycle)"

      else
         msg="Warning: failed of (non-backup, backup1, backup 2) \n ${fn_rrfs_air_std} Not created for RRFS"
         echo -e ${msg}
      fi

   fi # if [[ ${dim_k} -ge ${N_dim_cr_max} ]]



echo
echo "The script stofs_3d_atl_create_surface_forcing_rrfs.sh completed"
echo
