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
# No #SBATCH -o/-e above: Slurm's default slurm-%j.out catches its own
# epilogue (TIME LIMIT / node-failure kills), while this script self-
# redirects its own log below.

PACKAGEROOT=${PACKAGEROOT:-/work/PLACEHOLDER/packages}
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the
# resolver silently applies the WCOSS2 profile (PPN=120 on an 80-core node).
export NOS_MACHINE=hercules

# Working directory
export OFS=${OFS:-secofs_ufs}
RPTDIR=/work/PLACEHOLDER/ptmp/$LOGNAME/rpt/${OFS}
WORKDIR=/work/PLACEHOLDER/ptmp/$LOGNAME/work/${OFS}
mkdir -p -m 755 $RPTDIR $WORKDIR || { echo "FATAL: cannot create RPTDIR/WORKDIR ($RPTDIR, $WORKDIR) -- edit the /work/PLACEHOLDER paths above before submitting"; exit 1; }

# Per-job log files (Slurm jobid as suffix). #SBATCH -o/-e are omitted
# above (see the epilogue note); this redirect is what populates post logs.
_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/secofs_ufs_post_00.${_JOBID}"
touch "${_LOG_PREFIX}.out" "${_LOG_PREFIX}.err" || { echo "FATAL: cannot write to RPTDIR ($RPTDIR) -- edit the /work/PLACEHOLDER paths above before submitting"; exit 1; }
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== secofs_ufs_post_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR} || exit 1

# Module setup -- modulefiles/nos_hercules.intel.lua stands in for the
# WCOSS2 post module chain (Python + NCO, not UFS hpc-stack).
module purge
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

# Unified package root (STOFS + COMF scripts, J-jobs, YAML config)
export PACKAGEROOT=${PACKAGEROOT:-/work/PLACEHOLDER/packages}

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
