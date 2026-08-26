#!/bin/bash
# ============================================================================
# EDIT BEFORE FIRST RUN -- every /work/PLACEHOLDER/... path below is a
# stand-in for wherever this package, scratch, and the staged COMIN tree
# actually live on Hercules (PACKAGEROOT, COMROOT_STAGED, RPTDIR/WORKDIR,
# COMPATH/COMROOT/DCOMROOT/DATAROOT). Replace all of them before submitting.
# ============================================================================
#SBATCH --job-name=secofs_ufs_fc_00
#SBATCH --account=nos-surge
#SBATCH --qos=batch
#SBATCH --partition=hercules
#SBATCH --nodes=37
#SBATCH --ntasks-per-node=80
#SBATCH --exclusive
#SBATCH --time=05:30:00
#SBATCH --output=/dev/null
#SBATCH --error=/dev/null

PACKAGEROOT=${PACKAGEROOT:-/work/PLACEHOLDER/packages}
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the
# resolver silently applies the WCOSS2 profile (PPN=120 on an 80-core node).
export NOS_MACHINE=hercules

# Working directory
export OFS=${OFS:-secofs_ufs}
RPTDIR=/work/PLACEHOLDER/ptmp/$LOGNAME/rpt/${OFS}
WORKDIR=/work/PLACEHOLDER/ptmp/$LOGNAME/work/${OFS}
mkdir -p -m 755 $RPTDIR $WORKDIR

# Per-job log files (Slurm jobid as suffix). #SBATCH -o/-e are pointed at
# /dev/null above; this redirect is what populates forecast logs.
_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/secofs_ufs_forecast_00.${_JOBID}"
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== secofs_ufs_forecast_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR}

# Module setup -- modulefiles/nos_hercules.intel.lua stands in for the
# WCOSS2 hpc-stack chain (modules.fv3, cray-pals, ...).
module use ${PACKAGEROOT}/nos-workflow/modulefiles
module load nos_hercules.intel

module list

# MPI/OpenMP tuning proven for ufs-coastal on Hercules.
ulimit -s unlimited
export OMP_STACKSIZE=512M
export KMP_AFFINITY=scatter
export OMP_NUM_THREADS=1
export I_MPI_EXTRA_FILESYSTEM=ON
export FI_MLX_INJECT_LIMIT=0

# EXPORT list
set +x
export envir=dev
export OFS=${OFS:-secofs_ufs}
export cyc=${CYC:-00}
export PDY=${PDY:-$(date +%Y%m%d)}
export job=secofs_ufs_fc_00_$envir
export platform=ptmp

export KEEPDATA=YES
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO

# Data and COM paths
export COMPATH=/work/PLACEHOLDER/prod/com/nos
export COMROOT=/work/PLACEHOLDER/ptmp/$LOGNAME/com
export DCOMROOT=/work/PLACEHOLDER/prod/dcom
export DATAROOT=/work/PLACEHOLDER/ptmp/$LOGNAME/work/${OFS}
export COMIN=/work/PLACEHOLDER/prod/com

# Input data, staged ahead of the run -- ${HOMEnos}/ush/stage_comin.py
# populates this tree from the WCOSS2/NOMADS sources the pbs cards read
# directly.
export COMROOT_STAGED=${COMROOT_STAGED:-/work/PLACEHOLDER/comin}
export COMINnam=${COMINnam:-$COMROOT_STAGED/nam}
export COMINhrrr=${COMINhrrr:-$COMROOT_STAGED/hrrr}
export COMINrap=${COMINrap:-$COMROOT_STAGED/rap}
export COMINgfs=${COMINgfs:-$COMROOT_STAGED/gfs}
export COMINrtma=${COMINrtma:-$COMROOT_STAGED/rtma}
export COMINetss=${COMINetss:-$COMROOT_STAGED/petss}
export COMINrtofs_2d=${COMINrtofs_2d:-$COMROOT_STAGED/rtofs}
export COMINrtofs_3d=${COMINrtofs_3d:-$COMROOT_STAGED/rtofs}
export COMINnwm=${COMINnwm:-$COMROOT_STAGED/nwm}

# UFS-Coastal: MED+ATM share PETs 0-119, OCN PETs 120-2913.
export TOTAL_TASKS=${TOTAL_TASKS:-2914}

################################################
# CALL executable job script here
export pbsid=${SLURM_JOB_ID}
export job=${job:-$SLURM_JOB_NAME}
export jobid=${jobid:-$job.$SLURM_JOB_ID}

# YAML configuration for secofs_ufs
export HOMEnos=${PACKAGEROOT}/nos-workflow
export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS}.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

# Submit sequentially after each leg succeeds -- sbatch --dependency=afterok
# jnos_nowcast_00.sh, then this card, then jnos_post_00.sh.

# Filesystem-sync guard: staged inputs must be visible on every compute node
# before the parallel job starts reading them.
sync && sleep 1
${HOMEnos}/jobs/JNOS_FORECAST
