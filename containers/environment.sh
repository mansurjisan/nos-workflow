#!/bin/bash

if [ $# -ne 3 ]; then
  echo "Usage: source <PDY> <CYC> <WORKDIR>"
else
  export envir="prod" # "test", "para", or "prod"

  export CYC=$2
  export PDY=$1
  export WORKDIR=$3

  if [ ! -d $WORKDIR/stofs3d/$PDY ]; then
    mkdir $WORKDIR/stofs3d/$PDY
  fi

  export cyc=$CYC
  echo "DATE  "$PDY$CYC"0000WASHINGTON" > $WORKDIR/date/ncepdate
  echo "DATE  "$PDY$CYC"0000WASHINGTON" > $WORKDIR/date/t$CYC"z"
  export HOMEstofs=$WORKDIR/stofs3d
  source ${HOMEstofs}/versions/run.ver

  export COMIN=$WORKDIR/stofs3d/stofs/$stofs_ver/stofs.$PDY
  export COMINstofs=$WORKDIR/stofs3d/stofs/$stofs_ver
  export COMROOT=$WORKDIR
  export COMOUT=$WORKDIR/stofs3d/$PDY
  export COMOUT_PREV=$WORKDIR/stofs3d/prev
  export COMOUTrerun=$WORKDIR/stofs3d/rerun
  export DATAROOT=$WORKDIR/stofs3d/dataroot
  export DCOMROOT=$WORKDIR/dcom_root
  export KEEPDATA=YES
  export SENDECF=NO
  export WGRIB2=/usr/local/bin/wgrib2
  export NET=stofs
  export RUN=stofs_3d_atl
  export model=stof_3d_atl

  export PATH=$PATH:{HOMEstofs}/exec/

  export DIR_ECF=${HOMEstofs}/ecf/
  export DIR_JOBS=${HOMEstofs}/jobs/

  export NDATE=/opt/ncep/bin/ndate

fi
