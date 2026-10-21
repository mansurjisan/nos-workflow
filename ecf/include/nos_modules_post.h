# nos_modules_post.h - post stage modules, as pbs/jnos_post_00.pbs. MJ (10/20/26)
module purge
module load envvar/${envvar_ver:-1.0}
module load intel/${intel_ver:-19.1.3.304}
module load PrgEnv-intel/${PrgEnv_intel_ver:-8.1.0}
module load craype/${craype_ver:-2.7.8}
module load cray-mpich/${cray_mpich_ver:-8.1.7}
module load cray-pals/${cray_pals_ver:-1.0.12}
module load hdf5/${hdf5_ver:-1.10.6}
module load netcdf/${netcdf_ver:-4.7.4}

# The stock python lacks shapely.make_valid, so the geopackage product would silently vanish; ops uses ve/stofs. MJ (10/20/26)
module unload python 2>/dev/null || true
module load ve/stofs${ve_stofs:+/${ve_stofs}}
module load prod_envir/${prod_envir_ver:-2.0.6}
# prod_util/2.0.17 from run.ver is unknown on WCOSS2 and the cards run without it; a failed load must not end the task. MJ (10/21/26)
module load prod_util/${prod_util_ver:-2.0.17} || echo "WARNING: prod_util not loaded"
module load udunits/${udunits_ver:-2.2.28}
module load gsl/${gsl_ver:-2.7}
module load nco/${nco_ver:-5.0.6}
module list
