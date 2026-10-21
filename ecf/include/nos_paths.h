# nos_paths.h - after the module block, which purged ecflow and let prod_envir reset the roots. MJ (10/20/26)
if [ -d /apps/ops/prod ]; then
  set +x
  module load ecflow/$ecflow_ver
  set -x
fi

if [ -n "%COMROOT:%" ]; then export COMROOT=%COMROOT:%; fi
if [ -n "%DATAROOT:%" ]; then export DATAROOT=%DATAROOT:%; fi
if [ -n "%DCOMROOT:%" ]; then export DCOMROOT=%DCOMROOT:%; fi
# dirname rather than a suffix expansion of HOMEnos: ecFlow rejects a lone percent sign in a script. MJ (10/20/26)
export PACKAGEROOT=$(dirname "${HOMEnos}")

export OFS_CONFIG=${HOMEnos}/parm/systems/%OFS_YAML%.yaml
export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

%include <nos_env_%ENVSET%.h>
