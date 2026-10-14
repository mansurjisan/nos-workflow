#!/usr/bin/env bash
# Environment Check stage: module load, python imports, exe presence, wgrib2 -config. Fails fast, before any data staging or sbatch submit.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

setup_env
module list

echo "=== python imports ==="
command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 not on PATH"; exit 1; }
python3 -c 'import numpy, netCDF4, yaml, scipy, pandas, xarray' \
  || { echo "FATAL: python3 is missing one of numpy/netCDF4/yaml/scipy/pandas/xarray"; exit 1; }
echo "OK: numpy netCDF4 yaml scipy pandas xarray"

echo "=== executables ==="
EXEC_DIR="${HOMEnos}/exec"
if [ "${OFS}" = stofs_2d_glo ]; then
  # tide_fac and the ADCIRC build, the NCO tools of post_ncdiff/ncrcat, and the Slurm client the launcher needs. MJ (10/13/26)
  ADCIRC_DIR="${PACKAGEROOT}/adcirc_v56.1.0_exec"
  for exe in "${EXEC_DIR}/stofs_2d_glo_tide_fac" "${ADCIRC_DIR}/padcirc" "${ADCIRC_DIR}/adcprep"; do
    if [ ! -x "${exe}" ]; then
      echo "FATAL: ${exe} not found. Build it: ${HOMEnos}/tools/build_stofs_2d_glo_tide_fac_hercules.sh or build_stofs_2d_glo_adcirc_hercules.sh"
      exit 1
    fi
    echo "OK: ${exe}"
  done
  for tool in ncdiff ncrcat ncks sbatch sacct; do
    command -v "${tool}" >/dev/null 2>&1 || { echo "FATAL: ${tool} not on PATH"; exit 1; }
    echo "OK: ${tool}"
  done
  [ -f "${HOMEnos}/ush/python/nos-utils/nos_utils/forcing/adcirc_met.py" ] || { echo "FATAL: nos-utils is not deployed under ${HOMEnos}/ush/python/nos-utils (Deploy stage)"; exit 1; }
else
  for exe in fv3_coastalS.exe schism_combine_hotstart7.exe; do
    if [ ! -x "${EXEC_DIR}/${exe}" ]; then
      echo "FATAL: ${EXEC_DIR}/${exe} not found. Build it: ${HOMEnos}/sorc/build_hercules.sh"
      exit 1
    fi
    echo "OK: ${EXEC_DIR}/${exe}"
  done
fi

echo "=== wgrib2 -config ==="
command -v wgrib2 >/dev/null 2>&1 || { echo "FATAL: wgrib2 not on PATH"; exit 1; }
wgrib2 -config 2>&1 || true

echo "env_check PASS"
