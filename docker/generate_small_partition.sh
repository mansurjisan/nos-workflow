#!/bin/bash
# ============================================================================
# generate_small_partition.sh - Create partition.prop for small core counts
#
# SECOFS on WCOSS2 uses 1080-1200 SCHISM compute procs. For Docker testing
# on dev machines, we need a partition for much fewer procs (e.g., 10-12).
#
# This script generates partition.prop using SCHISM's built-in ParMETIS
# partitioning via the UFS-Coastal container.
#
# Usage:
#   # Generate partition for 10 SCHISM compute procs
#   bash generate_small_partition.sh /path/to/fix/secofs 10
#
#   # Generate for 4 procs (minimum viable)
#   bash generate_small_partition.sh /path/to/fix/secofs 4
#
# Output:
#   /path/to/fix/secofs/secofs.partition.prop.N  (N = nprocs)
#
# Requirements:
#   - Docker with nosofs/secofs-ufs:latest loaded
#   - Fix directory with secofs.hgrid.gr3
# ============================================================================
set -eu

FIX_DIR="${1:?Usage: $0 /path/to/fix/secofs NPROCS}"
NPROCS="${2:-10}"

echo "=============================================="
echo " SECOFS Small Partition Generator"
echo "=============================================="
echo " Fix dir: ${FIX_DIR}"
echo " Procs:   ${NPROCS}"
echo ""

# Verify input files
if [ ! -f "${FIX_DIR}/secofs.hgrid.gr3" ]; then
    echo "ERROR: secofs.hgrid.gr3 not found in ${FIX_DIR}" >&2
    exit 1
fi

# Method 1: Use Python SCHISM partitioning (if pyschism available)
# This is the preferred method — no MPI needed
echo ">>> Attempting Python-based partitioning..."

docker run --rm \
    -v "${FIX_DIR}:/fix:ro" \
    -v "$(pwd):/output" \
    --entrypoint bash nosofs/secofs-ufs:latest -c "
set -e
cd /tmp

# Try pyschism first
python3 -c '
import sys
try:
    from pyschism.mesh import Hgrid
    hgrid = Hgrid.open(\"/fix/secofs.hgrid.gr3\")
    print(f\"Grid: {hgrid.values.shape[0]} nodes, {hgrid.elements.id.shape[0]} elements\")

    # Generate partition using metis
    try:
        import metis
        partition = hgrid.partition(nprocs=${NPROCS})
        partition.to_file(\"/output/secofs.partition.prop.${NPROCS}\")
        print(f\"Partition saved: secofs.partition.prop.${NPROCS}\")
        sys.exit(0)
    except ImportError:
        print(\"pyschism metis not available, falling back to manual method\")
        sys.exit(1)
except ImportError:
    print(\"pyschism not available, falling back to manual method\")
    sys.exit(1)
' 2>/dev/null && exit 0

# Method 2: Simple round-robin partition (not optimal but functional)
echo 'Generating round-robin partition (non-optimal but functional)...'
python3 -c '
import sys

# Read hgrid.gr3 to get element count
with open(\"/fix/secofs.hgrid.gr3\") as f:
    header = f.readline()  # first line is description
    counts = f.readline().split()
    ne = int(counts[0])  # number of elements
    nn = int(counts[1])  # number of nodes

print(f\"Grid: {nn} nodes, {ne} elements\")
nprocs = ${NPROCS}

# Simple round-robin assignment
with open(\"/output/secofs.partition.prop.${NPROCS}\", \"w\") as out:
    for i in range(ne):
        out.write(f\"{i % nprocs}\n\")

print(f\"Round-robin partition saved: secofs.partition.prop.${NPROCS}\")
print(f\"WARNING: Round-robin is NOT load-balanced. For production, use ParMETIS.\")
'
" 2>&1

if [ -f "secofs.partition.prop.${NPROCS}" ]; then
    echo ""
    echo ">>> Partition generated: secofs.partition.prop.${NPROCS}"
    echo "    Elements: $(wc -l < secofs.partition.prop.${NPROCS})"
    echo "    Procs: ${NPROCS}"
    echo ""
    echo "    To use: copy to fix dir as 'secofs.partition.prop'"
    echo "    cp secofs.partition.prop.${NPROCS} ${FIX_DIR}/secofs.partition.prop"
    echo ""
    echo "    NOTE: For UFS-Coastal, SCHISM compute procs = TOTAL_TASKS - DATM_TASKS"
    echo "    Example: 12 total - 2 DATM = 10 SCHISM compute procs"
    echo "    The partition must match the SCHISM compute proc count."
else
    echo "ERROR: Partition generation failed" >&2
    exit 1
fi
