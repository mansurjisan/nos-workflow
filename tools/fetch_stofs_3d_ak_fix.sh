#!/bin/bash
# ======================================================================
# fetch_stofs_3d_ak_fix.sh
#
# Stage the STOFS-3D-AK static inputs into $FIXofs from the public NOAA
# hindcast archive, renamed to the <prefix>.<role> convention the runner
# resolves against.
#
# Source: the R09a member of
#   s3://noaa-gestofs-pds/_hindcast_archive/AK_Runs/R09a/
# (F. Cassalho). R09a is the wave-free run -- icou_elfe_wwm=0 -- so its
# inputs are the ones a DATM+SCHISM configuration can consume directly.
# The bucket is public; no credentials and no aws CLI are required.
#
# Usage:
#   ./tools/fetch_stofs_3d_ak_fix.sh [DEST]        # default: fix/stofs_3d_ak_ufs
#   ./tools/fetch_stofs_3d_ak_fix.sh --list        # print the manifest, fetch nothing
#   ./tools/fetch_stofs_3d_ak_fix.sh --reference   # also fetch validation references
#
# Downloads are resumable (curl -C -) and skipped when the local file
# already matches the remote size, so re-running is cheap.
#
# NOTE ON SIZE: the full set is ~2.6 GB, dominated by vgrid.in (1.0 GB,
# LSC2 over 1.34M nodes). Fetch on a login node with room in $FIXofs.
# ======================================================================
set -euo pipefail

BASE="https://noaa-gestofs-pds.s3.amazonaws.com/_hindcast_archive/AK_Runs/R09a"
PREFIX="stofs_3d_ak_ufs"

# remote-name  ->  local <prefix>.<role> name
# Held as a parallel-array manifest so it prints cleanly under --list.
REMOTE=(
  hgrid.gr3  hgrid.ll  vgrid.in  station.in
  albedo.gr3  diffmax.gr3  diffmin.gr3  rough.gr3
  watertype.gr3  windrot_geo2proj.gr3
  SAL_nudge.gr3  TEM_nudge.gr3
  partition.prop  tvd.prop
  bctides.in
)
LOCAL=(
  "${PREFIX}.hgrid.gr3"  "${PREFIX}.hgrid.ll"  "${PREFIX}.vgrid.in"  "${PREFIX}.station.in"
  "${PREFIX}.albedo.gr3"  "${PREFIX}.diffmax.gr3"  "${PREFIX}.diffmin.gr3"  "${PREFIX}.rough.gr3"
  "${PREFIX}.watertype.gr3"  "${PREFIX}.windrot_geo2proj.gr3"
  "${PREFIX}.SAL_nudge.gr3"  "${PREFIX}.TEM_nudge.gr3"
  "${PREFIX}.partition.prop"  "${PREFIX}.tvd.prop"
  # R09a's bctides.in carries the per-node harmonic amplitudes and phases for
  # both open-boundary segments (1613 + 219 nodes x 8 constituents), which are
  # date-independent, so it serves as the template. Staging it is NOT optional:
  # with no *bctides*template* in $FIXofs the tidal processor falls through to
  # its python-native mode, which writes a stub declaring ONE boundary with
  # ZERO nodes and "3 3 0 0" -- and still returns success (tidal.py:150-161),
  # so prep passes and the chained nowcast is released on a broken bctides.in.
  "${PREFIX}.bctides.in_template"
)

# Not staged as fix files -- these are the parity references the bring-up
# validates against (R09a's own tides, boundary forcing and namelist).
REF_REMOTE=(bctides.in param_noWWM.nml param.nml elev2D.th.nc uv3D.th.nc TEM_3D.th.nc SAL_3D.th.nc)

usage() { sed -n '2,26p' "$0"; exit 0; }

MODE=fetch
DEST=""
for arg in "$@"; do
  case "$arg" in
    --list)      MODE=list ;;
    --reference) MODE=reference ;;
    -h|--help)   usage ;;
    *)           DEST="$arg" ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${DEST:-${FIXofs:-${REPO_ROOT}/fix/${PREFIX}}}"

if [ "$MODE" = list ]; then
  printf '%-26s -> %s\n' "REMOTE (R09a)" "LOCAL (\$FIXofs)"
  for i in "${!REMOTE[@]}"; do
    printf '%-26s -> %s\n' "${REMOTE[$i]}" "${LOCAL[$i]}"
  done
  printf '\nreferences (--reference): %s\n' "${REF_REMOTE[*]}"
  printf 'destination would be    : %s\n' "$DEST"
  exit 0
fi

command -v curl >/dev/null || { echo "ERROR: curl not found" >&2; exit 1; }
mkdir -p "$DEST"
echo "Staging STOFS-3D-AK statics from R09a into: $DEST"
echo

remote_size() {
  curl -sIL "$1" | awk 'BEGIN{IGNORECASE=1} /^content-length:/{n=$2} END{gsub(/\r/,"",n); print n+0}'
}

fetch_one() {
  local url="$1" out="$2" want have
  want="$(remote_size "$url")"
  if [ "$want" -eq 0 ]; then
    echo "  MISSING on S3: $url" >&2
    return 1
  fi
  if [ -f "$out" ]; then
    have=$(stat -c%s "$out" 2>/dev/null || stat -f%z "$out")
    if [ "$have" -eq "$want" ]; then
      printf '  %-42s skip (complete, %s bytes)\n' "$(basename "$out")" "$want"
      return 0
    fi
  fi
  printf '  %-42s fetching %s bytes\n' "$(basename "$out")" "$want"
  curl -fL -C - --retry 3 --retry-delay 2 -o "$out" "$url"
  have=$(stat -c%s "$out" 2>/dev/null || stat -f%z "$out")
  [ "$have" -eq "$want" ] || { echo "  SIZE MISMATCH for $out ($have != $want)" >&2; return 1; }
}

failed=0
if [ "$MODE" = reference ]; then
  mkdir -p "$DEST/r09a_reference"
  for f in "${REF_REMOTE[@]}"; do
    fetch_one "$BASE/$f" "$DEST/r09a_reference/$f" || failed=$((failed+1))
  done
else
  for i in "${!REMOTE[@]}"; do
    fetch_one "$BASE/${REMOTE[$i]}" "$DEST/${LOCAL[$i]}" || failed=$((failed+1))
  done
fi

echo
if [ "$failed" -ne 0 ]; then
  echo "FAILED: $failed file(s) did not stage cleanly" >&2
  exit 1
fi
echo "OK: all files staged in $DEST"
cat <<'EOS'

Staged above and worth confirming:
  - <prefix>.bctides.in_template : R09a's bctides.in. NOT optional -- with no
    template in $FIXofs the tidal processor falls through to a stub declaring
    one boundary with zero nodes, and still reports success.
  - <prefix>.partition.prop : targets 2393 compute ranks, matching
    ufs_coastal.schism_tasks. Regenerate with tools/gen_stofs_partition_prop.sh
    if that count changes. Nothing checks it at staging time yet, so a missing
    or mis-sized file surfaces only when 2513 ranks abort at init -- verify it
    landed before submitting.

Still required and NOT in this archive:
  - <prefix>.param.nml : shipped in the repo at fix/stofs_3d_ak_ufs/
  - hotstart / restart : R09a's hotstart0.nc is 12 GB and is keyed to its own
    2019-07-01 12z start. The first cycle needs a restart seeded by hand --
    there is no cold-start path for a nowcast; stage_hotstart looks only for
    $COMOUT/<prefix>.t<cyc>z.<PDY>.init.nowcast.nc and raises without it.
EOS
