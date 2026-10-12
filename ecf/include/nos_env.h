#=============================================================================
# nos_env.h - common nos-workflow environment for every ecFlow task.
#
# ecFlow variables come from ecf/defs/nos_ufs_coastal.def (or the production
# suite). Values that NCO's prod_envir module provides in operations
# (COMROOT, DATAROOT, DCOMROOT) fall back to the suite variables in dev.
#=============================================================================

export OFS=%OFS%
export RUN=${OFS}
export cyc=%CYC%
export CYC=%CYC%
export envir=%ENVIR:dev%

export PACKAGEROOT=%PACKAGEROOT%
export HOMEnos=${PACKAGEROOT}/nos-workflow
export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS}.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

export COMROOT=${COMROOT:-%COMROOT%}
export DATAROOT=${DATAROOT:-%DATAROOT%}
export DCOMROOT=${DCOMROOT:-%DCOMROOT:/lfs/h1/ops/prod/dcom%}

# Cycle date: the dev suite repeats over PDY; without it the J-jobs fall back
# to setpdy.sh (prod_util), as in NCO operations.
_pdy=%PDY:none%
if [ "${_pdy}" != none ]; then export PDY=${_pdy}; fi

export job=${PBS_JOBNAME:-nos_${OFS}_%TASK%_${cyc}}
export jobid=${job}.${PBS_JOBID:-$$}
export pbsid=$(echo "${PBS_JOBID:-$$}" | cut -d. -f1)

export KEEPDATA=%KEEPDATA:NO%
export SENDCOM=%SENDCOM:YES%
export SENDDBN=%SENDDBN:NO%
export SENDECF=%SENDECF:YES%

# Package versions (gfs_ver, hrrr_ver, rtofs_ver, nwm_ver, module versions).
. ${HOMEnos}/versions/run.ver
