#!/bin/bash
# ======================================================================
# fetch_stofs_2d_glo_fix.sh
#
# Stage the STOFS-2D-Global (ADCIRC) static inputs the nos-workflow
# runner reads into $FIXofs (default fix/stofs_2d_glo). Names are kept as
# shipped by ops: the runner links stofs_2d_glo_grid as fort.14 and
# stofs_2d_glo_attr as fort.13 itself (the only names adcprep accepts), and
# parm/systems/stofs_2d_glo.yaml points grid.files at the ops names.
#
# Source: the operational package stofs.v3.1.5, copied from
#   /lfs/h1/ops/prod/packages/stofs.v3.1.5/fix/stofs_2d_glo   (WCOSS2)
# or, off WCOSS2, downloaded from the public NCO mirror of the same tree.
#
# Usage:
#   ./tools/fetch_stofs_2d_glo_fix.sh [DEST]   # default: fix/stofs_2d_glo
#
# Staged (bytes, v3.1.5 listing), about 3.3 GB. The runner itself reads only the first two:
#   stofs_2d_glo_grid       1,726,781,115   fort.14 mesh (12.8 M nodes)
#   stofs_2d_glo_attr       1,531,075,596   fort.13 nodal attributes
#   stofs_2d_glo_elev_stat        104,953   elevation station list
#   stofs_2d_glo_station.ctl       99,157   1687 post-processing stations
#   stofs_2d_glo_msl2mllw          18,711   datum offsets
#   stofs_2d_glo_surf.15            5,291   fort.15 template (surge)
#   stofs_2d_glo_tide.15            4,720   fort.15 template (tide only)
#   stofs_2d_glo_met                   78   fort.22 OWI-NetCDF descriptor
#   stofs_2d_glo_rotm                  68   fort.rotm
# Optional, WITH_BODY=1 (about 7.2 GB total): stofs_2d_glo_body 3,900,032,696 (fort.24
# self-attraction/loading, used by the ops scripts and linked into the adcprep set when present,
# but not by Zach's runner).
# Left out (post-processing only, not read by the runner): the *.mask files
# (alaska 41 MB, conus.east/west 266 MB each, northpacific 142 MB, guam,
# hawaii, puertori), cron.bnt, ft03.dta, ft07.dta, cloned_stations.csv,
# extracted_stations.txt.
#
# Re-running is cheap: a file whose size already matches the source is
# skipped, and every copy lands under a .partial name first; an interrupted
# curl resumes from its .partial. MJ (10/05/26)
# ======================================================================
set -euo pipefail

DEST="${1:-fix/stofs_2d_glo}"
OPS_DIR="${OPS_DIR:-/lfs/h1/ops/prod/packages/stofs.v3.1.5/fix/stofs_2d_glo}"
OPS_URL="${OPS_URL:-https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/stofs.v3.1.5/fix/stofs_2d_glo}"

# "ops name  staged name"; identical, so a rename never hides a missing file. MJ (10/05/26)
FILES="
stofs_2d_glo_grid       stofs_2d_glo_grid
stofs_2d_glo_attr       stofs_2d_glo_attr
stofs_2d_glo_rotm       stofs_2d_glo_rotm
stofs_2d_glo_elev_stat  stofs_2d_glo_elev_stat
stofs_2d_glo_met        stofs_2d_glo_met
stofs_2d_glo_station.ctl stofs_2d_glo_station.ctl
stofs_2d_glo_msl2mllw   stofs_2d_glo_msl2mllw
stofs_2d_glo_surf.15    stofs_2d_glo_surf.15
stofs_2d_glo_tide.15    stofs_2d_glo_tide.15
"
# fort.24 is 3.9 GB and the runner does not need it; opt in explicitly. MJ (10/05/26)
if [ "${WITH_BODY:-0}" = 1 ]; then
    FILES="$FILES
stofs_2d_glo_body       stofs_2d_glo_body
"
fi

src_size() {
    if [ -f "$OPS_DIR/$1" ]; then
        stat -c '%s' "$OPS_DIR/$1"
    else
        curl -sfI "$OPS_URL/$1" | tr -d '\r' |
            awk 'tolower($1)=="content-length:"{print $2; exit}'
    fi
}

fetch_one() {
    local src="$1" dst="$DEST/$2" want have
    want="$(src_size "$src" || true)"
    if [ -z "$want" ]; then
        echo "FAIL  $src: not found in $OPS_DIR or $OPS_URL"
        return 1
    fi
    have="$(stat -c '%s' "$dst" 2>/dev/null || true)"
    if [ "$have" = "$want" ]; then
        echo "SKIP  $2"
        return 0
    fi
    if [ -f "$OPS_DIR/$src" ]; then
        echo "COPY  $2"
        cp -f "$OPS_DIR/$src" "$dst.partial" || return 1
    else
        echo "CURL  $2"
        curl -sf -C - -o "$dst.partial" "$OPS_URL/$src" || return 1
    fi
    have="$(stat -c '%s' "$dst.partial")"
    if [ "$have" != "$want" ]; then
        echo "FAIL  $2: $have bytes, expected $want (kept as $2.partial)"
        return 1
    fi
    mv -f "$dst.partial" "$dst"
}

mkdir -p "$DEST"
echo "source: $([ -d "$OPS_DIR" ] && echo "$OPS_DIR" || echo "$OPS_URL")"
echo "dest:   $DEST"

failed=0
while read -r src dst; do
    [ -n "$src" ] || continue
    fetch_one "$src" "$dst" || failed=$((failed + 1))
done <<< "$FILES"

if [ "$failed" -gt 0 ]; then
    echo "$failed file(s) failed; re-run to resume."
    exit 1
fi

# The mesh must be the 12.8 M node global grid; a truncated or wrong file fails the GWCE solve
# much later. Line 2 of fort.14 is "NE NP". MJ (10/05/26)
read -r ne np_ < <(sed -n 2p "$DEST/stofs_2d_glo_grid")
echo "grid:  $np_ nodes, $ne elements"
if [ "$np_" -lt 12700000 ] || [ "$np_" -gt 12900000 ]; then
    echo "WARNING: node count $np_ is not the expected ~12.8 M"
    exit 2
fi
echo "OK"
