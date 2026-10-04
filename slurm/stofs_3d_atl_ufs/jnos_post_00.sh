#!/bin/bash
# ============================================================================
# STOFS-3D-ATL UFS-COUPLED (DATM + CMEPS + SCHISM, fv3_stofs_3d_atl.exe)
# post on Hercules, cycle 12z (file name _00 matches the pbs cards).
#
# Required env (sbatch passes the caller's environment): PDY, and for prep DCOMROOT
# (bundle dcom dir, laid out dcom/YYYYMMDD/...). Optional: CYC (default 12), COMROOT,
# COMROOT_STAGED (stage_comin.py output), PACKAGEROOT, NOS_PTMP, NOS_VENV, COMINrerun.
# Do NOT chain stages with --dependency=afterok (JNOS_* can exit 0 after a failed stage);
# submit each stage after the previous one logs STAGE_SUMMARY status=PASS. MJ (10/04/26)
# ============================================================================
#SBATCH --job-name=stofs_3d_atl_ufs_post_00
#SBATCH --account=nos-surge
#SBATCH --qos=batch
#SBATCH --partition=hercules
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --time=01:00:00
# No #SBATCH -o/-e: Slurm's default slurm-%j.out catches its own epilogue, the script
# self-redirects its own log below.

PACKAGEROOT=${PACKAGEROOT:-/work2/noaa/nos-surge/mjisan}
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the resolver
# silently applies the WCOSS2 profile (PPN=120 on an 80-core node).
export NOS_MACHINE=hercules

# Standalone and coupled use the same RUN name and need SEPARATE COMROOTs. MJ (10/04/26)
export OFS=${OFS:-stofs_3d_atl_ufs}
NOS_PTMP=${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}
RPTDIR=${RPTDIR:-${NOS_PTMP}/$LOGNAME/rpt/${OFS}}
WORKDIR=${WORKDIR:-${NOS_PTMP}/$LOGNAME/work/stofs_3d_atl_ufs}
mkdir -p -m 755 $RPTDIR $WORKDIR || { echo "FATAL: cannot create RPTDIR/WORKDIR ($RPTDIR, $WORKDIR)"; exit 1; }

_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/stofs_3d_atl_ufs_post_00.${_JOBID}"
touch "${_LOG_PREFIX}.out" "${_LOG_PREFIX}.err" || { echo "FATAL: cannot write to RPTDIR ($RPTDIR)"; exit 1; }
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== stofs_3d_atl_ufs_post_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR} || exit 1

module purge
module use ${PACKAGEROOT}/nos-workflow/modulefiles
module load nos_hercules.intel
# python venv overlay: scipy + editable nos-utils live outside the spack stack
NOS_VENV=${NOS_VENV:-${VENV_PATH:-$HOME/nos-venv}}
if [ -f "${NOS_VENV}/bin/activate" ]; then . "${NOS_VENV}/bin/activate"; fi

module list

# EXPORT list
set +x
export envir=dev
export OFS=${OFS:-stofs_3d_atl_ufs}
export cyc=${CYC:-12}
export CYC=${cyc}
export PDY=${PDY:?set PDY (YYYYMMDD)}
export job=stofs_3d_atl_ufs_post_${cyc}_$envir
export platform=ptmp
export framework=stofs_ufs

export KEEPDATA=YES
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO
# Archive manifest on: ATL standalone stages flux.th and the run inputs through it.
export NOS_ARCHIVE_MANIFEST=${NOS_ARCHIVE_MANIFEST:-YES}

export PACKAGEROOT=${PACKAGEROOT:-/work2/noaa/nos-surge/mjisan}

# Data and COM paths
export COMROOT=${COMROOT:-${NOS_PTMP}/$LOGNAME/com_atl_ufs}
export DATAROOT=${DATAROOT:-${NOS_PTMP}/$LOGNAME/work/stofs_3d_atl_ufs}

################################################
# CALL executable job script here
export pbsid=${SLURM_JOB_ID}
export job=${job:-$SLURM_JOB_NAME}
export jobid=${jobid:-$job.$SLURM_JOB_ID}

export HOMEnos=${PACKAGEROOT}/nos-workflow
export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS}.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

${HOMEnos}/jobs/JNOS_POST
