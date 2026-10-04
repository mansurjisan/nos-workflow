#!/bin/bash
# ============================================================================
# STOFS-3D-ATL STANDALONE (ops-equivalent pschism, nws=2 sflux)
# post on Hercules, cycle 12z (file name _00 matches the pbs cards).
#
# Required env (sbatch passes the caller's environment): PDY, and for prep DCOMROOT
# (bundle dcom dir, laid out dcom/YYYYMMDD/...). Optional: CYC (default 12), COMROOT_SA / COMROOT_UFS (per variant),
# COMROOT_STAGED (stage_comin.py output), PACKAGEROOT, NOS_PTMP, NOS_VENV, COMINrerun.
# Do NOT chain stages with --dependency=afterok (JNOS_* can exit 0 after a failed stage);
# submit each stage after the previous one logs STAGE_SUMMARY status=PASS. MJ (10/04/26)
# ============================================================================
#SBATCH --job-name=stofs_3d_atl_ufs_sa_post_00
#SBATCH --account=nos-surge
#SBATCH --qos=batch
#SBATCH --partition=hercules
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --mem=0
#SBATCH --time=02:00:00
# No #SBATCH -o/-e: Slurm's default slurm-%j.out catches its own epilogue, the script
# self-redirects its own log below. MJ (10/04/26)

PACKAGEROOT=${PACKAGEROOT:-/work2/noaa/nos-surge/mjisan}
. ${PACKAGEROOT}/nos-workflow/versions/run.hercules.ver

# Load-bearing: must be set before anything sources yaml_to_env, or the resolver
# silently applies the WCOSS2 profile (PPN=120 on an 80-core node). MJ (10/04/26)
export NOS_MACHINE=hercules

# Standalone and coupled use the same RUN name and need SEPARATE COMROOTs; OFS is pinned, inherited values ignored. MJ (10/04/26)
export OFS=stofs_3d_atl_ufs
NOS_PTMP=${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}
RPTDIR=${RPTDIR:-${NOS_PTMP}/$LOGNAME/rpt/${OFS}}
WORKDIR=${NOS_PTMP}/$LOGNAME/work/stofs_3d_atl_ufs_standalone
mkdir -p -m 755 $RPTDIR $WORKDIR || { echo "FATAL: cannot create RPTDIR/WORKDIR ($RPTDIR, $WORKDIR)"; exit 1; }

_JOBID=${SLURM_JOB_ID}
_LOG_PREFIX="$RPTDIR/stofs_3d_atl_ufs_standalone_post_00.${_JOBID}"
touch "${_LOG_PREFIX}.out" "${_LOG_PREFIX}.err" || { echo "FATAL: cannot write to RPTDIR ($RPTDIR)"; exit 1; }
exec > "${_LOG_PREFIX}.out" 2> "${_LOG_PREFIX}.err"
echo "=== stofs_3d_atl_ufs_standalone_post_00 -- Slurm jobid ${SLURM_JOB_ID} on $(hostname) at $(date) ==="
cd ${WORKDIR} || exit 1

module purge
module use ${PACKAGEROOT}/nos-workflow/modulefiles
module load nos_hercules.intel
# python venv overlay: scipy + editable nos-utils live outside the spack stack MJ (10/04/26)
NOS_VENV=${NOS_VENV:-${VENV_PATH:-$HOME/nos-venv}}
if [ -f "${NOS_VENV}/bin/activate" ]; then . "${NOS_VENV}/bin/activate"; fi

module list

# EXPORT list MJ (10/04/26)
set +x
export envir=dev
export OFS=stofs_3d_atl_ufs
export cyc=${CYC:-12}
export CYC=${cyc}
export PDY=${PDY:?set PDY (YYYYMMDD)}
export job=stofs_3d_atl_ufs_sa_post_${cyc}_$envir
export platform=ptmp
export framework=stofs_ufs

export KEEPDATA=YES
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO
# Archive manifest on: ATL standalone stages flux.th and the run inputs through it. MJ (10/04/26)
export NOS_ARCHIVE_MANIFEST=${NOS_ARCHIVE_MANIFEST:-YES}

export PACKAGEROOT=${PACKAGEROOT:-/work2/noaa/nos-surge/mjisan}

# Data and COM paths
# Variant-specific override only: an inherited generic COMROOT/DATAROOT is ignored. MJ (10/04/26)
export COMROOT=${COMROOT_SA:-${NOS_PTMP}/$LOGNAME/com_atl_sa}
export DATAROOT=${NOS_PTMP}/$LOGNAME/work/stofs_3d_atl_ufs_standalone
export EXECnos=${EXECnos:-${PACKAGEROOT}/nos-workflow/exec}

################################################
# CALL executable job script here MJ (10/04/26)
export pbsid=${SLURM_JOB_ID}
export job=${job:-$SLURM_JOB_NAME}
export jobid=${jobid:-$job.$SLURM_JOB_ID}

export HOMEnos=${PACKAGEROOT}/nos-workflow
export OFS_CONFIG=${HOMEnos}/parm/systems/stofs_3d_atl_ufs_standalone.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

# Preflight: nos_utils must come from the checked-out submodule, not a venv editable install. MJ (10/04/26)
export PYTHONPATH=${HOMEnos}/ush/python:${HOMEnos}/ush/python/nos-utils:${PYTHONPATH:-}
_nu=$(python3 -c 'import nos_utils; print(nos_utils.__file__)' 2>&1) || { echo "FATAL: cannot import nos_utils: ${_nu}"; exit 1; }
_nu_root=$(readlink -f "${HOMEnos}/ush/python/nos-utils")
case "$(readlink -f "${_nu}")" in
    "${_nu_root}"/*) ;;
    *) echo "FATAL: nos_utils resolves to ${_nu}, not under ${_nu_root} (submodule not initialised? git submodule update --init)"; exit 1 ;;
esac
_nu_head=$(git -C "${_nu_root}" rev-parse HEAD 2>/dev/null || echo unknown)
_nu_pin=$(git -C "${HOMEnos}" ls-tree HEAD ush/python/nos-utils 2>/dev/null | awk '{print $3}')
echo "nos_utils: ${_nu} HEAD=${_nu_head} gitlink=${_nu_pin:-unknown}"
[ -z "${_nu_pin}" ] || [ "${_nu_head}" = "${_nu_pin}" ] || echo "WARNING: nos-utils HEAD differs from the gitlink"

${HOMEnos}/jobs/JNOS_POST
