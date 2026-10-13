#!/bin/bash
# ======================================================================
# hercules_2d_glo_stage_forcing.sh
#
# Stage the STOFS-2D-Global ops-mode surface forcing of one cycle on Hercules from the public
# NCO rerun files (9 files, about 39 GB):
#   https://noaa-gestofs-pds.s3.amazonaws.com/stofs_2d_glo.${PDY}/${CYC}/rerun/stofs_2d_glo_{ncst,fcst1,fcst2}.{221,222,225}.nc
# and write the six files the nos-workflow ops mode reads (ncst 7 records, one hourly fcst of 181
# records; tools/stage_stofs_2d_glo_ops_forcing.py) to the cycle's rerun directory
#   ${COMROOT_2DGLO}/nos/stofs_2d_glo.${PDY}/${CYC}/rerun
# It also downloads the ops reference station files for the later comparison:
#   stofs_2d_glo.${PDY}/stofs_2d_glo.t${CYC}z.points.{htp,cwl.noanomaly,swl}.nc
#
# Usage:
#   tools/hercules_2d_glo_stage_forcing.sh [--rm-raw] <PDY> <CYC>
# Run it on a LOGIN node (compute nodes have no internet), in tmux: the download takes 45-90 min and
# resumes. A file whose size already matches the HEAD Content-Length is skipped; when the HEAD fails the
# file is fetched anyway (resumed with curl -C -). Re-running after an interrupt or a failed stage is safe.
# The staging (about 8 min, under 1 GB memory, I/O bound, no internet) runs on the node you are on;
# STAGE_SRUN puts it on a compute node instead, e.g.
#   STAGE_SRUN="srun -A nos-surge -p hercules --qos=batch -N 1 -n 1 --mem=16G -t 2:00:00"
# The input check (--check, header reads only) always runs on this node.
# --rm-raw deletes the nine raw downloads (39 GB) after the record counts check out; the reference
# station files stay. Default: keep everything.
#
# Env (all optional): NOS_PTMP (default /work2/noaa/nos-surge/mjisan/nos-run/ptmp),
#   COMROOT_2DGLO (default ${NOS_PTMP}/${LOGNAME}/com_2dglo, the default of the Slurm cards),
#   RERUN_DIR (output, default under COMROOT_2DGLO as above),
#   OPS_WORK (download area, default ${NOS_PTMP}/${LOGNAME}/ops_s3/${PDY}${CYC}; forcing/ and products/ below it),
#   NCST_RECORDS (default 7), DL_JOBS (parallel downloads, default 4), STAGE_SRUN (default none),
#   STAGE_FORCE=1 (rebuild outputs that exist), NOS_VENV (default ${VENV_PATH:-$HOME/nos-venv}).
# Python comes from module nos_hercules.intel plus the venv, as in slurm/stofs_2d_glo/jnos_prep_00.sh.
# Exit 3: forcing staged, but a reference station file could not be downloaded. MJ (10/13/26)
# ======================================================================
set -euo pipefail

usage() { sed -n '3,/^# =====/{/^# =====/d;s/^# \{0,1\}//;p}' "$0"; }

RM_RAW=0; POS=()
for a in "$@"; do
  case "$a" in
    --rm-raw) RM_RAW=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown option: $a" >&2; usage >&2; exit 2 ;;
    *) POS+=("$a") ;;
  esac
done
[ "${#POS[@]}" -eq 2 ] || { usage >&2; exit 2; }
PDY=${POS[0]}; CYC=${POS[1]}
case "${PDY}" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;; *) echo "FATAL: PDY must be YYYYMMDD, got '${PDY}'" >&2; exit 2 ;; esac
case "${CYC}" in 00|06|12|18) ;; *) echo "FATAL: CYC must be 00, 06, 12 or 18, got '${CYC}'" >&2; exit 2 ;; esac

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
HELPER=${REPO_ROOT}/tools/stage_stofs_2d_glo_ops_forcing.py
NU=${REPO_ROOT}/ush/python/nos-utils
[ -f "${NU}/nos_utils/forcing/adcirc_met.py" ] || { echo "FATAL: ${NU} is empty (git submodule update --init ush/python/nos-utils)" >&2; exit 1; }

# These defaults must stay equal to the ones in slurm/stofs_2d_glo/jnos_*_00.sh, or the cards will not find the forcing. MJ (10/13/26)
NOS_PTMP=${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}
U=${LOGNAME:-$(id -un)}
COMROOT_2DGLO=${COMROOT_2DGLO:-${NOS_PTMP}/${U}/com_2dglo}
RERUN_DIR=${RERUN_DIR:-${COMROOT_2DGLO}/nos/stofs_2d_glo.${PDY}/${CYC}/rerun}
OPS_WORK=${OPS_WORK:-${NOS_PTMP}/${U}/ops_s3/${PDY}${CYC}}
OPSIN=${OPS_WORK}/forcing
OPSP=${OPS_WORK}/products
NCST_RECORDS=${NCST_RECORDS:-7}
DL_JOBS=${DL_JOBS:-4}
STAGE_SRUN=${STAGE_SRUN:-}
# Lustre rejects HDF5 file locks on read. MJ (10/13/26)
export HDF5_USE_FILE_LOCKING=FALSE

S3=https://noaa-gestofs-pds.s3.amazonaws.com/stofs_2d_glo.${PDY}
mkdir -p "${OPSIN}" "${OPSP}" "${RERUN_DIR}"

# dl <url> <dest>: resumable; skipped only when the HEAD worked and the sizes already match. MJ (10/13/26)
dl() {
  local url=$1 dest=$2 name want have
  name=$(basename "${dest}")
  want=$(curl -fsSI --retry 3 "${url}" 2>/dev/null | tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}' || true)
  have=$(stat -c %s "${dest}" 2>/dev/null || echo 0)
  if [ -n "${want}" ] && [ "${have}" = "${want}" ]; then echo "SKIP ${name}"; return 0; fi
  echo "GET  ${name} (${want:-size unknown}, have ${have})"
  curl -fsS --retry 5 --retry-delay 10 -C - -o "${dest}" "${url}" || { echo "FAIL ${name}: curl failed" >&2; return 1; }
  if [ -n "${want}" ] && [ "$(stat -c %s "${dest}")" != "${want}" ]; then
    echo "FAIL ${name}: size $(stat -c %s "${dest}") != ${want} (delete the file and re-run)" >&2; return 1
  fi
  echo "OK   ${name}"
}
export -f dl

# the big fcst1 files first so the parallel slots stay busy. MJ (10/13/26)
forcing=(); products=()
for seg in fcst1 fcst2 ncst; do
  for n in 221 222 225; do
    f=stofs_2d_glo_${seg}.${n}.nc
    forcing+=("${S3}/${CYC}/rerun/${f}" "${OPSIN}/${f}")
  done
done
for p in htp cwl.noanomaly swl; do
  f=stofs_2d_glo.t${CYC}z.points.${p}.nc
  products+=("${S3}/${f}" "${OPSP}/${f}")
done

echo "=== ${PDY}${CYC}: downloading 9 forcing files to ${OPSIN} ($(date)) ==="
printf '%s\0' "${forcing[@]}" | xargs -0 -n 2 -P "${DL_JOBS}" bash -c 'dl "$0" "$1"' \
  || { echo "FATAL: forcing download failed (see FAIL lines; re-run to resume)" >&2; exit 1; }
du -sh "${OPSIN}"

NPROD_FAIL=0
echo "=== reference station files to ${OPSP} ==="
printf '%s\0' "${products[@]}" | xargs -0 -n 2 -P "${DL_JOBS}" bash -c 'dl "$0" "$1"' || NPROD_FAIL=1

# python env as the Slurm cards load it; without a module command the python3 on PATH is used. MJ (10/13/26)
set +u
if ! type module >/dev/null 2>&1; then
  for f in /etc/profile.d/modules.sh "${LMOD_PKG:-/nonexistent}/init/bash"; do
    if [ -r "${f}" ]; then . "${f}"; break; fi
  done
fi
if type module >/dev/null 2>&1; then
  module purge
  module use "${REPO_ROOT}/modulefiles"
  . "${REPO_ROOT}/versions/run.hercules.ver"
  module load nos_hercules.intel
else
  echo "WARNING: no module command; using python3 from PATH ($(command -v python3 || echo none))" >&2
fi
NOS_VENV=${NOS_VENV:-${VENV_PATH:-$HOME/nos-venv}}
if [ -f "${NOS_VENV}/bin/activate" ]; then . "${NOS_VENV}/bin/activate"; fi
set -u
python3 -c 'import numpy, netCDF4' 2>/dev/null || { echo "FATAL: python3 lacks numpy/netCDF4 (module nos_hercules.intel and ${NOS_VENV}); the downloads are kept, re-run to continue" >&2; exit 1; }

HARGS=(--ops-dir "${OPSIN}" --out "${RERUN_DIR}" --nos-utils "${NU}" --ncst-records "${NCST_RECORDS}")
if [ "${STAGE_FORCE:-0}" = 1 ]; then HARGS+=(--force); fi
echo "=== checking the ops inputs ==="
python3 "${HELPER}" "${HARGS[@]}" --check
echo "=== staging into ${RERUN_DIR} ($(date)) ==="
# STAGE_SRUN is a command prefix, left unquoted to split. MJ (10/13/26)
# shellcheck disable=SC2086
time ${STAGE_SRUN} python3 "${HELPER}" "${HARGS[@]}"

echo "=== record counts ==="
python3 - "${RERUN_DIR}" "${NCST_RECORDS}" <<'PY' || { echo "FATAL: record counts differ, the 180 h run needs ncst ${NCST_RECORDS} and fcst 181; raw downloads kept" >&2; exit 1; }
import sys
from netCDF4 import Dataset
out, want, bad = sys.argv[1], {"ncst": int(sys.argv[2]), "fcst": 181}, 0
for seg in ("ncst", "fcst"):
    for n in ("221", "222", "225"):
        f = "stofs_2d_glo_%s.%s.nc" % (seg, n)
        try:
            with Dataset(out + "/" + f) as d:
                got = len(d.dimensions["record"])
        except (OSError, RuntimeError, KeyError) as e:
            got = "unreadable (%s)" % e
        bad += got != want[seg]
        print("  %s record = %s%s" % (f, got, "" if got == want[seg] else "   EXPECTED %d" % want[seg]))
sys.exit(1 if bad else 0)
PY

if [ "${RM_RAW}" = 1 ]; then
  for ((i = 1; i < ${#forcing[@]}; i += 2)); do rm -f "${forcing[i]}"; done
  rmdir --ignore-fail-on-non-empty "${OPSIN}"
  echo "raw forcing downloads deleted"
fi
ls -l "${RERUN_DIR}"
echo "forcing staged: ${RERUN_DIR}"
if [ "${NPROD_FAIL}" != 0 ]; then
  echo "WARNING: a reference station file in ${OPSP} could not be downloaded (see FAIL above); re-run to retry" >&2
  exit 3
fi
