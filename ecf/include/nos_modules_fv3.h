# nos_modules_fv3.h - nowcast and forecast modules of the UFS-Coastal systems, as pbs/jnos_nowcast_00.pbs. MJ (10/20/26)
module purge
module reset

# run.ver pins versions that would override the modules.fv3.lua defaults the executable was built with. MJ (10/20/26)
unset PrgEnv_intel_ver craype_ver cmake_ver g2_ver w3emc_ver 2>/dev/null || true

module use ${HOMEnos}/modulefiles
module load modules.fv3
module load cray-pals
module load python/${python_ver:-3.8.6}
module load prod_envir/${prod_envir_ver:-2.0.6}
# prod_util/2.0.17 from run.ver is unknown on WCOSS2 and the cards run without it; a failed load must not end the task. MJ (10/21/26)
module load prod_util/${prod_util_ver:-2.0.17} || echo "WARNING: prod_util not loaded"
module list
