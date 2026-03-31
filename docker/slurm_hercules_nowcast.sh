#!/bin/bash
#SBATCH --job-name=secofs_nowcast
#SBATCH --account=nos-surge
#SBATCH --nodes=1
#SBATCH --ntasks=32
#SBATCH --mem=120G
#SBATCH --time=02:00:00
#SBATCH --partition=hercules
#SBATCH --output=%x_%j.log
#
# SECOFS nowcast model execution in Singularity container on MSU Hercules
#
# Usage:
#   sbatch slurm_hercules_nowcast.sh
#
# Pre-requisites:
#   1. Prep must have completed (run slurm_hercules_prep.sh first)
#   2. Strip GCC-incompatible namelist vars from nowcast.in:
#      sed -i '/nbins_veg_vert/d; /veg_/d; /marsh_/d; /SAV_/d; ...' \
#        ${BASE}/com/nosofs/v3.7/secofs.${PDY}/secofs.t${CYC}z.${PDY}.nowcast.in
#   3. Create metnum=1 sflux tar if missing (see docker/README)
#
# Notes:
#   - Container OpenMPI uses shared memory (vader) on single node
#   - InfiniBand disabled (--mca btl self,vader,tcp)
#   - 0 scribes (all procs are compute), partition.prop auto-generated
#   - With 32 procs on 1.7M-node grid: ~53K nodes/proc, ~3.5 GB/proc

module load apptainer

BASE=${SECOFS_DOCKER_ROOT:-/work2/noaa/nos-surge/${USER}/secofs_docker}
OFS=${OFS:-secofs}
PDY=${PDY:-20260324}
CYC=${CYC:-18}
NPROCS=${SLURM_NTASKS:-32}

echo "=============================================="
echo " SECOFS Container Nowcast — Hercules"
echo " BASE: ${BASE}"
echo " OFS=${OFS} PDY=${PDY} CYC=${CYC} NPROCS=${NPROCS}"
echo "=============================================="

# Generate partition.prop for compute proc count
singularity exec \
  --bind ${BASE}/fix/${OFS}:${BASE}/fix/${OFS} \
  ${BASE}/images/secofs-ufs-gcc.sif \
  python3 /opt/nosofs/docker/generate_partition.py \
  ${BASE}/fix/${OFS}/${OFS}.hgrid.gr3 ${NPROCS} \
  ${BASE}/fix/${OFS}/partition.prop

rm -rf ${BASE}/work/${OFS}/${OFS}_nowcast_${CYC}_dev 2>/dev/null

# Update mpiexec_simple.sh to use correct proc count
export MPI_MAX_TASKS=${NPROCS}
sed -i "s/MPI_MAX_TASKS:-[0-9]*/MPI_MAX_TASKS:-${NPROCS}/" ${BASE}/mpiexec_simple.sh

singularity exec \
  --writable-tmpfs \
  --env LOGNAME=nosuser \
  --env TOTAL_TASKS=${NPROCS} \
  --env NSCRIBES=0 \
  --env MPI_MAX_TASKS=${NPROCS} \
  --env LD_PRELOAD="" \
  --env OMPI_MCA_btl="self,vader,tcp" \
  --env OMPI_MCA_btl_tcp_if_include="lo" \
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
  /opt/nosofs/docker/run_secofs_ufs.sh nowcast --pdy ${PDY} --cyc ${CYC} --ofs ${OFS}
