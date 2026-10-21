# nos_modules_pschism.h - STOFS-3D-ATL standalone nowcast and forecast: the ops stofs module versions, as
# pbs/stofs_3d_atl_ufs_standalone/jnos_nowcast_00.pbs (STOFS_RUNVER is a suite variable here). MJ (10/20/26)
if [ ! -r "%STOFS_RUNVER%" ]; then echo "ERROR: no readable STOFS run.ver (STOFS_RUNVER=%STOFS_RUNVER%)" >&2; exit 1; fi
_py_ver=${python_ver:-}
. "%STOFS_RUNVER%"
python_ver=${_py_ver}

module purge
module reset
module load intel/${intel_ver}
module load PrgEnv-intel/${PrgEnv_intel_ver}
module load craype/${craype_ver}
module load cray-mpich/${cray_mpich_ver}
module load cray-pals/${cray_pals_ver}
module load hdf5/${hdf5_ver}
module load netcdf/${netcdf_ver}
module load jasper/${jasper_ver}
module load udunits/${udunits_ver}
module load zlib/${zlib_ver}
module load bufr/${bufr_ver}
module load g2/${g2_ver}
module load w3nco/${w3nco_ver}
module load w3emc/${w3emc_ver}
module load libjpeg/${libjpeg_ver}
module load grib_util/${grib_util_ver}
module load gsl/${gsl_ver}
module load wgrib2/${wgrib2_ver}
module load nco/${nco_ver}
module load python/${python_ver:-3.8.6}
module load prod_envir/${prod_envir_ver:-2.0.6}
module load prod_util/${prod_util_ver:-2.0.17}
module list
