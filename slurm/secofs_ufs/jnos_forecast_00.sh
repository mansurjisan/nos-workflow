#!/bin/bash
# ============================================================================
# PACKAGEROOT/RPTDIR/WORKDIR/COMROOT/DATAROOT default to the nos-surge
# Hercules account (verified 2026-08-27); override via env/sbatch --export
# for a different account. COMPATH/COMIN/DCOMROOT/COMROOT_STAGED still say
# /work/PLACEHOLDER -- unused by the secofs_ufs UFS prep/nowcast/forecast/
# post path (COMROOT_STAGED is normally supplied by the caller); edit only
# if a downstream script starts reading them.
# ============================================================================
#SBATCH --job-name=secofs_ufs_fc_00
#SBATCH --account=nos-surge
#SBATCH --qos=batch
#SBATCH --partition=hercules
#SBATCH --nodes=37
#SBATCH --ntasks-per-node=80
#SBATCH --exclusive
#SBATCH --time=05:30:00
#SBATCH --output=%x.%j.out
#SBATCH --error=%x.%j.err

PACKAGEROOT=${PACKAGEROOT:-/work2/noaa/nos-surge/mjisan}
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the
# resolver silently applies the WCOSS2 profile (PPN=120 on an 80-core node).
export NOS_MACHINE=hercules

# Working directory
export OFS=${OFS:-secofs_ufs}
RPTDIR=/work2/noaa/nos-surge/mjisan/nos-run/ptmp/$LOGNAME/rpt/${OFS}
WORKDIR=/work2/noaa/nos-surge/mjisan/nos-run/ptmp/$LOGNAME/work/${OFS}
mkdir -p -m 755 $RPTDIR $WORKDIR || { echo "FATAL: cannot create RPTDIR/WORKDIR ($RPTDIR, $WORKDIR)"; exit 1; }

# Per-job log files (Slurm jobid as suffix). The #SBATCH -o/-e above catch
# only Slurm's own epilogue (TIME LIMIT / node-failure kills, which a
# SIGKILLed job never lives long enough to redirect itself); this exec
# redirect is what populates the real forecast logs.
_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/secofs_ufs_forecast_00.${_JOBID}"
touch "${_LOG_PREFIX}.out" "${_LOG_PREFIX}.err" || { echo "FATAL: cannot write to RPTDIR ($RPTDIR)"; exit 1; }
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== secofs_ufs_forecast_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR} || exit 1

# Module setup -- modulefiles/nos_hercules.intel.lua stands in for the
# WCOSS2 hpc-stack chain (modules.fv3, cray-pals, ...).
module purge
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

# Unified package root (STOFS + COMF scripts, J-jobs, YAML config)
export PACKAGEROOT=${PACKAGEROOT:-/work2/noaa/nos-surge/mjisan}

# Data and COM paths
export COMPATH=/work/PLACEHOLDER/prod/com/nos
export COMROOT=/work2/noaa/nos-surge/mjisan/nos-run/ptmp/$LOGNAME/com
export DCOMROOT=/work/PLACEHOLDER/prod/dcom
export DATAROOT=/work2/noaa/nos-surge/mjisan/nos-run/ptmp/$LOGNAME/work/${OFS}
export COMIN=/work/PLACEHOLDER/prod/com

# Input data, staged ahead of the run -- ${HOMEnos}/ush/stage_comin.py
# populates this tree from the WCOSS2/NOMADS sources the pbs cards read
# directly. secofs_ufs.yaml only names gfs/hrrr forcing sources -- nam/
# rap/rtma/etss are never staged or read, so no COMIN exports for them.
export COMROOT_STAGED=${COMROOT_STAGED:-/work/PLACEHOLDER/comin}
export COMINhrrr=${COMINhrrr:-$COMROOT_STAGED/hrrr}
export COMINgfs=${COMINgfs:-$COMROOT_STAGED/gfs}
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

# Submission: do NOT chain these with `sbatch --dependency=afterok:` --
# JNOS_* does not reliably propagate the stage exit code (it ends on
# postmsg/date), so a crashed leg can still exit 0 and an afterok dependent
# would run on bad output. Submit sequentially after each leg succeeds
# instead, gating on the STAGE_SUMMARY line each stage writes to its log
# (see pbs/launch_secofs_ufs.sh, which polls exactly that):
#   sbatch jnos_nowcast_00.sh    # wait for STAGE_SUMMARY status=PASS
#   sbatch jnos_forecast_00.sh   # after nowcast PASS
#   sbatch jnos_post_00.sh       # after forecast PASS

# Filesystem-sync guard: staged inputs must be visible on every compute node
# before the parallel job starts reading them.
sync && sleep 1
${HOMEnos}/jobs/JNOS_FORECAST
