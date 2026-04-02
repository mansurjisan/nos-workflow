#!/bin/bash
###############################################################################
#  exnos_ofs_prep_python.sh
#
#  Python-based prep using nos-utils package.
#  Replaces shell-based exnos_ofs_prep.sh when USE_PYTHON_PREP=YES.
#
#  Requires:
#    - nos-utils package at ${USHnos}/python/nos-utils (or PYTHONPATH)
#    - Python 3.9+ with numpy, netCDF4
#    - wgrib2 in PATH (for GRIB2 extraction)
#
#  Environment: Standard NCO variables (PDY, cyc, COMINgfs, FIXofs, etc.)
###############################################################################

set -x

echo "exnos_ofs_prep_python.sh started at $(date)"
echo "  OFS=${RUN}  PDY=${PDY}  cyc=${cyc}"

# --- Setup Python environment ---

# nos-utils package location
NOS_UTILS_DIR=${NOS_UTILS_DIR:-${USHnos}/python/nos-utils}
export PYTHONPATH="${NOS_UTILS_DIR}:${PYTHONPATH}"

# Unset LD_PRELOAD to avoid Fortran lib conflicts with Python/numpy
# (lesson #6: LD_PRELOAD must be isolated to Fortran execution)
_SAVED_LD_PRELOAD=${LD_PRELOAD}
unset LD_PRELOAD

# Verify nos-utils is importable
python3 -c "from nos_utils.nco_bridge import run_prep; print('nos-utils OK')" || {
    echo "FATAL: nos-utils package not found at ${NOS_UTILS_DIR}"
    echo "Set NOS_UTILS_DIR or install nos-utils in PYTHONPATH"
    export err=99; err_chk
}

# --- Run Nowcast Prep ---
echo ""
echo "========================================="
echo "  Nowcast Prep (Python orchestrator)"
echo "========================================="

python3 -c "
import sys, logging
logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
from nos_utils.nco_bridge import run_prep
success = run_prep(phase='nowcast')
sys.exit(0 if success else 1)
"
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: Python nowcast prep failed with exit code $err"
    err_chk
fi

# --- Run Forecast Prep ---
echo ""
echo "========================================="
echo "  Forecast Prep (Python orchestrator)"
echo "========================================="

python3 -c "
import sys, logging
logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
from nos_utils.nco_bridge import run_prep
success = run_prep(phase='forecast')
sys.exit(0 if success else 1)
"
export err=$?
if [ $err -ne 0 ]; then
    echo "FATAL: Python forecast prep failed with exit code $err"
    err_chk
fi

# --- Restore LD_PRELOAD for downstream Fortran execution ---
if [ -n "${_SAVED_LD_PRELOAD}" ]; then
    export LD_PRELOAD=${_SAVED_LD_PRELOAD}
fi

echo ""
echo "exnos_ofs_prep_python.sh completed at $(date)"
