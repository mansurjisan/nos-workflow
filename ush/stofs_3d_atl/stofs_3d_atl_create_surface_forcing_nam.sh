#!/bin/bash

############################################################################
#  Name: stofs_3d_atl_create_surface_forcing_nam.sh                        #
#  This script reads the NCEP/NAM data to create the NAM based surface     #
#  forcing files, stofs_3d_atl.t12z.nam.{air,prc,rad}.nc for ensemble      #
#  atmospheric forcing members.                                            #
#                                                                          #
#  NAM is used as a secondary (sflux stack 2) source since its domain      #
#  (lat ~14-43N) does not cover the full STOFS-3D-ATL domain (lat ~7-53N). #
#  SCHISM uses the primary source (GFS) where secondary is missing.        #
#                                                                          #
#  Adapted from stofs_3d_atl_create_surface_forcing_hrrr.sh                #
#                                                        February, 2026    #
############################################################################

# ---------------------------> Begin ...
set -x

echo 'The script stofs_3d_atl_create_surface_forcing_nam.sh started '

# ---------------------------> Load YAML Configuration (with fallback to defaults)
# Try to load from YAML if OFS_CONFIG is set and yaml_to_env.py is available
if [ -n "${OFS_CONFIG}" ] && [ -f "${OFS_CONFIG}" ]; then
    _yaml_to_env="${USHnos:-${HOMEnos}/ush}/python/nos_ofs/utils/yaml_to_env.py"
    if [ -f "${_yaml_to_env}" ]; then
        echo "Loading NAM config from YAML: ${OFS_CONFIG}"
        _yaml_exports=$(python3 "${_yaml_to_env}" "${OFS_CONFIG}" --framework stofs 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "${_yaml_exports}" ]; then
            eval "${_yaml_exports}"
            echo "YAML config loaded successfully"
        fi
    fi
fi


# ---------------------------> SAFETY CHECK: Validate required environment variables
# This prevents catastrophic deletion if variables are not set
if [ -z "${DATA_prep_nam}" ]; then
    echo "FATAL ERROR: DATA_prep_nam is not set. Exiting to prevent accidental file deletion."
    echo "Please set DATA_prep_nam to a valid working directory path before running this script."
    exit 1
fi

# Additional safety: ensure path is not root or system directory
case "${DATA_prep_nam}" in
    /|/bin|/boot|/dev|/etc|/home|/lib*|/opt|/proc|/root|/run|/sbin|/sys|/tmp|/usr|/var|/mnt|/media)
        echo "FATAL ERROR: DATA_prep_nam='${DATA_prep_nam}' appears to be a system directory."
        echo "Refusing to delete contents of system directories. Exiting."
        exit 1
        ;;
esac

# ---------------------------> directory/file names
  dir_wk=${DATA_prep_nam}/

  mkdir -p $dir_wk
  cd $dir_wk || { echo "ERROR: Cannot cd to $dir_wk"; exit 1; }

  pgmout=pgmout_nam.$$


# ---------------------------> Global Variables
  fn_nco_update_time_varName=${FIXstofs3d}/stofs_3d_atl_nam_input_nco_update_var.nco

  fn_nam_rad_schism=sflux_rad_2.0001.nc
  fn_nam_rad_date_tag=${RUN}.nam.rad.nfcast.${PDYHH_FCAST_BEGIN:0:8}.${cycle}.nc
  fn_nam_rad_std=${RUN}.${cycle}.nam.rad.nc

  fn_nam_prc_schism=sflux_prc_2.0001.nc
  fn_nam_prc_date_tag=${RUN}.nam.prc.nfcast.${PDYHH_FCAST_BEGIN:0:8}.${cycle}.nc
  fn_nam_prc_std=${RUN}.${cycle}.nam.prc.nc

  fn_nam_air_schism=sflux_air_2.0001.nc
  fn_nam_air_date_tag=${RUN}.nam.air.nfcast.${PDYHH_FCAST_BEGIN:0:8}.${cycle}.nc
  fn_nam_air_std=${RUN}.${cycle}.nam.air.nc


# --------------------------> Region of interest
# NAM domain: covers roughly CONUS + partial offshore
# Values from YAML config (forcing.atmospheric.nam_blend.*) or defaults
  LONMIN=${NAM_LONMIN:--89.15}
  LONMAX=${NAM_LONMAX:--58.17}
  LATMIN=${NAM_LATMIN:-14.34}
  LATMAX=${NAM_LATMAX:-42.61}
  echo "NAM Domain bounds: LONMIN=$LONMIN LONMAX=$LONMAX LATMIN=$LATMIN LATMAX=$LATMAX"

 #--------------------------> dates
  yyyymmdd_today=${PDYHH_FCAST_BEGIN:0:8}
  yyyymmdd_prev=${PDYHH_NCAST_BEGIN:0:8}


# ------> form the input file lists
  # NAM runs at 00/06/12/18Z with hourly output to f36 and 3-hourly to f84
  # For 12Z cycle: use yesterday t12z f06+ through today t12z f01-f60
  #
  # yesterday: t12z, f06-f36 (hourly, covers 18Z-00Z+12h)
  list_hr_prev_12z=`seq -f "%02g" 6 1 36`

  str_base_prev_12z=${COMINnam}/nam.${yyyymmdd_prev}/nam.t12z.awphys
  list_fn_prev=''
  for num_k in $list_hr_prev_12z
  do
    fn_k=${str_base_prev_12z}${num_k}.tm00.grib2
    list_fn_prev=${list_fn_prev}' '${fn_k}
  done

  # yesterday: t18z, f01-f36 (hourly)
  list_hr_prev_18z=`seq -f "%02g" 1 1 36`

  str_base_prev_18z=${COMINnam}/nam.${yyyymmdd_prev}/nam.t18z.awphys
  list_fn_prev_18z=''
  for num_k in $list_hr_prev_18z
  do
    fn_k=${str_base_prev_18z}${num_k}.tm00.grib2
    list_fn_prev_18z=${list_fn_prev_18z}' '${fn_k}
  done

  # today: t00z, f01-f36 (hourly)
  list_hr_today_00z=`seq -f "%02g" 1 1 36`

  str_base_today_00z=${COMINnam}/nam.${yyyymmdd_today}/nam.t00z.awphys
  list_fn_today_1=''
  for num_k in $list_hr_today_00z
  do
    fn_k=${str_base_today_00z}${num_k}.tm00.grib2
    list_fn_today_1=${list_fn_today_1}' '${fn_k}
  done

  # today: t06z, f01-f36 (hourly)
  list_hr_today_06z=`seq -f "%02g" 1 1 36`

  str_base_today_06z=${COMINnam}/nam.${yyyymmdd_today}/nam.t06z.awphys
  list_fn_today_06z=''
  for num_k in $list_hr_today_06z
  do
    fn_k=${str_base_today_06z}${num_k}.tm00.grib2
    list_fn_today_06z=${list_fn_today_06z}' '${fn_k}
  done

  # today: t12z, f01-f60 (hourly to f36, 3-hourly f39-f60)
  list_hr_today_12z_hourly=`seq -f "%02g" 1 1 36`
  list_hr_today_12z_3hourly=`seq -f "%02g" 39 3 60`

  str_base_today_12z=${COMINnam}/nam.${yyyymmdd_today}/nam.t12z.awphys
  list_fn_today_2=''
  for num_k in $list_hr_today_12z_hourly $list_hr_today_12z_3hourly
  do
    fn_k=${str_base_today_12z}${num_k}.tm00.grib2
    list_fn_today_2=${list_fn_today_2}' '${fn_k}
  done

# concatenate dir/file names
 LIST_fn_all="${list_fn_prev} "
 LIST_fn_all+="${list_fn_prev_18z[@]} "
 LIST_fn_all+="${list_fn_today_1[@]} "
 LIST_fn_all+="${list_fn_today_06z[@]} "
 LIST_fn_all+="${list_fn_today_2[@]} "


# check file sizes (NAM awphys files are ~50-100MB)
 FILESIZE=50000000

 LIST_fn_final=''
 for fn_nam_k_sz in $LIST_fn_all
 do
   echo "Processing:: " $fn_nam_k_sz

   if [ -s $fn_nam_k_sz ]; then
      filesize=`wc -c $fn_nam_k_sz | awk '{print $1}' `

      if [ $filesize -ge $FILESIZE ];
      then
         LIST_fn_final+="${fn_nam_k_sz} "
      else
         echo "WARNING: " $fn_nam_k_sz ": filesize $filesize less than $FILESIZE"
         echo "WARNING: " $fn_nam_k_sz ": filesize $filesize less than $FILESIZE"
      fi

   else
      echo "WARNING: "  $fn_nam_k_sz " does not exist"
      echo "WARNING: "  $fn_nam_k_sz " does not exist"
   fi
 done



# -------------------> variables of OI (grb2)
# NAM uses PRMSL (not MSLMA like HRRR)
   list_var_oi='TMP:2 m above|RH:2 m above|SPFH:2 m above|PRMSL|PRATE|UGRD:10 m above|VGRD:10 m above|ALBDO:surface|DSWRF:surface|USWRF:surface|DLWRF:surface|ULWRF:surface'

   iyr=`echo ${yyyymmdd_prev} | cut -c1-4`
   imon=`echo ${yyyymmdd_prev} | cut  -c5-6`
   iday=`echo ${yyyymmdd_prev} | cut -c7-8`
   ihr=12


 rm -f NAM_voi_*

 let cnt=-1
 for fn_nam_k in $LIST_fn_final
 do
   let cnt=$cnt+1

   str_xxx_cnt=`seq -f "%03g" $cnt 1 $cnt`
   echo "Processing($str_xxx_cnt): " $fn_nam_k

      ln -sf $fn_nam_k NAM_${str_xxx_cnt}.grb2


      fn_varOI=NAM_voi_${str_xxx_cnt}.grb2
      $WGRIB2  -s  $fn_nam_k  | egrep "$list_var_oi" | $WGRIB2  -i  $fn_nam_k  -grib  $fn_varOI  >> $pgmout 2> errfile
      export err=$?;

      fn_roi=NAM_voi_rio_${str_xxx_cnt}.grb2
      $WGRIB2  $fn_varOI  -small_grib ${LONMIN}:${LONMAX} ${LATMIN}:${LATMAX} $fn_roi   >> $pgmout 2> errfile
      export err=$?;

      fn_0_rnVar_with_xy=NAM_voi_rio_0rename_with_xy_${str_xxx_cnt}.nc
      $WGRIB2  $fn_roi -netcdf $fn_0_rnVar_with_xy    >> $pgmout 2> errfile
      export err=$?;

      fn_0_rnVar=NAM_voi_rio_0rename_${str_xxx_cnt}.nc
      ncks -CO -x -v y,x $fn_0_rnVar_with_xy  $fn_0_rnVar    >> $pgmout 2> errfile
      export err=$?;

      fn_1time=NAM_voi_rio_0rename_1time_${str_xxx_cnt}.nc

      str_time=`echo '"'days since $iyr-$imon-$iday 00:00:00'"'`
      let hr_cnt_since_hr00=${ihr}+${cnt}

      ncap2 -Oh -s "tin=${hr_cnt_since_hr00}"  -s "time@units=$str_time"  -s "time@base_date ={ $iyr, $imon, $iday, 0}" -S $fn_nco_update_time_varName -v ${fn_0_rnVar} ${fn_1time}    >> $pgmout 2> errfile
      export err=$?;

 done


  fn_merged_sflux=nam_date_${PDYHH_FCAST_BEGIN}_${PDYHH_FCAST_END}.nc
  rm -rf $fn_merged_sflux
  find . -size 0  -exec rm -f {} \;

  ncrcat -O NAM_voi_rio_0rename_1time_???.nc $fn_merged_sflux
  export err=$?;



# -----------------------------> ln -s
rm -f sflux_???_2.????.nc

fn_link_src=${fn_merged_sflux}

# NAM merged file is smaller than HRRR (~12km vs ~3km resolution)
FILESIZE_min=200000000
if [ -f $fn_link_src ]; then

   sz_fn_link_src=`wc -c $fn_link_src | awk '{print $1}'`
   if [ $sz_fn_link_src -ge $FILESIZE_min ]; then

    ln -sf $fn_link_src  ${fn_nam_rad_schism}
    ln -sf $fn_link_src  ${fn_nam_prc_schism}
    ln -sf $fn_link_src  ${fn_nam_air_schism}

    cpreq -pf $fn_link_src ${COMOUTrerun}/${fn_nam_rad_std}
    cpreq -pf $fn_link_src ${COMOUTrerun}/${fn_nam_prc_std}
    cpreq -pf $fn_link_src ${COMOUTrerun}/${fn_nam_air_std}


    echo " sflux/nam forcing files: renames & copied to COMOUT "

   fi

else
    echo " sflux/nam forcing file not created or file size is too small: $fn_link_src "
fi

export err=$?;


echo
echo "The script stofs_3d_atl_create_surface_forcing_nam.sh completed  "
echo


