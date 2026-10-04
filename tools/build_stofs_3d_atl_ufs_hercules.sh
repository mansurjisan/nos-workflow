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
#   UFS_DIR      default /work2/noaa/nos-surge/$USER/ufs-weather-model
#   EXECnos      required install dir
#   COMPILE_ID   default stofs_atl_pe
#   MAKE_OPT     default below; PREC_EVAP and NO_PARMETIS are verified in
#                CMakeCache.txt afterwards, the typed flags are not trusted.
# Run on a login node or inside an sbatch allocation; it takes a while. MJ (10/04/26)
# ======================================================================
set -euo pipefail

: "${UFS_COMMIT:?set UFS_COMMIT to the ufs-weather-model commit used on WCOSS2}"
: "${EXECnos:?set EXECnos to the exec/ install destination}"
UFS_DIR=${UFS_DIR:-/work2/noaa/nos-surge/${USER}/ufs-weather-model}
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
found_utils=$(find "${BUILD_DIR}" ../build -maxdepth 6 -type f -perm -111 \
  \( -name 'combine_hotstart7' -o -name 'combine_output11' -o -name 'combine_output11_MPI' \) \
  ! -name '*.o' 2>/dev/null | awk '{b=$0; sub(/.*\//, "", b); if (!seen[b]++) print}')
for u in ${found_utils}; do
  b=$(basename "${u}")
  dest="${EXECnos}/${b}"
  [ "${b}" = "combine_hotstart7" ] && dest="${EXECnos}/schism_combine_hotstart7.exe"
  if [ -e "${dest}" ]; then echo "keeping existing ${dest}"; continue; fi
  install -m 0755 "${u}" "${dest}"
  echo "installed ${dest}"
done
