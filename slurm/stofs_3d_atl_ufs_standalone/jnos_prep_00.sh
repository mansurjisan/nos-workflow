#!/bin/bash
# ============================================================================
# STOFS-3D-ATL STANDALONE (ops-equivalent pschism, nws=2 sflux)
# prep on Hercules, cycle 12z (file name _00 matches the pbs cards).
#
# Required env (sbatch passes the caller's environment): PDY, and for prep DCOMROOT
# (bundle dcom dir, laid out dcom/YYYYMMDD/...). Optional: CYC (default 12), COMROOT_SA / COMROOT_UFS (per variant),
# COMROOT_STAGED (stage_comin.py output), PACKAGEROOT, NOS_PTMP, NOS_VENV, COMINrerun.
# Do NOT chain stages with --dependency=afterok (JNOS_* can exit 0 after a failed stage);
# submit each stage after the previous one logs STAGE_SUMMARY status=PASS. MJ (10/04/26)
# ============================================================================
#SBATCH --job-name=stofs_3d_atl_ufs_sa_prep_00
#SBATCH --account=nos-surge
#SBATCH --qos=batch
#SBATCH --partition=hercules
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --mem=0
#SBATCH --time=03:00:00
#SBATCH --output=%x.%j.out
#SBATCH --error=%x.%j.err

# PACKAGEROOT must be set explicitly: the old default held the SECOFS package, whose code would run silently. MJ (10/04/26)
PACKAGEROOT=${PACKAGEROOT:?export PACKAGEROOT=<dir holding the ATL nos-workflow clone>}
[ -d "${PACKAGEROOT}/nos-workflow/slurm/stofs_3d_atl_ufs" ] || { echo "FATAL: ${PACKAGEROOT}/nos-workflow has no ATL cards (wrong PACKAGEROOT?)"; exit 1; }
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the resolver
# silently applies the WCOSS2 profile (PPN=120 on an 80-core node). MJ (10/04/26)
export NOS_MACHINE=hercules

# Standalone and coupled use the same RUN name and need SEPARATE COMROOTs; OFS is pinned, inherited values ignored. MJ (10/04/26)
export OFS=stofs_3d_atl_ufs
# Inherited paths would bypass COMROOT_SA/COMROOT_UFS and the preflight checks; JNOS re-derives them. MJ (10/04/26)
unset COMOUT COMOUTroot DATA COMOUT_PREV COMOUTrerun COMINadt COMINwl COMINlaw
# Mode and executable come only from the card's yaml: shell_mappings lets an inherited non-empty value win, and nos_run.sh honours UFS_EXEC as a path. MJ (10/05/26)
unset USE_DATM UFS_EXEC_NAME UFS_EXEC SCHISM_EXEC NTASKS USHnos SCRIPTSnos PARMnos FIXofs
# Pin the job identity JNOS derives for this OFS (NET=nos, RUN=PREFIXNOS=OFS), so a leaked value cannot move the COMOUT layout. MJ (10/05/26)
export NET=nos RUN=stofs_3d_atl_ufs PREFIXNOS=stofs_3d_atl_ufs
NOS_PTMP=${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}
RPTDIR=${RPTDIR:-${NOS_PTMP}/$LOGNAME/rpt/${OFS}}
WORKDIR=${NOS_PTMP}/$LOGNAME/work/stofs_3d_atl_ufs_standalone
mkdir -p -m 755 $RPTDIR $WORKDIR || { echo "FATAL: cannot create RPTDIR/WORKDIR ($RPTDIR, $WORKDIR)"; exit 1; }

_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/stofs_3d_atl_ufs_standalone_prep_00.${_JOBID}"
touch "${_LOG_PREFIX}.out" "${_LOG_PREFIX}.err" || { echo "FATAL: cannot write to RPTDIR ($RPTDIR)"; exit 1; }
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== stofs_3d_atl_ufs_standalone_prep_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
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
: "${DCOMROOT:?set DCOMROOT to the bundle dcom dir (dcom/YYYYMMDD/{coops_waterlvlobs,can_streamgauge,validation_data})}"
[ -d "${DCOMROOT}/${PDY:?set PDY}" ] || { echo "FATAL: ${DCOMROOT}/${PDY} missing"; exit 1; }

# EXPORT list MJ (10/04/26)
set +x
export envir=dev
export OFS=stofs_3d_atl_ufs
export cyc=${CYC:-12}
export CYC=${cyc}
export PDY=${PDY:?set PDY (YYYYMMDD)}
export NET=nos
export model=nosofs
export job=stofs_3d_atl_ufs_sa_prep_${cyc}_$envir
export platform=ptmp
export framework=stofs_ufs

export KEEPDATA=YES
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO
# Archive manifest on: ATL standalone stages flux.th and the run inputs through it. MJ (10/04/26)
export NOS_ARCHIVE_MANIFEST=${NOS_ARCHIVE_MANIFEST:-YES}

export PACKAGEROOT

# Data and COM paths
# Variant-specific override only: an inherited generic COMROOT/DATAROOT is ignored. MJ (10/04/26)
export COMROOT=${COMROOT_SA:-${NOS_PTMP}/$LOGNAME/com_atl_sa}
export DATAROOT=${NOS_PTMP}/$LOGNAME/work/stofs_3d_atl_ufs_standalone
export EXECnos=${EXECnos:-${PACKAGEROOT}/nos-workflow/exec}
# dcom inputs (ADT, CO-OPS water level, St. Lawrence) come from the case bundle. MJ (10/04/26)
export DCOMROOT

# Public-bucket inputs staged by ush/stage_comin.py --profile stofs_3d_atl. MJ (10/04/26)
export COMROOT_STAGED=${COMROOT_STAGED:-${NOS_PTMP}/$LOGNAME/comin_atl}
export COMINgfs=${COMINgfs:-$COMROOT_STAGED/gfs}
export COMINhrrr=${COMINhrrr:-$COMROOT_STAGED/hrrr}
export COMINrtofs_2d=${COMINrtofs_2d:-$COMROOT_STAGED/rtofs}
export COMINrtofs_3d=${COMINrtofs_3d:-$COMROOT_STAGED/rtofs}
export COMINnwm=${COMINnwm:-$COMROOT_STAGED/nwm}
# Previous-cycle dynamic-adjust seed: lay it out with tools/hercules_atl_seed_prev.sh
# (COMOUT_PREV layout, read by default) or export COMINrerun=<seed dir> to override. MJ (10/04/26)

################################################
# CALL executable job script here MJ (10/04/26)
export pbsid=${SLURM_JOB_ID}
export job=${job:-$SLURM_JOB_NAME}
export jobid=${jobid:-$job.$SLURM_JOB_ID}

export HOMEnos=${PACKAGEROOT}/nos-workflow
export OFS_CONFIG=${HOMEnos}/parm/systems/stofs_3d_atl_ufs_standalone.yaml
# exnos_*.sh prepend inherited NOS_WORKFLOW_DIR/NOS_UTILS_DIR to PYTHONPATH; pin them to what the preflight checks. MJ (10/05/26)
export NOS_WORKFLOW_DIR=${HOMEnos}/ush/python
export NOS_UTILS_DIR=${HOMEnos}/ush/python/nos-utils
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

export USE_PYTHON_PREP=YES
export FULL_PYTHON_PREP=YES

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

# Preflight: Fortran tide_fac must be installed, else tidal.py silently uses Python nodal factors (bctides off from ops). MJ (10/04/26)
[ -x "${EXECnos}/stofs_3d_atl_tide_fac" ] || [ -x "${EXECnos}/nos_ofs_create_tide_fac_schism" ] || { echo "FATAL: no tide_fac executable in ${EXECnos} (tools/build_stofs_3d_atl_tide_fac_hercules.sh)"; exit 1; }
# Preflight: dcom inputs and the previous-cycle dynamic-adjust seed (paths as adt.py, st_lawrence.py, dynamic_adjust.py, orchestrator.py read them). MJ (10/04/26)
PDYM1=$(date -u -d "${PDY} -1 day" +%Y%m%d)
for _d in ${PDY} ${PDYM1}; do
    _f="${DCOMROOT}/${_d}/validation_data/marine/cmems/ssh/nrt_global_allsat_phy_l4_${_d}_${_d}.nc"
    [ -s "${_f}" ] || { echo "FATAL: ADT file missing: ${_f}"; exit 1; }
done
compgen -G "${DCOMROOT}/${PDY}/coops_waterlvlobs/*.xml" >/dev/null || { echo "FATAL: no CO-OPS xml in ${DCOMROOT}/${PDY}/coops_waterlvlobs"; exit 1; }
_law=0
for _d in ${PDY} ${PDYM1}; do [ -s "${DCOMROOT}/${_d}/can_streamgauge/02OA016_hydrometric.csv" ] && _law=1; done
[ ${_law} = 1 ] || { echo "FATAL: St. Lawrence 02OA016_hydrometric.csv missing for ${PDY} and ${PDYM1} under ${DCOMROOT}/<day>/can_streamgauge"; exit 1; }
if [ -n "${COMINrerun:-}" ]; then
    [ "$(stat -L -c %s "${COMINrerun}/staout_1" 2>/dev/null || echo 0)" -ge 10000 ] || { echo "FATAL: ${COMINrerun}/staout_1 missing or under 10000 bytes (dynamic adjust skips it)"; exit 1; }
    [ -s "${COMINrerun}/${OFS}.t${cyc}z.avg_bias" ] || [ -s "${COMINrerun}/average_bias_today" ] || { echo "FATAL: ${COMINrerun}/${OFS}.t${cyc}z.avg_bias missing"; exit 1; }
    [ -s "${COMINrerun}/${OFS}.t${cyc}z.param.nml" ] || [ -s "${COMINrerun}/param.nml" ] || echo "WARNING: no param.nml in ${COMINrerun}"
else
    _prev="${COMROOT}/nos/${OFS}.${PDYM1}"
    [ "$(stat -L -c %s "${_prev}/staout_1" 2>/dev/null || echo 0)" -ge 10000 ] || { echo "FATAL: ${_prev}/staout_1 missing or under 10000 bytes (tools/hercules_atl_seed_prev.sh)"; exit 1; }
    [ -s "${_prev}/rerun/${OFS}.t${cyc}z.avg_bias" ] || { echo "FATAL: ${_prev}/rerun/${OFS}.t${cyc}z.avg_bias missing"; exit 1; }
fi

${HOMEnos}/jobs/JNOS_PREP
