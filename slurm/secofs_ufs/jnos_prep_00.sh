#!/bin/bash
# ============================================================================
# PACKAGEROOT/RPTDIR/WORKDIR/COMROOT/DATAROOT default to the nos-surge
# Hercules account (verified 2026-08-27); override via env/sbatch --export
# for a different account. DCOMROOT/COMROOT_STAGED still say
# /work/PLACEHOLDER -- unused by the secofs_ufs UFS prep/nowcast/forecast/
# post path (COMROOT_STAGED is normally supplied by the caller); edit only
# if a downstream script starts reading them.
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

PACKAGEROOT=${PACKAGEROOT:-/work2/noaa/nos-surge/mjisan}
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the
# resolver silently applies the WCOSS2 profile (PPN=120 on an 80-core node).
export NOS_MACHINE=hercules

# Working directory
NOS_PTMP=${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}
RPTDIR=${RPTDIR:-${NOS_PTMP}/$LOGNAME/rpt/secofs_ufs}
WORKDIR=${WORKDIR:-${NOS_PTMP}/$LOGNAME/work/secofs_ufs}
mkdir -p -m 755 $RPTDIR $WORKDIR || { echo "FATAL: cannot create RPTDIR/WORKDIR ($RPTDIR, $WORKDIR)"; exit 1; }

# Per-job log files (Slurm jobid as suffix). The #SBATCH -o/-e above catch
# only Slurm's own epilogue (TIME LIMIT / node-failure kills, which a
# SIGKILLed job never lives long enough to redirect itself); this exec
# redirect is what populates the real prep logs.
_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/secofs_ufs_prep_00.${_JOBID}"
touch "${_LOG_PREFIX}.out" "${_LOG_PREFIX}.err" || { echo "FATAL: cannot write to RPTDIR ($RPTDIR)"; exit 1; }
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== secofs_ufs_prep_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR} || exit 1

# Module setup -- modulefiles/nos_hercules.intel.lua stands in for the
# whole WCOSS2 module chain (COMF/nosofs + ESMF).
module purge
module use ${PACKAGEROOT}/nos-workflow/modulefiles
module load nos_hercules.intel
# python venv overlay: scipy + editable nos-utils live outside the spack stack
NOS_VENV=${NOS_VENV:-${VENV_PATH:-$HOME/nos-venv}}
if [ -f "${NOS_VENV}/bin/activate" ]; then . "${NOS_VENV}/bin/activate"; fi

module list

# Preflight: front-load the known-unverified env risks (wgrib2 IPOLATES
# support, python packages) before any data is touched, instead of failing
# partway through the prep pipeline.
command -v wgrib2 >/dev/null 2>&1 || { echo "FATAL: wgrib2 not found on PATH -- module spider wgrib2"; exit 1; }
if ! wgrib2 -config 2>/dev/null | grep -qi ipolates; then
    # A token-presence grep against -config can false-fail on wording alone,
    # so this is a warning, not a gate: dump the full config for a human to
    # check, and only actually block if HRRR -new_grid regridding fails.
    echo "WARNING: wgrib2 -config has no IPOLATES token -- needed for HRRR -new_grid regridding. This may be a false negative (differing -config wording); verify manually, or drop hrrr from staging/forcing (GFS-only) if regridding fails. Full wgrib2 -config below:"
    wgrib2 -config 2>&1 | head -20
fi
command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 not found on PATH -- module spider python"; exit 1; }
python3 -c 'import numpy, netCDF4, yaml, scipy, pandas, xarray' 2>/dev/null || { echo "FATAL: python3 is missing one of numpy/netCDF4/yaml/scipy/pandas/xarray -- module spider py-scipy/py-pandas/py-xarray (or the relevant py-* module)"; exit 1; }

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
export PACKAGEROOT=${PACKAGEROOT:-/work2/noaa/nos-surge/mjisan}

# Data and COM paths
export COMROOT=${COMROOT:-${NOS_PTMP}/$LOGNAME/com}
export DCOMROOT=/work/PLACEHOLDER/prod/dcom
export DATAROOT=${DATAROOT:-${NOS_PTMP}/$LOGNAME/work/${OFS}}

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
