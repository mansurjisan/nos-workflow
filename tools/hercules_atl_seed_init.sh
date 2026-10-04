#!/bin/bash
# ======================================================================
# hercules_atl_seed_init.sh
#
# Seed the STOFS-3D-ATL nowcast initial state from the public ops restart:
#   s3://noaa-nos-stofs3d-pds/STOFS-3D-Atl/stofs_3d_atl.${PDY}/rerun/stofs_3d_atl.t12z.restart.nc
# (26 GB; the exact state ops starts cycle PDY from) and write it as
#   ${COMOUT}/stofs_3d_atl_ufs.t12z.${PDY}.init.nowcast.nc   (NETCDF4_CLASSIC)
#
# Usage:
#   tools/hercules_atl_seed_init.sh <PDY> <COMOUT> [LINK_COMOUT ...]
# COMOUT is the full cycle directory, e.g. $COMROOT_SA/nos/stofs_3d_atl_ufs.20261001.
# Each LINK_COMOUT (e.g. the coupled COMROOT's cycle dir) gets a symlink to the file.
#
# Env: CYC (default 12), RUN (default stofs_3d_atl_ufs), WORKDIR (download dir,
# default COMOUT/.seed), KEEP_RAW=1 keeps the raw restart.
# The download resumes (curl -C -); re-running after the convert is a no-op.
# Do not validate with make_cold_start_hotstart.py --verify: it false-flags the
# 0-D time variable of ops restarts. MJ (10/04/26)
# ======================================================================
set -euo pipefail

[ "$#" -ge 2 ] || { echo "Usage: $0 <PDY> <COMOUT> [LINK_COMOUT ...]" >&2; exit 2; }
PDY=$1; COMOUT=$2; shift 2
CYC=${CYC:-12}
RUN=${RUN:-stofs_3d_atl_ufs}
WORKDIR=${WORKDIR:-${COMOUT}/.seed}
URL="https://noaa-nos-stofs3d-pds.s3.amazonaws.com/STOFS-3D-Atl/stofs_3d_atl.${PDY}/rerun/stofs_3d_atl.t${CYC}z.restart.nc"
OUT="${COMOUT}/${RUN}.t${CYC}z.${PDY}.init.nowcast.nc"
EXPECT="node=3052121 elem=5872610 side=8924888 nVert=49 ntracers=2"

mkdir -p "${COMOUT}" "${WORKDIR}"
RAW="${WORKDIR}/stofs_3d_atl.t${CYC}z.restart.${PDY}.nc"

check_dims() {
  local f=$1 got
  if command -v ncdump >/dev/null 2>&1; then
    got=$(ncdump -h "$f" | awk '/^\t[A-Za-z_]+ = [0-9]+ ;/{gsub(";","");d[$1]=$3} END{printf "node=%s elem=%s side=%s nVert=%s ntracers=%s", d["node"],d["elem"],d["side"],d["nVert"],d["ntracers"]}')
  else
    got=$(python3 - "$f" <<'PY'
import sys
from netCDF4 import Dataset
d = Dataset(sys.argv[1]).dimensions
print("node=%d elem=%d side=%d nVert=%d ntracers=%d" % tuple(len(d[k]) for k in ("node","elem","side","nVert","ntracers")))
PY
)
  fi
  echo "dims: ${got}"
  [ "${got}" = "${EXPECT}" ] || { echo "FATAL: dims differ from expected (${EXPECT})" >&2; return 1; }
}

if [ -s "${OUT}" ] && check_dims "${OUT}"; then
  echo "init already present and valid: ${OUT}"
else
  rm -f "${OUT}.partial"
  want=$(curl -sI "${URL}" | awk 'tolower($1)=="content-length:"{gsub("\r","");print $2}')
  [ -n "${want}" ] || { echo "FATAL: cannot HEAD ${URL}" >&2; exit 1; }
  have=$(stat -c %s "${RAW}" 2>/dev/null || echo 0)
  if [ "${have}" != "${want}" ]; then
    echo "downloading ${URL} (${want} bytes, have ${have})"
    curl -fL --retry 5 --retry-delay 10 -C - -o "${RAW}" "${URL}"
  fi
  [ "$(stat -c %s "${RAW}")" = "${want}" ] || { echo "FATAL: size mismatch after download" >&2; exit 1; }

  if command -v nccopy >/dev/null 2>&1; then
    nccopy -k 'netCDF-4 classic model' "${RAW}" "${OUT}.partial"
  elif command -v ncks >/dev/null 2>&1; then
    echo "nccopy not found, using ncks -7 (netCDF4 classic)"
    ncks -O -7 "${RAW}" "${OUT}.partial"
  else
    echo "FATAL: neither nccopy nor ncks on PATH (module load nos_hercules.intel first)" >&2
    exit 1
  fi
  check_dims "${OUT}.partial"
  mv "${OUT}.partial" "${OUT}"
  [ "${KEEP_RAW:-0}" = 1 ] || rm -f "${RAW}"
fi

if command -v ncdump >/dev/null 2>&1; then
  ncdump -k "${OUT}" | grep -q "classic" || echo "WARNING: ${OUT} kind is $(ncdump -k "${OUT}"), expected netCDF-4 classic" >&2
fi

for link in "$@"; do
  mkdir -p "${link}"
  ln -sfn "${OUT}" "${link}/$(basename "${OUT}")"
  echo "linked ${link}/$(basename "${OUT}")"
done
echo "init seed ready: ${OUT}"
