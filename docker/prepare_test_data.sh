#!/bin/bash
# ============================================================================
# prepare_test_data.sh - Stage test data and load Docker images
#
# Usage on ParallelWorks:
#   bash prepare_test_data.sh /lustre/mjisan/secofs_docker
#
# Usage on WCOSS2 (stage data only, no Docker):
#   bash prepare_test_data.sh /path/to/staging --stage-only
#
# This script:
#   1. Creates the directory structure
#   2. Loads Docker images from tar.gz
#   3. Generates GFS .idx files (if missing)
#   4. Creates nosofs.met.parmlist.dat (if missing)
#   5. Verifies all required files
#   6. Prints the docker-compose run command
# ============================================================================
set -eu

BASEDIR="${1:-.}"
STAGE_ONLY="${2:-}"

echo "=============================================="
echo " SECOFS UFS Docker Test Data Preparation"
echo "=============================================="
echo " Target: ${BASEDIR}"
echo ""

# ---- Directory structure ----
echo ">>> Creating directory structure..."
mkdir -p "${BASEDIR}/images"
mkdir -p "${BASEDIR}/data/com/gfs/v16.3"
mkdir -p "${BASEDIR}/data/com/hrrr/v4.1"
mkdir -p "${BASEDIR}/data/com/nwm/v3.0"
mkdir -p "${BASEDIR}/data/com/rtofs/v2.5"
mkdir -p "${BASEDIR}/data/com/nosofs/v3.7"
mkdir -p "${BASEDIR}/data/fix/secofs"
mkdir -p "${BASEDIR}/data/fix/shared"
mkdir -p "${BASEDIR}/work"

# ---- Load Docker images ----
if [ "${STAGE_ONLY}" != "--stage-only" ]; then
    echo ""
    echo ">>> Loading Docker images..."
    for img in secofs-ufs-gcc.tar.gz ufs-coastal.tar.gz secofs-ufs-intel.tar.gz; do
        if [ -f "${BASEDIR}/images/${img}" ]; then
            echo "  Loading ${img}..."
            docker load < "${BASEDIR}/images/${img}"
        else
            echo "  SKIP: ${img} not found (upload it to ${BASEDIR}/images/)"
        fi
    done
fi

# ---- Generate GFS .idx files ----
echo ""
echo ">>> Checking GFS .idx files..."
IDX_COUNT=0
for gfs_dir in "${BASEDIR}"/data/com/gfs/v16.3/gfs.*/*/atmos; do
    [ -d "$gfs_dir" ] || continue
    for f in "$gfs_dir"/gfs.t*.pgrb2.0p25.f???; do
        [ -f "$f" ] || continue
        if [ ! -f "${f}.idx" ]; then
            echo "  Generating $(basename ${f}).idx..."
            if command -v wgrib2 >/dev/null 2>&1; then
                wgrib2 "$f" -s > "${f}.idx"
            elif command -v docker >/dev/null 2>&1; then
                docker run --rm -v "$(dirname $f)":"$(dirname $f)" \
                    --entrypoint bash nosofs/secofs-ufs:latest \
                    -c "wgrib2 $f -s" > "${f}.idx"
            else
                echo "    WARNING: No wgrib2 available, cannot create .idx"
            fi
            IDX_COUNT=$((IDX_COUNT + 1))
        fi
    done
done
echo "  Generated ${IDX_COUNT} new .idx files"

# ---- Create nosofs.met.parmlist.dat ----
PARMLIST="${BASEDIR}/data/fix/shared/nosofs.met.parmlist.dat"
if [ ! -f "${PARMLIST}" ]; then
    echo ""
    echo ">>> Creating nosofs.met.parmlist.dat..."
    cat > "${PARMLIST}" << 'PARMEOF'
:PRMSL:mean sea level:
:TMP:2 m above ground:
:SPFH:2 m above ground:
:RH:2 m above ground:
:UGRD:10 m above ground:
:VGRD:10 m above ground:
:PRATE:surface:
:DSWRF:surface:
:DLWRF:surface:
:USWRF:surface:
:ULWRF:surface:
:SHTFL:surface:
:LHTFL:surface:
:TCDC:entire atmosphere:
:APCP:surface:
:DPT:2 m above ground:
:PRES:surface:
:EVP:surface:
:MSLMA:mean sea level:
PARMEOF
    echo "  Created ${PARMLIST}"
fi

# ---- Verify required files ----
echo ""
echo "=============================================="
echo " Verification"
echo "=============================================="

check_dir() {
    local path="$1"
    local desc="$2"
    if [ -d "$path" ]; then
        local count=$(find "$path" -type f | wc -l)
        echo "  OK: ${desc} (${count} files)"
    else
        echo "  MISSING: ${desc} → ${path}"
    fi
}

check_file() {
    local path="$1"
    local desc="$2"
    if [ -f "$path" ]; then
        echo "  OK: ${desc} ($(du -sh "$path" | cut -f1))"
    else
        echo "  MISSING: ${desc} → ${path}"
    fi
}

echo ""
echo "--- Input Data ---"
check_dir "${BASEDIR}/data/com/gfs/v16.3" "GFS GRIB2"
check_dir "${BASEDIR}/data/com/hrrr/v4.1" "HRRR GRIB2"
check_dir "${BASEDIR}/data/com/nwm/v3.0" "NWM"
check_dir "${BASEDIR}/data/com/rtofs/v2.5" "RTOFS"
check_dir "${BASEDIR}/data/com/nosofs/v3.7" "Hotstart (optional)"

echo ""
echo "--- Fix Files ---"
check_dir "${BASEDIR}/data/fix/secofs" "SECOFS fix files"
check_dir "${BASEDIR}/data/fix/shared" "Shared fix files"
check_file "${PARMLIST}" "Met parmlist"

echo ""
echo "--- GFS .idx Files ---"
IDX_FOUND=$(find "${BASEDIR}/data/com/gfs" -name "*.idx" 2>/dev/null | wc -l)
GFS_FOUND=$(find "${BASEDIR}/data/com/gfs" -name "gfs.t*.pgrb2.0p25.f???" 2>/dev/null | wc -l)
echo "  GFS files: ${GFS_FOUND}, .idx files: ${IDX_FOUND}"
if [ "${IDX_FOUND}" -lt "${GFS_FOUND}" ]; then
    echo "  WARNING: Some .idx files missing — run this script again after loading Docker image"
fi

if [ "${STAGE_ONLY}" != "--stage-only" ]; then
    echo ""
    echo "--- Docker Images ---"
    docker images nosofs/secofs-ufs --format "  {{.Tag}}\t{{.Size}}" 2>/dev/null || echo "  No images loaded"
    docker images nosofs/ufs-coastal --format "  {{.Tag}}\t{{.Size}}" 2>/dev/null
fi

# ---- Print run commands ----
echo ""
echo "=============================================="
echo " Ready to Run"
echo "=============================================="
echo ""
echo " # Standalone SECOFS prep (no UFS, no model run):"
echo " DATA_ROOT=${BASEDIR}/data OFS=secofs PDY=20260324 CYC=18 \\"
echo "   docker compose -f docker/docker-compose.yml run --rm secofs-prep"
echo ""
echo " # UFS SECOFS prep (uses DATM forcing generation):"
echo " DATA_ROOT=${BASEDIR}/data OFS=secofs_ufs PDY=20260324 CYC=18 \\"
echo "   docker compose -f docker/docker-compose.yml run --rm secofs-prep"
echo ""
echo " # Full UFS chain (prep → nowcast → forecast → post):"
echo " DATA_ROOT=${BASEDIR}/data OFS=secofs_ufs PDY=20260324 CYC=18 \\"
echo "   docker compose -f docker/docker-compose.yml run --rm secofs-all"
echo ""

# ---- Data staging from WCOSS2 (reference) ----
cat << 'WCOSS2_REF'
============================================
 WCOSS2 Data Staging Reference
============================================

If staging directly from WCOSS2 to Lustre:

# GFS (24 files, ~13GB)
NOSOFS=/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nosofs.v3.7.0
mkdir -p data/com/gfs/v16.3/gfs.20260324/{06,12}/atmos
cp /lfs/h1/ops/prod/com/gfs/v16.3/gfs.20260324/12/atmos/gfs.t12z.pgrb2.0p25.f{000..054..3} data/com/gfs/v16.3/gfs.20260324/12/atmos/
cp /lfs/h1/ops/prod/com/gfs/v16.3/gfs.20260324/06/atmos/gfs.t06z.pgrb2.0p25.f{000..012..3} data/com/gfs/v16.3/gfs.20260324/06/atmos/

# HRRR (58 files, ~8GB)
mkdir -p data/com/hrrr/v4.1/hrrr.20260324/conus
cp /lfs/h1/ops/prod/com/hrrr/v4.1/hrrr.20260324/conus/hrrr.t{08..17}z.wrfsfcf01.grib2 data/com/hrrr/v4.1/hrrr.20260324/conus/
for f in $(seq -w 1 48); do cp /lfs/h1/ops/prod/com/hrrr/v4.1/hrrr.20260324/conus/hrrr.t18z.wrfsfcf${f}.grib2 data/com/hrrr/v4.1/hrrr.20260324/conus/; done

# NWM (18 files, ~0.25GB)
mkdir -p data/com/nwm/v3.0/nwm.20260324/short_range
cp /lfs/h1/ops/prod/com/nwm/v3.0/nwm.20260324/short_range/nwm.t18z.short_range.channel_rt.f0{01..18}.conus.nc data/com/nwm/v3.0/nwm.20260324/short_range/

# RTOFS (76 files, ~15GB)
mkdir -p data/com/rtofs/v2.5/rtofs.20260324
cp /lfs/h1/ops/prod/com/rtofs/v2.5/rtofs.20260324/rtofs_glo_3dz_f{006..090..6}_6hrly_hvr_US_east.nc data/com/rtofs/v2.5/rtofs.20260324/
cp /lfs/h1/ops/prod/com/rtofs/v2.5/rtofs.20260324/rtofs_glo_2ds_f{006..066}_diag.nc data/com/rtofs/v2.5/rtofs.20260324/

# Fix files (~6GB)
mkdir -p data/fix/secofs data/fix/shared
for f in hgrid.gr3 hgrid.ll vgrid.in vgrid.nu.in vgrid.fake.in station.in rough.gr3 shapiro.gr3 diffmin.gr3 diffmax.gr3 albedo.gr3 watertype.gr3 windrot_geo2proj.gr3 bctides.in bctides.in_template nudge.gr3 SAL_nudge.gr3 TEM_nudge.gr3 elev.ic river.ctl obc.ctl sflux_inputs.txt nwm.reach.dat nobc_nudge_index.dat param.nml nv.nc sigma.dat station.lat.lon; do
    cp -L $NOSOFS/fix/secofs/secofs.${f} data/fix/secofs/ 2>/dev/null
done
cp $NOSOFS/fix/shared/nosofs.{clim.WOA05.nc,river.clim.usgs.nc,HC_NWLON.nc} data/fix/shared/

# Hotstart (~18GB, optional)
mkdir -p data/com/nosofs/v3.7/secofs.20260324
cp $COMROOT/nosofs/v3.7/secofs.20260324/secofs.t12z.20260324.rst.nowcast.nc data/com/nosofs/v3.7/secofs.20260324/
WCOSS2_REF
