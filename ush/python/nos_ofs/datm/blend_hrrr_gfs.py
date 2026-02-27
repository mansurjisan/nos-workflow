#!/usr/bin/env python
"""
Blend HRRR and GFS forcing files for CDEPS/DATM.
Memory-optimized version for WCOSS2.

- HRRR provides high-res (3km) forcing over CONUS
- GFS provides global coverage at 0.25 deg
- Output time grid covers the FULL GFS range at hourly resolution
  - Within HRRR time range: blended HRRR+GFS (HRRR over CONUS, GFS elsewhere)
  - Beyond HRRR time range: GFS-only (interpolated from 3-hourly to hourly)
  This ensures the forcing file always covers the full forecast window,
  even when HRRR extended forecasts (F19+) are unavailable.
- Spatial interpolation: Delaunay bilinear for HRRR, RegularGridInterpolator for GFS
- Output on a regular lat/lon grid at configurable resolution

Usage:
    python blend_hrrr_gfs.py HRRR_FILE GFS_FILE OUTPUT_FILE DOMAIN [RESOLUTION]

Arguments:
    HRRR_FILE   - Input HRRR forcing NetCDF file
    GFS_FILE    - Input GFS forcing NetCDF file
    OUTPUT_FILE - Output blended NetCDF file
    DOMAIN      - Domain preset: ATLANTIC, SECOFS, STOFS3D_ATL
    RESOLUTION  - Grid resolution in degrees (default: 0.025)

Requires: numpy, netCDF4, scipy

Author: SECOFS UFS-Coastal (from ufs-nos-ofs)
"""

import numpy as np
from netCDF4 import Dataset
from scipy.spatial import Delaunay
from scipy.interpolate import RegularGridInterpolator, interp1d
from datetime import datetime
import sys
import gc

# Parse arguments
if len(sys.argv) < 5:
    print("Usage: python blend_hrrr_gfs.py HRRR_FILE GFS_FILE OUTPUT_FILE DOMAIN [RESOLUTION]")
    sys.exit(1)

HRRR_FILE = sys.argv[1]
GFS_FILE = sys.argv[2]
OUTPUT_FILE = sys.argv[3]
DOMAIN = sys.argv[4]
RESOLUTION = float(sys.argv[5]) if len(sys.argv) > 5 else 0.025

# Domain bounds (lon_min, lon_max, lat_min, lat_max)
# Each domain should cover the full model grid with some padding
DOMAINS = {
    'ATLANTIC': (-98.0, -55.0, 10.0, 53.0),
    'SECOFS': (-90.0, -61.0, 15.0, 42.0),
    'STOFS3D_ATL': (-99.0, -52.0, 7.0, 53.0),
}

if DOMAIN not in DOMAINS:
    print(f"ERROR: Unknown domain {DOMAIN}. Use: ATLANTIC, SECOFS, STOFS3D_ATL")
    sys.exit(1)

TARGET_LON_MIN, TARGET_LON_MAX, TARGET_LAT_MIN, TARGET_LAT_MAX = DOMAINS[DOMAIN]
TARGET_DLON = RESOLUTION
TARGET_DLAT = RESOLUTION
BUFFER = 1.0

print("============================================")
print("HRRR + GFS Blending for CDEPS/DATM")
print("============================================")
print(f"HRRR input:   {HRRR_FILE}")
print(f"GFS input:    {GFS_FILE}")
print(f"Output:       {OUTPUT_FILE}")
print(f"Domain:       {DOMAIN}")
print(f"Resolution:   {RESOLUTION} deg")
print(f"Bounds:       {TARGET_LAT_MIN}N-{TARGET_LAT_MAX}N, {TARGET_LON_MIN}E-{TARGET_LON_MAX}E")
print("============================================")

print("Loading HRRR coordinates...")
hrrr = Dataset(HRRR_FILE, 'r')
hrrr_lon2d_full = hrrr.variables['longitude'][:]
hrrr_lat2d_full = hrrr.variables['latitude'][:]
hrrr_lon2d_full = np.where(hrrr_lon2d_full > 180, hrrr_lon2d_full - 360, hrrr_lon2d_full)
hrrr_time_raw = np.array(hrrr.variables['time'][:])
n_hrrr_times = len(hrrr_time_raw)
print(f"  HRRR full grid: {hrrr_lon2d_full.shape}, {n_hrrr_times} times")

# Subset HRRR to target domain + buffer (memory optimization)
print("Subsetting HRRR to target domain...")
hrrr_mask = ((hrrr_lon2d_full >= TARGET_LON_MIN - BUFFER) &
             (hrrr_lon2d_full <= TARGET_LON_MAX + BUFFER) &
             (hrrr_lat2d_full >= TARGET_LAT_MIN - BUFFER) &
             (hrrr_lat2d_full <= TARGET_LAT_MAX + BUFFER))

# Find bounding box indices for HRRR subset
rows_with_data = np.any(hrrr_mask, axis=1)
cols_with_data = np.any(hrrr_mask, axis=0)
if np.any(rows_with_data) and np.any(cols_with_data):
    row_min, row_max = np.where(rows_with_data)[0][[0, -1]]
    col_min, col_max = np.where(cols_with_data)[0][[0, -1]]
    hrrr_row_slice = slice(row_min, row_max + 1)
    hrrr_col_slice = slice(col_min, col_max + 1)
    hrrr_lon2d = np.array(hrrr_lon2d_full[hrrr_row_slice, hrrr_col_slice], dtype=np.float32)
    hrrr_lat2d = np.array(hrrr_lat2d_full[hrrr_row_slice, hrrr_col_slice], dtype=np.float32)
    print(f"  HRRR subset: {hrrr_lon2d.shape} (reduced from {hrrr_lon2d_full.shape})")
else:
    print("  WARNING: No HRRR data in target domain, using GFS only")
    hrrr_lon2d = np.array([[TARGET_LON_MIN]])
    hrrr_lat2d = np.array([[0.0]])  # Outside domain
    hrrr_row_slice = slice(0, 1)
    hrrr_col_slice = slice(0, 1)

# Free full arrays
del hrrr_lon2d_full, hrrr_lat2d_full, hrrr_mask
gc.collect()

print("Loading GFS...")
gfs = Dataset(GFS_FILE, 'r')
gfs_lat_full = np.array(gfs.variables['latitude'][:], dtype=np.float32)
gfs_lon_full = np.array(gfs.variables['longitude'][:], dtype=np.float32)
gfs_time = np.array(gfs.variables['time'][:])
gfs_lon_180 = np.where(gfs_lon_full > 180, gfs_lon_full - 360, gfs_lon_full)

# Subset GFS to domain
lat_mask = (gfs_lat_full >= TARGET_LAT_MIN - 1) & (gfs_lat_full <= TARGET_LAT_MAX + 1)
lon_mask = (gfs_lon_180 >= TARGET_LON_MIN - 1) & (gfs_lon_180 <= TARGET_LON_MAX + 1)
gfs_lat_idx = np.where(lat_mask)[0]
gfs_lon_idx = np.where(lon_mask)[0]
gfs_lat = gfs_lat_full[lat_mask]
gfs_lon = gfs_lon_180[lon_mask]
print(f"  GFS subset: {len(gfs_lat)} x {len(gfs_lon)}")

print("Creating target grid...")
target_lon = np.arange(TARGET_LON_MIN, TARGET_LON_MAX + TARGET_DLON/2, TARGET_DLON, dtype=np.float32)
target_lat = np.arange(TARGET_LAT_MIN, TARGET_LAT_MAX + TARGET_DLAT/2, TARGET_DLAT, dtype=np.float32)
target_lon2d, target_lat2d = np.meshgrid(target_lon, target_lat)
ny, nx = len(target_lat), len(target_lon)
print(f"  Grid: {ny} x {nx} = {ny*nx:,} points")

print("Building HRRR Delaunay triangulation (bilinear interpolation)...")
hrrr_points = np.column_stack([hrrr_lon2d.ravel(), hrrr_lat2d.ravel()])
tri = Delaunay(hrrr_points)

# Find which triangle each target point falls in
target_points_flat = np.column_stack([target_lon2d.ravel(), target_lat2d.ravel()])
simplices = tri.find_simplex(target_points_flat)

# HRRR valid mask: target points inside the HRRR triangulation convex hull
hrrr_valid_mask = (simplices >= 0).reshape(ny, nx)
print(f"  HRRR coverage: {100*np.sum(hrrr_valid_mask)/hrrr_valid_mask.size:.1f}%")

# Precompute barycentric coordinates for bilinear interpolation
# Only for points inside the triangulation (simplex >= 0)
valid_flat = simplices >= 0
n_valid = int(np.sum(valid_flat))
print(f"  Valid points for bilinear: {n_valid:,}")

valid_simplices = simplices[valid_flat]
valid_targets = target_points_flat[valid_flat]  # (n_valid, 2)

# Triangle vertex indices into hrrr_points array
tri_vert_idx = tri.simplices[valid_simplices]  # (n_valid, 3)

# Vertex coordinates
v0 = hrrr_points[tri_vert_idx[:, 0]]  # (n_valid, 2)
v1 = hrrr_points[tri_vert_idx[:, 1]]
v2 = hrrr_points[tri_vert_idx[:, 2]]

# Barycentric coordinates: for triangle (v0,v1,v2) and point p
det = (v1[:, 1] - v2[:, 1]) * (v0[:, 0] - v2[:, 0]) + \
      (v2[:, 0] - v1[:, 0]) * (v0[:, 1] - v2[:, 1])
lam0 = ((v1[:, 1] - v2[:, 1]) * (valid_targets[:, 0] - v2[:, 0]) +
        (v2[:, 0] - v1[:, 0]) * (valid_targets[:, 1] - v2[:, 1])) / det
lam1 = ((v2[:, 1] - v0[:, 1]) * (valid_targets[:, 0] - v2[:, 0]) +
        (v0[:, 0] - v2[:, 0]) * (valid_targets[:, 1] - v2[:, 1])) / det
lam2 = 1.0 - lam0 - lam1

bary_coords = np.column_stack([lam0, lam1, lam2]).astype(np.float32)  # (n_valid, 3)
valid_flat_indices = np.where(valid_flat)[0]  # indices into flattened target grid

# Free intermediate arrays
del hrrr_points, target_points_flat, simplices, valid_targets
del v0, v1, v2, det, lam0, lam1, lam2, valid_simplices, valid_flat, tri
gc.collect()

# =========================================================================
# Lambert Conformal wind rotation pre-computation
# HRRR uses Lambert Conformal projection — U/V winds in GRIB2 are
# grid-relative and must be rotated to earth-relative for DATM.
# Parameters from HRRR GRIB2 metadata (Grid 227, 3km CONUS):
#   LoV (central meridian)  = 262.5° = -97.5°
#   LaD (true latitude)     = 38.5° (tangent cone, Latin1 = Latin2)
# Rotation formula (matches nos_ofs_create_forcing_met.f lines 1998-2018):
#   angle = sin(LaD) * (lon - LoV) * D2R
#   U_earth =  cos(angle) * U_grid + sin(angle) * V_grid
#   V_earth = -sin(angle) * U_grid + cos(angle) * V_grid
# =========================================================================
HRRR_LOV = -97.5   # longitude of vertical (central meridian), degrees
HRRR_LAD = 38.5    # latitude at which projection is true, degrees
D2R = np.pi / 180.0
ROTCON = np.sin(HRRR_LAD * D2R)

rot_angle = ROTCON * (target_lon2d - HRRR_LOV) * D2R
cos_rot = np.cos(rot_angle).astype(np.float32)
sin_rot = np.sin(rot_angle).astype(np.float32)
print(f"  LCC wind rotation: LoV={HRRR_LOV}°, LaD={HRRR_LAD}°")
print(f"  Rotation angle range: {np.degrees(rot_angle.min()):.1f}° to {np.degrees(rot_angle.max()):.1f}°")
del rot_angle

# =========================================================================
# Build unified hourly time grid covering the FULL GFS range
# HRRR may not cover the entire forecast period (e.g., extended forecasts
# F19+ unavailable), so we use GFS's time range as the master and fill
# with GFS-only data where HRRR is missing.
# =========================================================================
print("Building unified time grid...")
# Determine hourly interval from HRRR (typically 3600 seconds)
if n_hrrr_times >= 2:
    hrrr_dt = hrrr_time_raw[1] - hrrr_time_raw[0]
else:
    hrrr_dt = 3600.0

# The output time grid covers the union of HRRR and GFS, at hourly resolution
# Use the earliest start and latest end from both sources
t_start = min(hrrr_time_raw[0], gfs_time[0])
t_end = max(hrrr_time_raw[-1], gfs_time[-1])
out_time = np.arange(t_start, t_end + hrrr_dt / 2, hrrr_dt)
n_times = len(out_time)

# Determine which output timesteps have HRRR coverage
# (within half a timestep of any HRRR time record)
hrrr_t_set = set(hrrr_time_raw.tolist())
hrrr_time_has = np.array([
    any(abs(ot - ht) < hrrr_dt / 2 for ht in hrrr_time_raw) for ot in out_time
])
n_hrrr_covered = int(np.sum(hrrr_time_has))
n_gfs_only = n_times - n_hrrr_covered

if n_gfs_only > 0:
    print(f"  HRRR covers {n_hrrr_covered}/{n_times} timesteps")
    print(f"  GFS-only fill for {n_gfs_only} timesteps (beyond HRRR range)")
else:
    print(f"  HRRR covers all {n_times} timesteps")

# Map output timesteps to HRRR time indices (for blended timesteps)
hrrr_time_to_idx = {}
for i, ht in enumerate(hrrr_time_raw):
    hrrr_time_to_idx[ht] = i

print("Setting up GFS temporal interpolation...")
gfs_time_interp = interp1d(gfs_time, np.arange(len(gfs_time)),
                            kind='linear', bounds_error=False, fill_value='extrapolate')
target_to_gfs_idx = gfs_time_interp(out_time)

print("Creating output NetCDF...")
ncout = Dataset(OUTPUT_FILE, 'w', format='NETCDF4')
ncout.createDimension('time', None)
ncout.createDimension('y', ny)
ncout.createDimension('x', nx)

time_var = ncout.createVariable('time', 'f8', ('time',))
time_var.units = 'seconds since 1970-01-01 00:00:00'
time_var.calendar = 'standard'
time_var.axis = 'T'
time_var[:] = out_time

lat_var = ncout.createVariable('latitude', 'f4', ('y', 'x'))
lat_var.units = 'degrees_north'
lat_var.long_name = 'latitude'
lat_var.axis = 'Y'
lat_var.standard_name = 'latitude'
lat_var[:] = target_lat2d

lon_var = ncout.createVariable('longitude', 'f4', ('y', 'x'))
lon_var.units = 'degrees_east'
lon_var.long_name = 'longitude'
lon_var.axis = 'X'
lon_var.standard_name = 'longitude'
lon_var[:] = target_lon2d

source_var = ncout.createVariable('data_source', 'i1', ('y', 'x'))
source_var.long_name = 'Data source (1=HRRR, 0=GFS)'
source_var[:] = hrrr_valid_mask.astype(np.int8)

ncout.title = 'Blended HRRR+GFS Forcing for CDEPS/DATM'
ncout.source = 'HRRR (CONUS) + GFS (gap fill)'
ncout.history = f'Created {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}'
ncout.Conventions = 'CF-1.6'

# Variable mapping (HRRR name -> GFS name)
VARIABLES = [
    ('UGRD_10maboveground', 'UGRD_10maboveground'),
    ('VGRD_10maboveground', 'VGRD_10maboveground'),
    ('TMP_2maboveground', 'TMP_2maboveground'),
    ('SPFH_2maboveground', 'SPFH_2maboveground'),
    ('PRATE_surface', 'PRATE_surface'),
    ('DSWRF_surface', 'DSWRF_surface'),
    ('DLWRF_surface', 'DLWRF_surface'),
    ('MSLMA_meansealevel', 'PRMSL_meansealevel'),
]

# GFS lat order
if gfs_lat[0] > gfs_lat[-1]:
    gfs_lat_asc = gfs_lat[::-1]
    gfs_flip = True
else:
    gfs_lat_asc = gfs_lat
    gfs_flip = False

print("Processing variables...")
for hrrr_name, gfs_name in VARIABLES:
    # Need at least GFS; HRRR is optional for GFS-only timesteps
    if gfs_name not in gfs.variables:
        print(f"  Skipping {hrrr_name} (not in GFS)")
        continue
    hrrr_has_var = hrrr_name in hrrr.variables

    print(f"  {hrrr_name}...", end='', flush=True)

    hrrr_var = hrrr.variables[hrrr_name] if hrrr_has_var else None
    gfs_var = gfs.variables[gfs_name]

    # Get units/long_name from whichever source is available
    if hrrr_has_var:
        var_units = hrrr_var.units if hasattr(hrrr_var, 'units') else ''
        var_long_name = hrrr_var.long_name if hasattr(hrrr_var, 'long_name') else hrrr_name
    else:
        var_units = gfs_var.units if hasattr(gfs_var, 'units') else ''
        var_long_name = gfs_var.long_name if hasattr(gfs_var, 'long_name') else gfs_name

    out_var = ncout.createVariable(hrrr_name, 'f4', ('time', 'y', 'x'), fill_value=9.999e+20)
    out_var.short_name = hrrr_name
    out_var.units = var_units
    out_var.long_name = var_long_name

    for t in range(n_times):
        cur_time = out_time[t]
        use_hrrr = hrrr_time_has[t] and hrrr_has_var

        # --- GFS data with temporal interpolation (always needed) ---
        gfs_t_idx = target_to_gfs_idx[t]
        t_low = int(np.floor(gfs_t_idx))
        t_high = int(np.ceil(gfs_t_idx))
        t_frac = gfs_t_idx - t_low
        t_low = max(0, min(t_low, len(gfs_time) - 1))
        t_high = max(0, min(t_high, len(gfs_time) - 1))

        gfs_data_low = np.array(gfs_var[t_low, gfs_lat_idx[0]:gfs_lat_idx[-1]+1, gfs_lon_idx[0]:gfs_lon_idx[-1]+1], dtype=np.float32)
        gfs_data_high = np.array(gfs_var[t_high, gfs_lat_idx[0]:gfs_lat_idx[-1]+1, gfs_lon_idx[0]:gfs_lon_idx[-1]+1], dtype=np.float32)

        if t_low == t_high:
            gfs_data = gfs_data_low
        else:
            gfs_data = (1 - t_frac) * gfs_data_low + t_frac * gfs_data_high

        if gfs_flip:
            gfs_data = gfs_data[::-1, :]

        gfs_interp = RegularGridInterpolator(
            (gfs_lat_asc, gfs_lon), gfs_data,
            method='linear', bounds_error=False, fill_value=np.nan
        )
        gfs_regrid = gfs_interp(np.column_stack([target_lat2d.ravel(),
                                                  target_lon2d.ravel()])).reshape(ny, nx)

        if use_hrrr:
            # --- Blended: HRRR over CONUS + GFS gap fill ---
            # Find matching HRRR time index
            hrrr_t = None
            for ht, hi in hrrr_time_to_idx.items():
                if abs(cur_time - ht) < hrrr_dt / 2:
                    hrrr_t = hi
                    break

            if hrrr_t is not None:
                hrrr_data = np.array(hrrr_var[hrrr_t, hrrr_row_slice, hrrr_col_slice], dtype=np.float32).ravel()
                hrrr_data = np.where(hrrr_data > 1e10, np.nan, hrrr_data)
                # Bilinear interpolation via precomputed Delaunay barycentric coords
                vals_at_verts = hrrr_data[tri_vert_idx]  # (n_valid, 3)
                hrrr_interp_valid = np.sum(vals_at_verts * bary_coords, axis=1)
                hrrr_regrid = np.full(ny * nx, np.nan, dtype=np.float32)
                hrrr_regrid[valid_flat_indices] = hrrr_interp_valid
                hrrr_regrid = hrrr_regrid.reshape(ny, nx)
                combined = np.where(hrrr_valid_mask & ~np.isnan(hrrr_regrid), hrrr_regrid, gfs_regrid)
                del hrrr_data, vals_at_verts, hrrr_interp_valid, hrrr_regrid
            else:
                # Fallback: GFS only (shouldn't happen if hrrr_time_has is correct)
                combined = gfs_regrid
        else:
            # --- GFS-only timestep (beyond HRRR range) ---
            combined = gfs_regrid

        out_var[t, :, :] = combined

        # Free memory each timestep
        del gfs_data_low, gfs_data_high, gfs_data, gfs_regrid, combined

    gc.collect()
    print(" done")

# =========================================================================
# Apply Lambert Conformal wind rotation to HRRR-sourced wind data.
# HRRR U/V are grid-relative; rotate to earth-relative where HRRR was used.
# GFS-only timesteps and GFS-filled grid cells are already earth-relative.
# =========================================================================
if 'UGRD_10maboveground' in ncout.variables and 'VGRD_10maboveground' in ncout.variables:
    print("Applying Lambert Conformal wind rotation to HRRR wind data...")
    u_var = ncout.variables['UGRD_10maboveground']
    v_var = ncout.variables['VGRD_10maboveground']
    n_rotated = 0

    for t in range(n_times):
        if not hrrr_time_has[t]:
            continue  # GFS-only timestep — winds already earth-relative

        u_data = np.array(u_var[t, :, :], dtype=np.float32)
        v_data = np.array(v_var[t, :, :], dtype=np.float32)

        # Rotate only where HRRR data was used (hrrr_valid_mask)
        u_rot = np.where(hrrr_valid_mask,
                         cos_rot * u_data + sin_rot * v_data, u_data)
        v_rot = np.where(hrrr_valid_mask,
                         -sin_rot * u_data + cos_rot * v_data, v_data)

        u_var[t, :, :] = u_rot
        v_var[t, :, :] = v_rot
        n_rotated += 1

    print(f"  Rotated {n_rotated} blended timesteps ({n_times - n_rotated} GFS-only, skipped)")
    del cos_rot, sin_rot
    gc.collect()

ncout.close()
hrrr.close()
gfs.close()

print(f"\nOutput: {OUTPUT_FILE}")
print(f"Grid: {nx} x {ny}")
print(f"Time steps: {n_times} (hourly)")
if n_gfs_only > 0:
    print(f"  Blended (HRRR+GFS): {n_hrrr_covered} timesteps")
    print(f"  GFS-only extension: {n_gfs_only} timesteps")
print("SUCCESS!")
