#!/bin/bash
# ======================================================================
# launch_stofs3datl_ensemble.sh - Submit STOFS-3D-ATL ensemble workflow via PBS
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
# With --atmos-ensemble, an atmospheric prep job is inserted:
#
#   prep --> atmos_prep --> member_000 \
#                       --> member_001  |
#                       --> member_002  |--> post_ensemble
#                       --> member_003  |
#                       --> member_004 /
#
# The deterministic workflow (nowcast/forecast) can optionally
# run in parallel alongside the ensemble.
#
# Usage:
#   ./launch_stofs3datl_ensemble.sh                          # Default: cyc=12, 5 members
#   ./launch_stofs3datl_ensemble.sh 12                       # Cycle 12
#   ./launch_stofs3datl_ensemble.sh 12 3                     # Cycle 12, 3 members
#   ./launch_stofs3datl_ensemble.sh 12 5 --with-det          # Also submit deterministic
#   ./launch_stofs3datl_ensemble.sh 12 3 --atmos-ensemble    # Include atmospheric forcing ensemble
#   ./launch_stofs3datl_ensemble.sh 12 3 --pdy 20260216      # Explicit PDY
#
# Requirements:
#   - Run from the pbs/ directory (or set PBS_DIR)
#   - Prep job PBS script must exist: jnos_stofs3datl_prep_${CYC}.pbs
#   - Ensemble member/post PBS scripts in same directory
#
# Make executable: chmod +x launch_stofs3datl_ensemble.sh
# ======================================================================
set -e

# ---- Configuration ---------------------------------------------------
CYC=${1:-12}
N_MEMBERS=${2:-5}
WITH_DET=false
SKIP_PREP=false
ATMOS_ENSEMBLE=false

# Check for flags
shift 2 2>/dev/null || true
for arg in "$@"; do
    case "$arg" in
        --with-det)          WITH_DET=true ;;
        --skip-prep)         SKIP_PREP=true ;;
        --atmos-ensemble)    ATMOS_ENSEMBLE=true ;;
        --pdy)               _NEXT_IS_PDY=true ;;
        *)
            if [ "${_NEXT_IS_PDY:-}" = true ]; then
                PDY="$arg"
                _NEXT_IS_PDY=false
            fi
            ;;
    esac
done
unset _NEXT_IS_PDY

# PDY: use env var, --pdy flag, or default to today
PDY=${PDY:-$(date +%Y%m%d)}
export PDY

PBS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=============================================="
echo " STOFS-3D-ATL Ensemble Launcher"
echo "=============================================="
echo " PDY:       ${PDY}"
echo " Cycle:     ${CYC}"
echo " Members:   ${N_MEMBERS} (1 control + $((N_MEMBERS - 1)) perturbed)"
echo " Det run:   ${WITH_DET}"
echo " Atmos ens: ${ATMOS_ENSEMBLE}"
echo " Skip prep: ${SKIP_PREP}"
echo " PBS dir:   ${PBS_DIR}"
echo "=============================================="

# ---- Validate PBS scripts exist --------------------------------------
PREP_PBS="${PBS_DIR}/jnos_stofs3datl_prep_${CYC}.pbs"
MEMBER_PBS="${PBS_DIR}/jnos_stofs3datl_ensemble_member.pbs"
POST_PBS="${PBS_DIR}/jnos_stofs3datl_ensemble_post.pbs"
ATMOS_PREP_PBS="${PBS_DIR}/jnos_stofs3datl_ensemble_atmos_prep.pbs"

for script in "${PREP_PBS}" "${MEMBER_PBS}" "${POST_PBS}"; do
    if [ ! -f "${script}" ]; then
        echo "ERROR: PBS script not found: ${script}" >&2
        exit 1
    fi
done

if [ "${ATMOS_ENSEMBLE}" = true ] && [ ! -f "${ATMOS_PREP_PBS}" ]; then
    echo "ERROR: Atmos prep PBS script not found: ${ATMOS_PREP_PBS}" >&2
    echo "  Required when --atmos-ensemble is used" >&2
    exit 1
fi

RPTDIR=/lfs/h1/nos/ptmp/$LOGNAME/rpt/stofs_3d_atl
mkdir -p ${RPTDIR} 2>/dev/null || true

# ---- Step 1: Submit prep job (unless --skip-prep) --------------------
if [ "${SKIP_PREP}" = true ]; then
    echo ""
    echo ">>> Skipping prep (--skip-prep). Members will run without dependency."
    PREP_JOBID_SHORT=""
else
    echo ""
    echo ">>> Submitting prep job..."
    PREP_JOBID=$(qsub -v "PDY=${PDY}" "${PREP_PBS}")
    PREP_JOBID_SHORT=${PREP_JOBID%%.*}
    echo "    Prep job: ${PREP_JOBID}"
fi

# ---- Step 1b: Submit atmos prep job (if --atmos-ensemble) ------------
ATMOS_PREP_JOBID_SHORT=""
if [ "${ATMOS_ENSEMBLE}" = true ]; then
    echo ""
    echo ">>> Submitting atmospheric ensemble prep job..."
    ATMOS_QSUB_ARGS=(-v "CYC=${CYC},PDY=${PDY}" \
                      -N "stofs3datl_atmos_prep_${CYC}" \
                      -o "${RPTDIR}/stofs3datl_atmos_prep_${CYC}.out" \
                      -e "${RPTDIR}/stofs3datl_atmos_prep_${CYC}.err")
    if [ -n "${PREP_JOBID_SHORT}" ]; then
        ATMOS_QSUB_ARGS+=(-W "depend=afterok:${PREP_JOBID_SHORT}")
    fi
    ATMOS_PREP_JOBID=$(qsub "${ATMOS_QSUB_ARGS[@]}" "${ATMOS_PREP_PBS}")
    ATMOS_PREP_JOBID_SHORT=${ATMOS_PREP_JOBID%%.*}
    echo "    Atmos prep: ${ATMOS_PREP_JOBID}"
fi

# ---- Step 2: Submit ensemble members (depend on prep + atmos_prep) ---
echo ""
echo ">>> Submitting ${N_MEMBERS} ensemble members..."
MEMBER_JOBIDS=()

# Build member dependency string
# Members depend on prep, and also on atmos_prep when --atmos-ensemble is used
MEMBER_DEP_STR=""
if [ -n "${PREP_JOBID_SHORT}" ] && [ -n "${ATMOS_PREP_JOBID_SHORT}" ]; then
    MEMBER_DEP_STR="afterok:${PREP_JOBID_SHORT}:${ATMOS_PREP_JOBID_SHORT}"
elif [ -n "${PREP_JOBID_SHORT}" ]; then
    MEMBER_DEP_STR="afterok:${PREP_JOBID_SHORT}"
elif [ -n "${ATMOS_PREP_JOBID_SHORT}" ]; then
    MEMBER_DEP_STR="afterok:${ATMOS_PREP_JOBID_SHORT}"
fi

for i in $(seq 0 $((N_MEMBERS - 1))); do
    MID=$(printf '%03d' $i)
    QSUB_ARGS=(-v "MEMBER_ID=${MID},CYC=${CYC},PDY=${PDY}" \
               -N "stofs3datl_ens${MID}_${CYC}" \
               -o "${RPTDIR}/stofs3datl_ens${MID}_${CYC}.out" \
               -e "${RPTDIR}/stofs3datl_ens${MID}_${CYC}.err")
    if [ -n "${MEMBER_DEP_STR}" ]; then
        QSUB_ARGS+=(-W "depend=${MEMBER_DEP_STR}")
    fi
    MJOB=$(qsub "${QSUB_ARGS[@]}" "${MEMBER_PBS}")
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
    -v "N_MEMBERS=${N_MEMBERS},CYC=${CYC},PDY=${PDY}" \
    -N "stofs3datl_enspost_${CYC}" \
    -W depend=${DEP_STR} \
    "${POST_PBS}")
echo "    Ensemble post: ${ENSPOST_JOBID}"

# ---- Step 4 (optional): Submit deterministic workflow ----------------
if [ "${WITH_DET}" = true ]; then
    echo ""
    echo ">>> Submitting deterministic workflow..."

    NCST_PBS="${PBS_DIR}/jnos_stofs3datl_nowcast_${CYC}.pbs"
    FCST_PBS="${PBS_DIR}/jnos_stofs3datl_forecast_${CYC}.pbs"

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
if [ -n "${ATMOS_PREP_JOBID_SHORT}" ]; then
    echo "     └─> atmos_prep (${ATMOS_PREP_JOBID_SHORT})"
fi
for i in $(seq 0 $((N_MEMBERS - 1))); do
    MID=$(printf '%03d' $i)
    MJOB_SHORT=${MEMBER_JOBIDS[$i]%%.*}
    echo "     └─> member_${MID} (${MJOB_SHORT})"
done
ENSPOST_SHORT=${ENSPOST_JOBID%%.*}
echo "           └─> post_ensemble (${ENSPOST_SHORT})"
echo ""
echo " Monitor with:  qstat -u $LOGNAME"
ALL_JOBIDS="${PREP_JOBID_SHORT}"
[ -n "${ATMOS_PREP_JOBID_SHORT}" ] && ALL_JOBIDS="${ALL_JOBIDS} ${ATMOS_PREP_JOBID_SHORT}"
ALL_JOBIDS="${ALL_JOBIDS} ${MEMBER_JOBIDS[*]%%.*} ${ENSPOST_SHORT}"
echo " Cancel all:    qdel ${ALL_JOBIDS}"
echo ""
