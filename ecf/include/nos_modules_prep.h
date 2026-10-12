#=============================================================================
# nos_modules_prep.h - WCOSS2 modules for the prep and post stages.
# Same set as pbs/jnos_prep_00.pbs; versions come from versions/run.ver.
#=============================================================================
set +u
module purge
module load envvar/${envvar_ver}
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
module load python/${python_ver}
module load prod_envir/${prod_envir_ver}
module load prod_util/${prod_util_ver}
module load cfp/${cfp_ver}
module load libjpeg/${libjpeg_ver}
module load grib_util/${grib_util_ver}
module load gsl/${gsl_ver}
module load wgrib2/${wgrib2_ver}
module load nco/${nco_ver}
# ESMF_Scrip2Unstruct for the DATM mesh (prep only; harmless for post)
module load esmf/${esmf_ver:-8.4.2} 2>/dev/null || echo "WARNING: esmf module not available"
module list
set -u
