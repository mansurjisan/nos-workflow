# nos_modules_adcirc.h - STOFS-2D-Global modules for all four jobs, as pbs/stofs_2d_glo/jnos_{prep,nowcast}_00.pbs.
# The ops run.ver also sets python_ver=3.12.0, which has no yaml/netCDF4; keep this package's python. MJ (10/20/26)
# adcirc/post.py reads STOFS_RUNVER to find the ops ex-scripts. MJ (10/21/26)
export STOFS_RUNVER=%STOFS_RUNVER%
if [ -r "${STOFS_RUNVER}" ]; then
  _py_ver=${python_ver:-}
  . "${STOFS_RUNVER}"
  python_ver=${_py_ver}
fi

module purge
module reset
module load PrgEnv-intel/${PrgEnv_intel_ver}
module load craype/${craype_ver}
module load intel/${intel_ver}
module load cray-mpich/${cray_mpich_ver}
module load cray-pals/${cray_pals_ver}
module load hdf5/${hdf5_ver}
module load netcdf/${netcdf_ver}
module load udunits/${udunits_ver}
module load gsl/${gsl_ver}
module load libjpeg/${libjpeg_ver}
if [ -n "%ADCIRC_MODULE_PATH:%" ]; then module use %ADCIRC_MODULE_PATH:%; fi
module load adcirc/${adcirc_ver}
module load python/${python_ver:-3.8.6}
module load prod_envir/${prod_envir_ver:-2.0.6}
# prod_util/2.0.17 from run.ver is unknown on WCOSS2 and the cards run without it; a failed load must not end the task. MJ (10/21/26)
module load prod_util/${prod_util_ver:-2.0.17} || echo "WARNING: prod_util not loaded"
case "${NOS_STAGE}" in
  prep|post)
    module load wgrib2/${wgrib2_ver:-2.0.8}
    module load nco/${nco_ver:-5.0.6}
    ;;
esac

# The post steps add the modules the ops ecf files load, once per segment list; python comes from ve/stofs. MJ (10/20/26)
_seg=" ${ADCIRC_SEGMENT//,/ } "
case "${_seg}" in *" anomaly "*|*" bias "*) module unload python 2>/dev/null || true ;; esac
case "${_seg}" in *" bias "*|*" grib2 "*) module load cfp/${cfp_ver} util_shared/${util_shared_ver} ;; esac
case "${_seg}" in *" grib2 "*) module load grib_util/${grib_util_ver} ;; esac
case "${_seg}" in *" anomaly "*|*" bias "*) module load ve/stofs/${ve_stofs} ;; esac

module list
