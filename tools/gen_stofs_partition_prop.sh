#!/bin/bash
# ======================================================================
# gen_stofs_partition_prop.sh
#
# Generate a pre-computed partition.prop for STOFS-3D-ATL-UFS using
# SCHISM's bundled METIS utilities. Required when fv3_coastalS.exe is
# built with -DNO_PARMETIS=ON (bypasses runtime ParMETIS).
#
# Usage:
#   ./tools/gen_stofs_partition_prop.sh <N_OCN_RANKS> [SCHISM_SRC] [HGRID]
#
# Defaults:
#   N_OCN_RANKS = 2794 (SECOFS-equivalent rank count for v2.1 STOFS mesh)
#   SCHISM_SRC  = $LOGNAME/packages/IT-stofs.v2.1.0/sorc/stofs_3d_atl/stofs_3d_atl_pschism.fd
#   HGRID       = $LOGNAME/packages/IT-stofs.v2.1.0/fix/stofs_3d_atl/stofs_3d_atl_hgrid.gr3
#
# Produces:
#   partition.prop.<N> in cwd, optionally staged to $PKG/fix/...
#
# Reference: SCHISM Preprocessed Partitioning Tutorial (Mansur Jisan, 2025-06-27)
# ======================================================================
set -e

NCORES=${1:-2794}
SCHISM_SRC=${2:-/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/IT-stofs.v2.1.0/sorc/stofs_3d_atl/stofs_3d_atl_pschism.fd}
HGRID=${3:-/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/IT-stofs.v2.1.0/fix/stofs_3d_atl/stofs_3d_atl_hgrid.gr3}

GRID_SCRIPTS=${SCHISM_SRC}/src/Utility/Grid_Scripts
METIS_DIR=${SCHISM_SRC}/src/metis-5.1.0

echo "============================================="
echo "STOFS partition.prop generator"
echo "============================================="
echo " N OCN ranks : ${NCORES}"
echo " SCHISM src  : ${SCHISM_SRC}"
echo " hgrid       : ${HGRID}"
echo "============================================="

# Sanity checks
[ -d "${GRID_SCRIPTS}" ] || { echo "ERROR: SCHISM Utility/Grid_Scripts not found: ${GRID_SCRIPTS}"; exit 1; }
[ -d "${METIS_DIR}" ]    || { echo "ERROR: METIS bundle not found: ${METIS_DIR}"; exit 1; }
[ -f "${HGRID}" ]        || { echo "ERROR: hgrid.gr3 not found: ${HGRID}"; exit 1; }

# Step 1: Build metis_prep if missing
if [ ! -x "${GRID_SCRIPTS}/metis_prep" ]; then
    echo ">>> Building metis_prep..."
    (cd ${GRID_SCRIPTS} && ifort -mcmodel=medium -O2 -CB -g -traceback -o metis_prep metis_prep.f90)
fi

# Step 2: Build METIS if missing
if [ ! -x "${METIS_DIR}/build/Linux-x86_64/programs/gpmetis" ]; then
    echo ">>> Building METIS (this may take a few minutes)..."
    (cd ${METIS_DIR} && make config && make)
fi

# Step 3: Run partition_offline.pl in a temp work dir
WORK=$(mktemp -d -t stofs_partition_XXXXXX)
trap "rm -rf ${WORK}" EXIT
cp ${GRID_SCRIPTS}/partition_offline.pl ${WORK}/
ln -s ${GRID_SCRIPTS}/metis_prep ${WORK}/metis_prep
ln -s ${METIS_DIR}/build/Linux-x86_64/programs/gpmetis ${WORK}/gpmetis
ln -s ${HGRID} ${WORK}/hgrid.gr3

# Patch the perl script to use local paths
sed -i 's|\$prep=.*;|\$prep="./metis_prep";|' ${WORK}/partition_offline.pl
sed -i 's|\$gpmetis=.*;|\$gpmetis="./gpmetis";|' ${WORK}/partition_offline.pl

cd ${WORK}
echo ">>> Running partition_offline.pl ${NCORES}..."
perl partition_offline.pl ${NCORES}

# Step 4: Stage to repo's expected location (if $PKG set)
OUTPUT="partition.prop.${NCORES}"
[ -f "${OUTPUT}" ] || { echo "ERROR: partition_offline.pl did not produce ${OUTPUT}"; exit 1; }

if [ -n "${PKG:-}" ] && [ -d "${PKG}/fix/stofs_3d_atl_ufs" ]; then
    DEST=${PKG}/fix/stofs_3d_atl_ufs/stofs_3d_atl_ufs.partition.prop
    cp ${OUTPUT} ${DEST}
    echo ">>> Staged to: ${DEST}"
else
    cp ${OUTPUT} ${OLDPWD}/partition.prop.${NCORES}
    echo ">>> Copied to: ${OLDPWD}/partition.prop.${NCORES}"
    echo "   (\$PKG not set or fix dir absent — manually stage to \$PKG/fix/stofs_3d_atl_ufs/stofs_3d_atl_ufs.partition.prop)"
fi

# Verify max rank
MAX_RANK=$(awk 'NR>1 {if ($2>max) max=$2} END {print max}' ${OUTPUT})
EXPECTED=$((NCORES - 1))
echo ">>> Verify: max rank = ${MAX_RANK} (expected ${EXPECTED})"
if [ "${MAX_RANK}" -ne "${EXPECTED}" ]; then
    echo "WARN: max rank ${MAX_RANK} != expected ${EXPECTED}; review partition.prop"
fi

echo ">>> DONE"
