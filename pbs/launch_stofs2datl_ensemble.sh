#!/bin/bash
# ======================================================================
# launch_stofs2datl_ensemble.sh - Submit STOFS-2D-ATL barotropic ensemble via PBS
#
# GEFS atmospheric-only ensemble (no physics perturbation).
# Uses the same 1.8M-node horizontal grid as 3D ATL but only 2 vertical
# levels for rapid water level forecasts.
#
# Chains jobs with qsub -W depend=afterok: dependencies:
#
#   prep --> gefs_atmos_prep --> member_000 \
#                             --> member_001  |
#                             --> member_002  |--> post_ensemble
#                             --> member_003  |
#                             --> member_004  |
#                             --> member_005 /
#
# The deterministic workflow (nowcast/forecast) can optionally
# run in parallel alongside the ensemble.
#
# Usage:
#   ./launch_stofs2datl_ensemble.sh                          # Default: cyc=12, 6 members, GEFS
#   ./launch_stofs2datl_ensemble.sh 12                       # Cycle 12
#   ./launch_stofs2datl_ensemble.sh 12 3                     # Cycle 12, 3 members
#   ./launch_stofs2datl_ensemble.sh 12 --with-det            # Also submit deterministic
#   ./launch_stofs2datl_ensemble.sh 12 --pdy 20260223        # Explicit PDY
#   ./launch_stofs2datl_ensemble.sh 12 --det-only            # Deterministic only (prep->nowcast->forecast)
#   ./launch_stofs2datl_ensemble.sh 12 --skip-prep           # Skip prep (already ran)
#
# Requirements:
#   - Run from the pbs/ directory (or set PBS_DIR)
#   - PBS scripts must exist in same directory
#
# Make executable: chmod +x launch_stofs2datl_ensemble.sh
# ======================================================================
set -e

# ---- Configuration ---------------------------------------------------
CYC=${1:-12}
# Track whether user explicitly provided N_MEMBERS
_USER_SET_MEMBERS=false
if [[ "${2:-}" != --* ]] && [ -n "${2:-}" ]; then
    _USER_SET_MEMBERS=true
fi
# If $2 is a flag (starts with --), don't consume it as N_MEMBERS
if [[ "${2:-}" == --* ]]; then
    N_MEMBERS=6
    shift 1 2>/dev/null || true
else
    N_MEMBERS=${2:-6}
    shift 2 2>/dev/null || true
fi
WITH_DET=false
SKIP_PREP=false
DET_ONLY=false

# Check for flags
for arg in "$@"; do
    case "$arg" in
        --with-det)    WITH_DET=true ;;
        --skip-prep)   SKIP_PREP=true ;;
        --det-only)    DET_ONLY=true ;;
        --pdy)         _NEXT_IS_PDY=true ;;
        *)
            if [ "${_NEXT_IS_PDY:-}" = true ]; then
                PDY="$arg"
                _NEXT_IS_PDY=false
            fi
            ;;
    esac
done
unset _NEXT_IS_PDY _USER_SET_MEMBERS

# PDY: use env var, --pdy flag, or default to today
PDY=${PDY:-$(date +%Y%m%d)}
export PDY

PBS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=============================================="
echo " STOFS-2D-ATL Barotropic Ensemble Launcher"
echo "=============================================="
echo " PDY:       ${PDY}"
echo " Cycle:     ${CYC}"
if [ "${DET_ONLY}" = true ]; then
echo " Mode:      DETERMINISTIC ONLY (prep->nowcast->forecast)"
else
echo " Members:   ${N_MEMBERS} (1 control GFS+HRRR + 4 GEFS + 1 RRFS)"
echo " Ensemble:  GEFS atmospheric-only (no physics perturbation)"
echo " Det run:   ${WITH_DET}"
fi
echo " Skip prep: ${SKIP_PREP}"
echo " PBS dir:   ${PBS_DIR}"
echo "=============================================="

# ---- Validate PBS scripts exist --------------------------------------
PREP_PBS="${PBS_DIR}/jnos_stofs2datl_prep_${CYC}.pbs"
MEMBER_PBS="${PBS_DIR}/jnos_stofs2datl_ensemble_member.pbs"
POST_PBS="${PBS_DIR}/jnos_stofs2datl_ensemble_post.pbs"
ATMOS_PREP_PBS="${PBS_DIR}/jnos_stofs2datl_ensemble_atmos_prep.pbs"

if [ "${DET_ONLY}" != true ]; then
    for script in "${PREP_PBS}" "${MEMBER_PBS}" "${POST_PBS}" "${ATMOS_PREP_PBS}"; do
        if [ ! -f "${script}" ]; then
            echo "ERROR: PBS script not found: ${script}" >&2
            exit 1
        fi
    done
else
    if [ ! -f "${PREP_PBS}" ]; then
        echo "ERROR: Prep PBS script not found: ${PREP_PBS}" >&2
        exit 1
    fi
fi

RPTDIR=/lfs/h1/nos/ptmp/$LOGNAME/rpt/stofs_2d_atl
mkdir -p ${RPTDIR} 2>/dev/null || true

# Archive old log files before submission
for f in ${RPTDIR}/stofs2datl_*_${CYC}.out ${RPTDIR}/stofs2datl_*_${CYC}.err; do
    [ -s "$f" ] && mv "$f" "${f}.$(date -r "$f" +%Y%m%d_%H%M%S)" 2>/dev/null || true
done

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

# ---- Deterministic-only mode: just prep -> nowcast -> forecast -------
if [ "${DET_ONLY}" = true ]; then
    echo ""
    echo ">>> Deterministic-only mode: submitting nowcast + forecast..."

    NCST_PBS="${PBS_DIR}/jnos_stofs2datl_nowcast_${CYC}.pbs"
    FCST_PBS="${PBS_DIR}/jnos_stofs2datl_forecast_${CYC}.pbs"

    if [ ! -f "${NCST_PBS}" ] || [ ! -f "${FCST_PBS}" ]; then
        echo "ERROR: Deterministic PBS scripts not found:" >&2
        [ ! -f "${NCST_PBS}" ] && echo "  Missing: ${NCST_PBS}" >&2
        [ ! -f "${FCST_PBS}" ] && echo "  Missing: ${FCST_PBS}" >&2
        exit 1
    fi

    NCST_JOBID=$(qsub \
        -v "PDY=${PDY},cyc=${CYC}" \
        ${PREP_JOBID_SHORT:+-W depend=afterok:${PREP_JOBID_SHORT}} \
        "${NCST_PBS}")
    NCST_SHORT=${NCST_JOBID%%.*}
    echo "    Nowcast:  ${NCST_JOBID}"

    FCST_JOBID=$(qsub \
        -v "PDY=${PDY},cyc=${CYC}" \
        -W depend=afterok:${NCST_SHORT} \
        "${FCST_PBS}")
    FCST_SHORT=${FCST_JOBID%%.*}
    echo "    Forecast: ${FCST_JOBID}"

    echo ""
    echo "=============================================="
    echo " Deterministic workflow submitted successfully"
    echo "=============================================="
    echo ""
    echo " Dependency chain:"
    echo "   prep (${PREP_JOBID_SHORT:-skipped})"
    echo "     +-> nowcast (${NCST_SHORT})"
    echo "           +-> forecast (${FCST_SHORT})"
    echo ""
    echo " Monitor with:  qstat -u $LOGNAME"
    echo " Cancel all:    qdel ${PREP_JOBID_SHORT:-} ${NCST_SHORT} ${FCST_SHORT}"
    echo ""
    exit 0
fi

# ---- Step 1b: Submit GEFS atmospheric prep job -----------------------
echo ""
echo ">>> Submitting GEFS+RRFS atmospheric ensemble prep job..."
ATMOS_QSUB_ARGS=(-v "CYC=${CYC},PDY=${PDY},GEFS_ENSEMBLE=true" \
                  -N "stofs2datl_gefs_prep_${CYC}" \
                  -o "${RPTDIR}/stofs2datl_gefs_prep_${CYC}.out" \
                  -e "${RPTDIR}/stofs2datl_gefs_prep_${CYC}.err")
if [ -n "${PREP_JOBID_SHORT}" ]; then
    ATMOS_QSUB_ARGS+=(-W "depend=afterok:${PREP_JOBID_SHORT}")
fi
ATMOS_PREP_JOBID=$(qsub "${ATMOS_QSUB_ARGS[@]}" "${ATMOS_PREP_PBS}")
ATMOS_PREP_JOBID_SHORT=${ATMOS_PREP_JOBID%%.*}
echo "    GEFS atmos prep: ${ATMOS_PREP_JOBID}"

# ---- Step 2a (optional): Submit deterministic nowcast before ensemble --
NCST_JOBID_SHORT=""
FCST_JOBID_SHORT=""
if [ "${WITH_DET}" = true ]; then
    echo ""
    echo ">>> Submitting deterministic nowcast (required for ensemble ihot=2)..."

    NCST_PBS="${PBS_DIR}/jnos_stofs2datl_nowcast_${CYC}.pbs"
    FCST_PBS="${PBS_DIR}/jnos_stofs2datl_forecast_${CYC}.pbs"

    if [ ! -f "${NCST_PBS}" ]; then
        echo "ERROR: Nowcast PBS script not found: ${NCST_PBS}" >&2
        exit 1
    fi

    NCST_JOBID=$(qsub \
        -v "PDY=${PDY},cyc=${CYC}" \
        ${PREP_JOBID_SHORT:+-W depend=afterok:${PREP_JOBID_SHORT}} \
        "${NCST_PBS}")
    NCST_JOBID_SHORT=${NCST_JOBID%%.*}
    echo "    Nowcast:  ${NCST_JOBID}"

    if [ -f "${FCST_PBS}" ]; then
        FCST_JOBID=$(qsub \
            -v "PDY=${PDY},cyc=${CYC}" \
            -W depend=afterok:${NCST_JOBID_SHORT} \
            "${FCST_PBS}")
        FCST_JOBID_SHORT=${FCST_JOBID%%.*}
        echo "    Forecast: ${FCST_JOBID} (parallel with ensemble)"
    fi
fi

# ---- Step 2b: Submit ensemble members --------------------------------
echo ""
echo ">>> Submitting ${N_MEMBERS} ensemble members (GEFS atmospheric-only)..."
MEMBER_JOBIDS=()

# Build member dependency string
MEMBER_DEP_PARTS=()
if [ -n "${NCST_JOBID_SHORT}" ]; then
    MEMBER_DEP_PARTS+=("${NCST_JOBID_SHORT}")
elif [ -n "${PREP_JOBID_SHORT}" ]; then
    MEMBER_DEP_PARTS+=("${PREP_JOBID_SHORT}")
fi
if [ -n "${ATMOS_PREP_JOBID_SHORT}" ]; then
    MEMBER_DEP_PARTS+=("${ATMOS_PREP_JOBID_SHORT}")
fi

MEMBER_DEP_STR=""
if [ ${#MEMBER_DEP_PARTS[@]} -gt 0 ]; then
    MEMBER_DEP_STR="afterok"
    for dep in "${MEMBER_DEP_PARTS[@]}"; do
        MEMBER_DEP_STR="${MEMBER_DEP_STR}:${dep}"
    done
fi

for i in $(seq 0 $((N_MEMBERS - 1))); do
    MID=$(printf '%03d' $i)
    GEFS_MEM_ID=$(printf '%02d' $i)
    MEMBER_VARS="MEMBER_ID=${MID},CYC=${CYC},PDY=${PDY},GEFS_ENSEMBLE=true,GEFS_MEMBER_ID=${GEFS_MEM_ID}"
    QSUB_ARGS=(-v "${MEMBER_VARS}" \
               -N "stofs2datl_ens${MID}_${CYC}" \
               -o "${RPTDIR}/stofs2datl_ens${MID}_${CYC}.out" \
               -e "${RPTDIR}/stofs2datl_ens${MID}_${CYC}.err")
    if [ -n "${MEMBER_DEP_STR}" ]; then
        QSUB_ARGS+=(-W "depend=${MEMBER_DEP_STR}")
    fi
    MJOB=$(qsub "${QSUB_ARGS[@]}" "${MEMBER_PBS}")
    MEMBER_JOBIDS+=("${MJOB}")
    MJOB_SHORT=${MJOB%%.*}
    if [ "${MID}" = "000" ]; then
        echo "    Member ${MID} (control GFS+HRRR): ${MJOB}"
    elif [ "${MID}" = "005" ]; then
        echo "    Member ${MID} (RRFS 3km): ${MJOB}"
    else
        echo "    Member ${MID} (GEFS gep${GEFS_MEM_ID}): ${MJOB}"
    fi
done

# ---- Step 3: Submit ensemble post (depend on ALL members) ------------
echo ""
echo ">>> Submitting ensemble post-processing..."

DEP_STR="afterok"
for mjob in "${MEMBER_JOBIDS[@]}"; do
    DEP_STR="${DEP_STR}:${mjob%%.*}"
done

ENSPOST_JOBID=$(qsub \
    -v "N_MEMBERS=${N_MEMBERS},CYC=${CYC},PDY=${PDY}" \
    -N "stofs2datl_enspost_${CYC}" \
    -o "${RPTDIR}/stofs2datl_enspost_${CYC}.out" \
    -e "${RPTDIR}/stofs2datl_enspost_${CYC}.err" \
    -W depend=${DEP_STR} \
    "${POST_PBS}")
echo "    Ensemble post: ${ENSPOST_JOBID}"

# ---- Summary ---------------------------------------------------------
echo ""
echo "=============================================="
echo " Barotropic ensemble workflow submitted"
echo "=============================================="
echo ""
echo " Dependency chain:"
echo "   prep (${PREP_JOBID_SHORT:-skipped})"
if [ -n "${NCST_JOBID_SHORT}" ]; then
    echo "     +-> nowcast (${NCST_JOBID_SHORT})"
    if [ -n "${FCST_JOBID_SHORT}" ]; then
        echo "     |     +-> forecast (${FCST_JOBID_SHORT})"
    fi
fi
echo "     +-> gefs_atmos_prep (${ATMOS_PREP_JOBID_SHORT})"
for i in $(seq 0 $((N_MEMBERS - 1))); do
    MID=$(printf '%03d' $i)
    MJOB_SHORT=${MEMBER_JOBIDS[$i]%%.*}
    echo "     +-> member_${MID} (${MJOB_SHORT})"
done
ENSPOST_SHORT=${ENSPOST_JOBID%%.*}
echo "           +-> post_ensemble (${ENSPOST_SHORT})"
if [ -n "${NCST_JOBID_SHORT}" ]; then
    echo ""
    echo " Members wait for nowcast to finish (ihot=2 continuous staout)"
fi
echo ""
echo " Monitor with:  qstat -u $LOGNAME"
ALL_JOBIDS="${PREP_JOBID_SHORT:-}"
[ -n "${NCST_JOBID_SHORT}" ] && ALL_JOBIDS="${ALL_JOBIDS} ${NCST_JOBID_SHORT}"
[ -n "${FCST_JOBID_SHORT}" ] && ALL_JOBIDS="${ALL_JOBIDS} ${FCST_JOBID_SHORT}"
ALL_JOBIDS="${ALL_JOBIDS} ${ATMOS_PREP_JOBID_SHORT} ${MEMBER_JOBIDS[*]%%.*} ${ENSPOST_SHORT}"
echo " Cancel all:    qdel ${ALL_JOBIDS}"
echo ""
