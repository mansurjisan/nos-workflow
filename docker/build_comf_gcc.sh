#!/bin/bash
# ============================================================================
# build_comf_gcc.sh - Build COMF Fortran executables with GCC/GFortran
#
# Adapts the Intel-based makefiles (ush/python/sorc/*.fd/) for GCC compilation.
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

export COMP_F=gfortran
export COMP_CC=gcc
export LIBnos EXECnos NETCDF

mkdir -p "${LIBnos}" "${EXECnos}"

# ---- Patch all makefiles: Intel flags -> GCC flags ----
echo "=== Patching makefiles for GCC compilation ==="
for mkfile in "${SORC_DIR}"/*/makefile; do
    [ -f "$mkfile" ] || continue
    # -extend-source -> -ffixed-line-length-none -ffree-line-length-none
    sed -i 's/-extend-source/-ffixed-line-length-none -ffree-line-length-none/g' "$mkfile"
    # -traceback -> -fbacktrace
    sed -i 's/-traceback/-fbacktrace/g' "$mkfile"
    # -check all -> -fcheck=all
    sed -i 's/-check all/-fcheck=all/g' "$mkfile"
    # -qnosave -> -fno-automatic
    sed -i 's/-qnosave/-fno-automatic/g' "$mkfile"
    # Add GCC legacy Fortran compatibility flags (rank mismatch, implicit types)
    # These are needed because Intel Fortran accepts scalar-to-array argument passing
    sed -i 's/FFLAGS\s*=\s*-O/FFLAGS = -fallow-argument-mismatch -fallow-invalid-boz -O/g' "$mkfile"
done

# ---- Step 1: Build utility library (dependency for all executables) ----
echo ""
echo "=== Building nos_ofs_utility library ==="
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
    echo "=== Building ${name} ==="
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

# ---- Summary ----
echo ""
echo "=============================================="
echo " COMF Fortran Build Summary (GCC)"
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
