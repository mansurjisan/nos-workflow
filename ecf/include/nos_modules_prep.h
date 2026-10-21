# nos_modules_prep.h - prep stage modules, as pbs/jnos_prep_00.pbs (ESMF for the DATM mesh). MJ (10/20/26)
module purge
module load envvar/${envvar_ver:-1.0}
module load intel/${intel_ver:-19.1.3.304}
module load PrgEnv-intel/${PrgEnv_intel_ver:-8.1.0}
module load craype/${craype_ver:-2.7.8}
module load cray-mpich/${cray_mpich_ver:-8.1.7}
module load cray-pals/${cray_pals_ver:-1.0.12}
module load hdf5/${hdf5_ver:-1.10.6}
module load netcdf/${netcdf_ver:-4.7.4}
module load jasper/${jasper_ver:-2.0.25}
module load udunits/${udunits_ver:-2.2.28}
module load zlib/${zlib_ver:-1.2.11}
module load bufr/${bufr_ver:-11.5.0}
module load g2/${g2_ver:-3.4.5}
module load w3nco/${w3nco_ver:-2.4.1}
module load w3emc/${w3emc_ver:-2.9.2}
module load subversion/${subversion_ver:-1.14.0}
module load python/${python_ver:-3.8.6}
module load prod_envir/${prod_envir_ver:-2.0.6}
module load prod_util/${prod_util_ver:-2.0.17}
module load cfp/${cfp_ver:-2.0.4}
module load libjpeg/${libjpeg_ver:-9c}
module load grib_util/${grib_util_ver:-1.2.4}
module load gsl/${gsl_ver:-2.7}
module load wgrib2/${wgrib2_ver:-2.0.8}
module load nco/${nco_ver:-5.0.6}
module load esmf/${esmf_ver:-8.4.2} 2>/dev/null || echo "WARNING: esmf module not available"
module list
