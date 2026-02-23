#!/usr/bin/env python3
"""
Modify HRRR NetCDF for ESMF Mesh Generation
Adapted from ERA5 workflow (modify_era5_4_esmfmesh2.py)

HRRR uses a Lambert Conformal projection (3km resolution over CONUS).
This script converts to lat/lon for ESMF mesh generation.

Usage:
    python modify_hrrr_4_esmfmesh.py hrrr.t06z.wrfsfcf00.nc hrrr_for_esmf.nc

Steps performed:
    1. Handle Lambert Conformal -> lat/lon coordinates
    2. Add required ESMF attributes
    3. Ensure CF-1.6 compliance

Author: Adapted for SECOFS UFS-Coastal transition
Date: January 2026
"""

import argparse
import numpy as np
from netCDF4 import Dataset
import os
import sys


def modify_hrrr_for_esmf(input_file, output_file, verbose=True):
    """
    Modify HRRR NetCDF file for ESMF mesh generation.

    HRRR files from wgrib2 may already have lat/lon as 2D arrays
    (since HRRR is on Lambert Conformal grid).

    Parameters
    ----------
    input_file : str
        Path to input HRRR NetCDF file
    output_file : str
        Path to output modified NetCDF file
    verbose : bool
        Print progress messages
    """

    if verbose:
        print(f"Reading: {input_file}")

    ds_in = Dataset(input_file, 'r')

    # HRRR coordinates from wgrib2 (typically 2D lat/lon arrays)
    # Common names: latitude, longitude or lat, lon or gridlat_0, gridlon_0
    lat_name = None
    lon_name = None
    time_name = None

    for var in ds_in.variables:
        var_lower = var.lower()
        if 'lat' in var_lower and lat_name is None:
            lat_name = var
        elif 'lon' in var_lower and lon_name is None:
            lon_name = var
        elif var_lower in ['time', 't']:
            time_name = var

    if lat_name is None or lon_name is None:
        # Try dimension names
        for dim in ds_in.dimensions:
            if 'lat' in dim.lower() or 'y' in dim.lower():
                lat_name = dim
            elif 'lon' in dim.lower() or 'x' in dim.lower():
                lon_name = dim

    if verbose:
        print(f"Found lat: {lat_name}, lon: {lon_name}, time: {time_name}")

    lat = ds_in.variables[lat_name][:]
    lon = ds_in.variables[lon_name][:]

    if verbose:
        print(f"Lat shape: {lat.shape}, Lon shape: {lon.shape}")

    # Determine if 1D or 2D coordinates
    is_2d_coords = len(lat.shape) == 2

    if is_2d_coords:
        nlat, nlon = lat.shape
        if verbose:
            print(f"HRRR has 2D coordinates (Lambert Conformal grid)")
            print(f"Grid size: {nlon} x {nlat}")
    else:
        nlat = len(lat)
        nlon = len(lon)
        if verbose:
            print(f"HRRR has 1D coordinates")
            print(f"Grid size: {nlon} x {nlat}")

    # Create output file
    if verbose:
        print(f"Creating: {output_file}")

    ds_out = Dataset(output_file, 'w', format='NETCDF4')

    # Global attributes
    ds_out.Conventions = 'CF-1.6'
    ds_out.title = 'HRRR 3km data prepared for ESMF mesh generation'
    ds_out.source = 'NOAA HRRR (High-Resolution Rapid Refresh)'
    ds_out.history = f'Modified by modify_hrrr_4_esmfmesh.py from {os.path.basename(input_file)}'
    ds_out.grid_type = 'Lambert Conformal Conic'

    # Create dimensions
    if is_2d_coords:
        ds_out.createDimension('x', nlon)
        ds_out.createDimension('y', nlat)
    else:
        ds_out.createDimension('lon', nlon)
        ds_out.createDimension('lat', nlat)

    if time_name is not None:
        time_in = ds_in.variables[time_name]
        ds_out.createDimension('time', None)

        time_out = ds_out.createVariable('time', 'f8', ('time',))
        time_out.units = getattr(time_in, 'units', 'hours since 1900-01-01 00:00:00')
        time_out.calendar = getattr(time_in, 'calendar', 'standard')
        time_out.axis = 'T'
        time_out.long_name = 'time'
        time_out[:] = time_in[:]

    if is_2d_coords:
        # For curvilinear grids, lat/lon are 2D
        lat_out = ds_out.createVariable('lat', 'f8', ('y', 'x'))
        lat_out.units = 'degrees_north'
        lat_out.long_name = 'latitude'
        lat_out.standard_name = 'latitude'
        lat_out[:] = lat[:]

        lon_out = ds_out.createVariable('lon', 'f8', ('y', 'x'))
        lon_out.units = 'degrees_east'
        lon_out.long_name = 'longitude'
        lon_out.standard_name = 'longitude'
        lon_out[:] = lon[:]

        # Also create 1D auxiliary coordinates for ESMF
        x_out = ds_out.createVariable('x', 'i4', ('x',))
        x_out.units = '1'
        x_out.long_name = 'x grid index'
        x_out[:] = np.arange(nlon)

        y_out = ds_out.createVariable('y', 'i4', ('y',))
        y_out.units = '1'
        y_out.long_name = 'y grid index'
        y_out[:] = np.arange(nlat)
    else:
        lon_out = ds_out.createVariable('lon', 'f8', ('lon',))
        lon_out.units = 'degrees_east'
        lon_out.axis = 'X'
        lon_out.long_name = 'longitude'
        lon_out.standard_name = 'longitude'
        lon_out[:] = lon[:]

        lat_out = ds_out.createVariable('lat', 'f8', ('lat',))
        lat_out.units = 'degrees_north'
        lat_out.axis = 'Y'
        lat_out.long_name = 'latitude'
        lat_out.standard_name = 'latitude'
        lat_out[:] = lat[:]

    # DATM variable mapping for HRRR
    datm_vars = {
        'TMP_2maboveground': {'datm_name': 'Sa_tbot', 'long_name': '2m temperature', 'units': 'K'},
        'SPFH_2maboveground': {'datm_name': 'Sa_shum', 'long_name': '2m specific humidity', 'units': 'kg/kg'},
        'PRES_surface': {'datm_name': 'Sa_pslv', 'long_name': 'surface pressure', 'units': 'Pa'},
        'UGRD_10maboveground': {'datm_name': 'Sa_u', 'long_name': '10m u-wind', 'units': 'm/s'},
        'VGRD_10maboveground': {'datm_name': 'Sa_v', 'long_name': '10m v-wind', 'units': 'm/s'},
        'DSWRF_surface': {'datm_name': 'Faxa_swdn', 'long_name': 'downward shortwave radiation', 'units': 'W/m2'},
        'DLWRF_surface': {'datm_name': 'Faxa_lwdn', 'long_name': 'downward longwave radiation', 'units': 'W/m2'},
        'PRATE_surface': {'datm_name': 'Faxa_rain', 'long_name': 'precipitation rate', 'units': 'kg/m2/s'},
    }

    # Copy data variables
    for varname in ds_in.variables:
        if varname in [lat_name, lon_name, time_name]:
            continue

        # Skip grid mapping variables
        if 'grid_mapping' in varname.lower() or 'projection' in varname.lower():
            continue

        # Skip x/y coordinate variables (already created)
        if varname in ['x', 'y']:
            continue

        var_in = ds_in.variables[varname]

        var_info = datm_vars.get(varname, None)

        # Determine dimensions
        dims_out = []
        for dim in var_in.dimensions:
            dim_lower = dim.lower()
            if dim == time_name or 'time' in dim_lower:
                dims_out.append('time')
            elif 'lat' in dim_lower or dim_lower == 'y' or dim_lower.startswith('ygrid'):
                dims_out.append('y' if is_2d_coords else 'lat')
            elif 'lon' in dim_lower or dim_lower == 'x' or dim_lower.startswith('xgrid'):
                dims_out.append('x' if is_2d_coords else 'lon')
            else:
                # Create dimension if it doesn't exist
                if dim not in ds_out.dimensions:
                    ds_out.createDimension(dim, ds_in.dimensions[dim].size)
                dims_out.append(dim)

        if verbose:
            print(f"  Copying: {varname} {dims_out}")

        var_out = ds_out.createVariable(varname, var_in.dtype, tuple(dims_out),
                                        fill_value=getattr(var_in, '_FillValue', None))

        for attr in var_in.ncattrs():
            if attr != '_FillValue':
                setattr(var_out, attr, getattr(var_in, attr))

        if var_info:
            var_out.long_name = var_info['long_name']
            var_out.units = var_info['units']

        var_out.coordinates = 'lon lat'
        var_out[:] = var_in[:]

    ds_in.close()
    ds_out.close()

    if verbose:
        print(f"Done! Output: {output_file}")
        if is_2d_coords:
            print(f"Note: HRRR has curvilinear grid - use ESMF_Scrip2Unstruct for mesh")


def main():
    parser = argparse.ArgumentParser(
        description='Modify HRRR NetCDF for ESMF mesh generation')
    parser.add_argument('input_file', help='Input HRRR NetCDF file')
    parser.add_argument('output_file', help='Output modified NetCDF file')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Suppress progress messages')

    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Error: Input file not found: {args.input_file}")
        sys.exit(1)

    modify_hrrr_for_esmf(args.input_file, args.output_file, verbose=not args.quiet)


if __name__ == '__main__':
    main()
