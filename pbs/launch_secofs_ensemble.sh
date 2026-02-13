#!/bin/bash
# ======================================================================
# launch_secofs_ensemble.sh - Submit SECOFS ensemble workflow via PBS
#
# Shell-based alternative to ecFlow for running the ensemble on WCOSS2.
# Chains jobs with qsub -W depend=afterok: dependencies:
#
#   prep --> member_000 \
#        --> member_001  |
#        --> member_002  |--> post_ensemble
#        --> member_003  |
#        --> member_004 /
#
# The deterministic workflow (nowcast/forecast/post) can optionally
# run in parallel alongside the ensemble.
#
# Usage:
#   ./launch_secofs_ensemble.sh                  # Default: cyc=00, 5 members
#   ./launch_secofs_ensemble.sh 12               # Cycle 12
#   ./launch_secofs_ensemble.sh 00 3             # Cycle 00, 3 members
#   ./launch_secofs_ensemble.sh 00 5 --with-det  # Also submit deterministic
#
# Requirements:
#   - Run from the pbs/ directory (or set PBS_DIR)
#   - Prep job PBS script must exist: jnos_secofs_prep_${CYC}.pbs
#   - Ensemble member/post PBS scripts in same directory
# ======================================================================
set -e

# ---- Configuration ---------------------------------------------------
CYC=${1:-00}
N_MEMBERS=${2:-5}
WITH_DET=false

# Check for --with-det flag
for arg in "$@"; do
    if [ "$arg" = "--with-det" ]; then
        WITH_DET=true
    fi
done

PBS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=============================================="
echo " SECOFS Ensemble Launcher"
echo "=============================================="
echo " Cycle:    ${CYC}"
echo " Members:  ${N_MEMBERS} (1 control + $((N_MEMBERS - 1)) perturbed)"
echo " Det run:  ${WITH_DET}"
echo " PBS dir:  ${PBS_DIR}"
echo "=============================================="

# ---- Validate PBS scripts exist --------------------------------------
PREP_PBS="${PBS_DIR}/jnos_secofs_prep_${CYC}.pbs"
MEMBER_PBS="${PBS_DIR}/jnos_secofs_ensemble_member.pbs"
POST_PBS="${PBS_DIR}/jnos_secofs_ensemble_post.pbs"

for script in "${PREP_PBS}" "${MEMBER_PBS}" "${POST_PBS}"; do
    if [ ! -f "${script}" ]; then
        echo "ERROR: PBS script not found: ${script}" >&2
        exit 1
    fi
done

# ---- Step 1: Submit prep job -----------------------------------------
echo ""
echo ">>> Submitting prep job..."
PREP_JOBID=$(qsub "${PREP_PBS}")
PREP_JOBID_SHORT=${PREP_JOBID%%.*}
echo "    Prep job: ${PREP_JOBID}"

# ---- Step 2: Submit ensemble members (depend on prep) ----------------
echo ""
echo ">>> Submitting ${N_MEMBERS} ensemble members..."
MEMBER_JOBIDS=()

for i in $(seq 0 $((N_MEMBERS - 1))); do
    MID=$(printf '%03d' $i)
    MJOB=$(qsub \
        -v "MEMBER_ID=${MID},CYC=${CYC}" \
        -N "secofs_ens${MID}_${CYC}" \
        -W depend=afterok:${PREP_JOBID_SHORT} \
        "${MEMBER_PBS}")
    MEMBER_JOBIDS+=("${MJOB}")
    MJOB_SHORT=${MJOB%%.*}
    if [ "${MID}" = "000" ]; then
        echo "    Member ${MID} (control): ${MJOB}"
    else
        echo "    Member ${MID} (perturbed): ${MJOB}"
    fi
done

# ---- Step 3: Submit ensemble post (depend on ALL members) ------------
echo ""
echo ">>> Submitting ensemble post-processing..."

# Build dependency string: afterok:id1:id2:id3:...
DEP_STR="afterok"
for mjob in "${MEMBER_JOBIDS[@]}"; do
    DEP_STR="${DEP_STR}:${mjob%%.*}"
done

ENSPOST_JOBID=$(qsub \
    -v "N_MEMBERS=${N_MEMBERS},CYC=${CYC}" \
    -N "secofs_enspost_${CYC}" \
    -W depend=${DEP_STR} \
    "${POST_PBS}")
echo "    Ensemble post: ${ENSPOST_JOBID}"

# ---- Step 4 (optional): Submit deterministic workflow ----------------
if [ "${WITH_DET}" = true ]; then
    echo ""
    echo ">>> Submitting deterministic workflow..."

    NCST_PBS="${PBS_DIR}/jnos_secofs_nowcast_${CYC}.pbs"
    FCST_PBS="${PBS_DIR}/jnos_secofs_forecast_${CYC}.pbs"

    if [ ! -f "${NCST_PBS}" ] || [ ! -f "${FCST_PBS}" ]; then
        echo "    WARNING: Deterministic PBS scripts not found, skipping"
    else
        NCST_JOBID=$(qsub \
            -W depend=afterok:${PREP_JOBID_SHORT} \
            "${NCST_PBS}")
        echo "    Nowcast:  ${NCST_JOBID}"

        NCST_SHORT=${NCST_JOBID%%.*}
        FCST_JOBID=$(qsub \
            -W depend=afterok:${NCST_SHORT} \
            "${FCST_PBS}")
        echo "    Forecast: ${FCST_JOBID}"
    fi
fi

# ---- Summary ---------------------------------------------------------
echo ""
echo "=============================================="
echo " Ensemble workflow submitted successfully"
echo "=============================================="
echo ""
echo " Dependency chain:"
echo "   prep (${PREP_JOBID_SHORT})"
for i in $(seq 0 $((N_MEMBERS - 1))); do
    MID=$(printf '%03d' $i)
    MJOB_SHORT=${MEMBER_JOBIDS[$i]%%.*}
    echo "     └─> member_${MID} (${MJOB_SHORT})"
done
ENSPOST_SHORT=${ENSPOST_JOBID%%.*}
echo "           └─> post_ensemble (${ENSPOST_SHORT})"
echo ""
echo " Monitor with:  qstat -u $LOGNAME"
echo " Cancel all:    qdel ${PREP_JOBID_SHORT} ${MEMBER_JOBIDS[*]%%.*} ${ENSPOST_SHORT}"
echo ""
