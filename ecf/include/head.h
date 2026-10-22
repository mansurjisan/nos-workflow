# head.h - development stand-in for the NCO ecFlow header (gfs.v16.3.x head.h).
# NCO's own head.h replaces this file in operations; keep this directory last in ECF_INCLUDE. MJ (10/20/26)
date
hostname
set -xe

export PS4='+ $SECONDS + '

export ECF_NAME=%ECF_NAME%
export ECF_HOST=%ECF_HOST%
export ECF_PORT=%ECF_PORT%
export ECF_PASS=%ECF_PASS%
export ECF_TRYNO=%ECF_TRYNO%
export ECF_RID=${ECF_RID:-${PBS_JOBID:-$(hostname -s).$$}}
export ECF_JOB=%ECF_JOB%
export ECF_JOBOUT=%ECF_JOBOUT%
export ecflow_ver=%ecflow_ver%

if [ -d /apps/ops/prod ]; then # On WCOSS2. MJ (10/21/26)
  set +x
  module reset
  set -x
fi

modelhome=%PACKAGEHOME%
eval "export HOME${model:?'model undefined'}=$modelhome"
eval "versionfile=\$HOME${model}/versions/run.ver"
if [ -f "$versionfile" ]; then . $versionfile ; fi

export envir=%ENVIR%
export KEEPDATA=%KEEPDATA:NO%
export SENDCOM=NO
export SENDDBN=NO
export SENDSMS=NO

if [ -d /apps/ops/prod ]; then # On WCOSS2. MJ (10/21/26)
  set +x
  # ecflow_ver is a placeholder; a failed load here would end the job before --init and leave the task submitted. MJ (10/21/26)
  module load ecflow/$ecflow_ver || module load ecflow
  module list
  set -x
fi

timeout 300 ecflow_client --init=${ECF_RID}

# The module blocks purge, which drops ecflow; reload it so the abort still reaches the server. MJ (10/20/26)
ERROR() {
  set +ex
  if ! command -v ecflow_client >/dev/null 2>&1 && [ -d /apps/ops/prod ]; then module load ecflow/$ecflow_ver || module load ecflow; fi
  if [ "$1" -eq 0 ]; then
     msg="Killed by signal (likely via qdel)"
  else
     msg="Killed by signal $1"
  fi
  ecflow_client --abort="$msg"
  echo $msg
  trap 0; exit $1
}
trap 'ERROR $?' ERR EXIT
