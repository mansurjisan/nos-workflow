#!/bin/bash
# status_stofs_2d_glo.sh
#
# Slurm state, elapsed time and the log's STAGE_SUMMARY status/runtime of each job that launch_stofs_2d_glo.sh queued.
#
# Usage:    ./status_stofs_2d_glo.sh <jobs file>  |  <PDY:YYYYMMDD> <CYC:HH>
# Example:  ./status_stofs_2d_glo.sh 20261012 06
#
# PDY CYC resolve the launcher's job list $NOS_PTMP/$LOGNAME/slurm_2dglo/jobs_<PDY><CYC>.txt; the logs are read from the
# cards' rpt dir $NOS_PTMP/$LOGNAME/rpt/stofs_2d_glo. A job without a log has not started. MJ (10/13/26)
set -u
LOGNAME="${LOGNAME:-$(id -un)}"
# Same default as the cards, the launcher and tools/hercules_2d_glo_stage_forcing.sh (a test compares them). MJ (10/13/26)
NOS_PTMP="${NOS_PTMP:-/work2/noaa/nos-surge/mjisan/nos-run/ptmp}"
case "$#" in
  1) JOBS="$1" ;;
  2) JOBS="${NOS_PTMP}/${LOGNAME}/slurm_2dglo/jobs_$1$2.txt" ;;
  *) echo "Usage: $0 <jobs file> | <PDY:YYYYMMDD> <CYC:HH>" >&2; exit 2 ;;
esac
# An empty or missing list is an error, not an empty table (a forgotten argument must not pass silently). MJ (10/13/26)
[ -s "${JOBS}" ] || { echo "ERROR: no job list at ${JOBS} (usage: $0 <jobs file> | <PDY> <CYC>)" >&2; exit 1; }
RPT="${NOS_PTMP}/${LOGNAME}/rpt/stofs_2d_glo"

printf '%-13s %-9s %-16s %-9s %s\n' job id state elapsed stage
while read -r label id; do
  [ -n "${id}" ] || continue
  st=""; el=""
  IFS='|' read -r st el < <(sacct -j "${id}" -X -n -P -o State,Elapsed 2>/dev/null | head -1) || true
  s=""
  for L in "${RPT}"/*."${id}".out; do
    [ ! -f "${L}" ] || s=$(grep -o 'STAGE_SUMMARY.*' "${L}" | grep -o 'status=[A-Za-z]* runtime_s=[0-9.]*' | tail -1)
    break
  done
  printf '%-13s %-9s %-16s %-9s %s\n' "${label}" "${id}" "${st:--}" "${el:--}" "${s}"
done < "${JOBS}"
