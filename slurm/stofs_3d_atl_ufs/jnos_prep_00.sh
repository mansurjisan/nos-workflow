#!/bin/bash
# ============================================================================
# STOFS-3D-ATL UFS-COUPLED (DATM + CMEPS + SCHISM, fv3_stofs_3d_atl.exe)
# prep on Hercules, cycle 12z (file name _00 matches the pbs cards).
#
# Required env (sbatch passes the caller's environment): PDY, and for prep DCOMROOT
# (bundle dcom dir, laid out dcom/YYYYMMDD/...). Optional: CYC (default 12), COMROOT,
# COMROOT_STAGED (stage_comin.py output), PACKAGEROOT, NOS_PTMP, NOS_VENV, COMINrerun.
# Do NOT chain stages with --dependency=afterok (JNOS_* can exit 0 after a failed stage);
# submit each stage after the previous one logs STAGE_SUMMARY status=PASS. MJ (10/04/26)
# ============================================================================
#SBATCH --job-name=stofs_3d_atl_ufs_prep_00
#SBATCH --account=nos-surge
#SBATCH --qos=batch
#SBATCH --partition=hercules
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --time=03:00:00
#SBATCH --output=%x.%j.out
#SBATCH --error=%x.%j.err

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
_LOG_PREFIX="$RPTDIR/stofs_3d_atl_ufs_prep_00.${_JOBID}"
touch "${_LOG_PREFIX}.out" "${_LOG_PREFIX}.err" || { echo "FATAL: cannot write to RPTDIR ($RPTDIR)"; exit 1; }
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== stofs_3d_atl_ufs_prep_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR} || exit 1

module purge
module use ${PACKAGEROOT}/nos-workflow/modulefiles
module load nos_hercules.intel
# python venv overlay: scipy + editable nos-utils live outside the spack stack
NOS_VENV=${NOS_VENV:-${VENV_PATH:-$HOME/nos-venv}}
if [ -f "${NOS_VENV}/bin/activate" ]; then . "${NOS_VENV}/bin/activate"; fi

module list

command -v wgrib2 >/dev/null 2>&1 || { echo "FATAL: wgrib2 not found on PATH -- module spider wgrib2"; exit 1; }
if ! wgrib2 -config 2>/dev/null | grep -qi ipolates; then
    echo "WARNING: wgrib2 -config has no IPOLATES token -- needed for HRRR -new_grid regridding (may be a false negative)"
    wgrib2 -config 2>&1 | head -20
fi
python3 -c 'import numpy, netCDF4, yaml, scipy, pandas, xarray' 2>/dev/null || { echo "FATAL: python3 is missing one of numpy/netCDF4/yaml/scipy/pandas/xarray"; exit 1; }
: "${DCOMROOT:?set DCOMROOT to the bundle dcom dir (dcom/YYYYMMDD/{coops_waterlvlobs,can_streamgauge,validation_data})}"
[ -d "${DCOMROOT}/${PDY:?set PDY}" ] || { echo "FATAL: ${DCOMROOT}/${PDY} missing"; exit 1; }

# EXPORT list
set +x
export envir=dev
export OFS=${OFS:-stofs_3d_atl_ufs}
export cyc=${CYC:-12}
export CYC=${cyc}
export PDY=${PDY:?set PDY (YYYYMMDD)}
export NET=nos
export model=nosofs
export job=stofs_3d_atl_ufs_prep_${cyc}_$envir
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
# dcom inputs (ADT, CO-OPS water level, St. Lawrence) come from the case bundle.
export DCOMROOT

# Public-bucket inputs staged by ush/stage_comin.py --profile stofs_3d_atl.
export COMROOT_STAGED=${COMROOT_STAGED:-${NOS_PTMP}/$LOGNAME/comin_atl}
export COMINgfs=${COMINgfs:-$COMROOT_STAGED/gfs}
export COMINhrrr=${COMINhrrr:-$COMROOT_STAGED/hrrr}
export COMINrtofs_2d=${COMINrtofs_2d:-$COMROOT_STAGED/rtofs}
export COMINrtofs_3d=${COMINrtofs_3d:-$COMROOT_STAGED/rtofs}
export COMINnwm=${COMINnwm:-$COMROOT_STAGED/nwm}
# Previous-cycle dynamic-adjust seed: lay it out with tools/hercules_atl_seed_prev.sh
# (COMOUT_PREV layout, read by default) or export COMINrerun=<seed dir> to override.

################################################
# CALL executable job script here
export pbsid=${SLURM_JOB_ID}
export job=${job:-$SLURM_JOB_NAME}
export jobid=${jobid:-$job.$SLURM_JOB_ID}

export HOMEnos=${PACKAGEROOT}/nos-workflow
export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS}.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

export USE_PYTHON_PREP=YES
export FULL_PYTHON_PREP=YES

${HOMEnos}/jobs/JNOS_PREP
