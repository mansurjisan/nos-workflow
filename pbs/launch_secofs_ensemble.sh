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
# With --atmos-ensemble, an atmospheric prep job is inserted:
#
#   prep --> atmos_prep --> member_000 \
#                       --> member_001  |
#                       --> member_002  |--> post_ensemble
#                       --> member_003  |
#                       --> member_004 /
#
# The deterministic workflow (nowcast/forecast/post) can optionally
# run in parallel alongside the ensemble.
#
# Usage:
#   ./launch_secofs_ensemble.sh                          # Default: cyc=00, 5 members, PDY=today
#   ./launch_secofs_ensemble.sh 12                       # Cycle 12
#   ./launch_secofs_ensemble.sh 00 3                     # Cycle 00, 3 members
#   ./launch_secofs_ensemble.sh 00 5 --with-det          # Also submit deterministic
#   ./launch_secofs_ensemble.sh 00 3 --atmos-ensemble    # Include atmospheric forcing ensemble
#   ./launch_secofs_ensemble.sh 00 --gefs                 # GEFS ensemble (10 members, auto)
#   ./launch_secofs_ensemble.sh 00 5 --gefs               # GEFS ensemble (5 members, override)
#   PDY=20260212 ./launch_secofs_ensemble.sh 00 3        # Explicit PDY
#   ./launch_secofs_ensemble.sh 00 3 --pdy 20260212      # Explicit PDY (alt)
#   ./launch_secofs_ensemble.sh 00 3 --skip-prep         # Skip prep, submit members only
#   ./launch_secofs_ensemble.sh 00 --det-only             # Deterministic only (prep→nowcast→forecast)
#   ./launch_secofs_ensemble.sh 00 --det-only --pdy 20260216
#
# Requirements:
#   - Run from the pbs/ directory (or set PBS_DIR)
#   - Prep job PBS script must exist: jnos_secofs_prep_${CYC}.pbs
#   - Ensemble member/post PBS scripts in same directory
# ======================================================================
set -e

# ---- Configuration ---------------------------------------------------
CYC=${1:-00}
# Track whether user explicitly provided N_MEMBERS (before shift consumes $2)
_USER_SET_MEMBERS=false
if [[ "${2:-}" != --* ]] && [ -n "${2:-}" ]; then
    _USER_SET_MEMBERS=true
fi
# If $2 is a flag (starts with --), don't consume it as N_MEMBERS
if [[ "${2:-}" == --* ]]; then
    N_MEMBERS=5
    shift 1 2>/dev/null || true
else
    N_MEMBERS=${2:-5}
    shift 2 2>/dev/null || true
fi
WITH_DET=false
SKIP_PREP=false
ATMOS_ENSEMBLE=false
GEFS_ENSEMBLE=false
DET_ONLY=false

# Check for flags
for arg in "$@"; do
    case "$arg" in
        --with-det)          WITH_DET=true ;;
        --skip-prep)         SKIP_PREP=true ;;
        --atmos-ensemble)    ATMOS_ENSEMBLE=true ;;
        --gefs)              GEFS_ENSEMBLE=true; ATMOS_ENSEMBLE=true ;;
        --det-only)          DET_ONLY=true ;;
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

# GEFS defaults: 6 members for SECOFS (4 GEFS + 1 RRFS + 1 control)
if [ "${GEFS_ENSEMBLE}" = true ] && [ "${_USER_SET_MEMBERS}" = false ]; then
    N_MEMBERS=6
fi
unset _USER_SET_MEMBERS

# PDY: use env var, --pdy flag, or default to today
PDY=${PDY:-$(date +%Y%m%d)}
export PDY

PBS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=============================================="
echo " SECOFS Ensemble Launcher"
echo "=============================================="
echo " PDY:      ${PDY}"
echo " Cycle:    ${CYC}"
if [ "${DET_ONLY}" = true ]; then
echo " Mode:      DETERMINISTIC ONLY (prep→nowcast→forecast)"
else
echo " Members:  ${N_MEMBERS} (1 control + $((N_MEMBERS - 1)) perturbed)"
echo " Det run:  ${WITH_DET}"
echo " Atmos ens: ${ATMOS_ENSEMBLE}"
if [ "${GEFS_ENSEMBLE}" = true ]; then
echo " GEFS ens:  true (0.25 deg pgrb2sp25, members gep01-gep$(printf '%02d' $((N_MEMBERS - 1))))"
fi
fi
echo " Skip prep: ${SKIP_PREP}"
echo " PBS dir:  ${PBS_DIR}"
echo "=============================================="

# ---- Validate PBS scripts exist --------------------------------------
PREP_PBS="${PBS_DIR}/jnos_secofs_prep_${CYC}.pbs"
MEMBER_PBS="${PBS_DIR}/jnos_secofs_ensemble_member.pbs"
POST_PBS="${PBS_DIR}/jnos_secofs_ensemble_post.pbs"
ATMOS_PREP_PBS="${PBS_DIR}/jnos_secofs_ensemble_atmos_prep.pbs"

# For det-only mode, only prep + nowcast + forecast are needed
if [ "${DET_ONLY}" != true ]; then
    for script in "${PREP_PBS}" "${MEMBER_PBS}" "${POST_PBS}"; do
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

if [ "${ATMOS_ENSEMBLE}" = true ] && [ ! -f "${ATMOS_PREP_PBS}" ]; then
    echo "ERROR: Atmos prep PBS script not found: ${ATMOS_PREP_PBS}" >&2
    echo "  Required when --atmos-ensemble is used" >&2
    exit 1
fi

RPTDIR=/lfs/h1/nos/ptmp/$LOGNAME/rpt/v3.7.0
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

# ---- Deterministic-only mode: just prep → nowcast → forecast ---------
if [ "${DET_ONLY}" = true ]; then
    echo ""
    echo ">>> Deterministic-only mode: submitting nowcast + forecast..."

    NCST_PBS="${PBS_DIR}/jnos_secofs_nowcast_${CYC}.pbs"
    FCST_PBS="${PBS_DIR}/jnos_secofs_forecast_${CYC}.pbs"

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

    # Summary
    echo ""
    echo "=============================================="
    echo " Deterministic workflow submitted successfully"
    echo "=============================================="
    echo ""
    echo " Dependency chain:"
    echo "   prep (${PREP_JOBID_SHORT:-skipped})"
    echo "     └─> nowcast (${NCST_SHORT})"
    echo "           └─> forecast (${FCST_SHORT})"
    echo ""
    echo " Monitor with:  qstat -u $LOGNAME"
    echo " Cancel all:    qdel ${PREP_JOBID_SHORT:-} ${NCST_SHORT} ${FCST_SHORT}"
    echo ""
    exit 0
fi

# ---- Step 1b: Submit atmos prep job (if --atmos-ensemble or --gefs) ---
ATMOS_PREP_JOBID_SHORT=""
if [ "${ATMOS_ENSEMBLE}" = true ]; then
    echo ""
    if [ "${GEFS_ENSEMBLE}" = true ]; then
        echo ">>> Submitting GEFS atmospheric ensemble prep job..."
        # Don't pass GEFS_MEMBERS — let the J-job read from YAML config.
        # YAML correctly distinguishes GEFS members from RRFS/other sources.
        ATMOS_QSUB_ARGS=(-v "CYC=${CYC},PDY=${PDY},GEFS_ENSEMBLE=true" \
                          -N "secofs_gefs_prep_${CYC}" \
                          -o "${RPTDIR}/secofs_gefs_prep_${CYC}.out" \
                          -e "${RPTDIR}/secofs_gefs_prep_${CYC}.err")
    else
        echo ">>> Submitting atmospheric ensemble prep job..."
        ATMOS_QSUB_ARGS=(-v "CYC=${CYC},PDY=${PDY}" \
                          -N "secofs_atmos_prep_${CYC}" \
                          -o "${RPTDIR}/secofs_atmos_prep_${CYC}.out" \
                          -e "${RPTDIR}/secofs_atmos_prep_${CYC}.err")
    fi
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
    # Base variables for every member
    MEMBER_VARS="MEMBER_ID=${MID},CYC=${CYC},PDY=${PDY}"
    # Pass GEFS_ENSEMBLE flag so J-job knows to stage GEFS sflux files
    if [ "${GEFS_ENSEMBLE}" = true ]; then
        GEFS_MEM_ID=$(printf '%02d' $i)
        MEMBER_VARS="${MEMBER_VARS},GEFS_ENSEMBLE=true,GEFS_MEMBER_ID=${GEFS_MEM_ID}"
    fi
    QSUB_ARGS=(-v "${MEMBER_VARS}" \
               -N "secofs_ens${MID}_${CYC}" \
               -o "${RPTDIR}/secofs_ens${MID}_${CYC}.out" \
               -e "${RPTDIR}/secofs_ens${MID}_${CYC}.err")
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
