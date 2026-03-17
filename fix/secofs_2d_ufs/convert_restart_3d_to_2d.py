#!/usr/bin/env python3
"""Convert 3D SCHISM restart (nvrt=63) to 2D barotropic (nvrt=3).

Copies 2D fields as-is (eta2, idry, cumsum_eta, time, etc.).
Slices 3D fields to nvrt=3: level 1 = dry fill (-9), level 2 = bottom,
level 3 = surface. Zeros out tracers and turbulence for barotropic.

Usage:
    python3 convert_restart_3d_to_2d.py <input_3d.nc> <output_2d.nc>
"""

import sys
import numpy as np
from netCDF4 import Dataset


def convert_restart(input_path, output_path, nvrt_2d=3):
    ds_in = Dataset(input_path, 'r')

    nvrt_3d = len(ds_in.dimensions['nVert'])
    n_node = len(ds_in.dimensions['node'])
    n_elem = len(ds_in.dimensions['elem'])
    n_side = len(ds_in.dimensions['side'])
    n_tracers = len(ds_in.dimensions['ntracers'])

    print(f"Input:  {input_path}")
    print(f"  nodes={n_node}, elems={n_elem}, sides={n_side}")
    print(f"  nvrt_3d={nvrt_3d}, ntracers={n_tracers}")
    print(f"Output: {output_path} (nvrt={nvrt_2d})")

    ds_out = Dataset(output_path, 'w', format='NETCDF4')

    # Create dimensions (replace nVert with nvrt_2d)
    for dname, dim in ds_in.dimensions.items():
        if dname == 'nVert':
            ds_out.createDimension(dname, nvrt_2d)
        else:
            ds_out.createDimension(dname, len(dim))

    # Process each variable
    for vname, var_in in ds_in.variables.items():
        dims = var_in.dimensions
        dtype = var_in.dtype

        # Create output variable with same dimensions
        var_out = ds_out.createVariable(vname, dtype, dims)

        # Copy attributes
        for attr in var_in.ncattrs():
            var_out.setncattr(attr, var_in.getncattr(attr))

        if 'nVert' not in dims:
            # 2D variable — copy directly
            var_out[:] = var_in[:]
            print(f"  {vname}: copied as-is {var_in.shape}")

        else:
            # 3D variable — slice to nvrt_2d levels
            data_3d = var_in[:]
            shape_3d = data_3d.shape
            vert_axis = list(dims).index('nVert')

            # Build 2D array: level 0 = dry fill, level 1 = bottom, level 2 = surface
            # Bottom = index 0 in 3D, Surface = index -1 in 3D
            if vname in ('tr_nd', 'tr_nd0', 'tr_el'):
                # Tracers: zero for barotropic (no T/S)
                new_shape = list(shape_3d)
                new_shape[vert_axis] = nvrt_2d
                data_2d = np.zeros(new_shape, dtype=np.float64)
                print(f"  {vname}: zeroed (barotropic, no tracers) {shape_3d} -> {tuple(new_shape)}")

            elif vname in ('q2', 'xl', 'dfv', 'dfh', 'dfq1', 'dfq2'):
                # Turbulence: zero for barotropic
                new_shape = list(shape_3d)
                new_shape[vert_axis] = nvrt_2d
                data_2d = np.zeros(new_shape, dtype=np.float64)
                print(f"  {vname}: zeroed (no turbulence in 2D) {shape_3d} -> {tuple(new_shape)}")

            elif vname == 'we':
                # Vertical velocity at elements: (elem, nVert) -> zero
                new_shape = list(shape_3d)
                new_shape[vert_axis] = nvrt_2d
                data_2d = np.zeros(new_shape, dtype=np.float64)
                print(f"  {vname}: zeroed (no vertical vel in 2D) {shape_3d} -> {tuple(new_shape)}")

            elif vname in ('su2', 'sv2'):
                # Horizontal velocity at sides: (side, nVert)
                # Level 0: dry fill, Level 1: depth-averaged (use bottom),
                # Level 2: depth-averaged (use surface)
                new_shape = list(shape_3d)
                new_shape[vert_axis] = nvrt_2d
                data_2d = np.zeros(new_shape, dtype=np.float64)
                # Use bottom (index 0) and surface (index -1) from 3D
                if vert_axis == 1:
                    data_2d[:, 1] = data_3d[:, 0]    # bottom
                    data_2d[:, 2] = data_3d[:, -1]   # surface
                print(f"  {vname}: bottom+surface extracted {shape_3d} -> {tuple(new_shape)}")

            else:
                # Unknown 3D variable: take bottom and surface
                new_shape = list(shape_3d)
                new_shape[vert_axis] = nvrt_2d
                data_2d = np.zeros(new_shape, dtype=np.float64)
                if vert_axis == 1:
                    data_2d[:, 1] = data_3d[:, 0]
                    data_2d[:, 2] = data_3d[:, -1]
                print(f"  {vname}: bottom+surface extracted {shape_3d} -> {tuple(new_shape)}")

            var_out[:] = data_2d

    ds_in.close()
    ds_out.close()

    import os
    in_size = os.path.getsize(input_path) / 1e9
    out_size = os.path.getsize(output_path) / 1e9
    print(f"\nDone: {in_size:.2f} GB -> {out_size:.2f} GB")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input_3d_restart.nc> <output_2d_restart.nc>")
        sys.exit(1)
    convert_restart(sys.argv[1], sys.argv[2])
