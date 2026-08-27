#!/usr/bin/env bash
# Build fv3_coastalS.exe (DATM+SCHISM) on Hercules and install it to EXECnos.
# Mirrors the user's proven invocation (2026-08-26) from their working clone.
set -euo pipefail

# The fork lives IN the ufs-weather-model repo, not a separate "ufs-coastal"
# repo -- oceanmodeling/ufs-coastal-app is an unrelated, much smaller docs repo.
UFS_COASTAL_REPO=${UFS_COASTAL_REPO:-https://github.com/oceanmodeling/ufs-weather-model.git}
# feature/coastal_app tip observed 2026-08-26; used only for a FRESH clone.
UFS_COASTAL_REF=${UFS_COASTAL_REF:-d84244a30194e8a3ec181a65f91782aebbb9c0aa}
# Default: the user's existing working clone. An existing clone is built AS-IS
# (no fetch/checkout -- never disturb a tree the user works in); its HEAD is
# recorded below for reproducibility.
UFS_COASTAL_DIR=${UFS_COASTAL_DIR:-/work2/noaa/nos-surge/${USER}/ufs-weather-model}

# Proven flag set. NO_PARMETIS=ON: ParMETIS deadlocks SCHISM partitioning on
# Hercules at 2794 ranks (2026-08-26 secofs run0; same pathology crashes
# WCOSS2 at 2914 -- nos-workflow #98). The guard needs a matching
# partition.prop staged in the run dir. Small-rank runs (<~1000) may set
# NO_PARMETIS=OFF via env to partition at runtime instead.
# OLDIO=ON: exe expects nscribes=0 and a post-run combine step -- the runtime
# yaml must match. BUILD_UTILS=ON provides the schism combine executables.
MAKE_OPT=${MAKE_OPT:-"-DAPP=CSTLS -DUSE_ATMOS=ON -DNO_PARMETIS=ON -DOLDIO=ON -DBUILD_UTILS=ON"}
COMPILE_ID=${COMPILE_ID:-coastalS_V3}

: "${EXECnos:?set EXECnos to the exec/ install destination (e.g. \$HOMEnos/exec)}"

if [ ! -d "${UFS_COASTAL_DIR}/.git" ]; then
  git clone --recursive "${UFS_COASTAL_REPO}" "${UFS_COASTAL_DIR}"
  cd "${UFS_COASTAL_DIR}"
  git fetch origin "${UFS_COASTAL_REF}"
  git checkout "${UFS_COASTAL_REF}"
  git submodule update --init --recursive
else
  cd "${UFS_COASTAL_DIR}"
fi
echo "building from $(git rev-parse HEAD) in ${UFS_COASTAL_DIR}"

cd tests
./compile.sh hercules "${MAKE_OPT}" "${COMPILE_ID}" intel YES NO 2>&1 | tee build.log

mkdir -p "${EXECnos}"
install -m 0755 "fv3_${COMPILE_ID}.exe" "${EXECnos}/fv3_coastalS.exe"
echo "installed ${EXECnos}/fv3_coastalS.exe (from fv3_${COMPILE_ID}.exe)"

# BUILD_UTILS=ON drops the SCHISM utility binaries in the build tree; install
# the combine tools the workflow invokes at runtime, if present. compile.sh
# (at the pinned SHA) sets BUILD_DIR=$(pwd)/build_fv3_${COMPILE_ID}, i.e.
# tests/build_fv3_coastalS_V3 -- not build_${COMPILE_ID} -- and is invoked
# above with clean_after=NO precisely so that directory survives for this
# search. The -name group is parenthesized so -perm/-type apply to every
# alternative, not just the first; names are matched exactly (not a '*'
# prefix) and ! -name '*.o' + -perm -111 keep object/module build
# byproducts out of the harvest. No head cap -- de-dup by basename instead,
# so a duplicate hit under both search roots still installs once.
found_utils=$(find "build_fv3_${COMPILE_ID}" ../build -maxdepth 6 -type f -perm -111 \
  \( -name 'combine_hotstart7' -o -name 'combine_output11' -o -name 'combine_output11_MPI' \) \
  ! -name '*.o' 2>/dev/null | awk '{b=$0; sub(/.*\//, "", b); if (!seen[b]++) print}')
if [ -n "${found_utils}" ]; then
  echo "${found_utils}" | while read -r u; do
    b="$(basename "${u}")"
    # ush/nos_run.sh's OLDIO combine search looks for schism_combine_
    # hotstart7.exe, not the build's own combine_hotstart7 basename --
    # rename on install so the nowcast->forecast handoff finds it.
    # combine_output11(_MPI) already match what nos_run.sh looks for, so
    # those install under their own basename.
    if [ "${b}" = "combine_hotstart7" ]; then
      dest="${EXECnos}/schism_combine_hotstart7.exe"
    else
      dest="${EXECnos}/${b}"
    fi
    install -m 0755 "${u}" "${dest}"
    echo "installed ${dest} (from ${u})"
  done
else
  echo "note: no combine utilities found under the build tree; locate them manually if the run needs schism_combine_hotstart7.exe"
fi
