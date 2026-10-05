#!/usr/bin/env bash
# ======================================================================
# build_stofs_3d_atl_pschism_hercules.sh
#
# Build the ops-equivalent standalone pschism for STOFS-3D-ATL v3.1.5 on
# Hercules and install it as $EXECnos/stofs_3d_atl_pschism_v3.1.5.
#
# Ops builds sorc/stofs_3d_atl/stofs_3d_atl_pschism.fd/src with the legacy
# Makefile (not cmake): mk/include_modules sets NO_PARMETIS=yes,
# USE_PREC_EVAP=yes, TVD_LIM=VL, mk/Make.defs.local sets ENV=WCOSS2 with ftn
# and the WCOSS2 netcdf, no extra optimisation flags (build_codes.out:
# -DMPIVERSION=2 -DSCHISM -DNO_PARMETIS -DPREC_EVAP -DTVD_VL, exe pschism_WCOSS2_VL).
# This script builds a COPY of that tree with the same Makefile and flags and
# only Make.defs.local replaced by a Hercules one (mpiifort/ifort + spack
# netcdf via nf-config). The source tree is not modified.
#
# Usage:
#   SRC=/path/to/stofs_3d_atl_pschism.fd EXECnos=<exec dir> tools/build_stofs_3d_atl_pschism_hercules.sh
# Run after `module load nos_hercules.intel` (the cards' module set).
#
# A Hercules build is the same source and flags but a different compiler,
# MPI and netcdf from ops' module binary, so results agree to round-off only;
# do not expect a byte-identical executable. MJ (10/04/26)
# ======================================================================
set -euo pipefail

: "${SRC:?set SRC to the ops stofs_3d_atl_pschism.fd directory}"
: "${EXECnos:?set EXECnos to the exec/ install destination}"
BUILD=${BUILD:-${PWD}/build_stofs_3d_atl_pschism}
NAME=${NAME:-stofs_3d_atl_pschism_v3.1.5}

[ -f "${SRC}/src/Makefile" ] && [ -f "${SRC}/mk/include_modules" ] || { echo "FATAL: ${SRC} is not a legacy-Makefile pschism tree (src/Makefile, mk/include_modules)" >&2; exit 1; }
for tool in mpiifort ifort nf-config nc-config; do
  command -v "${tool}" >/dev/null 2>&1 || { echo "FATAL: ${tool} not on PATH (module load nos_hercules.intel)" >&2; exit 1; }
done

rm -rf "${BUILD}"
mkdir -p "${BUILD}"
cp -a "${SRC}/." "${BUILD}/"
rm -rf "${BUILD}/src/o" "${BUILD}/src/build" "${BUILD}"/src/*.a "${BUILD}"/src/pschism_*

# The three ops flags must be on in the copied include_modules, not just assumed. MJ (10/04/26)
grep -Eq '^[[:space:]]*NO_PARMETIS[[:space:]]*=[[:space:]]*yes' "${BUILD}/mk/include_modules" || { echo "FATAL: NO_PARMETIS is not enabled in mk/include_modules" >&2; exit 1; }
grep -Eq '^[[:space:]]*USE_PREC_EVAP[[:space:]]*=[[:space:]]*yes' "${BUILD}/mk/include_modules" || { echo "FATAL: USE_PREC_EVAP is not enabled in mk/include_modules" >&2; exit 1; }
grep -Eq '^[[:space:]]*TVD_LIM[[:space:]]*=[[:space:]]*VL' "${BUILD}/mk/include_modules" || { echo "FATAL: TVD_LIM is not VL in mk/include_modules" >&2; exit 1; }

cat > "${BUILD}/mk/Make.defs.local" <<MK
ENV = HERCULES
EXEC   := pschism_\$(ENV)
FCP = mpiifort
FCS = ifort
FLD = \$(FCP)
PPFLAGS := \$(PPFLAGS) -DMPIVERSION=2
FCPFLAGS = \$(PPFLAGS)
FLDFLAGS =
CDFLIBS = -Wl,-rpath,$(nc-config --libdir) -Wl,-rpath,$(nf-config --prefix)/lib -L$(nc-config --libdir) -L$(nf-config --prefix)/lib -lnetcdff -lnetcdf
CDFMOD = $(nf-config --fflags) -I$(nc-config --includedir)
include ../mk/include_modules
GTMMOD =
GTMLIBS =
MK

# src/Makefile runs `python Core/gen_version.py`; give it a python if only python3 exists. MJ (10/04/26)
if ! command -v python >/dev/null 2>&1; then
  mkdir -p "${BUILD}/.bin"
  ln -sf "$(command -v python3)" "${BUILD}/.bin/python"
  export PATH="${BUILD}/.bin:${PATH}"
fi

cd "${BUILD}/src"
make clean >/dev/null 2>&1 || true
make pschism 2>&1 | tee "${BUILD}/build.log"

# Verify from the actual compile lines, not the config. MJ (10/04/26)
awk '/-DNO_PARMETIS/ && /-DPREC_EVAP/ && /-DTVD_VL/ {n++} END {exit n ? 0 : 1}' "${BUILD}/build.log" || { echo "FATAL: compile lines lack -DNO_PARMETIS -DPREC_EVAP -DTVD_VL" >&2; exit 1; }
if grep -Eq -- '-lparmetis|-lmetis' "${BUILD}/build.log"; then echo "FATAL: link line has parmetis" >&2; exit 1; fi
EXE=$(ls pschism_HERCULES_VL 2>/dev/null || true)
[ -x "${EXE}" ] || { echo "FATAL: pschism_HERCULES_VL not built" >&2; exit 1; }
echo "flags verified: -DNO_PARMETIS -DPREC_EVAP -DTVD_VL, no parmetis"

mkdir -p "${EXECnos}"
install -m 0755 "${EXE}" "${EXECnos}/${NAME}"
md5sum "${EXECnos}/${NAME}"
echo "installed ${EXECnos}/${NAME}"
