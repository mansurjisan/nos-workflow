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
#   tools/hercules_2d_glo_stage_forcing.sh [--rm-raw] <PDY> <CYC>                 # --source ops (default): the ops rerun files above
#   tools/hercules_2d_glo_stage_forcing.sh --source gfs <PDY> <CYC>               # nos-workflow builds the forcing itself (below)
# Run it on a LOGIN node (compute nodes have no internet), in tmux: the download takes 45-90 min and
# resumes. A file whose size already matches the HEAD Content-Length is skipped; when the HEAD fails the
# file is fetched anyway (resumed with curl -C -). Re-running after an interrupt or a failed stage is safe.
# When the six rerun files already exist the forcing download and the staging are skipped (the record-count check and the reference
# files still run), so a re-run after --rm-raw does not fetch the 39 GB again; STAGE_FORCE=1 redoes both. MJ (10/13/26)
# The staging (about 8 min, under 1 GB memory, I/O bound, no internet) runs on the node you are on;
# STAGE_SRUN puts it on a compute node instead, e.g.
#   STAGE_SRUN="srun -A nos-surge -p hercules --qos=batch -N 1 -n 1 --mem=16G -t 2:00:00"
# The input check (--check, header reads only) always runs on this node.
# --rm-raw deletes the nine raw downloads (39 GB) after the record counts check out; the reference
# station files stay. Default: keep everything.
#
# --source gfs does not copy or build the rerun files. It downloads only the four needed messages of every public GFS flux file the
# prep job will read (PRES:surface, UGRD/VGRD:10 m above ground, ICEC:surface; byte ranges from the .idx, about 15 MB an hour of the
# 310 MB file, about 2-3 GB a cycle, about 150 files for ncst and fcst) from
#   https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.${PDY}/${CYC}/atmos/gfs.t${CYC}z.sfluxgrbfFFF.grib2
# into a GFS-like tree, ${COMROOT_STAGED:-${NOS_PTMP}/${LOGNAME}/comin_2dglo}/gfs/gfs.${PDY}/${CYC}/atmos (the tree the Slurm cards
# read as COMINgfs), then checks each file has four messages (wgrib2 -s). The file list is nos-utils' gfs_input_files(source=sflux), so
# it is exactly what the builder reads. A complete file is skipped; a failed file is retried 3 times; a transfer that stalls (under
# 10 kB/s for 60 s) is aborted. The reference station files are still downloaded. Then run
#   SUBMIT_GFS=1 COLD=0 slurm/stofs_2d_glo/launch_stofs_2d_glo.sh <PDY> <CYC>
# The result is not bitwise equal to the ops files (GRIB2 packing differs from the netCDF sfcf). MJ (10/14/26)
#
# Env (all optional): NOS_PTMP (default /work2/noaa/nos-surge/mjisan/nos-run/ptmp),
#   COMROOT_2DGLO (default ${NOS_PTMP}/${LOGNAME}/com, the default of the Slurm cards),
#   RERUN_DIR (output, default under COMROOT_2DGLO as above),
#   OPS_WORK (download area, default ${NOS_PTMP}/${LOGNAME}/ops_s3/${PDY}${CYC}; forcing/ and products/ below it),
#   NCST_RECORDS (default 7), DL_JOBS (parallel downloads, default 4), STAGE_SRUN (default none),
#   STAGE_FORCE=1 (download and rebuild even when the six outputs exist), NOS_VENV (default ${VENV_PATH:-$HOME/nos-venv}).
# Python comes from module nos_hercules.intel plus the venv, as in slurm/stofs_2d_glo/jnos_prep_00.sh.
# GFS source only: COMROOT_STAGED (see above), STAGE_NOS_UTILS (nos-utils checkout, default this repo's submodule). MJ (10/14/26)
# Exit 3: forcing staged, but a reference station file could not be downloaded. MJ (10/13/26)
# ======================================================================
set -euo pipefail

usage() { sed -n '3,/^# =====/{/^# =====/d;s/^# \{0,1\}//;p}' "$0"; }

RM_RAW=0; POS=(); SOURCE=ops
while [ "$#" -gt 0 ]; do
  a=$1; shift
  case "$a" in
    --rm-raw) RM_RAW=1 ;;
    --source) [ "$#" -gt 0 ] || { echo "--source needs ops or gfs" >&2; exit 2; }; SOURCE=$1; shift ;;
    --source=*) SOURCE=${a#--source=} ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown option: $a" >&2; usage >&2; exit 2 ;;
    *) POS+=("$a") ;;
  esac
done
case "${SOURCE}" in ops|gfs) ;; *) echo "FATAL: --source must be ops or gfs, got '${SOURCE}'" >&2; exit 2 ;; esac
[ "${#POS[@]}" -eq 2 ] || { usage >&2; exit 2; }
PDY=${POS[0]}; CYC=${POS[1]}
case "${PDY}" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;; *) echo "FATAL: PDY must be YYYYMMDD, got '${PDY}'" >&2; exit 2 ;; esac
case "${CYC}" in 00|06|12|18) ;; *) echo "FATAL: CYC must be 00, 06, 12 or 18, got '${CYC}'" >&2; exit 2 ;; esac

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
HELPER=${REPO_ROOT}/tools/stage_stofs_2d_glo_ops_forcing.py
NU=${STAGE_NOS_UTILS:-${REPO_ROOT}/ush/python/nos-utils}
[ -f "${NU}/nos_utils/forcing/adcirc_met.py" ] || { echo "FATAL: ${NU} is empty (git submodule update --init ush/python/nos-utils)" >&2; exit 1; }

# These defaults must stay equal to the ones in slurm/stofs_2d_glo/jnos_*_00.sh, or the cards will not find the forcing. MJ (10/13/26)
NOS_PTMP=${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}
U=${LOGNAME:-$(id -un)}
COMROOT_2DGLO=${COMROOT_2DGLO:-${NOS_PTMP}/${U}/com}
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
mkdir -p "${OPSP}"
[ "${SOURCE}" = gfs ] || mkdir -p "${RERUN_DIR}"

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

STAGE_SKIP=0
if [ "${SOURCE}" = ops ]; then
  # The helper writes each output through .partial, so a present file is a complete one. MJ (10/13/26)
  HAVE_ALL=1
  for seg in ncst fcst; do
    for n in 221 222 225; do [ -s "${RERUN_DIR}/stofs_2d_glo_${seg}.${n}.nc" ] || HAVE_ALL=0; done
  done
  if [ "${HAVE_ALL}" = 1 ] && [ "${STAGE_FORCE:-0}" != 1 ]; then STAGE_SKIP=1; fi

  if [ "${STAGE_SKIP}" = 1 ]; then
    echo "=== ${PDY}${CYC}: the six rerun files exist in ${RERUN_DIR}; skipping the forcing download and staging (STAGE_FORCE=1 to redo) ==="
  else
    mkdir -p "${OPSIN}"
    echo "=== ${PDY}${CYC}: downloading 9 forcing files to ${OPSIN} ($(date)) ==="
    printf '%s\0' "${forcing[@]}" | xargs -0 -n 2 -P "${DL_JOBS}" bash -c 'dl "$0" "$1"' \
      || { echo "FATAL: forcing download failed (see FAIL lines; re-run to resume)" >&2; exit 1; }
    du -sh "${OPSIN}"
  fi
fi

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

if [ "${SOURCE}" = gfs ]; then
  command -v wgrib2 >/dev/null || { echo "FATAL: wgrib2 not on PATH (module nos_hercules.intel)" >&2; exit 1; }
  COMIN=${COMROOT_STAGED:-${NOS_PTMP}/${U}/comin_2dglo}/gfs
  GFS_S3=https://noaa-gfs-bdp-pds.s3.amazonaws.com
  export HELPER NU COMIN GFS_S3
  # dlg <file under COMIN>: skip a file with four messages; else fetch the .idx and the four byte ranges, retry 3 times. MJ (10/14/26)
  dlg() {
    local f=$1 rel url t r n ranges
    [[ ${f} =~ (gfs\.[0-9]{8}/[0-9]{2}/atmos/[^/]+)$ ]] || { echo "FAIL ${f}: not a gfs.YYYYMMDD/HH/atmos/<file> path" >&2; return 1; }
    rel=${BASH_REMATCH[1]}; url=${GFS_S3}/${rel}; t=${f}.partial.$$   # unique: adjacent cycles share files. MJ (10/14/26)
    mkdir -p "$(dirname "${f}")"
    if [ -s "${f}" ] && [ -s "${f}.idx" ] && [ "$(gfs_count "${f}")" = 4 ]; then echo "SKIP ${rel}"; return 0; fi
    for n in 1 2 3; do
      rm -f "${t}" "${t}.idx"
      if curl -fsS --retry 3 --retry-delay 5 -o "${t}.idx" "${url}.idx" \
         && ranges=$(python3 "${HELPER}" --idx-ranges "${t}.idx" --nos-utils "${NU}") \
         && ( for r in ${ranges}; do
                curl -fsS --retry 3 --retry-delay 5 --speed-limit 10000 --speed-time 60 -r "${r}" "${url}" >> "${t}" || exit 1
              done ) \
         && [ -s "${t}" ] && [ "$(gfs_count "${t}")" = 4 ]; then
        # the .idx lands after the grib is complete: nos-utils reads it as the readiness marker. MJ (10/14/26)
        mv "${t}" "${f}"; mv "${t}.idx" "${f}.idx"; echo "OK   ${rel} ($(stat -c %s "${f}") bytes)"; return 0
      fi
      echo "RETRY ${rel} (attempt ${n})" >&2; sleep 5
    done
    rm -f "${t}" "${t}.idx"; echo "FAIL ${rel}" >&2; return 1
  }
  gfs_count() { wgrib2 "$1" -s 2>/dev/null | grep -cE ':(PRES:surface|UGRD:10 m above ground|VGRD:10 m above ground|ICEC:surface):' || true; }
  export -f gfs_count
  export -f dlg
  files=$(python3 "${HELPER}" --gfs-files "${COMIN}" --cycle "${PDY}${CYC}" --segments ncst,fcst --nos-utils "${NU}" \
          --ncst-records "${NCST_RECORDS}") || { echo "FATAL: cannot list the GFS sflux files (nos-utils too old for source=sflux?)" >&2; exit 1; }
  echo "=== ${PDY}${CYC}: $(echo "${files}" | wc -l) GFS sflux files (four messages each) to ${COMIN} ($(date)) ==="
  echo "${files}" | tr '\n' '\0' | xargs -0 -n 1 -P "${DL_JOBS}" bash -c 'dlg "$0"' \
    || { echo "FATAL: GFS download failed (see FAIL lines; re-run to resume)" >&2; exit 1; }
  du -sh "${COMIN}/gfs.${PDY}/${CYC}" 2>/dev/null || true
  echo "GFS forcing staged: ${COMIN}; next: SUBMIT_GFS=1 COLD=0 slurm/stofs_2d_glo/launch_stofs_2d_glo.sh ${PDY} ${CYC}"
  if [ "${NPROD_FAIL}" != 0 ]; then
    echo "WARNING: a reference station file in ${OPSP} could not be downloaded (see FAIL above); re-run to retry" >&2
    exit 3
  fi
  exit 0
fi

HARGS=(--ops-dir "${OPSIN}" --out "${RERUN_DIR}" --nos-utils "${NU}" --ncst-records "${NCST_RECORDS}")
if [ "${STAGE_FORCE:-0}" = 1 ]; then HARGS+=(--force); fi
if [ "${STAGE_SKIP}" != 1 ]; then
  echo "=== checking the ops inputs ==="
  python3 "${HELPER}" "${HARGS[@]}" --check
  echo "=== staging into ${RERUN_DIR} ($(date)) ==="
  # STAGE_SRUN is a command prefix, left unquoted to split. MJ (10/13/26)
  # shellcheck disable=SC2086
  time ${STAGE_SRUN} python3 "${HELPER}" "${HARGS[@]}"
fi

echo "=== record counts ==="
python3 - "${RERUN_DIR}" "${NCST_RECORDS}" <<'PY' || { echo "FATAL: record counts differ, the 180 h run needs ncst ${NCST_RECORDS} and fcst 181; raw downloads kept, STAGE_FORCE=1 rebuilds the outputs" >&2; exit 1; }
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
  [ ! -d "${OPSIN}" ] || rmdir --ignore-fail-on-non-empty "${OPSIN}"
  echo "raw forcing downloads deleted"
fi
ls -l "${RERUN_DIR}"
echo "forcing staged: ${RERUN_DIR}"
if [ "${NPROD_FAIL}" != 0 ]; then
  echo "WARNING: a reference station file in ${OPSP} could not be downloaded (see FAIL above); re-run to retry" >&2
  exit 3
fi
