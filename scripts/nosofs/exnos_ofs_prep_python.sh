#!/bin/bash
###############################################################################
#  exnos_ofs_prep_python.sh
#
#  Hybrid prep: Python (nos-utils) for met/param/tidal,
#               legacy shell for OBC/river.
#
#  Python handles: hotstart, GFS, HRRR, tidal (bctides.in), param.nml
#  Legacy handles: OBC (needs Fortran gen_3Dth_from_hycom), river (NWM)
#
#  Sources nos_ofs_launch.sh first to set up all env vars needed by
#  both Python and legacy paths (DBASE_*, time_hotstart, GRIDFILE, etc.)
#
#  Environment: Standard NCO variables (PDY, cyc, COMINgfs, FIXofs, etc.)
###############################################################################

set -x

echo "exnos_ofs_prep_python.sh started at $(date)"
echo "  OFS=${RUN}  PDY=${PDY}  cyc=${cyc}"
echo "  Mode: HYBRID (Python met/param/tidal + legacy OBC/river)"

# =========================================
#  STEP 0: Source nos_ofs_launch.sh
# =========================================
# This sets up ALL env vars needed by both Python and legacy paths:
#   DBASE_MET_NOW, DBASE_TS_NOW, time_hotstart, time_nowcastend,
#   time_forecastend, GRIDFILE, OCEAN_MODEL, FIXofs, EXECnos, etc.
# Without this, legacy OBC/river scripts will fail.

. ${USHnos}/nos_ofs_launch.sh ${OFS} prep
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: nos_ofs_launch.sh failed"
    err_chk
fi

echo "  time_hotstart=${time_hotstart}"
echo "  time_nowcastend=${time_nowcastend}"
echo "  time_forecastend=${time_forecastend}"

# =========================================
#  STEP 1: Python prep (met/param/tidal)
# =========================================

NOS_UTILS_DIR=${NOS_UTILS_DIR:-${USHnos}/python/nos-utils}
export PYTHONPATH="${NOS_UTILS_DIR}:${PYTHONPATH}"

# Save and unset LD_PRELOAD for Python (lesson #6)
_SAVED_LD_PRELOAD=${LD_PRELOAD}
unset LD_PRELOAD

# Verify nos-utils
python3 -c "from nos_utils.nco_bridge import run_prep; print('nos-utils OK')" || {
    echo "FATAL: nos-utils package not found at ${NOS_UTILS_DIR}"
    export err=99; err_chk
}

# FULL_PYTHON_PREP=YES: Python handles ALL steps (met, OBC, river, tidal, param)
# FULL_PYTHON_PREP=NO (default): Python handles met/param/tidal, legacy handles OBC/river
FULL_PYTHON_PREP=${FULL_PYTHON_PREP:-NO}

if [ "${FULL_PYTHON_PREP^^}" = "YES" ]; then
    SKIP_LEGACY="False"
    echo "  Mode: FULL PYTHON (all steps including OBC/river)"
else
    SKIP_LEGACY="True"
    echo "  Mode: HYBRID (Python met/param/tidal + legacy OBC/river)"
fi

echo ""
echo "========================================="
echo "  Nowcast Prep"
echo "========================================="

python3 << PYEOF
import sys, os, logging
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
from nos_utils.nco_bridge import run_prep
skip = ${SKIP_LEGACY}
success = run_prep(phase="nowcast", skip_legacy=skip)
sys.exit(0 if success else 1)
PYEOF
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: Python nowcast prep failed with exit code $err"
    err_chk
fi

echo ""
echo "========================================="
echo "  Forecast Prep"
echo "========================================="

python3 << PYEOF
import sys, os, logging
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
from nos_utils.nco_bridge import run_prep
skip = ${SKIP_LEGACY}
success = run_prep(phase="forecast", skip_legacy=skip)
sys.exit(0 if success else 1)
PYEOF
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: Python forecast prep failed with exit code $err"
    err_chk
fi

# =========================================
#  STEP 2: Legacy shell (OBC + river) — only when NOT in full Python mode
# =========================================
# When FULL_PYTHON_PREP=YES, run_prep already produced river/OBC/nudging
# via the Python orchestrator (NWMProcessor, RTOFSProcessor, NudgingProcessor —
# byte-identical to COMF v3.7 per SECOFS V18). Re-running the legacy
# Fortran here would overwrite those outputs.

if [ "${FULL_PYTHON_PREP^^}" = "YES" ]; then
    echo ""
    echo "========================================="
    echo "  Skipping legacy OBC/river (FULL_PYTHON_PREP=YES)"
    echo "  Python orchestrator already produced river + OBC + nudging."
    echo "========================================="
else
    # Restore LD_PRELOAD for Fortran executables (lesson #6)
    if [ -n "${_SAVED_LD_PRELOAD}" ]; then
        export LD_PRELOAD=${_SAVED_LD_PRELOAD}
    fi

    echo ""
    echo "========================================="
    echo "  OBC + River: Legacy shell + Fortran"
    echo "========================================="

    # River forcing
    echo "Running legacy river forcing..."
    ${USHnos}/nos_ofs_create_forcing_river.sh
    export err=$?; err_chk

    # OBC forcing (needs Fortran gen_3Dth_from_hycom for boundary interpolation)
    echo "Running legacy OBC forcing..."
    ${USHnos}/nos_ofs_create_forcing_obc.sh
    export err=$?; err_chk
fi

echo ""
echo "exnos_ofs_prep_python.sh completed at $(date)"
