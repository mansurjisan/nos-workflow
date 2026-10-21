# nos_modules_pschism.h - STOFS-3D-ATL standalone nowcast and forecast: the stofs module versions, as
# pbs/stofs_3d_atl_ufs_standalone/jnos_nowcast_00.pbs. MJ (10/21/26)
# The card's version file: the IT-stofs one pschism was built against, else the ops one; a STOFS_RUNVER in the def wins. MJ (10/21/26)
STOFS_RUNVER=%STOFS_RUNVER:%
STOFS_RUNVER=${STOFS_RUNVER:-$(dirname "${HOMEnos}")/IT-stofs.v2.1.0/versions/stofs_3d_atl/run.ver}
[ -r "${STOFS_RUNVER}" ] || STOFS_RUNVER=/lfs/h1/ops/prod/packages/stofs.v3.1.5/versions/run.ver
[ -r "${STOFS_RUNVER}" ] || { echo "ERROR: no readable STOFS run.ver (set STOFS_RUNVER)" >&2; exit 1; }
export STOFS_RUNVER
echo "STOFS_RUNVER=${STOFS_RUNVER}"
_py_ver=${python_ver:-}
. "${STOFS_RUNVER}"
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
# prod_util/2.0.17 from run.ver is unknown on WCOSS2 and the cards run without it; a failed load must not end the task. MJ (10/21/26)
module load prod_util/${prod_util_ver:-2.0.17} || echo "WARNING: prod_util not loaded"
module list
