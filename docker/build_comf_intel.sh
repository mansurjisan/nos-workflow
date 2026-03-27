#!/bin/bash
# ============================================================================
# build_comf_intel.sh - Build COMF Fortran executables with Intel ifort/icc
#
# The COMF makefiles are Intel-native (using -extend-source, -traceback, etc.)
# so NO flag patching is needed — unlike the GCC build which must translate
# every Intel flag to its GCC equivalent.
#
# Builds the NOS utility library first, then all 22 executables.
#
# Required environment variables:
#   SORC_DIR    - Path to sorc/ directory (default: /opt/nosofs/sorc)
#   LIBnos      - Path for compiled libraries (default: /opt/nosofs/lib)
#   EXECnos     - Path for compiled executables (default: /opt/nosofs/exec)
#   NETCDF      - NetCDF installation prefix (default: /usr)
#   G2_INC4     - GRIB2 include path
#   G2_LIB4     - GRIB2 library path
#   W3NCO_LIB4  - W3NCO library path
#   W3EMC_LIB4  - W3EMC library path
#   BACIO_LIB4  - BACIO library path
#   BUFR_LIB4   - BUFR library path (optional)
#   JASPER_LIB  - Jasper library path
#   PNG_LIB     - PNG library path
#   Z_LIB       - Zlib library path
#   Z_LIB4      - Zlib library path (alias)
# ============================================================================
set -eu

SORC_DIR=${SORC_DIR:-/opt/nosofs/sorc}
LIBnos=${LIBnos:-/opt/nosofs/lib}
EXECnos=${EXECnos:-/opt/nosofs/exec}
NETCDF=${NETCDF:-/usr}

# Source Intel oneAPI environment if not already active
if ! command -v ifort &>/dev/null; then
    echo "=== Sourcing Intel oneAPI compiler environment ==="
    source /opt/intel/oneapi/compiler/2023.2.1/env/vars.sh
fi

echo "Using Intel Fortran: $(which ifort) — $(ifort --version 2>&1 | head -1)"
echo "Using Intel C:       $(which icc) — $(icc --version 2>&1 | head -1)"

# Set compilers — these are read by COMF makefiles via ${COMP_F} and ${COMP_CC}
export COMP_F=ifort
export COMP_CC=icc
export LIBnos EXECnos NETCDF

mkdir -p "${LIBnos}" "${EXECnos}"

# NOTE: No makefile patching needed.
# The COMF makefiles are Intel-native and use flags like:
#   -extend-source  (ifort: allow 132+ column fixed-form)
#   -traceback      (ifort: runtime backtrace on crash)
#   -check all      (ifort: array bounds, pointer, format checks)
# These are the correct flags for ifort — no translation required.

# ---- Step 1: Build utility library (dependency for all executables) ----
echo ""
echo "=== Building nos_ofs_utility library (Intel) ==="
cd "${SORC_DIR}/nos_ofs_utility.fd"
make clean 2>/dev/null || true
make
make install
echo "  -> libnosutil.a installed to ${LIBnos}"

# ---- Step 2: Build all executables ----
FAILED=()
SUCCEEDED=()

for dir in "${SORC_DIR}"/*.fd; do
    name=$(basename "$dir")
    # Skip utility library (already built) and any non-directory
    [ "$name" = "nos_ofs_utility.fd" ] && continue
    [ ! -d "$dir" ] && continue
    [ ! -f "$dir/makefile" ] && continue

    echo ""
    echo "=== Building ${name} (Intel) ==="
    cd "$dir"

    if make clean 2>/dev/null && make 2>&1; then
        make install 2>/dev/null || cp -p "$(echo "$name" | sed 's/\.fd$//')" "${EXECnos}/" 2>/dev/null || true
        SUCCEEDED+=("$name")
        echo "  -> OK"
    else
        FAILED+=("$name")
        echo "  -> FAILED (non-fatal, continuing)"
    fi
done

# ---- Create aliases for executables with alternate names ----
# SCHISM/FVCOM use nos_ofs_create_forcing_met_fvcom (same binary as nos_ofs_create_forcing_met)
[ -f "${EXECnos}/nos_ofs_create_forcing_met" ] && \
    ln -sf nos_ofs_create_forcing_met "${EXECnos}/nos_ofs_create_forcing_met_fvcom"
# combine_hotstart has alternate names on WCOSS2
[ -f "${EXECnos}/nos_ofs_combine_hotstart_schism" ] && \
    ln -sf nos_ofs_combine_hotstart_schism "${EXECnos}/schism_combine_hotstart7.exe"

# ---- Summary ----
echo ""
echo "=============================================="
echo " COMF Fortran Build Summary (Intel ifort/icc)"
echo "=============================================="
echo " Succeeded: ${#SUCCEEDED[@]}"
for s in "${SUCCEEDED[@]}"; do echo "   OK: $s"; done

if [ ${#FAILED[@]} -gt 0 ]; then
    echo ""
    echo " Failed: ${#FAILED[@]}"
    for f in "${FAILED[@]}"; do echo "   FAIL: $f"; done
    echo ""
    echo " Note: Some executables may not be needed for SECOFS."
    echo " Critical for SECOFS prep: nos_ofs_create_forcing_met,"
    echo "   nos_ofs_create_forcing_obc_schism, nos_ofs_create_forcing_river,"
    echo "   nos_ofs_create_tide_fac_schism, nos_ofs_met_file_search,"
    echo "   nos_ofs_read_restart, nos_ofs_combine_hotstart_schism"
fi

echo ""
echo "Executables in ${EXECnos}:"
ls -la "${EXECnos}/"
