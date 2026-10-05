#!/bin/bash
# ======================================================================
# hercules_atl_seed_prev.sh
#
# Lay the previous-cycle dynamic-SSH-adjust seed out in the ops layout that
# nos-workflow reads (COMOUT_PREV = ${COMROOT}/nos/${RUN}.${PDYm1}):
#   <COMOUT_PREV>/staout_1
#   <COMOUT_PREV>/rerun/${RUN}.t12z.avg_bias
#   <COMOUT_PREV>/rerun/${RUN}.t12z.param.nml   (if the seed has one)
#
# Usage:
#   tools/hercules_atl_seed_prev.sh <SEED_DIR> <COMROOT> <PDY> [COMROOT ...]
# SEED_DIR is the bundle's seeds/dyn_seed_<PDYm1> (staout_1, <run>.t12z.avg_bias,
# param.nml). Give the standalone COMROOT_SA and the coupled COMROOT_UFS (the cards read
# those variables, nothing else). Files are
# copied, not linked, so a COMROOT can be purged independently.
#
# The WCOSS2 parity tests instead exported COMINrerun=<SEED_DIR> (flat dir,
# overrides this layout); do that in the sbatch environment to reproduce them
# exactly. Both read the same staout_1 and avg_bias. MJ (10/04/26)
# ======================================================================
set -euo pipefail

[ "$#" -ge 3 ] || { echo "Usage: $0 <SEED_DIR> <COMROOT> <PDY> [COMROOT ...]" >&2; exit 2; }
SEED=$1; PDY=$3
ROOTS=("$(realpath -m "$2")")
for r in "${@:4}"; do ROOTS+=("$(realpath -m "$r")"); done
CYC=${CYC:-12}
RUN=${RUN:-stofs_3d_atl_ufs}
NET=${NET:-nos}
PDYM1=$(date -u -d "${PDY} -1 day" +%Y%m%d)
BIAS="${RUN}.t${CYC}z.avg_bias"

[ -s "${SEED}/staout_1" ] || { echo "FATAL: ${SEED}/staout_1 missing" >&2; exit 1; }
[ -s "${SEED}/${BIAS}" ] || { echo "FATAL: ${SEED}/${BIAS} missing" >&2; exit 1; }

for root in "${ROOTS[@]}"; do
  prev="${root}/${NET}/${RUN}.${PDYM1}"
  mkdir -p "${prev}/rerun"
  cp -f "${SEED}/staout_1" "${prev}/staout_1"
  cp -f "${SEED}/${BIAS}" "${prev}/rerun/${BIAS}"
  [ -s "${SEED}/param.nml" ] && cp -f "${SEED}/param.nml" "${prev}/rerun/${RUN}.t${CYC}z.param.nml"
  echo "seeded ${prev}"
done
