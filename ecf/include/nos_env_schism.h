# nos_env_schism.h - input paths of the SCHISM-UFS cards (secofs_ufs, secofs_ufs_ww3, stofs_3d_atl_ufs and its standalone variant). MJ (10/20/26)
case "${NOS_STAGE}" in
  prep)
    export COMINgfs=${COMINgfs:-/lfs/h1/ops/prod/com/gfs/${gfs_ver}}
    export COMINhrrr=${COMINhrrr:-/lfs/h1/ops/prod/com/hrrr/${hrrr_ver}}
    export COMINrtofs_2d=${COMINrtofs_2d:-/lfs/h1/ops/prod/com/rtofs/${rtofs_ver}}
    export COMINrtofs_3d=${COMINrtofs_3d:-/lfs/h1/ops/prod/com/rtofs/${rtofs_ver}}
    export COMINnwm=${COMINnwm:-/lfs/h1/ops/prod/com/nwm/${nwm_ver}}
    ;;
  nowcast|forecast)
    export COMPATH=/lfs/h1/ops/prod/com/nos
    export COMIN=/lfs/h1/ops/prod/com
    export COMINnam=${COMINnam:-/lfs/h1/ops/prod/com/nam/${nam_ver}}
    export COMINhrrr=${COMINhrrr:-/lfs/h1/ops/prod/com/hrrr/${hrrr_ver}}
    export COMINrap=${COMINrap:-/lfs/h1/ops/prod/com/rap/${rap_ver}}
    export COMINgfs=${COMINgfs:-/lfs/h1/ops/prod/com/gfs/${gfs_ver}}
    export COMINrtma=${COMINrtma:-/lfs/h1/ops/prod/com/rtma/${rtma_ver}}
    export COMINetss=${COMINetss:-/lfs/h1/ops/prod/com/petss/${petss_ver}}
    export COMINrtofs_2d=${COMINrtofs_2d:-/lfs/h1/ops/prod/com/rtofs/${rtofs_ver}}
    export COMINrtofs_3d=${COMINrtofs_3d:-/lfs/h1/ops/prod/com/rtofs/${rtofs_ver}}
    export COMINnwm=${COMINnwm:-/lfs/h1/ops/prod/com/nwm/${nwm_ver}}
    ;;
  post)
    export COMPATH=/lfs/h1/ops/prod/com/nos
    ;;
esac
