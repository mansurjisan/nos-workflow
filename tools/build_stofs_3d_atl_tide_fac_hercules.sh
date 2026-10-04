#!/usr/bin/env bash
# ======================================================================
# build_stofs_3d_atl_tide_fac_hercules.sh
#
# Build the ops stofs_3d_atl_tide_fac (Fortran nodal factors for bctides.in)
# on Hercules and install it into $EXECnos. nos-utils tidal.py uses the Fortran
# path only when stofs_3d_atl_tide_fac or nos_ofs_create_tide_fac_schism is in
# EXECnos; otherwise it silently falls back to Python nodal factors and bctides.in
# no longer matches ops. The ATL prep cards refuse to run without it.
#
# Ops builds it with the sorc makefile: ftn -o stofs_3d_atl_tide_fac
# stofs_3d_atl_tide_fac.f90 tf_selfe.f90 (no extra flags, build_codes.out). Same
# source list and flags here with ifort.
#
# Usage:
#   SRC=/path/to/stofs_3d_atl_tide_fac.fd EXECnos=<exec dir> tools/build_stofs_3d_atl_tide_fac_hercules.sh
# Run after `module load nos_hercules.intel`.
#
# Confirm at prep: the prep log shows "Running Fortran tide_fac: <EXECnos>/stofs_3d_atl_tide_fac"
# and "Created bctides.in using Fortran tide_fac"; the fallback warns "Fortran tide_fac not
# available". MJ (10/04/26)
# ======================================================================
set -euo pipefail

: "${SRC:?set SRC to the ops stofs_3d_atl_tide_fac.fd directory}"
: "${EXECnos:?set EXECnos to the exec/ install destination}"
for f in stofs_3d_atl_tide_fac.f90 tf_selfe.f90; do
  [ -s "${SRC}/${f}" ] || { echo "FATAL: ${SRC}/${f} missing" >&2; exit 1; }
done
command -v ifort >/dev/null 2>&1 || { echo "FATAL: ifort not on PATH (module load nos_hercules.intel)" >&2; exit 1; }

BUILD=${BUILD:-${PWD}/build_stofs_3d_atl_tide_fac}
rm -rf "${BUILD}"; mkdir -p "${BUILD}"
cp "${SRC}/stofs_3d_atl_tide_fac.f90" "${SRC}/tf_selfe.f90" "${BUILD}/"
cd "${BUILD}"
ifort -o stofs_3d_atl_tide_fac stofs_3d_atl_tide_fac.f90 tf_selfe.f90
[ -x stofs_3d_atl_tide_fac ] || { echo "FATAL: build failed" >&2; exit 1; }

mkdir -p "${EXECnos}"
install -m 0755 stofs_3d_atl_tide_fac "${EXECnos}/stofs_3d_atl_tide_fac"
md5sum "${EXECnos}/stofs_3d_atl_tide_fac"
echo "installed ${EXECnos}/stofs_3d_atl_tide_fac"
