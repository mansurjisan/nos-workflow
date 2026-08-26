#!/bin/bash
# ============================================================================
# EDIT BEFORE FIRST RUN -- every /work/PLACEHOLDER/... path below is a
# stand-in for wherever this package and scratch actually live on Hercules
# (PACKAGEROOT, RPTDIR/WORKDIR, COMPATH/COMROOT/DCOMROOT/DATAROOT). Replace
# all of them before submitting.
# ============================================================================
#SBATCH --job-name=secofs_ufs_post_00
#SBATCH --account=nos-surge
#SBATCH --qos=batch
#SBATCH --partition=hercules
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --time=02:00:00
# NOT /dev/null: Slurm writes its own epilogue here -- "TIME LIMIT" /
# node-failure kills -- and that is the one message the in-script redirect
# below cannot capture, because a SIGKILLed job never reaches any trap.
# These files stay near-empty; the real logs are the redirect below.

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

# Per-job log files (Slurm jobid as suffix). #SBATCH -o/-e are omitted
# above (see the epilogue note); this redirect is what populates post logs.
_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/secofs_ufs_post_00.${_JOBID}"
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== secofs_ufs_post_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR}

# Module setup -- nos_hercules.intel (drafted by a parallel workstream)
# stands in for the WCOSS2 post module chain (Python + NCO, not UFS hpc-stack).
module use ${PACKAGEROOT}/nos-workflow/modulefiles
module load nos_hercules.intel

module list

# EXPORT list
set +x
export envir=dev
export OFS=${OFS:-secofs_ufs}
export cyc=${CYC:-00}
export PDY=${PDY:-$(date +%Y%m%d)}
export job=secofs_ufs_post_${cyc}_$envir
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

################################################
# CALL executable job script here
export pbsid=${SLURM_JOB_ID}
export job=${job:-$SLURM_JOB_NAME}
export jobid=${jobid:-$job.$SLURM_JOB_ID}

# YAML configuration for secofs_ufs
export HOMEnos=${PACKAGEROOT}/nos-workflow
export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS}.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

${HOMEnos}/jobs/JNOS_POST
