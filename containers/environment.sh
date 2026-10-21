#!/bin/bash
# Environment for STOFS-3D-ATL v3.1 prep in the container.
# Usage: source environment.sh PDY CYC SANDBOX    (OFS=stofs_3d_atl_ufs_standalone by default,
#        OFS=stofs_3d_atl_ufs for the coupled variant; then run $HOMEnos/jobs/JNOS_PREP). MJ (10/20/26)

if [ $# -ne 3 ]; then
  echo "Usage: source environment.sh <PDY> <CYC> <SANDBOX>"
  return 1 2>/dev/null || exit 1
fi

export PDY=$1
export CYC=$2
export cyc=$(printf '%02d' "$((10#$2))")
export SANDBOX=$3

export HOMEnos=${HOMEnos:-/opt/nosofs}
export HOMEstofs=${HOMEnos}
export PACKAGEROOT=/lfs/h1/nos/nosofs/packages
. ${HOMEnos}/versions/run.ver
export COLDSTART=NO
# The ATL v3.1 inputs: NWM v3.0 (override with nwm_ver=... before sourcing). MJ (10/20/26)
export nwm_ver=${NWM_VER:-v3.0}

# Variant: the standalone variant is the base system plus its own yaml (RUN/FIX/COMOUT use the base name)
OFS_IN=${OFS:-stofs_3d_atl_ufs_standalone}
case "${OFS_IN}" in
  *_standalone) export OFS=${OFS_IN%_standalone}; export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS_IN}.yaml ;;
  *)            export OFS=${OFS_IN}; export OFS_CONFIG=${HOMEnos}/parm/systems/${OFS}.yaml ;;
esac
export NET=nos RUN=${OFS} PREFIXNOS=${OFS} model=nosofs envir=dev platform=ptmp framework=stofs_ufs
export LOGNAME=${LOGNAME:-wcoss2}
export USE_PYTHON_PREP=YES FULL_PYTHON_PREP=YES
export KEEPDATA=YES SENDCOM=NO SENDDBN=NO SENDSMS=NO SENDECF=NO

# Inputs: mount the staged trees at /lfs/h1/ops/prod/com/{gfs,hrrr,nwm,rtofs} and /lfs/h1/ops/prod/dcom;
# a <name>/<ver> subdirectory is used when present.
_comin() { [ -d "$1/$2" ] && echo "$1/$2" || echo "$1"; }
_P=/lfs/h1/ops/prod/com
export COMINgfs=${COMINgfs:-$(_comin $_P/gfs ${gfs_ver})}
export COMINhrrr=${COMINhrrr:-$(_comin $_P/hrrr ${hrrr_ver})}
export COMINnwm=${COMINnwm:-$(_comin $_P/nwm ${nwm_ver})}
export COMINrtofs=${COMINrtofs:-$(_comin $_P/rtofs ${rtofs_ver})}
export COMINrtofs_2d=${COMINrtofs_2d:-$COMINrtofs} COMINrtofs_3d=${COMINrtofs_3d:-$COMINrtofs}
export DCOMROOT=${DCOMROOT:-/lfs/h1/ops/prod/dcom}

# Outputs and work under the sandbox (COMOUT = $COMROOT/nos/${OFS}.${PDY}; seed the first cycle there).
export COMROOT=${COMROOT:-$SANDBOX/com}
export DATAROOT=${DATAROOT:-$SANDBOX/work/${OFS}}
mkdir -p "$COMROOT/nos" "$DATAROOT"

# Fix and executables: mount the fix tree over $HOMEnos/fix/${OFS}; tide_fac etc. are in $HOMEnos/exec.
export FIXofs=${FIXofs:-${HOMEnos}/fix/${OFS}}
export FIXstofs3d=${FIXofs}
export EXECnos=${HOMEnos}/exec EXECofs=${HOMEnos}/exec
export PARMnos=${HOMEnos}/parm USHnos=${HOMEnos}/ush SCRIPTSnos=${HOMEnos}/scripts

export NOS_WORKFLOW_DIR=${HOMEnos}/ush/python NOS_UTILS_DIR=${HOMEnos}/ush/python/nos-utils
export PYTHONPATH=${NOS_WORKFLOW_DIR}:${NOS_UTILS_DIR}:${PYTHONPATH:-}
export WGRIB2=$(command -v wgrib2)
export NDATE=$(command -v ndate || echo /opt/ncep/bin/ndate)
export PATH=${HOMEnos}/exec:/opt/ncep/bin:/opt/wgrib2/bin:$PATH

export job=${OFS}_prep_${cyc}_${envir}
export jobid=${job}.$$
