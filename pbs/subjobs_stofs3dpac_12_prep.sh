#!/bin/bash
# subjobs_stofs3dpac_12_prep.sh - Submit STOFS-3D Pacific job chain
#
# Submits: prep → nowcast → forecast → post1 → post2
# Each job depends on the previous one via PBS dependencies.

. /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nosofs.v3.7.0/versions/stofs_3d_pac/run.ver
module load envvar/${envvar_ver:?}
module load PrgEnv-intel/${PrgEnv_intel_ver}
module load craype/${craype_ver}
module load intel/${intel_ver}

# Create log and report directories
RPTDIR=/lfs/h1/nos/ptmp/$LOGNAME/rpt/stofs_3d_pac
if [ ! -d $RPTDIR ]; then
   mkdir -p $RPTDIR
fi

rm -f ${RPTDIR}/stofs3dpac_prep_12.out
rm -f ${RPTDIR}/stofs3dpac_prep_12.err

export LSFDIR=/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nosofs.v3.7.0/pbs
export OFS_CONFIG=/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nosofs.v3.7.0/parm/systems/stofs_3d_pac.yaml
export PYTHONPATH=/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nosofs.v3.7.0/ush/python:$PYTHONPATH

# Submit the job chain with dependencies
PREP=$(qsub $LSFDIR/jnos_stofs3dpac_prep_12.pbs)
echo "Submitted STOFS-3D-PAC PREP job: $PREP"

NCST=$(qsub -W depend=afterok:${PREP} $LSFDIR/jnos_stofs3dpac_nowcast_12.pbs)
echo "Submitted STOFS-3D-PAC NOWCAST job: $NCST (depends on PREP)"

FCST=$(qsub -W depend=afterok:${NCST} $LSFDIR/jnos_stofs3dpac_forecast_12.pbs)
echo "Submitted STOFS-3D-PAC FORECAST job: $FCST (depends on NOWCAST)"

POST1=$(qsub -W depend=afterok:${FCST} $LSFDIR/jnos_stofs3dpac_post1_12.pbs)
echo "Submitted STOFS-3D-PAC POST1 job: $POST1 (depends on FORECAST)"

POST2=$(qsub -W depend=afterok:${POST1} $LSFDIR/jnos_stofs3dpac_post2_12.pbs)
echo "Submitted STOFS-3D-PAC POST2 job: $POST2 (depends on POST1)"

echo ""
echo "Job chain submitted successfully."
echo "Monitor with: qstat -u $USER"
echo "Check logs at: $RPTDIR/"
