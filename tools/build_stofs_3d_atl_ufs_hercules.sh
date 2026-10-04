#!/usr/bin/env bash
# ======================================================================
# build_stofs_3d_atl_ufs_hercules.sh
#
# Build the STOFS-3D-ATL coupled executable (DATM + CMEPS + SCHISM with
# PREC_EVAP) on Hercules and install it as $EXECnos/fv3_stofs_3d_atl.exe.
# Recipe only: reads the user's ufs-weather-model clone, never edits or
# commits to it. SECOFS's fv3_coastalS.exe is not touched (own compile id).
#
# Usage:
#   UFS_COMMIT=<sha as on WCOSS2> EXECnos=<exec dir> tools/build_stofs_3d_atl_ufs_hercules.sh
#
# Env:
#   UFS_COMMIT   required; the clone's HEAD must start with it (take it from
#                the WCOSS2 provenance file). Check out + update submodules first:
#                  git -C $UFS_DIR checkout $UFS_COMMIT && git -C $UFS_DIR submodule update --init --recursive
#   UFS_DIR      required; use a SEPARATE clone for ATL (never the SECOFS clone). The script
#                never checks out or modifies a clone, it only refuses if HEAD != UFS_COMMIT.
#   EXECnos      required install dir
#   COMPILE_ID   default stofs_atl_pe
#   MAKE_OPT     default below; PREC_EVAP and NO_PARMETIS are verified in
#                CMakeCache.txt afterwards, the typed flags are not trusted.
# Run on a login node or inside an sbatch allocation; it takes a while. MJ (10/04/26)
# ======================================================================
set -euo pipefail
HOMEWF=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

: "${UFS_COMMIT:?set UFS_COMMIT to the ufs-weather-model commit used on WCOSS2}"
: "${EXECnos:?set EXECnos to the exec/ install destination}"
: "${UFS_DIR:?set UFS_DIR to a separate ufs-weather-model clone for ATL}"
COMPILE_ID=${COMPILE_ID:-stofs_atl_pe}
MAKE_OPT=${MAKE_OPT:-"-DAPP=CSTLS -DUSE_ATMOS=ON -DNO_PARMETIS=ON -DOLDIO=ON -DBUILD_TOOLS=ON -DPREC_EVAP=ON"}

[ -d "${UFS_DIR}/.git" ] || { echo "FATAL: ${UFS_DIR} is not a git clone" >&2; exit 1; }
cd "${UFS_DIR}"
HEAD_SHA=$(git rev-parse HEAD)
case "${HEAD_SHA}" in
  "${UFS_COMMIT}"*) ;;
  *) echo "FATAL: HEAD ${HEAD_SHA} != UFS_COMMIT ${UFS_COMMIT}; check it out first (see header)" >&2; exit 1 ;;
esac
echo "building ${HEAD_SHA} in ${UFS_DIR} (compile id ${COMPILE_ID})"
git status --short | head -5 | sed 's/^/  local change: /'

cd tests
./compile.sh hercules "${MAKE_OPT}" "${COMPILE_ID}" intel YES NO 2>&1 | tee "build_${COMPILE_ID}.log"

CACHE=$(find . -maxdepth 2 -name CMakeCache.txt -path "*${COMPILE_ID}*" | head -1)
[ -n "${CACHE}" ] || { echo "FATAL: no CMakeCache.txt for ${COMPILE_ID} under tests/" >&2; exit 1; }
for opt in PREC_EVAP NO_PARMETIS OLDIO; do
  grep -Eq "^${opt}:BOOL=ON" "${CACHE}" || { echo "FATAL: ${opt} is not ON in ${CACHE}" >&2; exit 1; }
done
grep -E "^(APP|PREC_EVAP|NO_PARMETIS|OLDIO|TVD_LIM|USE_ATMOS):" "${CACHE}" || true
grep -Eq "^TVD_LIM:[A-Z]+=VL" "${CACHE}" || echo "WARNING: TVD_LIM is not VL in ${CACHE} (ops runs TVD_VL)" >&2

EXE="fv3_${COMPILE_ID}.exe"
[ -x "${EXE}" ] || { echo "FATAL: tests/${EXE} not built" >&2; exit 1; }
mkdir -p "${EXECnos}"
install -m 0755 "${EXE}" "${EXECnos}/fv3_stofs_3d_atl.exe"
md5sum "${EXECnos}/fv3_stofs_3d_atl.exe"
echo "installed ${EXECnos}/fv3_stofs_3d_atl.exe (from tests/${EXE}; commit ${HEAD_SHA})"

BUILD_DIR=$(dirname "${CACHE}")
SEARCH=("${BUILD_DIR}")
[ -d ../build ] && SEARCH+=(../build)
found_utils=$(find "${SEARCH[@]}" -maxdepth 6 -type f -perm -111 \
  \( -name 'combine_hotstart7' -o -name 'combine_output11' -o -name 'combine_output11_MPI' \) \
  ! -name '*.o' 2>/dev/null | awk '{b=$0; sub(/.*\//, "", b); if (!seen[b]++) print}' || true)
for u in ${found_utils}; do
  b=$(basename "${u}")
  dest="${EXECnos}/${b}"
  [ "${b}" = "combine_hotstart7" ] && dest="${EXECnos}/schism_combine_hotstart7.exe"
  if [ -e "${dest}" ]; then echo "keeping existing ${dest}"; continue; fi
  install -m 0755 "${u}" "${dest}"
  echo "installed ${dest}"
done

# Runtime-stack check: the exe must resolve every library under the cards' module set. MJ (10/04/26)
if type module >/dev/null 2>&1; then
  missing=$( ( module purge; module use "${HOMEWF}/modulefiles"; module load nos_hercules.intel; ldd "${EXECnos}/fv3_stofs_3d_atl.exe" | grep 'not found' ) 2>/dev/null || true)
  [ -z "${missing}" ] || { echo "FATAL: unresolved libraries under nos_hercules.intel:" >&2; echo "${missing}" >&2; exit 1; }
  echo "ldd under nos_hercules.intel: all libraries resolved"
else
  echo "WARNING: 'module' not available in this shell; run ldd under nos_hercules.intel by hand" >&2
fi
lua_val() { grep -E "^[[:space:]]*$2[[:space:]]*=" "$1" 2>/dev/null | sed -E 's/.*or "([^"]*)".*/\1/' | head -1; }
for v in spack_stack_ver spack_stack_env stack_intel_ver stack_impi_ver; do
  a=$(lua_val "${UFS_DIR}/modulefiles/ufs_hercules.intel.lua" "$v"); b=$(lua_val "${HOMEWF}/modulefiles/nos_hercules.intel.lua" "$v")
  echo "stack ${v}: fork=${a:-?} nos_hercules.intel=${b:-?}"
  [ -z "${a}" ] || [ "${a}" = "${b}" ] || echo "WARNING: ${v} differs between the fork modulefile and nos_hercules.intel" >&2
done
