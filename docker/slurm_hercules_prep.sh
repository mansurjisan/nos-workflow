#!/bin/bash
#SBATCH --job-name=secofs_prep
#SBATCH --account=nos-surge
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --time=02:00:00
#SBATCH --partition=hercules
#SBATCH --output=%x_%j.log
#
# SECOFS standalone prep in Singularity container on MSU Hercules
#
# Usage:
#   sbatch slurm_hercules_prep.sh
#
# Requires:
#   - secofs-ufs-gcc.sif in ${BASE}/images/
#   - Test data staged in ${BASE}/com/ and ${BASE}/fix/
#   - mpiexec_simple.sh in ${BASE}/

module load apptainer

BASE=${SECOFS_DOCKER_ROOT:-/work2/noaa/nos-surge/${USER}/secofs_docker}
OFS=${OFS:-secofs}
PDY=${PDY:-20260324}
CYC=${CYC:-18}

echo "=============================================="
echo " SECOFS Container Prep — Hercules"
echo " BASE: ${BASE}"
echo " OFS=${OFS} PDY=${PDY} CYC=${CYC}"
echo "=============================================="

singularity exec \
  --writable-tmpfs \
  --env LOGNAME=nosuser \
  --env TOTAL_TASKS=8 \
  --env NSCRIBES=0 \
  --env LD_PRELOAD="" \
  --bind ${BASE}/mpiexec_simple.sh:/usr/local/bin/mpiexec \
  --bind ${BASE}/com/gfs:/lfs/h1/ops/prod/com/gfs:ro \
  --bind ${BASE}/com/hrrr:/lfs/h1/ops/prod/com/hrrr:ro \
  --bind ${BASE}/com/nwm:/lfs/h1/ops/prod/com/nwm:ro \
  --bind ${BASE}/com/rtofs:/lfs/h1/ops/prod/com/rtofs:ro \
  --bind ${BASE}/fix/${OFS}:/lfs/h1/nos/nosofs/packages/nosofs.v3.7.0/fix/${OFS} \
  --bind ${BASE}/fix/shared:/lfs/h1/nos/nosofs/packages/nosofs.v3.7.0/fix/shared:ro \
  --bind ${BASE}/com/nosofs:/lfs/h1/nos/ptmp/nosuser/com/nosofs \
  --bind ${BASE}/work:/lfs/h1/nos/ptmp/nosuser/work \
  ${BASE}/images/secofs-ufs-gcc.sif \
  /opt/nosofs/docker/run_secofs_ufs.sh prep --pdy ${PDY} --cyc ${CYC} --ofs ${OFS}
