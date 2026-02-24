#!/usr/bin/env python3
"""
Blend HRRR and GFS forcing onto a common regular grid for CDEPS/DATM.

Both input files must already be on the same regular lat/lon grid
(regridded by wgrib2 during extraction). This script:
  - Uses HRRR data where available (CONUS coverage)
  - Fills gaps with GFS data (Caribbean, open ocean, Puerto Rico)
  - Applies smooth transition at HRRR boundary edges
  - Handles variable name differences (HRRR MSLMA -> PRMSL)
  - Writes CF/CDEPS-compliant output

Usage:
    python blend_hrrr_gfs.py HRRR_FILE GFS_FILE OUTPUT_FILE [--buffer DEGREES]

Arguments:
    HRRR_FILE   - HRRR forcing NetCDF (regridded to target grid)
    GFS_FILE    - GFS forcing NetCDF (regridded to target grid)
    OUTPUT_FILE - Blended output NetCDF
    --buffer    - Transition zone width in degrees (default: 0.5)

Requires: numpy, netCDF4 (no scipy needed since both files are same-grid)

Author: NOS-OFS Unified Workflow
Date: February 2026
"""

import argparse
import os
import sys
import numpy as np
from netCDF4 import Dataset


# Variable pairs: (GFS name, HRRR name, output name)
# GFS uses PRMSL, HRRR uses MSLMA for mean sea level pressure
VAR_PAIRS = [
    ('UGRD_10maboveground', 'UGRD_10maboveground', 'UGRD_10maboveground'),
    ('VGRD_10maboveground', 'VGRD_10maboveground', 'VGRD_10maboveground'),
    ('TMP_2maboveground',   'TMP_2maboveground',   'TMP_2maboveground'),
    ('SPFH_2maboveground',  'SPFH_2maboveground',  'SPFH_2maboveground'),
    ('PRMSL_meansealevel',  'MSLMA_meansealevel',   'PRMSL_meansealevel'),
    ('DSWRF_surface',       'DSWRF_surface',        'DSWRF_surface'),
    ('DLWRF_surface',       'DLWRF_surface',        'DLWRF_surface'),
    ('PRATE_surface',       'PRATE_surface',        'PRATE_surface'),
]


def create_blend_weights(hrrr_data_2d, buffer_pixels=20):
    """
    Create blending weight mask from HRRR valid data coverage.

    Parameters
    ----------
    hrrr_data_2d : numpy array
        A single 2D slice of HRRR data (lat x lon).
        Fill values / NaN indicate no HRRR coverage.
    buffer_pixels : int
        Number of grid cells for the smooth transition zone.

    Returns
    -------
    weights : numpy array (lat x lon)
        1.0 = use HRRR, 0.0 = use GFS, intermediate = blend
    """
    # Identify valid HRRR coverage
    valid = np.isfinite(hrrr_data_2d) & (np.abs(hrrr_data_2d) < 1e10)

    if not np.any(valid):
        return np.zeros_like(hrrr_data_2d, dtype=np.float32)

    if np.all(valid):
        return np.ones_like(hrrr_data_2d, dtype=np.float32)

    # Start with binary mask
    weights = valid.astype(np.float32)

    if buffer_pixels <= 0:
        return weights

    # Apply iterative box smoothing to create smooth transition
    # This erodes the HRRR edge and creates a gradient
    smoothed = weights.copy()
    for _ in range(buffer_pixels):
        padded = np.pad(smoothed, 1, mode='constant', constant_values=0)
        # 3x3 mean filter
        kernel_sum = (
            padded[:-2, :-2] + padded[:-2, 1:-1] + padded[:-2, 2:] +
            padded[1:-1, :-2] + padded[1:-1, 1:-1] + padded[1:-1, 2:] +
            padded[2:, :-2] + padded[2:, 1:-1] + padded[2:, 2:]
        )
        smoothed = kernel_sum / 9.0

    # Ensure core HRRR area stays at 1.0 (only smooth at boundaries)
    # Erode the valid mask by buffer_pixels to find the core
    core = valid.astype(np.float32)
    for _ in range(buffer_pixels):
        padded = np.pad(core, 1, mode='constant', constant_values=0)
        # Minimum filter (erosion)
        core = np.minimum(
            np.minimum(padded[:-2, :-2], padded[:-2, 1:-1]),
            np.minimum(padded[:-2, 2:],
            np.minimum(padded[1:-1, :-2], padded[1:-1, 1:-1]))
        )
        core = np.minimum(
            core,
            np.minimum(padded[1:-1, 2:],
            np.minimum(padded[2:, :-2],
            np.minimum(padded[2:, 1:-1], padded[2:, 2:])))
        )

    # Combine: core = 1.0, transition zone = smoothed, outside = 0.0
    weights = np.where(core > 0.5, 1.0, smoothed)
    weights = np.clip(weights, 0.0, 1.0)

    return weights


def blend_forcing(hrrr_file, gfs_file, output_file, buffer_deg=0.5):
    """
    Blend HRRR and GFS forcing files.

    Both files must be on the same regular lat/lon grid.

    Parameters
    ----------
    hrrr_file : str
        Path to regridded HRRR forcing NetCDF
    gfs_file : str
        Path to regridded GFS forcing NetCDF
    output_file : str
        Path to output blended NetCDF
    buffer_deg : float
        Transition zone width in degrees
    """
    print(f"Opening HRRR: {hrrr_file}")
    ds_hrrr = Dataset(hrrr_file, 'r')

    print(f"Opening GFS: {gfs_file}")
    ds_gfs = Dataset(gfs_file, 'r')

    # Find coordinate variables
    hrrr_coords = _find_coords(ds_hrrr)
    gfs_coords = _find_coords(ds_gfs)

    # Read coordinates
    lon = ds_gfs.variables[gfs_coords['lon']][:]
    lat = ds_gfs.variables[gfs_coords['lat']][:]
    time_gfs = ds_gfs.variables[gfs_coords['time']][:]

    print(f"Grid: {len(lon)} x {len(lat)} (lon x lat)")
    print(f"Time steps GFS: {len(time_gfs)}")

    # Determine buffer in pixels
    if len(lon) > 1:
        dx = abs(float(lon[1] - lon[0]))
        buffer_pixels = max(1, int(buffer_deg / dx))
    else:
        buffer_pixels = 10
    print(f"Transition buffer: {buffer_deg} deg = {buffer_pixels} pixels")

    # Check time alignment
    time_hrrr = ds_hrrr.variables[hrrr_coords['time']][:]
    nt_gfs = len(time_gfs)
    nt_hrrr = len(time_hrrr)

    if nt_gfs != nt_hrrr:
        print(f"WARNING: Time dimension mismatch: GFS={nt_gfs}, HRRR={nt_hrrr}")
        print(f"Using minimum: {min(nt_gfs, nt_hrrr)} time steps")
    nt = min(nt_gfs, nt_hrrr)

    # Create output file
    print(f"Creating output: {output_file}")
    ds_out = Dataset(output_file, 'w', format='NETCDF4')

    # Global attributes
    ds_out.Conventions = 'CF-1.6'
    ds_out.title = 'Blended HRRR+GFS forcing for UFS-Coastal DATM'
    ds_out.source = 'NCEP HRRR (CONUS 3km) + GFS (global 0.25deg)'
    ds_out.institution = 'NOAA/NOS/OCS'
    ds_out.history = f'Blended by blend_hrrr_gfs.py'
    ds_out.blend_method = ('HRRR where available over CONUS, '
                           'GFS elsewhere, smooth transition at boundary')
    ds_out.blend_buffer_deg = buffer_deg

    # Create dimensions
    ds_out.createDimension('longitude', len(lon))
    ds_out.createDimension('latitude', len(lat))
    ds_out.createDimension('time', None)

    # Create coordinate variables
    lon_out = ds_out.createVariable('longitude', 'f8', ('longitude',))
    lon_out.units = 'degrees_east'
    lon_out.axis = 'X'
    lon_out.long_name = 'longitude'
    lon_out.standard_name = 'longitude'
    lon_out[:] = lon[:]

    lat_out = ds_out.createVariable('latitude', 'f8', ('latitude',))
    lat_out.units = 'degrees_north'
    lat_out.axis = 'Y'
    lat_out.long_name = 'latitude'
    lat_out.standard_name = 'latitude'
    lat_out[:] = lat[:]

    # Copy time from GFS (reference source)
    time_var = ds_gfs.variables[gfs_coords['time']]
    time_out = ds_out.createVariable('time', 'f8', ('time',))
    time_out.units = getattr(time_var, 'units', 'seconds since 1970-01-01 00:00:00')
    time_out.calendar = getattr(time_var, 'calendar', 'standard')
    time_out.axis = 'T'
    time_out.long_name = 'time'
    time_out[:nt] = time_gfs[:nt]

    # Compute blend weights from first valid HRRR timestep
    weights = None

    # Blend each variable pair
    blend_stats = {}
    for gfs_name, hrrr_name, out_name in VAR_PAIRS:
        # Check if variables exist in both files
        if gfs_name not in ds_gfs.variables:
            print(f"  SKIP: {gfs_name} not in GFS file")
            continue

        if hrrr_name not in ds_hrrr.variables:
            print(f"  WARNING: {hrrr_name} not in HRRR file, using GFS only for {out_name}")
            # Copy GFS data directly
            gfs_data = ds_gfs.variables[gfs_name][:nt]
            var_out = ds_out.createVariable(
                out_name, 'f4', ('time', 'latitude', 'longitude'),
                fill_value=9.999e+20
            )
            var_out.long_name = getattr(ds_gfs.variables[gfs_name], 'long_name', out_name)
            var_out.units = getattr(ds_gfs.variables[gfs_name], 'units', 'unknown')
            var_out.coordinates = 'longitude latitude'
            var_out[:] = gfs_data
            blend_stats[out_name] = 'GFS-only'
            continue

        print(f"  Blending: {gfs_name} + {hrrr_name} -> {out_name}")

        gfs_data = ds_gfs.variables[gfs_name][:nt]
        hrrr_data = ds_hrrr.variables[hrrr_name][:nt]

        # Compute blend weights once (from first timestep of first variable)
        if weights is None:
            weights = create_blend_weights(hrrr_data[0], buffer_pixels)
            hrrr_pct = np.mean(weights > 0.5) * 100
            gfs_pct = np.mean(weights < 0.5) * 100
            trans_pct = 100 - hrrr_pct - gfs_pct
            print(f"  Blend weights: HRRR={hrrr_pct:.1f}%, GFS={gfs_pct:.1f}%, "
                  f"transition={trans_pct:.1f}%")

        # Apply blending: out = weight * hrrr + (1-weight) * gfs
        # Where HRRR has fill values, weight=0 so we get pure GFS
        blended = np.zeros_like(gfs_data, dtype=np.float32)
        for t in range(nt):
            hrrr_slice = hrrr_data[t]
            gfs_slice = gfs_data[t]

            # Replace HRRR fill values with GFS values before blending
            hrrr_valid = np.isfinite(hrrr_slice) & (np.abs(hrrr_slice) < 1e10)
            hrrr_filled = np.where(hrrr_valid, hrrr_slice, gfs_slice)

            blended[t] = weights * hrrr_filled + (1.0 - weights) * gfs_slice

        # Create output variable
        var_out = ds_out.createVariable(
            out_name, 'f4', ('time', 'latitude', 'longitude'),
            fill_value=9.999e+20
        )
        var_out.long_name = getattr(ds_gfs.variables[gfs_name], 'long_name', out_name)
        var_out.units = getattr(ds_gfs.variables[gfs_name], 'units', 'unknown')
        var_out.coordinates = 'longitude latitude'
        var_out[:] = blended
        blend_stats[out_name] = 'blended'

    ds_hrrr.close()
    ds_gfs.close()
    ds_out.close()

    # Summary
    print()
    print("=" * 50)
    print("Blending complete!")
    print("=" * 50)
    print(f"Output: {output_file}")
    print(f"Size: {os.path.getsize(output_file) / 1e6:.1f} MB")
    print(f"Grid: {len(lon)} x {len(lat)}")
    print(f"Time steps: {nt}")
    print(f"Variables:")
    for name, status in blend_stats.items():
        print(f"  {name}: {status}")
    print("=" * 50)


def _find_coords(ds):
    """Find coordinate variable names in a NetCDF dataset."""
    coords = {'lon': None, 'lat': None, 'time': None}
    for var in ds.variables:
        vl = var.lower()
        if vl in ('longitude', 'lon', 'x') and coords['lon'] is None:
            coords['lon'] = var
        elif vl in ('latitude', 'lat', 'y') and coords['lat'] is None:
            coords['lat'] = var
        elif vl in ('time', 't') and coords['time'] is None:
            coords['time'] = var
    return coords


def main():
    parser = argparse.ArgumentParser(
        description='Blend HRRR and GFS forcing for UFS-Coastal DATM')
    parser.add_argument('hrrr_file', help='HRRR forcing NetCDF (regridded)')
    parser.add_argument('gfs_file', help='GFS forcing NetCDF (regridded)')
    parser.add_argument('output_file', help='Output blended NetCDF')
    parser.add_argument('--buffer', type=float, default=0.5,
                        help='Transition zone width in degrees (default: 0.5)')

    args = parser.parse_args()

    for f in [args.hrrr_file, args.gfs_file]:
        if not os.path.exists(f):
            print(f"Error: File not found: {f}")
            sys.exit(1)

    blend_forcing(args.hrrr_file, args.gfs_file, args.output_file,
                  buffer_deg=args.buffer)


if __name__ == '__main__':
    main()
