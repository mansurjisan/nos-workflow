#!/usr/bin/env bash
# ======================================================================
# build_stofs_2d_glo_adcirc_hercules.sh
#
# Build the ops ADCIRC v56.1.0 (padcirc and adcprep) for STOFS-2D-Global on
# Hercules and install both into $ADCIRC_EXEC_DIR, the directory the Slurm cards
# (slurm/stofs_2d_glo) read. Hercules has no adcirc module.
#
# Source: the public NCO mirror of stofs.v3.1.5 (sorc/stofs_2d_glo/adcirc, version.F
# v56.1.0, hash 6e667fc9dcc759116f0620f4d9ac76cfd1361fbd). Ops' build-all has a missing
# backslash and never sets a build type, so the Release flags it lists were not applied;
# the mirror's own build/CMakeCache.txt shows RelWithDebInfo and flags.make shows the real
# flags (-O2 -g -132 -assume byterecl -mcmodel=medium). This script reproduces those, with
# -xCORE-AVX2 added in front for the AVX2 target ops intended, and checks the result
# against the mirror's flags.make.
#
# Usage:
#   [ADCIRC_EXEC_DIR=<dir>] [SRC=<dir>] [BLD=<dir>] tools/build_stofs_2d_glo_adcirc_hercules.sh [download|build|all]
#     download  fetch the source (and the ops flags.make) only; needs no compiler
#     build     configure, compile, install and verify from the source already in SRC; a compute
#               node (srun) keeps the compile off the login nodes
#     all       download, then build in the same run on the login node (make -j 4); the default
#   Compute nodes have no internet: download and all (with no source yet) need a login node. build and all need an
#   unlimited stack (ulimit -s); where the shell cannot raise it, run download here and build under srun. MJ (10/13/26)
#
# Env:
#   ADCIRC_EXEC_DIR  install dir, default <parent of the repo>/adcirc_v56.1.0_exec; export the same
#                    value before submitting the cards
#   SRC              source dir, default <parent of the repo>/adcirc_v56.1.0_src; it must NOT sit inside
#                    a git checkout, or scripts/adcirc_version.py stamps that checkout's hash into version.F
#   BLD              build dir (wiped on each build), default <parent of the repo>/adcirc_v56.1.0_build
#   OPS_FLAGS        where the mirror's padcirc flags.make is kept for the flags check, default
#                    <parent of the repo>/ops_padcirc_flags.make
#   MAKE_JOBS        default 4 on a login node, 8 inside a Slurm job
# Build modes load the cards' module set (modulefiles/nos_hercules.intel with versions/run.hercules.ver,
# plus cmake) when `module` is available; otherwise load nos_hercules.intel and cmake first.
#
# The install is verified, not assumed (the copy once did not run): both executables present and
# identical to the build, ldd without "not found" and with netcdf-fortran, netcdf-c, hdf5 and MPI
# resolved, padcirc -v prints v56.1.0 and padcirc --hash the ops hash. MJ (10/13/26)
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
ADCIRC_EXEC_DIR=$(realpath -m "${ADCIRC_EXEC_DIR:-${PARENT}/adcirc_v56.1.0_exec}")
SRC=$(realpath -m "${SRC:-${PARENT}/adcirc_v56.1.0_src}")
BLD=$(realpath -m "${BLD:-${PARENT}/adcirc_v56.1.0_build}")
OPS_FLAGS=${OPS_FLAGS:-${PARENT}/ops_padcirc_flags.make}
MAKE_JOBS=${MAKE_JOBS:-$([ -n "${SLURM_JOB_ID:-}" ] && echo 8 || echo 4)}
ADC_VERSION=v56.1.0
ADC_HASH=6e667fc9dcc759116f0620f4d9ac76cfd1361fbd
# --cut-dirs=7 strips pmb/codes/nwprod/stofs.v3.1.5/sorc/stofs_2d_glo/adcirc so the files land directly in SRC. MJ (10/13/26)
UP=/pmb/codes/nwprod/stofs.v3.1.5/sorc/stofs_2d_glo/adcirc
URL=https://www.nco.ncep.noaa.gov${UP}

src_missing() {
  local f
  for f in CMakeLists.txt version.F scripts/adcirc_version.py cmake/FindNetCDF.cmake src/adcirc.F prep/adcprep.F wind/vortex.F \
           thirdparty/KDTREE2/kdtree2.F thirdparty/metis/Lib/coarsen.c thirdparty/datetime_fortran/CMakeLists.txt; do
    [ -s "${SRC}/${f}" ] || echo "${f}"
  done
}

mkdir -p "${SRC}"
if git -C "${SRC}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "FATAL: ${SRC} is inside a git checkout; set SRC to a directory outside it" >&2; exit 1
fi

if [ "${MODE}" != build ]; then
  gap=$(src_missing)
  if [ -n "${gap}" ] || [ ! -s "${OPS_FLAGS}" ]; then
    # A compute node would just hang or fail on the network; say so up front. MJ (10/13/26)
    [ -z "${SLURM_JOB_ID:-}" ] || { echo "FATAL: inside Slurm job ${SLURM_JOB_ID}: compute nodes have no internet; run '$0 download' on a login node, then 'build'" >&2; exit 1; }
  fi
  if [ -n "${gap}" ]; then
    command -v wget >/dev/null 2>&1 || { echo "FATAL: wget not on PATH" >&2; exit 1; }
    # scripts/ is needed (version.cmake runs scripts/adcirc_version.py); build/, build.orig/ and the unused trees are skipped. MJ (10/13/26)
    wget -r -np -nH --cut-dirs=7 -l inf -e robots=off -nv -R "index.html*" -P "${SRC}" \
      -X "${UP}/build,${UP}/build.orig,${UP}/work,${UP}/docs,${UP}/containers,${UP}/thirdparty/wgrib2,${UP}/thirdparty/swan,${UP}/thirdparty/nuopc" \
      "${URL}/"
  else
    echo "source present: ${SRC} (remove it to fetch again)"
  fi
  if [ ! -s "${OPS_FLAGS}" ]; then
    curl -fsS --connect-timeout 30 --max-time 300 -o "${OPS_FLAGS}.partial" "${URL}/build/CMakeFiles/padcirc.dir/flags.make" \
      || { echo "FATAL: cannot fetch the ops flags.make from ${URL}" >&2; exit 1; }
    mv -f "${OPS_FLAGS}.partial" "${OPS_FLAGS}"
  fi
fi

gap=$(src_missing)
if [ -n "${gap}" ]; then
  echo "FATAL: ${SRC} is incomplete, missing:" >&2; echo "${gap}" | sed 's/^/  /' >&2
  [ "${MODE}" != build ] || echo "  run '$0 download' on a login node first" >&2
  exit 1
fi
grep -q "ADC_VERSION = \"${ADC_VERSION}\"" "${SRC}/version.F" || { echo "FATAL: ${SRC}/version.F is not ADCIRC ${ADC_VERSION}: $(grep ADC_VERSION "${SRC}/version.F" || true)" >&2; exit 1; }
grep -q "ADC_HASH = \"${ADC_HASH}\"" "${SRC}/version.F" || { echo "FATAL: ${SRC}/version.F hash is not ${ADC_HASH}" >&2; exit 1; }
# wget does not keep the execute bit and cmake runs scripts/adcirc_version.py directly. MJ (10/13/26)
chmod +x "${SRC}"/scripts/*.py
echo "source ok: ${SRC} (ADCIRC ${ADC_VERSION})"
[ "${MODE}" != download ] || exit 0

# As ops: with an unlimited stack cmake adds no -heap-arrays, so refuse a stack that cannot be raised before any module or cmake step. MJ (10/13/26)
ulimit -s unlimited 2>/dev/null || true
[ "$(ulimit -s)" = unlimited ] || { echo "FATAL: stack $(ulimit -s): cmake would add -heap-arrays; run 'build' under srun" >&2; exit 1; }

# Same module set as the cards, plus cmake at the version run.hercules.ver pins. MJ (10/13/26)
if type module >/dev/null 2>&1; then
  set +u
  module purge
  module use "${HOMEWF}/modulefiles"
  . "${HOMEWF}/versions/run.hercules.ver"
  module load nos_hercules.intel
  command -v cmake >/dev/null 2>&1 || module load "cmake/${cmake_ver}"
  set -u
else
  echo "NOTE: 'module' not available; using the tools already on PATH (module load nos_hercules.intel and cmake first)" >&2
fi
for tool in cmake make ifort mpiifort mpiicc mpiicpc nc-config nf-config ldd; do
  command -v "${tool}" >/dev/null 2>&1 || { echo "FATAL: ${tool} not on PATH (module load nos_hercules.intel, cmake)" >&2; exit 1; }
done
cmake --version | sed -n 1p

# mpiicc/mpiicpc map to icx/icpx on oneAPI 2024 (there is no icc/icpc); prove the three wrappers compile, else fall back to icx/icpx. MJ (10/13/26)
export FC=mpiifort CC=mpiicc CXX=mpiicpc
CHK=$(mktemp -d)
trap 'rm -rf "${CHK}"' EXIT
printf 'int main(void){return 0;}\n' > "${CHK}/t.c"
printf 'int main(){return 0;}\n' > "${CHK}/t.cpp"
printf 'program t\nend program t\n' > "${CHK}/t.f90"
wrappers_ok() { (cd "${CHK}" && mpiicc t.c -o tc && mpiicpc t.cpp -o tcpp && mpiifort t.f90 -o tf) >/dev/null 2>&1; }
if ! wrappers_ok; then
  export I_MPI_CC=icx I_MPI_CXX=icpx
  wrappers_ok || { echo "FATAL: mpiicc, mpiicpc and mpiifort do not compile, even with I_MPI_CC=icx I_MPI_CXX=icpx" >&2; exit 1; }
  echo "NOTE: mpiicc/mpiicpc failed as is; using I_MPI_CC=icx I_MPI_CXX=icpx"
fi

# spack-stack splits netcdf-c and netcdf-fortran into two prefixes, and the mirror's cmake/FindNetCDF.cmake searches
# no default paths, so the four cache variables below are set directly. MJ (10/13/26)
NCI=$(nc-config --includedir); NCL=$(nc-config --libdir); NFP=$(nf-config --prefix)
NFL=
for d in "${NFP}/lib" "${NFP}/lib64"; do
  if [ -e "${d}/libnetcdff.so" ]; then NFL=${d}; break; fi
done
[ -n "${NFL}" ] || { echo "FATAL: libnetcdff.so not under ${NFP}/lib or lib64" >&2; exit 1; }
for f in "${NCI}/netcdf.h" "${NCL}/libnetcdf.so" "${NFP}/include/netcdf.mod" "${NFL}/libnetcdff.so"; do
  [ -e "${f}" ] || { echo "FATAL: ${f} missing" >&2; exit 1; }
done

rm -rf "${BLD}"; mkdir -p "${BLD}"; cd "${BLD}"
cmake "${SRC}" -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DBUILD_PADCIRC=ON -DBUILD_ADCPREP=ON -DENABLE_DATETIME=ON -DENABLE_OUTPUT_NETCDF=ON \
  -DNETCDFHOME="$(nc-config --prefix)" \
  -DNETCDF_INCLUDE_DIR:PATH="${NCI}" -DNETCDF_LIBRARY:FILEPATH="${NCL}/libnetcdf.so" \
  -DNETCDF_F90_INCLUDE_DIR:PATH="${NFP}/include" -DNETCDF_F90_LIBRARY:FILEPATH="${NFL}/libnetcdff.so" \
  -DCMAKE_Fortran_FLAGS="-xCORE-AVX2" 2>&1 | tee cmake.log
grep -E "Unlimited stack|Found NetCDF|Found MPI_Fortran|Build files have been written" cmake.log || true
grep -q "Build files have been written" cmake.log || { echo "FATAL: cmake did not finish (see ${BLD}/cmake.log)" >&2; exit 1; }

# Compile flags must be the ops ones with -xCORE-AVX2 in front. MJ (10/13/26)
norm() { echo "$*" | tr -s ' ' | sed 's/^ //; s/ $//'; }
FL=${BLD}/CMakeFiles/padcirc.dir/flags.make
if [ -s "${OPS_FLAGS}" ]; then
  want_def=$(sed -n 's/^Fortran_DEFINES = //p' "${OPS_FLAGS}")
  want_flags="-xCORE-AVX2 $(sed -n 's/^Fortran_FLAGS = //p' "${OPS_FLAGS}")"
else
  echo "NOTE: ${OPS_FLAGS} missing (run download on a login node); comparing with the flags recorded from the mirror" >&2
  want_def="-DADCNETCDF -DCMPI -DCSCA -DDATETIME -DHAVE_NETCDF4 -DLINUX -DNETCDF_CAN_DEFLATE"
  want_flags="-xCORE-AVX2 -O2 -g -module CMakeFiles/mod/padcirc -132 -assume byterecl -mcmodel=medium"
fi
have_def=$(sed -n 's/^Fortran_DEFINES = //p' "${FL}"); have_flags=$(sed -n 's/^Fortran_FLAGS = //p' "${FL}")
[ "$(norm "${have_def}")" = "$(norm "${want_def}")" ] || { echo "FATAL: Fortran_DEFINES differ from ops: '${have_def}' != '${want_def}'" >&2; exit 1; }
[ "$(norm "${have_flags}")" = "$(norm "${want_flags}")" ] || { echo "FATAL: Fortran_FLAGS differ from ops (plus -xCORE-AVX2): '${have_flags}' != '${want_flags}'" >&2; exit 1; }
echo "flags verified: ${have_flags}"

# make -j can stop on a module-ordering error; a second pass finds the modules, then a serial pass. MJ (10/13/26)
run_make() { make -j "$1" 2>&1 | tee -a make.log; }
run_make "${MAKE_JOBS}" || { echo "make -j ${MAKE_JOBS} failed, running it once more"; run_make "${MAKE_JOBS}"; } || { echo "make failed again, running serially"; run_make 1; } \
  || { echo "FATAL: make failed (see ${BLD}/make.log)" >&2; exit 1; }
for x in padcirc adcprep; do
  [ -x "${BLD}/${x}" ] || { echo "FATAL: ${BLD}/${x} not built" >&2; exit 1; }
done
ls -l "${BLD}/padcirc" "${BLD}/adcprep"

mkdir -p "${ADCIRC_EXEC_DIR}"
cp -p "${BLD}/padcirc" "${BLD}/adcprep" "${ADCIRC_EXEC_DIR}/"

# Verify what the cards will run, in ADCIRC_EXEC_DIR. MJ (10/13/26)
for x in padcirc adcprep; do
  [ -x "${ADCIRC_EXEC_DIR}/${x}" ] || { echo "FATAL: ${ADCIRC_EXEC_DIR}/${x} missing or not executable after the copy" >&2; exit 1; }
  cmp -s "${BLD}/${x}" "${ADCIRC_EXEC_DIR}/${x}" || { echo "FATAL: ${ADCIRC_EXEC_DIR}/${x} differs from the build" >&2; exit 1; }
  missing=$(ldd "${ADCIRC_EXEC_DIR}/${x}" 2>&1 | grep 'not found' || true)
  [ -z "${missing}" ] || { echo "FATAL: unresolved libraries for ${ADCIRC_EXEC_DIR}/${x}:" >&2; echo "${missing}" >&2; exit 1; }
done
ls -l "${ADCIRC_EXEC_DIR}/padcirc" "${ADCIRC_EXEC_DIR}/adcprep"
LDD=$(ldd "${ADCIRC_EXEC_DIR}/padcirc" 2>&1 || true)
grep -E "netcdf|hdf5|libmpi" <<< "${LDD}" || true
for lib in 'libnetcdff\.so' 'libnetcdf\.so' libhdf5 libmpi; do
  grep -Eq "${lib}" <<< "${LDD}" || { echo "FATAL: padcirc is not linked against ${lib}" >&2; exit 1; }
done

# -v and --hash exit before the solver starts; if the login/compute shell cannot start MPI binaries, go through srun. MJ (10/13/26)
adc_query() {
  local out
  out=$("${ADCIRC_EXEC_DIR}/padcirc" "$1" 2>&1 || true)
  if ! grep -qx "$2" <<< "${out}" && [ -n "${SLURM_JOB_ID:-}" ] && command -v srun >/dev/null 2>&1; then
    out=$(srun --overlap -n 1 "${ADCIRC_EXEC_DIR}/padcirc" "$1" 2>&1 || true)
  fi
  grep -qx "$2" <<< "${out}" || { echo "FATAL: padcirc $1 did not print $2; got: $(echo "${out}" | head -3)" >&2; exit 1; }
  echo "padcirc $1: $2"
}
adc_query -v "${ADC_VERSION}"
adc_query --hash "${ADC_HASH}"
echo "installed padcirc and adcprep (ADCIRC ${ADC_VERSION}) in ${ADCIRC_EXEC_DIR}"
echo "cards: export ADCIRC_EXEC_DIR=${ADCIRC_EXEC_DIR}"
