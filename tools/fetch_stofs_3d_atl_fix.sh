#!/bin/bash
# ======================================================================
# fetch_stofs_3d_atl_fix.sh
#
# Stage the STOFS-3D-ATL v3.1 static inputs that stofs_3d_atl_ufs reads
# into $FIXofs, renamed to the <prefix>.<role> convention the runner
# resolves against.
#
# Source: the operational package stofs.v3.1.5, copied from
#   /lfs/h1/ops/prod/packages/stofs.v3.1.5/fix/stofs_3d_atl   (WCOSS2)
# or, off WCOSS2, downloaded from the public NCO mirror of the same tree.
#
# Usage:
#   ./tools/fetch_stofs_3d_atl_fix.sh [DEST]   # default: fix/stofs_3d_atl_ufs
#
# Re-running is cheap: a file whose size already matches the source is
# skipped, and every copy lands under a .partial name first. The set is
# ~5.5 GB (hgrid/vgrid/tvd.prop dominate). Ops ships 55 files; the 27
# below are the ones this port reads. graphinfo.txt (1.3 GB) is left out
# because the NO_PARMETIS build reads partition.prop instead. MJ (09/28/26)
# ======================================================================
set -euo pipefail

DEST="${1:-fix/stofs_3d_atl_ufs}"
OPS_DIR="/lfs/h1/ops/prod/packages/stofs.v3.1.5/fix/stofs_3d_atl"
OPS_URL="https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/stofs.v3.1.5/fix/stofs_3d_atl"
SCHISM_TASKS=4912

# "ops name  staged name". Grid/property files need the exact prefixed
# name (stage_files.py has no fallback); the SAL/TEM nudge renames are
# case-sensitive, and a lowercase miss makes SCHISM run without nudging
# and without an error. The bare-named entries are resolved by fix_file(),
# which tries the bare name first. MJ (09/28/26)
FILES="
stofs_3d_atl_hgrid.gr3                 stofs_3d_atl_ufs.hgrid.gr3
stofs_3d_atl_hgrid.ll                  stofs_3d_atl_ufs.hgrid.ll
stofs_3d_atl_vgrid.in                  stofs_3d_atl_ufs.vgrid.in
stofs_3d_atl_station.in                stofs_3d_atl_ufs.station.in
stofs_3d_atl_shapiro.gr3               stofs_3d_atl_ufs.shapiro.gr3
stofs_3d_atl_diffmax.gr3               stofs_3d_atl_ufs.diffmax.gr3
stofs_3d_atl_diffmin.gr3               stofs_3d_atl_ufs.diffmin.gr3
stofs_3d_atl_watertype.gr3             stofs_3d_atl_ufs.watertype.gr3
stofs_3d_atl_windrot_geo2proj.gr3      stofs_3d_atl_ufs.windrot_geo2proj.gr3
stofs_3d_atl_albedo.gr3                stofs_3d_atl_ufs.albedo.gr3
stofs_3d_atl_drag.gr3                  stofs_3d_atl_ufs.drag.gr3
stofs_3d_atl_sal_nudge.gr3             stofs_3d_atl_ufs.SAL_nudge.gr3
stofs_3d_atl_tem_nudge.gr3             stofs_3d_atl_ufs.TEM_nudge.gr3
stofs_3d_atl_tvd.prop                  stofs_3d_atl_ufs.tvd.prop
stofs_3d_atl_partition.prop            stofs_3d_atl_ufs.partition.prop
stofs_3d_atl_bctides.in_template       stofs_3d_atl_ufs.bctides.in_template
stofs_3d_atl_obc_3dth_nc.in            stofs_3d_atl_ufs.obc_3dth_nc.in
stofs_3d_atl_obc_nudge_nc.in           stofs_3d_atl_ufs.obc_nudge_nc.in
stofs_3d_atl_sflux_inputs.txt          stofs_3d_atl_ufs.sflux_inputs.txt
stofs_3d_atl_river_sources_conus.json  stofs_3d_atl_river_sources_conus.json
stofs_3d_atl_adt_weight.nc             stofs_3d_atl_adt_weight.nc
stofs_3d_atl_staout_nc.json            stofs_3d_atl_staout_nc.json
stofs_3d_atl_staout_nc.csv             stofs_3d_atl_staout_nc.csv
stofs_3d_atl_sta_cwl_xgeoid_to_msl.nco stofs_3d_atl_sta_cwl_xgeoid_to_msl.nco
stofs_3d_atl_node_id_city_poly_adcirc.txt stofs_3d_atl_node_id_city_poly_adcirc.txt
stofs_3d_atl_obc_adjust_station.bp     stofs_3d_atl_obc_adjust_station.bp
stofs_3d_atl_obc_adjust_msl_geoid.bp   stofs_3d_atl_obc_adjust_msl_geoid.bp
"

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

# The run launches $SCHISM_TASKS SCHISM ranks against this partition, so
# a rank-count mismatch fails at model start; catch it here instead. MJ (09/28/26)
read -r ne np_ < <(sed -n 2p "$DEST/stofs_3d_atl_ufs.hgrid.gr3")
nsta=$(sed -n 2p "$DEST/stofs_3d_atl_ufs.station.in" | awk '{print $1}')
nrank=$(awk '$NF+0 > m {m = $NF+0} END {print m + 1}' "$DEST/stofs_3d_atl_ufs.partition.prop")
echo "hgrid:          $np_ nodes, $ne elements"
echo "station.in:     $nsta stations"
echo "partition.prop: $nrank ranks (yaml ufs_coastal.schism_tasks = $SCHISM_TASKS)"
if [ "$nrank" != "$SCHISM_TASKS" ]; then
    echo "WARNING: partition.prop has $nrank ranks; either set schism_tasks and the"
    echo "         PBS select to match, or regenerate it for $SCHISM_TASKS ranks with"
    echo "         tools/gen_stofs_partition_prop.sh $SCHISM_TASKS <SCHISM_SRC> $DEST/stofs_3d_atl_ufs.hgrid.gr3"
    exit 2
fi
echo "OK"
