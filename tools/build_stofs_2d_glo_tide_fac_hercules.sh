#!/usr/bin/env bash
# ======================================================================
# build_stofs_2d_glo_tide_fac_hercules.sh
#
# Build the ops stofs_2d_glo_tide_fac (Fortran nodal factors and equilibrium
# arguments for the ADCIRC fort.15 templates) on Hercules and install it into
# <repo>/exec, the EXECnos of the 2D-Global cards. The cards refuse to run without it: the runner has no
# Python fallback (a float32/float64 difference would freeze different FFT/FACET
# values into every segment for 365 days). MJ (10/13/26)
#
# Source: stofs_2d_glo_tide_fac.f from the public NCO mirror of stofs.v3.1.5
# (sorc/stofs_2d_glo/stofs_2d_glo_tide_fac.fd). The ops sorc makefile builds it
# with FFLAGS = -O2 -fp-model strict and no libraries; same source and flags here
# with ifort.
#
# Usage:
#   [SRC=<dir>] [TIDE_FAC_EXEC_DIR=<exec dir>] tools/build_stofs_2d_glo_tide_fac_hercules.sh [download|build|all]
#     download  fetch the source only; needs no compiler
#     build     compile, install and smoke-test from the source already in SRC; login or compute node
#     all       download, then build in the same run; the default
#   Compute nodes have no internet: download and all (with no source yet) need a login node.
#
# Env:
#   SRC                source dir, default <parent of the repo>/tide_fac_src
#   TIDE_FAC_EXEC_DIR  install dir, default <repo>/exec; an inherited EXECnos (another package's shell) is ignored, with a warning
#   BLD                scratch build dir (wiped on each build), default <parent of the repo>/tide_fac_build
# Build modes load the cards' module set (modulefiles/nos_hercules.intel with versions/run.hercules.ver)
# when `module` is available; otherwise load nos_hercules.intel first. MJ (10/13/26)
#
# The install is then smoke-tested from the install dir: ldd resolves, and a 365 day run for 2026-10-05 00z
# writes 16 lines (header with four integers, then K1 O1 P1 Q1 M2 S2 N2 K2 ...). MJ (10/13/26)
# ======================================================================
set -euo pipefail
HOMEWF=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

usage() { sed -n '/^# Usage:/,/^#$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

MODE=${1:-all}
case "${MODE}" in
  download|build|all) ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; echo "FATAL: unknown mode '${MODE}' (download, build or all)" >&2; exit 2 ;;
esac

PARENT=$(dirname "${HOMEWF}")  # the directory holding the nos-workflow clone. MJ (10/13/26)
SRC=${SRC:-${PARENT}/tide_fac_src}
BLD=${BLD:-${PARENT}/tide_fac_build}
# An inherited EXECnos (the ATL or SECOFS shell) would install into another package; only TIDE_FAC_EXEC_DIR overrides <repo>/exec. MJ (10/13/26)
TIDE_FAC_EXEC_DIR=${TIDE_FAC_EXEC_DIR:-${HOMEWF}/exec}
if [ -n "${EXECnos:-}" ] && [ "$(realpath -m "${EXECnos}")" != "$(realpath -m "${TIDE_FAC_EXEC_DIR}")" ]; then
  echo "WARNING: inherited EXECnos=${EXECnos} ignored; installing into ${TIDE_FAC_EXEC_DIR}" >&2
fi
EXECnos=${TIDE_FAC_EXEC_DIR}
URL=${URL:-https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/stofs.v3.1.6/sorc/stofs_2d_glo/stofs_2d_glo_tide_fac.fd}
F=stofs_2d_glo_tide_fac.f

if [ "${MODE}" != build ]; then
  if grep -q 'PROGRAM TIDE_FAC' "${SRC}/${F}" 2>/dev/null; then
    echo "source present: ${SRC}/${F} (remove it to fetch again)"
  else
    # A compute node would just hang or fail on the network; say so up front. MJ (10/13/26)
    [ -z "${SLURM_JOB_ID:-}" ] || { echo "FATAL: inside Slurm job ${SLURM_JOB_ID}: compute nodes have no internet; run '$0 download' on a login node, then 'build'" >&2; exit 1; }
    mkdir -p "${SRC}"
    curl -fsS --connect-timeout 30 --max-time 300 -o "${SRC}/${F}.partial" "${URL}/${F}" || { echo "FATAL: cannot fetch ${URL}/${F}" >&2; exit 1; }
    grep -q 'PROGRAM TIDE_FAC' "${SRC}/${F}.partial" || { echo "FATAL: ${SRC}/${F}.partial is not the tide_fac source" >&2; exit 1; }
    mv -f "${SRC}/${F}.partial" "${SRC}/${F}"
    echo "downloaded ${SRC}/${F}"
  fi
  [ "${MODE}" = all ] || exit 0
fi

grep -q 'PROGRAM TIDE_FAC' "${SRC}/${F}" 2>/dev/null || { echo "FATAL: ${SRC}/${F} missing (run '$0 download' on a login node first)" >&2; exit 1; }

# Same module set as the cards. MJ (10/13/26)
if type module >/dev/null 2>&1; then
  set +u
  module purge
  module use "${HOMEWF}/modulefiles"
  . "${HOMEWF}/versions/run.hercules.ver"
  module load nos_hercules.intel
  set -u
else
  echo "NOTE: 'module' not available; using the tools already on PATH (module load nos_hercules.intel first)" >&2
fi
command -v ifort >/dev/null 2>&1 || { echo "FATAL: ifort not on PATH (module load nos_hercules.intel)" >&2; exit 1; }

rm -rf "${BLD}"; mkdir -p "${BLD}"
cp "${SRC}/${F}" "${BLD}/"
cd "${BLD}"
ifort -O2 -fp-model strict -o stofs_2d_glo_tide_fac "${F}"
[ -x stofs_2d_glo_tide_fac ] || { echo "FATAL: build failed" >&2; exit 1; }

mkdir -p "${EXECnos}"
install -m 0755 stofs_2d_glo_tide_fac "${EXECnos}/stofs_2d_glo_tide_fac"
md5sum "${EXECnos}/stofs_2d_glo_tide_fac"
echo "installed ${EXECnos}/stofs_2d_glo_tide_fac"

# Verify the installed copy, not the build dir: the ifort runtime libraries must resolve and the output must be what the runner reads. MJ (10/13/26)
missing=$(ldd "${EXECnos}/stofs_2d_glo_tide_fac" 2>&1 | grep 'not found' || true)
[ -z "${missing}" ] || { echo "FATAL: unresolved libraries for ${EXECnos}/stofs_2d_glo_tide_fac:" >&2; echo "${missing}" >&2; exit 1; }
T=$(mktemp -d)
trap 'rm -rf "${T}"' EXIT
"${EXECnos}/stofs_2d_glo_tide_fac" --length 365 --year 2026 --month 10 --day 5 --hour 0 --outputformat simple \
  --outputdir "${T}" --outputname nod_equi_test >/dev/null || { echo "FATAL: tide_fac smoke run failed" >&2; exit 1; }
n=$(wc -l < "${T}/nod_equi_test")
[ "${n}" -eq 16 ] || { echo "FATAL: smoke output has ${n} lines, expected 16" >&2; exit 1; }
head -1 "${T}/nod_equi_test" | grep -Eq '^ *[0-9]+ +[0-9]+ +[0-9]+ +[0-9]+ *$' || { echo "FATAL: smoke output line 1 is not four integers: $(head -1 "${T}/nod_equi_test")" >&2; exit 1; }
order=$(sed -n 2,9p "${T}/nod_equi_test" | awk '{print $1}' | paste -sd' ')
[ "${order}" = "K1 O1 P1 Q1 M2 S2 N2 K2" ] || { echo "FATAL: constituent order '${order}', the runner needs K1 O1 P1 Q1 M2 S2 N2 K2" >&2; exit 1; }
echo "smoke test passed: 16 lines, header '$(head -1 "${T}/nod_equi_test")'"
