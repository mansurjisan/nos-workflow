#!/bin/bash
# =============================================================================
# deploy_to_wcoss2.sh — Deploy merged branch files to WCOSS2 nosofs.v3.7.0
#
# Usage (run on WCOSS2 after cloning/pulling the merged branch):
#   cd /path/to/nos-workflow   # your git clone
#   bash deploy_to_wcoss2.sh [--dry-run]
#
# This script copies all new/changed files from the merged
# feature/ufs-coastal-secofs + feature/unified-nowcast-forecast branch
# to the WCOSS2 nosofs.v3.7.0 package directory.
#
# Prerequisites:
#   1. Merge feature/ufs-coastal-secofs with feature/unified-nowcast-forecast
#   2. Push to GitHub and pull on WCOSS2 (or rsync the repo)
# =============================================================================

set -eu

# --- Configuration ---
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_BASE="${NOSOFS_DIR:-/lfs/h1/nos/estofs/noscrub/${LOGNAME}/packages/nosofs.v3.7.0}"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN MODE — no files will be copied ==="
fi

echo "============================================"
echo "Deploy NOS-OFS to WCOSS2"
echo "============================================"
echo "Source repo:  $REPO_DIR"
echo "Target:       $TARGET_BASE"
echo "============================================"
echo ""

# --- Validate ---
if [ ! -d "$REPO_DIR/jobs" ] || [ ! -d "$REPO_DIR/ush" ]; then
    echo "ERROR: $REPO_DIR doesn't look like the nos-workflow repo"
    exit 1
fi

if [ "$DRY_RUN" = false ] && [ ! -d "$TARGET_BASE" ]; then
    echo "ERROR: Target directory $TARGET_BASE does not exist"
    echo "Set NOSOFS_DIR env var if using a different location"
    exit 1
fi

# --- Helper function ---
deploy_file() {
    local src="$1"
    local dst="$2"

    if [ ! -f "$src" ]; then
        echo "  SKIP (not found): $src"
        return
    fi

    local dst_dir=$(dirname "$dst")
    if [ "$DRY_RUN" = true ]; then
        echo "  COPY: $src → $dst"
    else
        mkdir -p "$dst_dir"
        cp -p "$src" "$dst"
        echo "  OK: $dst"
    fi
}

# =============================================================================
# GROUP 1: J-Jobs (jobs/ → jobs/)
# =============================================================================
echo "--- J-Jobs ---"
for f in JNOS_OFS_PREP JNOS_OFS_NOWCAST JNOS_OFS_FORECAST JNOS_OFS_POST \
         JNOS_OFS_ENSEMBLE_MEMBER JNOS_OFS_ENSEMBLE_POST JNOS_OFS_ENSEMBLE_ATMOS_PREP; do
    deploy_file "$REPO_DIR/jobs/$f" "$TARGET_BASE/jobs/$f"
done
echo ""

# =============================================================================
# GROUP 2: Ex-Scripts (scripts/nosofs/ → scripts/)
# NOTE: WCOSS2 has FLAT layout (scripts/exnos_ofs_*.sh)
#       Git repo has NESTED layout (scripts/nosofs/exnos_ofs_*.sh)
# =============================================================================
echo "--- Ex-Scripts (nosofs → flat) ---"
deploy_file "$REPO_DIR/scripts/nosofs/exnos_ofs_prep.sh" \
            "$TARGET_BASE/scripts/exnos_ofs_prep.sh"
echo ""

# =============================================================================
# GROUP 3: USH Scripts (ush/ → ush/)
# =============================================================================
echo "--- USH Scripts ---"
# Core shared scripts
deploy_file "$REPO_DIR/ush/nos_ofs_model_run.sh" \
            "$TARGET_BASE/ush/nos_ofs_model_run.sh"
deploy_file "$REPO_DIR/ush/nos_ofs_ensemble_run.sh" \
            "$TARGET_BASE/ush/nos_ofs_ensemble_run.sh"
deploy_file "$REPO_DIR/ush/nos_ofs_nowcast_forecast.sh" \
            "$TARGET_BASE/ush/nos_ofs_nowcast_forecast.sh"
echo ""

# DATM/UFS-Coastal specific USH scripts
echo "--- USH Scripts (DATM/UFS-Coastal) ---"
for f in nos_ofs_create_datm_forcing.sh \
         nos_ofs_create_datm_forcing_blended.sh \
         nos_ofs_blend_hrrr_gfs.sh \
         nos_ofs_create_esmf_mesh.sh \
         nos_ofs_gen_ufs_config.sh \
         modify_gfs_nco.sh \
         modify_hrrr_nco.sh; do
    # These go to ush/ (flat) on WCOSS2
    # On WCOSS2 the nosofs/ subdir may or may not exist
    # Safe: copy to both ush/ and ush/nosofs/
    deploy_file "$REPO_DIR/ush/nosofs/$f" "$TARGET_BASE/ush/$f"
done
echo ""

# =============================================================================
# GROUP 4: Python Scripts (ush/python/ → ush/python/)
# =============================================================================
echo "--- Python Scripts (DATM) ---"
mkdir -p "$TARGET_BASE/ush/python/nos_ofs/datm" 2>/dev/null || true
for f in __init__.py blend_hrrr_gfs.py modify_gfs_4_esmfmesh.py modify_hrrr_4_esmfmesh.py proc_scrip.py; do
    deploy_file "$REPO_DIR/ush/python/nos_ofs/datm/$f" \
                "$TARGET_BASE/ush/python/nos_ofs/datm/$f"
done
echo ""

# =============================================================================
# GROUP 5: YAML Config (parm/ → parm/)
# =============================================================================
echo "--- YAML Configs ---"
deploy_file "$REPO_DIR/parm/systems/secofs_ufs.yaml" \
            "$TARGET_BASE/parm/systems/secofs_ufs.yaml"
echo ""

# =============================================================================
# GROUP 6: Fix Files (fix/secofs_ufs/ → fix/secofs_ufs/)
# =============================================================================
echo "--- Fix Files (secofs_ufs) ---"
for f in ufs.configure \
         model_configure.template \
         datm_in.template \
         datm.streams.template \
         secofs_ufs.param.nml \
         fd_ufs.yaml \
         noahmptable.tbl; do
    deploy_file "$REPO_DIR/fix/secofs_ufs/$f" \
                "$TARGET_BASE/fix/secofs_ufs/$f"
done
echo ""

# =============================================================================
# GROUP 7: PBS Scripts (informational — these stay on login node)
# =============================================================================
echo "--- PBS Scripts (for reference) ---"
for f in jnos_secofs_ufs_prep_00.pbs \
         jnos_secofs_ufs_nowcast_00.pbs \
         jnos_secofs_ufs_forecast_00.pbs; do
    deploy_file "$REPO_DIR/pbs/$f" "$TARGET_BASE/pbs/$f"
done
echo ""

# =============================================================================
# GROUP 8: Fix file symlinks for secofs_ufs grid files
# These should point to ../secofs/secofs.{name}
# Only create if fix/secofs/ exists on WCOSS2
# =============================================================================
echo "--- Fix File Symlinks (grid files) ---"
SECOFS_FIX="$TARGET_BASE/fix/secofs"
UFS_FIX="$TARGET_BASE/fix/secofs_ufs"

if [ -d "$SECOFS_FIX" ] || [ "$DRY_RUN" = true ]; then
    for suffix in hgrid.gr3 hgrid.ll vgrid.in vgrid.nu.in vgrid.fake.in \
                  station.in shapiro.gr3 rough.gr3 diffmin.gr3 diffmax.gr3 \
                  albedo.gr3 river.ctl obc.ctl sflux_inputs.txt \
                  nudge.gr3 bctides.in bctides.in_template \
                  nwm.reach.dat nobc_nudge_index.dat; do
        src_file="../secofs/secofs.${suffix}"
        dst_link="$UFS_FIX/secofs_ufs.${suffix}"

        if [ "$DRY_RUN" = true ]; then
            echo "  SYMLINK: $dst_link → $src_file"
        else
            mkdir -p "$UFS_FIX"
            # Only create if source exists
            if [ -f "$SECOFS_FIX/secofs.${suffix}" ]; then
                ln -sf "$src_file" "$dst_link"
                echo "  OK: secofs_ufs.${suffix} → $src_file"
            else
                echo "  SKIP (source missing): secofs.${suffix}"
            fi
        fi
    done
else
    echo "  SKIP: $SECOFS_FIX not found — create symlinks manually"
fi
echo ""

# =============================================================================
# GROUP 9: Fix files for secofs_2d_ufs (2D barotropic)
# Uses same grid as secofs but with 2D-specific vgrid, param.nml, rough.gr3
# =============================================================================
echo "--- Fix Files (secofs_2d_ufs) ---"
UFS_2D_FIX="$TARGET_BASE/fix/secofs_2d_ufs"

# 2D-specific files from repo
for f in secofs_2d_ufs.param.nml \
         secofs_2d_ufs.vgrid.in \
         ufs.configure \
         model_configure.template \
         datm_in.template \
         datm.streams.template \
         fd_ufs.yaml \
         noahmptable.tbl \
         convert_bctides_2d.py \
         convert_restart_3d_to_2d.py \
         gen_elev2d_th.py \
         gen_vgrid_2d.py \
         scale_roughness_2d.py; do
    deploy_file "$REPO_DIR/fix/secofs_2d_ufs/$f" "$UFS_2D_FIX/$f"
done

# Symlinks from secofs (shared grid files, EXCEPT rough.gr3 and vgrid.in)
if [ -d "$SECOFS_FIX" ] || [ "$DRY_RUN" = true ]; then
    for suffix in hgrid.gr3 hgrid.ll \
                  station.in shapiro.gr3 diffmin.gr3 diffmax.gr3 \
                  albedo.gr3 river.ctl obc.ctl sflux_inputs.txt \
                  nudge.gr3 bctides.in bctides.in_template \
                  nwm.reach.dat nobc_nudge_index.dat; do
        src_file="../secofs/secofs.${suffix}"
        dst_link="$UFS_2D_FIX/secofs_2d_ufs.${suffix}"

        if [ "$DRY_RUN" = true ]; then
            echo "  SYMLINK: $dst_link → $src_file"
        else
            mkdir -p "$UFS_2D_FIX"
            if [ -f "$SECOFS_FIX/secofs.${suffix}" ]; then
                ln -sf "$src_file" "$dst_link"
                echo "  OK: secofs_2d_ufs.${suffix} → $src_file"
            else
                echo "  SKIP (source missing): secofs.${suffix}"
            fi
        fi
    done

    # Generate scaled rough.gr3 for 2D (scale=0.05 default)
    ROUGH_SCALE="${ROUGH_SCALE:-0.05}"
    ROUGH_SRC="$SECOFS_FIX/secofs.rough.gr3"
    ROUGH_DST="$UFS_2D_FIX/secofs_2d_ufs.rough.gr3"
    if [ -f "$ROUGH_SRC" ] && [ -f "$UFS_2D_FIX/scale_roughness_2d.py" ]; then
        if [ "$DRY_RUN" = true ]; then
            echo "  GENERATE: $ROUGH_DST (scale=$ROUGH_SCALE from 3D rough.gr3)"
        else
            echo "  Generating 2D rough.gr3 with scale=$ROUGH_SCALE ..."
            python3 "$UFS_2D_FIX/scale_roughness_2d.py" --scale "$ROUGH_SCALE" \
                "$ROUGH_SRC" "$ROUGH_DST"
            echo "  OK: secofs_2d_ufs.rough.gr3 (scale=$ROUGH_SCALE)"
        fi
    else
        echo "  SKIP: rough.gr3 scaling (source or script missing)"
        echo "  To scale manually: python3 scale_roughness_2d.py --scale 0.05 secofs.rough.gr3 secofs_2d_ufs.rough.gr3"
    fi
else
    echo "  SKIP: $SECOFS_FIX not found — create symlinks manually"
fi
echo ""

# =============================================================================
# Summary
# =============================================================================
echo "============================================"
if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN COMPLETE — no files were copied"
    echo "Run without --dry-run to actually deploy"
else
    echo "DEPLOYMENT COMPLETE"
    echo ""
    echo "Next steps:"
    echo "  1. Verify: ls -la $TARGET_BASE/fix/secofs_ufs/"
    echo "  2. Verify: ls -la $TARGET_BASE/ush/nos_ofs_model_run.sh"
    echo "  3. Ensure UFS-Coastal executable exists:"
    echo "     ls -la $TARGET_BASE/exec/fv3_coastalS.exe"
    echo "  4. Submit prep job:"
    echo "     qsub $TARGET_BASE/pbs/jnos_secofs_ufs_prep_00.pbs"
fi
echo "============================================"
