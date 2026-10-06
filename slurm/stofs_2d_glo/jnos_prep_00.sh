#!/bin/bash
# ============================================================================
# STOFS-2D-Global (ADCIRC padcirc) prep on Hercules, cycle 12z by default (file name _00 matches the pbs cards).
#
# adcprep is serial (about 85 min on the 12.8 M node mesh); the decomposition is cached at $COMGES/<RUN>_4064.tar. MJ (10/05/26)
#
# Required env (sbatch passes the caller's environment): PDY, PACKAGEROOT, ADCIRC_EXEC_DIR (dir holding
# padcirc and adcprep; no module exists on Hercules). Optional: CYC (default 12; 00/06/12/18), COMROOT_2DGLO
# (isolated test COMROOT), COMROOT_STAGED (GFS under <it>/gfs), NOS_PTMP, NOS_VENV.
# ============================================================================
#SBATCH --job-name=stofs_2d_glo_prep_00
#SBATCH --account=nos-surge
#SBATCH --qos=batch
#SBATCH --partition=hercules
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --mem=0
#SBATCH --time=06:00:00
#SBATCH --output=%x.%j.out
#SBATCH --error=%x.%j.err

# PACKAGEROOT must be set explicitly: a default could pick up the SECOFS or ATL package and run its code silently. MJ (10/05/26)
PACKAGEROOT=${PACKAGEROOT:?export PACKAGEROOT=<dir holding the 2D-Global nos-workflow clone>}
[ -d "${PACKAGEROOT}/nos-workflow/slurm/stofs_2d_glo" ] || { echo "FATAL: ${PACKAGEROOT}/nos-workflow has no 2D-Global cards (wrong PACKAGEROOT?)"; exit 1; }
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the resolver
# silently applies the WCOSS2 profile (PPN=120 on an 80-core node). MJ (10/04/26)
export NOS_MACHINE=hercules

# OFS is pinned, inherited values ignored. MJ (10/05/26)
export OFS=stofs_2d_glo
# Inherited paths would bypass COMROOT_2DGLO and the preflight checks; JNOS re-derives them. MJ (10/05/26)
unset COMOUT COMOUTroot COMGES DATA COMOUT_PREV COMOUTrerun
# shell_mappings lets an inherited non-empty value win over the yaml; the rank counts and paths come only from the card and yaml. MJ (10/05/26)
unset NCPU NUM_WRITERS TOT_NCPU NTASKS USHnos SCRIPTSnos PARMnos FIXofs
# Pin the job identity JNOS derives for this OFS (NET=nos, RUN=PREFIXNOS=OFS), so a leaked value cannot move the COMOUT layout. MJ (10/05/26)
export NET=nos RUN=stofs_2d_glo PREFIXNOS=stofs_2d_glo
NOS_PTMP=${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}
RPTDIR=${RPTDIR:-${NOS_PTMP}/$LOGNAME/rpt/${OFS}}
WORKDIR=${NOS_PTMP}/$LOGNAME/work/stofs_2d_glo
mkdir -p -m 755 $RPTDIR $WORKDIR || { echo "FATAL: cannot create RPTDIR/WORKDIR ($RPTDIR, $WORKDIR)"; exit 1; }

_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/stofs_2d_glo_prep_00.${_JOBID}"
touch "${_LOG_PREFIX}.out" "${_LOG_PREFIX}.err" || { echo "FATAL: cannot write to RPTDIR ($RPTDIR)"; exit 1; }
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== stofs_2d_glo_prep_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR} || exit 1

module purge
module use ${PACKAGEROOT}/nos-workflow/modulefiles
module load nos_hercules.intel
# python venv overlay: scipy + editable nos-utils live outside the spack stack MJ (10/04/26)
NOS_VENV=${NOS_VENV:-${VENV_PATH:-$HOME/nos-venv}}
if [ -f "${NOS_VENV}/bin/activate" ]; then . "${NOS_VENV}/bin/activate"; fi

module list

command -v wgrib2 >/dev/null 2>&1 || { echo "FATAL: wgrib2 not found on PATH -- module spider wgrib2"; exit 1; }
if ! wgrib2 -config 2>/dev/null | grep -qi ipolates; then
    echo "WARNING: wgrib2 -config has no IPOLATES token -- needed for HRRR -new_grid regridding (may be a false negative)"
    wgrib2 -config 2>&1 | head -20
fi
python3 -c 'import numpy, netCDF4, yaml, scipy, pandas, xarray' 2>/dev/null || { echo "FATAL: python3 is missing one of numpy/netCDF4/yaml/scipy/pandas/xarray"; exit 1; }

# EXPORT list MJ (10/04/26)
set +x
export envir=dev
export OFS=stofs_2d_glo
export cyc=${CYC:-12}
export CYC=${cyc}
export PDY=${PDY:?set PDY (YYYYMMDD)}
export NET=nos
export job=stofs_2d_glo_prep_${cyc}_$envir
export platform=ptmp
export framework=adcirc
export ADCIRC_MODE=${ADCIRC_MODE:-single}

export KEEPDATA=${KEEPDATA:-YES}
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO

export PACKAGEROOT

# Data and COM paths
# Isolated COMROOT: an inherited generic COMROOT/DATAROOT is ignored, so SECOFS and ATL are never touched. MJ (10/05/26)
export COMROOT=${COMROOT_2DGLO:-${NOS_PTMP}/$LOGNAME/com_2dglo}
export DATAROOT=${NOS_PTMP}/$LOGNAME/work/stofs_2d_glo
export EXECnos=${EXECnos:-${PACKAGEROOT}/nos-workflow/exec}
# padcirc/adcprep are a site build; the runner reads ADCIRC_EXEC_DIR. MJ (10/05/26)
export ADCIRC_EXEC_DIR=${ADCIRC_EXEC_DIR:?export ADCIRC_EXEC_DIR=<dir holding padcirc and adcprep>}
# GFS laid out as <COMROOT_STAGED>/gfs/gfs.YYYYMMDD/CC/atmos (ops COMINgfs layout). MJ (10/05/26)
export COMROOT_STAGED=${COMROOT_STAGED:-${NOS_PTMP}/$LOGNAME/comin_2dglo}
export COMINgfs=${COMINgfs:-$COMROOT_STAGED/gfs}

################################################
# CALL executable job script here MJ (10/04/26)
export pbsid=${SLURM_JOB_ID}
export job=${job:-$SLURM_JOB_NAME}
export jobid=${jobid:-$job.$SLURM_JOB_ID}

export HOMEnos=${PACKAGEROOT}/nos-workflow
export OFS_CONFIG=${HOMEnos}/parm/systems/stofs_2d_glo.yaml
# exnos_*.sh prepend inherited NOS_WORKFLOW_DIR/NOS_UTILS_DIR to PYTHONPATH; pin them to what the preflight checks. MJ (10/05/26)
export NOS_WORKFLOW_DIR=${HOMEnos}/ush/python
export NOS_UTILS_DIR=${HOMEnos}/ush/python/nos-utils
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

# Preflight: nos_utils must come from the checked-out submodule, not a venv editable install. MJ (10/04/26)
export PYTHONPATH=${NOS_WORKFLOW_DIR}:${NOS_UTILS_DIR}:${PYTHONPATH:-}
_nu=$(python3 -c 'import nos_utils; print(nos_utils.__file__)' 2>&1) || { echo "FATAL: cannot import nos_utils: ${_nu}"; exit 1; }
_nu_root=$(readlink -f "${NOS_UTILS_DIR}")
case "$(readlink -f "${_nu}")" in
    "${_nu_root}"/*) ;;
    *) echo "FATAL: nos_utils resolves to ${_nu}, not under ${_nu_root} (submodule not initialised? git submodule update --init)"; exit 1 ;;
esac
_nu_head=$(git -C "${_nu_root}" rev-parse HEAD 2>/dev/null || echo unknown)
_nu_pin=$(git -C "${HOMEnos}" ls-tree HEAD ush/python/nos-utils 2>/dev/null | awk '{print $3}')
echo "nos_utils: ${_nu} HEAD=${_nu_head} gitlink=${_nu_pin:-unknown}"
# A stale submodule (git pull without submodule update) would run old nos-utils code; NOS_ALLOW_NU_MISMATCH=1 overrides for deliberate tests. MJ (10/04/26)
[ -z "${_nu_pin}" ] || [ "${_nu_head}" = "${_nu_pin}" ] || [ "${NOS_ALLOW_NU_MISMATCH:-0}" = 1 ] || { echo "FATAL: nos-utils HEAD ${_nu_head} != gitlink ${_nu_pin} (git submodule update ush/python/nos-utils)"; exit 1; }

# Preflight: fix files, executables and the GFS tree, so a missing 1.7 GB mesh fails here and not mid-run. MJ (10/05/26)
FIXDIR=${HOMEnos}/fix/${OFS}
for _f in stofs_2d_glo_grid stofs_2d_glo_attr; do
    [ -s "${FIXDIR}/${_f}" ] || { echo "FATAL: ${FIXDIR}/${_f} missing (tools/fetch_stofs_2d_glo_fix.sh)"; exit 1; }
done
[ -x "${ADCIRC_EXEC_DIR}/adcprep" ] || { echo "FATAL: ${ADCIRC_EXEC_DIR}/adcprep not executable"; exit 1; }
[ "${ADCIRC_MODE}" = ops ] || [ -d "${COMINgfs}" ] || { echo "FATAL: COMINgfs ${COMINgfs} missing"; exit 1; }
# cfgrib/ecCodes preflight: a missing package fails here in seconds, not after the GFS copies. MJ (10/05/26)
if [ "${ATMOSPHERIC_FORCING:-true}" != "false" ] && [ "${ADCIRC_MODE}" != ops ]; then
    python3 -c 'import xarray, cfgrib, eccodes' 2>&1 || { echo "FATAL: xarray/cfgrib/eccodes not importable (pip install cfgrib eccodes; ECCODES_DIR / eccodes module)"; exit 1; }
fi

# ncdiff/ncrcat are the ops post jobs; they share this 1-node card (ecf: 1 cpu, 100 GB). MJ (10/06/26)
case "${ADCIRC_SEGMENT:-}" in ncdiff|ncrcat|anomaly|bias|grib2) ${HOMEnos}/jobs/JNOS_POST ;; *) ${HOMEnos}/jobs/JNOS_PREP ;; esac
# JNOS_* exits 0 even when the stage fails; stop the afterok chain unless the stage logged PASS, as ops does. MJ (10/06/26)
grep -q 'STAGE_SUMMARY .*status=PASS' "${_LOG_PREFIX}.out" || exit 1
