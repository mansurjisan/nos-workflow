#=============================================================================
# nos_modules_model.h - WCOSS2 modules for the nowcast and forecast stages.
#
# The UFS-Coastal executable is built against the hpc-stack in
# modulefiles/modules.fv3.lua, which differs from the system modules used by
# prep/post. Same sequence as pbs/jnos_nowcast_00.pbs.
#=============================================================================
set +u
module purge
module reset
# run.ver pins versions (e.g. PrgEnv_intel_ver=8.3.3) that would override the
# modules.fv3.lua defaults the executable was compiled with.
unset PrgEnv_intel_ver craype_ver cmake_ver g2_ver w3emc_ver 2>/dev/null || true
module use ${HOMEnos}/modulefiles
module load modules.fv3
module load cray-pals
module load python/${python_ver}
module load prod_envir/${prod_envir_ver}
module load prod_util/${prod_util_ver}
module list
set -u
