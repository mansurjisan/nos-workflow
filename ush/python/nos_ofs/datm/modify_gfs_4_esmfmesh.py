#!/usr/bin/env python3
"""
Modify GFS NetCDF for ESMF Mesh Generation
Adapted from ERA5 workflow (modify_era5_4_esmfmesh2.py)

This script prepares GFS 0.25-degree NetCDF files for ESMF mesh generation.

Usage:
    python modify_gfs_4_esmfmesh.py gfs.t06z.f000.nc gfs_for_esmf.nc

Steps performed:
    1. Rename lat/lon to match ESMF expectations
    2. Add required attributes (units, axis, bounds)
    3. Ensure CF-1.6 compliance
    4. Handle coordinate ordering (lat should be S->N for ESMF)

Author: Adapted for SECOFS UFS-Coastal transition
Date: January 2026
"""

import argparse
import numpy as np
from netCDF4 import Dataset
import os
import sys


def modify_gfs_for_esmf(input_file, output_file, verbose=True):
    """
    Modify GFS NetCDF file for ESMF mesh generation.

    Parameters
    ----------
    input_file : str
        Path to input GFS NetCDF file (from wgrib2 -netcdf conversion)
    output_file : str
        Path to output modified NetCDF file
    verbose : bool
        Print progress messages
    """

    if verbose:
        print(f"Reading: {input_file}")

    # Open input file
    ds_in = Dataset(input_file, 'r')

    # Get coordinate variable names (may vary based on wgrib2 version)
    coord_names = {
        'lon': None,
        'lat': None,
        'time': None
    }

    # Find coordinate variables
    for var in ds_in.variables:
        var_lower = var.lower()
        if var_lower in ['longitude', 'lon', 'x']:
            coord_names['lon'] = var
        elif var_lower in ['latitude', 'lat', 'y']:
            coord_names['lat'] = var
        elif var_lower in ['time', 't']:
            coord_names['time'] = var

    if verbose:
        print(f"Found coordinates: {coord_names}")

    # Read coordinates
    lon = ds_in.variables[coord_names['lon']][:]
    lat = ds_in.variables[coord_names['lat']][:]

    # Check if latitude needs to be flipped (should be S->N for ESMF)
    flip_lat = False
    if lat[0] > lat[-1]:
        flip_lat = True
        if verbose:
            print("Latitude is N->S, will flip to S->N")

    # Create output file
    if verbose:
        print(f"Creating: {output_file}")

    ds_out = Dataset(output_file, 'w', format='NETCDF4')

    # Add global attributes
    ds_out.Conventions = 'CF-1.6'
    ds_out.title = 'GFS 0.25-degree data prepared for ESMF mesh generation'
    ds_out.source = 'NCEP GFS'
    ds_out.history = f'Modified by modify_gfs_4_esmfmesh.py from {os.path.basename(input_file)}'

    # Create dimensions
    nlon = len(lon)
    nlat = len(lat)

    ds_out.createDimension('lon', nlon)
    ds_out.createDimension('lat', nlat)

    if coord_names['time'] is not None:
        time_in = ds_in.variables[coord_names['time']]
        ntime = len(time_in)
        ds_out.createDimension('time', None)  # Unlimited

        # Create time variable
        time_out = ds_out.createVariable('time', 'f8', ('time',))
        time_out.units = getattr(time_in, 'units', 'hours since 1900-01-01 00:00:00')
        time_out.calendar = getattr(time_in, 'calendar', 'standard')
        time_out.axis = 'T'
        time_out.long_name = 'time'
        time_out[:] = time_in[:]

    # Create longitude variable with ESMF-required attributes
    lon_out = ds_out.createVariable('lon', 'f8', ('lon',))
    lon_out.units = 'degrees_east'
    lon_out.axis = 'X'
    lon_out.long_name = 'longitude'
    lon_out.standard_name = 'longitude'
    lon_out[:] = lon[:]

    # Create latitude variable with ESMF-required attributes
    lat_out = ds_out.createVariable('lat', 'f8', ('lat',))
    lat_out.units = 'degrees_north'
    lat_out.axis = 'Y'
    lat_out.long_name = 'latitude'
    lat_out.standard_name = 'latitude'
    if flip_lat:
        lat_out[:] = lat[::-1]
    else:
        lat_out[:] = lat[:]

    # DATM variable mapping (GFS wgrib2 names -> DATM field names)
    # These are the variables DATM needs for atmospheric forcing
    datm_vars = {
        'TMP_2maboveground': {'datm_name': 'Sa_tbot', 'long_name': '2m temperature', 'units': 'K'},
        'SPFH_2maboveground': {'datm_name': 'Sa_shum', 'long_name': '2m specific humidity', 'units': 'kg/kg'},
        'PRES_surface': {'datm_name': 'Sa_pslv', 'long_name': 'surface pressure', 'units': 'Pa'},
        'PRMSL_meansealevel': {'datm_name': 'Sa_pslv', 'long_name': 'mean sea level pressure', 'units': 'Pa'},
        'UGRD_10maboveground': {'datm_name': 'Sa_u', 'long_name': '10m u-wind', 'units': 'm/s'},
        'VGRD_10maboveground': {'datm_name': 'Sa_v', 'long_name': '10m v-wind', 'units': 'm/s'},
        'DSWRF_surface': {'datm_name': 'Faxa_swdn', 'long_name': 'downward shortwave radiation', 'units': 'W/m2'},
        'DLWRF_surface': {'datm_name': 'Faxa_lwdn', 'long_name': 'downward longwave radiation', 'units': 'W/m2'},
        'PRATE_surface': {'datm_name': 'Faxa_rain', 'long_name': 'precipitation rate', 'units': 'kg/m2/s'},
    }

    # Copy data variables
    for varname in ds_in.variables:
        if varname in [coord_names['lon'], coord_names['lat'], coord_names['time']]:
            continue  # Skip coordinates

        var_in = ds_in.variables[varname]

        # Determine output variable name (keep original or use DATM name)
        if varname in datm_vars:
            out_varname = varname  # Keep original for now, DATM streams will map
            var_info = datm_vars[varname]
        else:
            out_varname = varname
            var_info = None

        # Determine dimensions
        dims_out = []
        for dim in var_in.dimensions:
            if dim == coord_names['time'] or dim.lower() == 'time':
                dims_out.append('time')
            elif dim == coord_names['lat'] or dim.lower() in ['lat', 'latitude', 'y']:
                dims_out.append('lat')
            elif dim == coord_names['lon'] or dim.lower() in ['lon', 'longitude', 'x']:
                dims_out.append('lon')
            else:
                dims_out.append(dim)

        if verbose:
            print(f"  Copying variable: {varname} -> {out_varname} {dims_out}")

        # Create output variable
        var_out = ds_out.createVariable(out_varname, var_in.dtype, tuple(dims_out),
                                        fill_value=getattr(var_in, '_FillValue', None))

        # Copy attributes
        for attr in var_in.ncattrs():
            if attr != '_FillValue':
                setattr(var_out, attr, getattr(var_in, attr))

        # Add/update attributes
        if var_info:
            var_out.long_name = var_info['long_name']
            var_out.units = var_info['units']

        # Add coordinates attribute (required by CF/ESMF)
        var_out.coordinates = 'lon lat'

        # Copy data (flip lat if needed)
        data = var_in[:]
        if flip_lat and 'lat' in dims_out:
            lat_idx = dims_out.index('lat')
            data = np.flip(data, axis=lat_idx)

        var_out[:] = data

    ds_in.close()
    ds_out.close()

    if verbose:
        print(f"Done! Output: {output_file}")
        print(f"Grid size: {nlon} x {nlat}")


def main():
    parser = argparse.ArgumentParser(
        description='Modify GFS NetCDF for ESMF mesh generation')
    parser.add_argument('input_file', help='Input GFS NetCDF file')
    parser.add_argument('output_file', help='Output modified NetCDF file')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Suppress progress messages')

    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Error: Input file not found: {args.input_file}")
        sys.exit(1)

    modify_gfs_for_esmf(args.input_file, args.output_file, verbose=not args.quiet)


if __name__ == '__main__':
    main()
