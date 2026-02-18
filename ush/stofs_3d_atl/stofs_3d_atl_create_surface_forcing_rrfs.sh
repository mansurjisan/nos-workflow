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
#   - All other hours (01-05, 07-11, 13-17, 19-23): short runs, f001-f018 only
#
# Strategy for assembling nowcast + forecast coverage (~5.5 days = 132 hours):
#
# For a 12Z cycle (STOFS-3D-ATL standard):
#   Nowcast window (previous day ~12Z through today 12Z = ~24 hours):
#     - Previous day 06Z cycle: use f006 to get coverage at ~12Z yesterday
#     - Previous day 12Z cycle: f001-f006 (covers 13Z-18Z yesterday)
#     - Previous day 18Z cycle: f001-f006 (covers 19Z-00Z)
#     - Today 00Z cycle: f001-f006 (covers 01Z-06Z today)
#     - Today 06Z cycle: f001-f006 (covers 07Z-12Z today)
#   Forecast window (today 12Z + 84 hours = 3.5 days):
#     - Today 12Z cycle: f001-f084 (covers 13Z today through 00Z in 3.5 days)
#
# Total coverage: ~24h nowcast + 84h forecast = ~108 hours = 4.5 days
#
# LIMITATION: RRFS maximum forecast is 84h. For STOFS-3D-ATL 108h forecasts,
# the last ~24h must be filled by GFS (handled externally by the calling prep script).
# For SECOFS 48h forecasts from 00Z, a single 00Z 84h run provides full coverage.

# ------ Primary list (using today's cycles) ------

# Previous day 06Z cycle: f006 (1 file, providing coverage at ~12Z yesterday)
    list_fn_yest_t06z_1=''
    fn_k=${COMINrrfs}/rrfs.${yyyymmdd_prev}/06/rrfs.t06z.prslev.${RRFS_RESOLUTION}.f006.na.grib2
    if [ -f "${fn_k}" ]; then
        list_fn_yest_t06z_1="${fn_k}"
    fi

# Previous day 12Z cycle: f001-f006 (hourly, 6 files)
    list_fn_yest_t12z=''
    for str_hhh in $(seq -f "%03g" 1 1 6); do
        fn_k=${COMINrrfs}/rrfs.${yyyymmdd_prev}/12/rrfs.t12z.prslev.${RRFS_RESOLUTION}.f${str_hhh}.na.grib2
        list_fn_yest_t12z="${list_fn_yest_t12z} ${fn_k}"
    done

# Previous day 18Z cycle: f001-f006 (hourly, 6 files)
    list_fn_yest_t18z=''
    for str_hhh in $(seq -f "%03g" 1 1 6); do
        fn_k=${COMINrrfs}/rrfs.${yyyymmdd_prev}/18/rrfs.t18z.prslev.${RRFS_RESOLUTION}.f${str_hhh}.na.grib2
        list_fn_yest_t18z="${list_fn_yest_t18z} ${fn_k}"
    done

# Today 00Z cycle: f001-f006 (hourly, 6 files)
    list_fn_today_t00z=''
    for str_hhh in $(seq -f "%03g" 1 1 6); do
        fn_k=${COMINrrfs}/rrfs.${yyyymmdd_today}/00/rrfs.t00z.prslev.${RRFS_RESOLUTION}.f${str_hhh}.na.grib2
        list_fn_today_t00z="${list_fn_today_t00z} ${fn_k}"
    done

# Today 06Z cycle: f001-f006 (hourly, 6 files)
    list_fn_today_t06z=''
    for str_hhh in $(seq -f "%03g" 1 1 6); do
        fn_k=${COMINrrfs}/rrfs.${yyyymmdd_today}/06/rrfs.t06z.prslev.${RRFS_RESOLUTION}.f${str_hhh}.na.grib2
        list_fn_today_t06z="${list_fn_today_t06z} ${fn_k}"
    done

# Today 12Z cycle: f001-f084 (hourly, 84 files -- main forecast period)
    list_fn_today_t12z=''
    for str_hhh in $(seq -f "%03g" 1 1 84); do
        fn_k=${COMINrrfs}/rrfs.${yyyymmdd_today}/12/rrfs.t12z.prslev.${RRFS_RESOLUTION}.f${str_hhh}.na.grib2
        list_fn_today_t12z="${list_fn_today_t12z} ${fn_k}"
    done

    # Concatenate primary list
    # Total: 1 + 6 + 6 + 6 + 6 + 84 = 109 files (hourly, covering ~109 hours)
    LIST_fn_all_1="${list_fn_yest_t06z_1} "
    LIST_fn_all_1+="${list_fn_yest_t12z} "
    LIST_fn_all_1+="${list_fn_yest_t18z} "
    LIST_fn_all_1+="${list_fn_today_t00z} "
    LIST_fn_all_1+="${list_fn_today_t06z} "
    LIST_fn_all_1+="${list_fn_today_t12z}"


# ------ Backup list (previous day's 12Z extended forecast) ------
# If today's cycles are not yet available, fall back to yesterday's 12Z cycle
# which provides up to 84h of forecast data.

    list_fn_bk_1=''
    fn_k=${COMINrrfs}/rrfs.${yyyymmdd_prev}/06/rrfs.t06z.prslev.${RRFS_RESOLUTION}.f006.na.grib2
    if [ -f "${fn_k}" ]; then
        list_fn_bk_1="${fn_k}"
    fi

    # Previous day 12Z: f001-f084 (hourly, 84 files)
    list_fn_bk_2=''
    for str_hhh in $(seq -f "%03g" 1 1 84); do
        fn_k=${COMINrrfs}/rrfs.${yyyymmdd_prev}/12/rrfs.t12z.prslev.${RRFS_RESOLUTION}.f${str_hhh}.na.grib2
        list_fn_bk_2="${list_fn_bk_2} ${fn_k}"
    done

    LIST_fn_all_2="${list_fn_bk_1} "
    LIST_fn_all_2+="${list_fn_bk_2}"

    echo; echo "list_1 (primary):"
    A=$LIST_fn_all_1; for a in ${A[@]}; do echo $a; done

    echo; echo "list_2 (backup):"
    A=$LIST_fn_all_2; for a in ${A[@]}; do echo $a; done


# ------------------------> Check file sizes
# RRFS native 3km files are ~6GB each. After subsetting to the STOFS domain,
# files are much smaller (~50-200 MB depending on domain size).
# We check the ORIGINAL file size before subsetting.
# Set minimum threshold at 500 MB to catch truncated/corrupt files.
# (Even a subset of the domain at 3km is substantial)
list_route_no=(1 2)
for flag_route_no in ${list_route_no[@]}; do

 echo $flag_route_no
 if [[ $flag_route_no == 1 ]]; then
    list_wk=$LIST_fn_all_1
 else
    list_wk=$LIST_fn_all_2
 fi

 FILESIZE=500000000
 LIST_fn_final=''
 for fn_rrfs_k_sz in ${list_wk[@]}
 do
   echo "Processing:: " $fn_rrfs_k_sz

   if [ -s $fn_rrfs_k_sz ]; then
      filesize=`wc -c $fn_rrfs_k_sz | awk '{print $1}' `

      if [ $filesize -ge $FILESIZE ];
      then
         LIST_fn_final+="${fn_rrfs_k_sz} "
         echo "File size OK: $fn_rrfs_k_sz : filesize $filesize GE $FILESIZE"
      else
         echo "WARNING: " $fn_rrfs_k_sz ": filesize $filesize less than $FILESIZE"
         echo "WARNING: " $fn_rrfs_k_sz ": filesize $filesize less than $FILESIZE"  >> $pgmout
      fi

   else
      echo "WARNING: "  $fn_rrfs_k_sz " does not exist"
      echo "WARNING: "  $fn_rrfs_k_sz " does not exist"
   fi
 done


  if [[ $flag_route_no == 1 ]]; then
    LIST_fn_final_qa_sz_1=$LIST_fn_final
  else
    LIST_fn_final_qa_sz_2=$LIST_fn_final
  fi

done # for flag_route_no


# ----------> Combine primary and backup lists if needed
# RRFS hourly: ~109 files expected for full nowcast+forecast (primary list)
# Minimum target: ~70 files (~2.9 days coverage from nowcast start)
  N_list_target=${N_list_target:-70}

 A1=($LIST_fn_final_qa_sz_1)
 B2=($LIST_fn_final_qa_sz_2)

  N_list_1=${#A1[@]}; echo "Primary list count: $N_list_1"
  N_list_2=${#B2[@]}; echo "Backup list count: $N_list_2"


if [[ ${N_list_1} -gt 1 ]]; then

  LIST_fn_final_qa_sz=(${A1[@]})

  if [[ ${N_list_1} -lt ${N_list_target} ]] && [[ ${N_list_2} -gt ${N_list_1} ]]; then
    echo "N_list_1 = $N_list_1"; echo "N_list_2 = $N_list_2"

    n_diff_1_2=$((${N_list_2}-${N_list_1}))

    LIST_fn_final_qa_sz=(${A1[@]} ${B2[@]:$N_list_1:$n_diff_1_2})

    echo "combined: LIST_fn_1 & 2: "
    for a in ${LIST_fn_final_qa_sz[@]}; do echo $a; done

  else
    echo "List from LIST_fn_final_qa_sz_1"

  fi

elif  [[ ${N_list_2} -gt 1 ]]; then
  echo "List from LIST_fn_final_qa_sz_2"
  LIST_fn_final_qa_sz=(${B2[@]})

else
  LIST_fn_final_qa_sz=()

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

 ihr=$((10#${cyc:-12}))  # reference cycle hour (from env, default 12Z)
 hr_1st_file=0

 # Create symbolic links for reference
 let cnt="hr_1st_file-1"
 for fn_rrfs_k in ${LIST_fn_final_qa_sz[@]}
 do
   let cnt=$cnt+1
   str_xxx_cnt=`seq -f "%03g" $cnt 1 $cnt`
   ln -sf $fn_rrfs_k sorce_rrfs_no_${str_xxx_cnt}
 done

# Minimum number of time steps for a valid merged file
# RRFS hourly: 70 files covers ~2.9 days from nowcast start; 30 is absolute minimum (~1.25 days)
N_dim_cr_min_cntList=30
N_LIST_fn_final_qa_sz=${#LIST_fn_final_qa_sz[@]}

fn_merged_sflux=rrfs_merge_v1.nc

echo; echo "N_LIST_fn_final_qa_sz = ${N_LIST_fn_final_qa_sz}"; echo

if [[ ${N_LIST_fn_final_qa_sz} -gt ${N_dim_cr_min_cntList} ]]; then

  echo "N_LIST_fn_final_qa_sz = ${N_LIST_fn_final_qa_sz}"
  echo

  # Counter for hourly time steps
  # RRFS is hourly, so each file advances 1 hour (same as GFS)
  let cnt="hr_1st_file-1"
  for fn_rrfs_k in ${LIST_fn_final_qa_sz[@]}
  do

   let cnt=$cnt+1

   str_xxx_cnt=`seq -f "%03g" $cnt 1 $cnt`
   echo "Processing($str_xxx_cnt): " $fn_rrfs_k


   # Step 1: Extract variables of interest from GRIB2
   fn_varOI=RRFS_voi_${str_xxx_cnt}.grb2
      $WGRIB2  -s  $fn_rrfs_k  | egrep "$list_var_oi" | $WGRIB2  -i  $fn_rrfs_k  -grib  $fn_varOI  >> $pgmout 2> errfile
      export err=$?;

   # Step 2: Subset to region of interest (CRITICAL -- RRFS files are ~6GB at native 3km)
   # This reduces file size from ~6GB to ~50-200MB depending on domain
   fn_roi=iRRFS_voi_rio_${str_xxx_cnt}.grb2
      $WGRIB2  $fn_varOI  -small_grib ${LONMIN}:${LONMAX} ${LATMIN}:${LATMAX} $fn_roi   >> $pgmout 2> errfile
      export err=$?;

   # Step 3: Convert GRIB2 to NetCDF
   fn_0_rnVar_raw=RRFS_voi_rio_0rename_raw_${str_xxx_cnt}.nc
      $WGRIB2  $fn_roi -netcdf $fn_0_rnVar_raw  >> $pgmout 2> errfile
      export err=$?;

   # Step 4: Rename MSLET -> PRMSL for SCHISM compatibility
   # RRFS uses MSLET (Mean Sea Level Pressure, ETA model reduction) instead of PRMSL.
   # wgrib2 -netcdf names this MSLET_meansealevel. The NCO update script expects
   # PRMSL_meansealevel, so we must rename it before applying the NCO script.
   fn_0_rnVar=RRFS_voi_rio_0rename_${str_xxx_cnt}.nc
      cp ${fn_0_rnVar_raw} ${fn_0_rnVar}
      ncrename -O -v MSLET_meansealevel,PRMSL_meansealevel ${fn_0_rnVar}  >> $pgmout 2> errfile
      export err=$?;

      if [ $err -ne 0 ]; then
          echo "WARNING: ncrename MSLET->PRMSL failed for ${str_xxx_cnt}, checking if PRMSL already exists"
          # Some RRFS versions might use PRMSL directly; check and continue
          ncdump -h ${fn_0_rnVar_raw} | grep -q "PRMSL_meansealevel"
          if [ $? -eq 0 ]; then
              echo "INFO: PRMSL_meansealevel already present, using as-is"
              cp ${fn_0_rnVar_raw} ${fn_0_rnVar}
          else
              echo "ERROR: Neither MSLET nor PRMSL found in ${fn_rrfs_k}"
              echo "ERROR: Skipping file ${str_xxx_cnt}"  >> $pgmout
              rm -f ${fn_0_rnVar}
              continue
          fi
      fi

   # Step 5: Update time variable and rename to SCHISM sflux names
   fn_out=RRFS_sflux_no_${str_xxx_cnt}.nc

   str_time=`echo '"'days since $iyr-$imon-$iday 00:00:00'"'`
   # RRFS is hourly, so advance time by 1*cnt hours from start (same as GFS)
   let hr_cnt_since_hr00=${ihr}+${cnt}

     ncap2 -Oh -s "tin=${hr_cnt_since_hr00}"  -s "time@units=$str_time"  -s "time@base_date ={ $iyr, $imon, $iday, 0}" -S $fn_nco_update_time_varName -v ${fn_0_rnVar}  $fn_out   >> $pgmout 2> errfile
     export err=$?;

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



fn_ori=${fn_merged_sflux}
fn_std_1=${fn_rrfs_rad_std}
fn_std_2=${fn_rrfs_prc_std}
fn_std_3=${fn_rrfs_air_std}

fn_std=${fn_std_1}
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

      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_1}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_2}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_3}
      echo "done: method - non-backup (RRFS)"

   elif [[ ${dim_k} -ge ${N_dim_cr_min} ]]; then
      ncap2 -s "time(0)=float(0.499999);time(-1)=${time_end_step}" ${fn_ori} -O ${fn_std}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_1}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_2}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_3}
      echo "done: method - backup 1 (RRFS)"

   else
      if [[ -f  ${COMOUT_PREV}/rerun/${fn_std} ]]; then

        fn_prev=prev_${fn_std}
        cpreq -pf ${COMOUT_PREV}/rerun/${fn_std} ${fn_prev}

        ncap2 -s "time(-1)=float(${time_end_step})" ${fn_prev} -O ${fn_std}

         cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_1}
         cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_2}
         cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_3}
         echo "done: method - backup 2 (RRFS, from previous cycle)"

      else
         msg="Warning: failed of (non-backup, backup1, backup 2) \n ${fn_std} Not created for RRFS"
         echo -e ${msg}
      fi

   fi # if [[ ${dim_k} -ge ${N_dim_cr_max} ]]



echo
echo "The script stofs_3d_atl_create_surface_forcing_rrfs.sh completed"
echo
