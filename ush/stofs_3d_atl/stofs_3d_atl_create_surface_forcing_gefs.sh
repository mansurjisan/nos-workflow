#!/bin/bash

############################################################################
#  Name: stofs_3d_atl_create_surface_forcing_gefs.sh                       #
#  This script reads NCEP/GEFS data to create GEFS-based surface forcing   #
#  files for STOFS-3D-ATL ensemble members.                                #
#                                                                          #
#  GEFS (Global Ensemble Forecast System) provides 30 perturbed members    #
#  (gep01-gep30) plus 1 control (gec00) at 0.50 deg resolution.           #
#  Output: stofs_3d_atl.t12z.gefs_NN.{air,prc,rad}.nc                     #
#                                                                          #
#  Key differences from GFS:                                               #
#    - 0.50 deg resolution (pgrb2ap5 product)                              #
#    - 3-hourly temporal resolution (not hourly)                           #
#    - Has RH instead of SPFH (requires RH->SPFH conversion)              #
#    - Has APCP instead of PRATE (requires APCP->PRATE conversion)        #
#    - Requires PRES:surface for the RH->SPFH conversion                  #
#                                                                          #
#  Environment variables:                                                  #
#    GEFS_MEMBER  - Member ID: "01"-"30" for perturbation, "c00" for ctrl  #
#    COMINgefs    - GEFS input data root directory                         #
#    DATA_prep_gefs - Working directory for this script                    #
#                                                                          #
#  Adapted from stofs_3d_atl_create_surface_forcing_gfs.sh                 #
#                                                        February, 2026    #
############################################################################


# ---------------------------> Begin ...
set -x

echo 'stofs_3d_atl_create_surface_forcing_gefs.sh started'

# ---------------------------> Load YAML Configuration (with fallback to defaults)
# Try to load from YAML if OFS_CONFIG is set and yaml_to_env.py is available
if [ -n "${OFS_CONFIG}" ] && [ -f "${OFS_CONFIG}" ]; then
    _yaml_to_env="${USHnos:-${HOMEnos}/ush}/python/nos_ofs/utils/yaml_to_env.py"
    if [ -f "${_yaml_to_env}" ]; then
        echo "Loading GEFS config from YAML: ${OFS_CONFIG}"
        _yaml_exports=$(python3 "${_yaml_to_env}" "${OFS_CONFIG}" --framework stofs 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "${_yaml_exports}" ]; then
            eval "${_yaml_exports}"
            echo "YAML config loaded successfully"
        fi
    fi
fi


# ---------------------------> GEFS Member Configuration
# GEFS_MEMBER: "01"-"30" for perturbation members, "c00" for control
GEFS_MEMBER=${GEFS_MEMBER:-01}

# Determine the file prefix: gec00 for control, gepNN for perturbation
if [ "${GEFS_MEMBER}" = "c00" ]; then
    GEFS_FILE_PREFIX="gec00"
    GEFS_MEMBER_LABEL="c00"
else
    GEFS_FILE_PREFIX="gep${GEFS_MEMBER}"
    GEFS_MEMBER_LABEL="${GEFS_MEMBER}"
fi

echo "GEFS member: ${GEFS_MEMBER}, file prefix: ${GEFS_FILE_PREFIX}, label: ${GEFS_MEMBER_LABEL}"

# GEFS product directory and resolution
GEFS_PRODUCT=${GEFS_PRODUCT:-pgrb2ap5}
GEFS_RESOLUTION=${GEFS_RESOLUTION:-0p50}


# ---------------------------> SAFETY CHECK: Validate required environment variables
# This prevents catastrophic deletion if variables are not set
if [ -z "${DATA_prep_gefs}" ]; then
    echo "FATAL ERROR: DATA_prep_gefs is not set. Exiting to prevent accidental file deletion."
    echo "Please set DATA_prep_gefs to a valid working directory path before running this script."
    exit 1
fi

# Additional safety: ensure path is not root or system directory
case "${DATA_prep_gefs}" in
    /|/bin|/boot|/dev|/etc|/home|/lib*|/opt|/proc|/root|/run|/sbin|/sys|/tmp|/usr|/var|/mnt|/media)
        echo "FATAL ERROR: DATA_prep_gefs='${DATA_prep_gefs}' appears to be a system directory."
        echo "Refusing to delete contents of system directories. Exiting."
        exit 1
        ;;
esac

# ---------------------------> directory/file names

  dir_wk=${DATA_prep_gefs}/

  mkdir -p $dir_wk
  cd $dir_wk || { echo "ERROR: Cannot cd to $dir_wk"; exit 1; }
  rm -fr $dir_wk/*

  mkdir -p ${COMOUTrerun}


  pgmout=pgmout_gefs_${GEFS_MEMBER_LABEL}.$$


# ---------------------------> Global Variables
  # NCO update script: reuse the GFS variable renaming script.
  # After our ncap2 conversion steps, variables are named identically to GFS output
  # (SPFH_2maboveground, PRATE_surface, etc.), so the same NCO script applies.
  fn_nco_update_time_varName=${FIXstofs3d}/stofs_3d_atl_gefs_input_nco_update_var.nco

  # Fallback: if GEFS-specific NCO script does not exist, use the NAM one (same variable names)
  if [ ! -f "${fn_nco_update_time_varName}" ]; then
      fn_nco_update_time_varName=${FIXstofs3d}/stofs_3d_atl_nam_input_nco_update_var.nco
      echo "INFO: Using NAM NCO update script as fallback: ${fn_nco_update_time_varName}"
  fi

  fn_gefs_rad_schism=sflux_rad_1.0001.nc
  fn_gefs_rad_std=${RUN}.${cycle}.gefs_${GEFS_MEMBER_LABEL}.rad.nc

  fn_gefs_prc_schism=sflux_prc_1.0001.nc
  fn_gefs_prc_std=${RUN}.${cycle}.gefs_${GEFS_MEMBER_LABEL}.prc.nc

  fn_gefs_air_schism=sflux_air_1.0001.nc
  fn_gefs_air_std=${RUN}.${cycle}.gefs_${GEFS_MEMBER_LABEL}.air.nc


# ---------------> Region of interest: same as GFS (full STOFS domain)
# Values from YAML config (grid.domain.*) or defaults
    LONMIN=${LONMIN:--98.5035}
    LONMAX=${LONMAX:--52.4867}
    LATMIN=${LATMIN:-7.347}
    LATMAX=${LATMAX:-52.5904}
    echo "Domain bounds: LONMIN=$LONMIN LONMAX=$LONMAX LATMIN=$LATMIN LATMAX=$LATMAX"



# ---------------> Dates
   yyyymmdd_today=${PDYHH_FCAST_BEGIN:0:8}
   yyyymmdd_prev=${PDYHH_NCAST_BEGIN:0:8}

   echo yyyymmdd_prev=$yyyymmdd_prev

    iyr=`echo ${yyyymmdd_prev} | cut -c1-4`
    imon=`echo ${yyyymmdd_prev} | cut  -c5-6`
    iday=`echo ${yyyymmdd_prev} | cut -c7-8`


# --------------------------> Create file lists
# GEFS file naming: gep{NN}.t{HH}z.pgrb2a.0p50.f{FFF}  (perturbation)
#                    gec00.t{HH}z.pgrb2a.0p50.f{FFF}     (control)
# GEFS is 3-hourly: f000, f003, f006, ..., f240 (then 6-hourly f246-f384)
# For STOFS nowcast+forecast (~5.5 days = 132 hrs), we use f003 through f132

# ------ Primary list (today's cycle) ------
# Yesterday t06z: use f006 (provides 1 file at analysis+6h)
    list_fn_yest_t06z_1=''
    fn_k=${COMINgefs}/gefs.${yyyymmdd_prev}/06/atmos/${GEFS_PRODUCT}/${GEFS_FILE_PREFIX}.t06z.pgrb2a.${GEFS_RESOLUTION}.f006
    if [ -f "${fn_k}" ]; then
        list_fn_yest_t06z_1="${fn_k}"
    fi

# Yesterday t12z: f003-f006 (3-hourly, 2 files)
    list_fn_yest_t12z=''
    for str_hhh in $(seq -f "%03g" 3 3 6); do
        fn_k=${COMINgefs}/gefs.${yyyymmdd_prev}/12/atmos/${GEFS_PRODUCT}/${GEFS_FILE_PREFIX}.t12z.pgrb2a.${GEFS_RESOLUTION}.f${str_hhh}
        list_fn_yest_t12z="${list_fn_yest_t12z} ${fn_k}"
    done

# Yesterday t18z: f003-f006 (3-hourly, 2 files)
    list_fn_yest_t18z=''
    for str_hhh in $(seq -f "%03g" 3 3 6); do
        fn_k=${COMINgefs}/gefs.${yyyymmdd_prev}/18/atmos/${GEFS_PRODUCT}/${GEFS_FILE_PREFIX}.t18z.pgrb2a.${GEFS_RESOLUTION}.f${str_hhh}
        list_fn_yest_t18z="${list_fn_yest_t18z} ${fn_k}"
    done

# Today t00z: f003-f006 (3-hourly, 2 files)
    list_fn_today_t00z=''
    for str_hhh in $(seq -f "%03g" 3 3 6); do
        fn_k=${COMINgefs}/gefs.${yyyymmdd_today}/00/atmos/${GEFS_PRODUCT}/${GEFS_FILE_PREFIX}.t00z.pgrb2a.${GEFS_RESOLUTION}.f${str_hhh}
        list_fn_today_t00z="${list_fn_today_t00z} ${fn_k}"
    done

# Today t06z: f003-f006 (3-hourly, 2 files)
    list_fn_today_t06z=''
    for str_hhh in $(seq -f "%03g" 3 3 6); do
        fn_k=${COMINgefs}/gefs.${yyyymmdd_today}/06/atmos/${GEFS_PRODUCT}/${GEFS_FILE_PREFIX}.t06z.pgrb2a.${GEFS_RESOLUTION}.f${str_hhh}
        list_fn_today_t06z="${list_fn_today_t06z} ${fn_k}"
    done

# Today t12z: f003-f132 (3-hourly, 44 files covering 5.5 day forecast)
    # 132 hr = 5.5 days, matching the STOFS forecast period
    list_fn_today_t12z=''
    for str_hhh in $(seq -f "%03g" 3 3 132); do
        fn_k=${COMINgefs}/gefs.${yyyymmdd_today}/12/atmos/${GEFS_PRODUCT}/${GEFS_FILE_PREFIX}.t12z.pgrb2a.${GEFS_RESOLUTION}.f${str_hhh}
        list_fn_today_t12z="${list_fn_today_t12z} ${fn_k}"
    done

    # Concatenate primary list
    LIST_fn_all_1="${list_fn_yest_t06z_1} "
    LIST_fn_all_1+="${list_fn_yest_t12z} "
    LIST_fn_all_1+="${list_fn_yest_t18z} "
    LIST_fn_all_1+="${list_fn_today_t00z} "
    LIST_fn_all_1+="${list_fn_today_t06z} "
    LIST_fn_all_1+="${list_fn_today_t12z}"


# ------ Backup list (yesterday's 12Z extended forecast) ------
    list_fn_bk_1=''
    fn_k=${COMINgefs}/gefs.${yyyymmdd_prev}/06/atmos/${GEFS_PRODUCT}/${GEFS_FILE_PREFIX}.t06z.pgrb2a.${GEFS_RESOLUTION}.f006
    if [ -f "${fn_k}" ]; then
        list_fn_bk_1="${fn_k}"
    fi

    # Yesterday t12z: f003-f132 (3-hourly, 44 files)
    list_fn_bk_2=''
    for str_hhh in $(seq -f "%03g" 3 3 132); do
        fn_k=${COMINgefs}/gefs.${yyyymmdd_prev}/12/atmos/${GEFS_PRODUCT}/${GEFS_FILE_PREFIX}.t12z.pgrb2a.${GEFS_RESOLUTION}.f${str_hhh}
        list_fn_bk_2="${list_fn_bk_2} ${fn_k}"
    done

    LIST_fn_all_2="${list_fn_bk_1} "
    LIST_fn_all_2+="${list_fn_bk_2}"

    echo; echo "list_1 (primary):"
    A=$LIST_fn_all_1; for a in ${A[@]}; do echo $a; done

    echo; echo "list_2 (backup):"
    A=$LIST_fn_all_2; for a in ${A[@]}; do echo $a; done


# ------------------------> Check file sizes
# GEFS 0.50 deg files are ~15 MB (much smaller than GFS 0.25 deg at ~500 MB)
# Set minimum threshold at 5 MB to catch truncated/corrupt files
list_route_no=(1 2)
for flag_route_no in ${list_route_no[@]}; do

 echo $flag_route_no
 if [[ $flag_route_no == 1 ]]; then
    list_wk=$LIST_fn_all_1
 else
    list_wk=$LIST_fn_all_2
 fi

 FILESIZE=5000000
 LIST_fn_final=''
 for fn_gefs_k_sz in ${list_wk[@]}
 do
   echo "Processing:: " $fn_gefs_k_sz

   if [ -s $fn_gefs_k_sz ]; then
      filesize=`wc -c $fn_gefs_k_sz | awk '{print $1}' `

      if [ $filesize -ge $FILESIZE ];
      then
         LIST_fn_final+="${fn_gefs_k_sz} "
         echo "File size OK: $fn_gefs_k_sz : filesize $filesize GE $FILESIZE"
      else
         echo "WARNING: " $fn_gefs_k_sz ": filesize $filesize less than $FILESIZE"
         echo "WARNING: " $fn_gefs_k_sz ": filesize $filesize less than $FILESIZE"  >> $pgmout
      fi

   else
      echo "WARNING: "  $fn_gefs_k_sz " does not exist"
      echo "WARNING: "  $fn_gefs_k_sz " does not exist"
   fi
 done


  if [[ $flag_route_no == 1 ]]; then
    LIST_fn_final_qa_sz_1=$LIST_fn_final
  else
    LIST_fn_final_qa_sz_2=$LIST_fn_final
  fi

done # for flag_route_no


# ----------> Combine primary and backup lists if needed
# GEFS 3-hourly: ~53 files expected for full nowcast+forecast
# (1 from t06z + 2 from t12z + 2 from t18z + 2 from t00z + 2 from t06z + 44 from t12z)
# Minimum target: ~35 files (~4.4 days coverage)
  N_list_target=${N_list_target:-35}

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
# GEFS variables to extract via wgrib2:
#   - TMP:2 m above ground
#   - RH:2 m above ground     (GEFS uses RH, not SPFH -- will convert to SPFH)
#   - UGRD:10 m above ground
#   - VGRD:10 m above ground
#   - PRMSL:mean sea level
#   - APCP:surface             (GEFS uses APCP, not PRATE -- will convert to PRATE)
#   - PRES:surface             (needed for RH->SPFH conversion)
#   - DSWRF:surface
#   - DLWRF:surface
#   - ALBDO:surface / USWRF:surface / ULWRF:surface (bonus, if available)

 list_var_oi='TMP:2 m above|RH:2 m above|UGRD:10 m above|VGRD:10 m above|PRMSL|APCP:surface|PRES:surface|ALBDO:surface|DSWRF:surface|USWRF:surface|DLWRF:surface|ULWRF:surface'

 rm -f *_voi*.
 rm -f *_sflux.nc

 ihr=$((10#${cyc:-12}))  # reference cycle hour (from env, default 12Z)
 hr_1st_file=0

 # Create symbolic links for reference
 let cnt="hr_1st_file-1"
 for fn_gefs_k in ${LIST_fn_final_qa_sz[@]}
 do
   let cnt=$cnt+1
   str_xxx_cnt=`seq -f "%03g" $cnt 1 $cnt`
   ln -sf $fn_gefs_k sorce_gefs_no_${str_xxx_cnt}
 done

# Minimum number of time steps for a valid merged file
# GEFS 3-hourly: 35 files covers ~4.4 days; 15 is absolute minimum (~1.9 days)
N_dim_cr_min_cntList=15
N_LIST_fn_final_qa_sz=${#LIST_fn_final_qa_sz[@]}

fn_merged_sflux=gefs_${GEFS_MEMBER_LABEL}_merge_v1.nc

echo; echo "N_LIST_fn_final_qa_sz = ${N_LIST_fn_final_qa_sz}"; echo

if [[ ${N_LIST_fn_final_qa_sz} -gt ${N_dim_cr_min_cntList} ]]; then

  echo "N_LIST_fn_final_qa_sz = ${N_LIST_fn_final_qa_sz}"
  echo

  # Counter for 3-hourly time steps
  # GEFS is 3-hourly, so each file advances 3 hours
  let cnt="hr_1st_file-1"
  for fn_gefs_k in ${LIST_fn_final_qa_sz[@]}
  do

   let cnt=$cnt+1

   str_xxx_cnt=`seq -f "%03g" $cnt 1 $cnt`
   echo "Processing($str_xxx_cnt): " $fn_gefs_k


   # Step 1: Extract variables of interest from GRIB2
   fn_varOI=GEFS_voi_${str_xxx_cnt}.grb2
      $WGRIB2  -s  $fn_gefs_k  | egrep "$list_var_oi" | $WGRIB2  -i  $fn_gefs_k  -grib  $fn_varOI  >> $pgmout 2> errfile
      export err=$?;

   # Step 2: Subset to region of interest
   fn_roi=iGEFS_voi_rio_${str_xxx_cnt}.grb2
      $WGRIB2  $fn_varOI  -small_grib ${LONMIN}:${LONMAX} ${LATMIN}:${LATMAX} $fn_roi   >> $pgmout 2> errfile
      export err=$?;

   # Step 3: Convert GRIB2 to NetCDF
   fn_0_rnVar_raw=GEFS_voi_rio_0rename_raw_${str_xxx_cnt}.nc
      $WGRIB2  $fn_roi -netcdf $fn_0_rnVar_raw  >> $pgmout 2> errfile
      export err=$?;

   # Step 4: Convert GEFS-specific variables to GFS-equivalent names
   #   RH_2maboveground + TMP_2maboveground + PRES_surface -> SPFH_2maboveground
   #   APCP_surface -> PRATE_surface
   #
   # RH -> SPFH conversion (Tetens formula):
   #   es = 611.2 * exp(17.67 * (T - 273.15) / (T - 29.65))   [saturation vapor pressure, Pa]
   #   e  = (RH / 100.0) * es                                  [actual vapor pressure, Pa]
   #   SPFH = 0.622 * e / (P - 0.378 * e)                     [specific humidity, kg/kg]
   #
   # APCP -> PRATE conversion:
   #   PRATE = APCP / 10800.0   [kg/m2 accumulated over 3hr -> kg/m2/s]
   #
   fn_0_rnVar=GEFS_voi_rio_0rename_${str_xxx_cnt}.nc
      ncap2 -O -h \
        -s 'es=611.2f*exp(17.67f*(TMP_2maboveground-273.15f)/(TMP_2maboveground-29.65f))' \
        -s 'e_vap=(RH_2maboveground/100.0f)*es' \
        -s 'SPFH_2maboveground=0.622f*e_vap/(PRES_surface-0.378f*e_vap)' \
        -s 'PRATE_surface=APCP_surface/10800.0f' \
        ${fn_0_rnVar_raw}  ${fn_0_rnVar}   >> $pgmout 2> errfile
      export err=$?;

   # Remove intermediate variables (es, e_vap) and input-only variables (RH, APCP, PRES)
      ncks -O -x -v es,e_vap,RH_2maboveground,APCP_surface,PRES_surface ${fn_0_rnVar} ${fn_0_rnVar}  >> $pgmout 2> errfile
      export err=$?;

   # Step 5: Update time variable and rename to SCHISM sflux names
   fn_out=GEFS_sflux_no_${str_xxx_cnt}.nc

   str_time=`echo '"'days since $iyr-$imon-$iday 00:00:00'"'`
   # GEFS is 3-hourly, so advance time by 3*cnt hours from start
   let hr_cnt_since_hr00=${ihr}+3*${cnt}

     ncap2 -Oh -s "tin=${hr_cnt_since_hr00}"  -s "time@units=$str_time"  -s "time@base_date ={ $iyr, $imon, $iday, 0}" -S $fn_nco_update_time_varName -v ${fn_0_rnVar}  $fn_out   >> $pgmout 2> errfile
     export err=$?;

 done

# Merge all time steps into a single file
 rm -f ${fn_merged_sflux};

 echo fn_merged_sflux= $fn_merged_sflux

    rm -f $fn_merged_sflux
    find . -size 0  -exec rm -f {} \;

    list_GEFS_sflux_no=`ls GEFS_sflux_no_*.nc 2>/dev/null`
    if [ ! -z "$list_GEFS_sflux_no" ]; then
      ncrcat -O  GEFS_sflux_no_*.nc  $fn_merged_sflux
    fi

fi   # if [[ ${N_LIST_fn_final_qa_sz} -gt ${N_dim_cr_min_cntList} ]]



# ---------------------------------> QC & archive
# GEFS 3-hourly QC thresholds (different from GFS hourly):
#   - N_dim_cr_min: minimum number of time steps (~35 for ~4.4 days)
#   - N_dim_cr_max: expected full time steps (~53 for full coverage)
#   - File size: GEFS 0.50 deg merged sflux ~50 MB (much smaller than GFS)
#   - time_end_step: end time in fractional days from reference date

# For 3-hourly data: ~53 total files => ~53 time steps
# 132 hrs / 24 = 5.5 days of forecast from today 12Z
# Plus ~24 hrs of nowcast coverage = ~6.5 days total
# End time: about 10.0 fractional days from reference date
N_dim_cr_min=30
N_dim_cr_max=45
list_fn_sz_cr=(500000)
list_end_time_step=(10.0)
list_offset_time=(1.0)



fn_ori=${fn_merged_sflux}
fn_std_1=${fn_gefs_rad_std}
fn_std_2=${fn_gefs_prc_std}
fn_std_3=${fn_gefs_air_std}

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
      echo "done: method - non-backup (GEFS ${GEFS_MEMBER_LABEL})"

   elif [[ ${dim_k} -ge ${N_dim_cr_min} ]]; then
      ncap2 -s "time(0)=float(0.499999);time(-1)=${time_end_step}" ${fn_ori} -O ${fn_std}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_1}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_2}
      cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_3}
      echo "done: method - backup 1 (GEFS ${GEFS_MEMBER_LABEL})"

   else
      if [[ -f  ${COMOUT_PREV}/rerun/${fn_std} ]]; then

        fn_prev=prev_${fn_std}
        cpreq -pf ${COMOUT_PREV}/rerun/${fn_std} ${fn_prev}

        ncap2 -s "time(-1)=float(${time_end_step})" ${fn_prev} -O ${fn_std}

         cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_1}
         cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_2}
         cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std_3}
         echo "done: method - backup 2 (GEFS ${GEFS_MEMBER_LABEL}, from previous cycle)"

      else
         msg="Warning: failed of (non-backup, backup1, backup 2) \n ${fn_std} Not created for GEFS member ${GEFS_MEMBER_LABEL}"
         echo -e ${msg}
      fi

   fi # if [[ ${dim_k} -ge ${N_dim_cr_max} ]]



echo
echo "The script stofs_3d_atl_create_surface_forcing_gefs.sh completed for member ${GEFS_MEMBER_LABEL}"
echo
