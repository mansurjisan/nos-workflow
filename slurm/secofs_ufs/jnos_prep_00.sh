#!/bin/bash
# ============================================================================
# EDIT BEFORE FIRST RUN -- every /work/PLACEHOLDER/... path below is a
# stand-in for wherever this package, scratch, and the staged COMIN tree
# actually live on Hercules (PACKAGEROOT, COMROOT_STAGED, RPTDIR/WORKDIR,
# COMROOT/DCOMROOT/DATAROOT). Replace all of them before submitting.
# ============================================================================
#SBATCH --job-name=secofs_ufs_prep_00
#SBATCH --account=nos-surge
#SBATCH --qos=batch
#SBATCH --partition=hercules
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --time=02:00:00
#SBATCH --output=/dev/null
#SBATCH --error=/dev/null

PACKAGEROOT=${PACKAGEROOT:-/work/PLACEHOLDER/packages}
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the
# resolver silently applies the WCOSS2 profile (PPN=120 on an 80-core node).
export NOS_MACHINE=hercules

# Working directory
RPTDIR=/work/PLACEHOLDER/ptmp/$LOGNAME/rpt/secofs_ufs
WORKDIR=/work/PLACEHOLDER/ptmp/$LOGNAME/work/secofs_ufs
mkdir -p -m 755 $RPTDIR $WORKDIR

# Per-job log files (Slurm jobid as suffix). #SBATCH -o/-e are pointed at
# /dev/null above; this redirect is what populates prep logs.
_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/secofs_ufs_prep_00.${_JOBID}"
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== secofs_ufs_prep_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR}

# Module setup -- nos_hercules.intel (drafted by a parallel workstream)
# stands in for the whole WCOSS2 module chain (COMF/nosofs + ESMF).
module use ${PACKAGEROOT}/nos-workflow/modulefiles
module load nos_hercules.intel

module list

# EXPORT list
set +x
export envir=dev
export OFS=${OFS:-secofs_ufs}
export cyc=${CYC:-00}
export NET=nos
export model=nosofs
export job=secofs_ufs_prep_${cyc}_$envir
export platform=ptmp

export KEEPDATA=YES
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO

# Data and COM paths
export COMROOT=/work/PLACEHOLDER/ptmp/$LOGNAME/com
export DCOMROOT=/work/PLACEHOLDER/prod/dcom
export DATAROOT=/work/PLACEHOLDER/ptmp/$LOGNAME/work/${OFS}

# Input data for DATM forcing generation, staged ahead of the run --
# stage_comin.py (parallel workstream) populates this tree from the
# WCOSS2/NOMADS sources the pbs cards read directly.
export COMROOT_STAGED=${COMROOT_STAGED:-/work/PLACEHOLDER/comin}
export COMINgfs=${COMINgfs:-$COMROOT_STAGED/gfs}
export COMINhrrr=${COMINhrrr:-$COMROOT_STAGED/hrrr}
export COMINrtofs_2d=${COMINrtofs_2d:-$COMROOT_STAGED/rtofs}
export COMINrtofs_3d=${COMINrtofs_3d:-$COMROOT_STAGED/rtofs}
export COMINnwm=${COMINnwm:-$COMROOT_STAGED/nwm}

################################################
# CALL executable job script here
export pbsid=${SLURM_JOB_ID}
export job=${job:-$SLURM_JOB_NAME}
export jobid=${jobid:-$job.$SLURM_JOB_ID}

# YAML configuration for secofs_ufs
export HOMEnos=${PACKAGEROOT}/nos-workflow
export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS}.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

# Use nos-utils (Python) for the full prep pipeline -- see pbs/jnos_prep_00.pbs
# for what USE_PYTHON_PREP / FULL_PYTHON_PREP drive.
export USE_PYTHON_PREP=YES
export FULL_PYTHON_PREP=YES

${HOMEnos}/jobs/JNOS_PREP
