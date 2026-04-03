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

echo ""
echo "========================================="
echo "  Nowcast: Python (met + param + tidal)"
echo "========================================="

python3 << 'PYEOF'
import sys, logging
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
from nos_utils.nco_bridge import run_prep
success = run_prep(phase="nowcast", skip_legacy=True)
sys.exit(0 if success else 1)
PYEOF
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: Python nowcast prep failed with exit code $err"
    err_chk
fi

echo ""
echo "========================================="
echo "  Forecast: Python (met + param + tidal)"
echo "========================================="

python3 << 'PYEOF'
import sys, logging
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
from nos_utils.nco_bridge import run_prep
success = run_prep(phase="forecast", skip_legacy=True)
sys.exit(0 if success else 1)
PYEOF
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: Python forecast prep failed with exit code $err"
    err_chk
fi

# =========================================
#  STEP 2: Legacy shell (OBC + river)
# =========================================
# Restore LD_PRELOAD for Fortran executables

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

echo ""
echo "exnos_ofs_prep_python.sh completed at $(date)"
