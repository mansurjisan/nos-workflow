#!/bin/bash
# subjobs_stofs3datl_12_prep.sh - Submit STOFS-3D Atlantic prep job

. /lfs/h1/nos/estofs/noscrub/mansur.jisan/packages/IT-stofs.v2.1.0/versions/stofs_3d_atl/run.ver
module load envvar/${envvar_ver:?}
module load PrgEnv-intel/${PrgEnv_intel_ver}
module load craype/${craype_ver}
module load intel/${intel_ver}

# Create log and report directories
RPTDIR=/lfs/h1/nos/ptmp/mansur.jisan/rpt/stofs_3d_atl
if [ ! -d $RPTDIR ]; then
   mkdir -p $RPTDIR
fi

rm -f ${RPTDIR}/stofs3datl_prep_12.out
rm -f ${RPTDIR}/stofs3datl_prep_12.err

export LSFDIR=/lfs/h1/nos/estofs/noscrub/mansur.jisan/packages/nosofs.v3.7.0/pbs
export OFS_CONFIG=/lfs/h1/nos/estofs/noscrub/mansur.jisan/packages/nosofs.v3.7.0/parm/systems/stofs_3d_atl.yaml
export PYTHONPATH=/lfs/h1/nos/estofs/noscrub/mansur.jisan/packages/nosofs.v3.7.0/ush/python:$PYTHONPATH

# Submit the PREP job
PREP=$(qsub $LSFDIR/jnos_stofs3datl_prep_12.pbs)
echo "Submitted STOFS-3D-ATL PREP job: $PREP"
echo "Monitor with: qstat -u $USER"
echo "Check logs at: $RPTDIR/"
