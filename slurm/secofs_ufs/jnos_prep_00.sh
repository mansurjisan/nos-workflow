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
#SBATCH --output=%x.%j.out
#SBATCH --error=%x.%j.err

PACKAGEROOT=${PACKAGEROOT:-/work/PLACEHOLDER/packages}
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the
# resolver silently applies the WCOSS2 profile (PPN=120 on an 80-core node).
export NOS_MACHINE=hercules

# Working directory
RPTDIR=/work/PLACEHOLDER/ptmp/$LOGNAME/rpt/secofs_ufs
WORKDIR=/work/PLACEHOLDER/ptmp/$LOGNAME/work/secofs_ufs
mkdir -p -m 755 $RPTDIR $WORKDIR || { echo "FATAL: cannot create RPTDIR/WORKDIR ($RPTDIR, $WORKDIR) -- edit the /work/PLACEHOLDER paths above before submitting"; exit 1; }

# Per-job log files (Slurm jobid as suffix). The #SBATCH -o/-e above catch
# only Slurm's own epilogue (TIME LIMIT / node-failure kills, which a
# SIGKILLed job never lives long enough to redirect itself); this exec
# redirect is what populates the real prep logs.
_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/secofs_ufs_prep_00.${_JOBID}"
touch "${_LOG_PREFIX}.out" "${_LOG_PREFIX}.err" || { echo "FATAL: cannot write to RPTDIR ($RPTDIR) -- edit the /work/PLACEHOLDER paths above before submitting"; exit 1; }
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== secofs_ufs_prep_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR} || exit 1

# Module setup -- modulefiles/nos_hercules.intel.lua stands in for the
# whole WCOSS2 module chain (COMF/nosofs + ESMF).
module purge
module use ${PACKAGEROOT}/nos-workflow/modulefiles
module load nos_hercules.intel

module list

# Preflight: front-load the two known-unverified env risks (wgrib2
# IPOLATES support, py-scipy) before any data is touched, instead of
# failing partway through the prep pipeline.
command -v wgrib2 >/dev/null 2>&1 || { echo "FATAL: wgrib2 not found on PATH -- module spider wgrib2"; exit 1; }
wgrib2 -config 2>/dev/null | grep -qi ipolates || { echo "FATAL: wgrib2 lacks IPOLATES (needed for HRRR -new_grid regridding); rebuild wgrib2 with IPOLATES or run GFS-only (drop hrrr from staging/forcing)"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 not found on PATH -- module spider python"; exit 1; }
python3 -c 'import numpy, netCDF4, yaml, scipy' 2>/dev/null || { echo "FATAL: python3 is missing one of numpy/netCDF4/yaml/scipy -- module spider py-scipy (or the relevant py-* module)"; exit 1; }

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

# Unified package root (STOFS + COMF scripts, J-jobs, YAML config)
export PACKAGEROOT=${PACKAGEROOT:-/work/PLACEHOLDER/packages}

# Data and COM paths
export COMROOT=/work/PLACEHOLDER/ptmp/$LOGNAME/com
export DCOMROOT=/work/PLACEHOLDER/prod/dcom
export DATAROOT=/work/PLACEHOLDER/ptmp/$LOGNAME/work/${OFS}

# Input data for DATM forcing generation, staged ahead of the run --
# ${HOMEnos}/ush/stage_comin.py populates this tree from the WCOSS2/NOMADS
# sources the pbs cards read directly.
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
