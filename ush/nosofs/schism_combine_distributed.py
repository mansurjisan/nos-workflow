#!/usr/bin/env python3
"""
schism_combine_distributed.py — Combine distributed SCHISM old I/O to new I/O format.

UFS-Coastal SCHISM uses old I/O, writing one schout_RRRRRR_N.nc per MPI rank per
output stack. This script combines them into the new I/O format files (out2d_N.nc,
temperature_N.nc, etc.) that the post-processing combiner expects.

Requires local_to_global_* files for the local-to-global index mapping.

Usage:
    python3 schism_combine_distributed.py <outputs_dir> [<run_dir>]

    outputs_dir: Directory containing schout_*.nc files
    run_dir:     Directory containing local_to_global_* files (default: search
                 outputs_dir, then parent directory)
"""

import os
import sys
import glob
import re
import numpy as np
import netCDF4 as nc


# Variable name mapping: old I/O name -> (new I/O name, output file base)
# Handles both old naming (elev, temp, salt) and new naming (elevation, temperature, salinity)
VAR_MAP_2D = {
    'elevation': ('elevation', 'out2d'),
    'elev':      ('elevation', 'out2d'),
    'windSpeedX': ('windSpeedX', 'out2d'),
    'windSpeedY': ('windSpeedY', 'out2d'),
}

VAR_MAP_3D = {
    'temperature':    ('temperature',    'temperature'),
    'temp':           ('temperature',    'temperature'),
    'salinity':       ('salinity',       'salinity'),
    'salt':           ('salinity',       'salinity'),
    'horizontalVelX': ('horizontalVelX', 'horizontalVelX'),
    'horizontalVelY': ('horizontalVelY', 'horizontalVelY'),
    'zCoordinates':   ('zCoordinates',   'zCoordinates'),
    'zcor':           ('zCoordinates',   'zCoordinates'),
}

VAR_MAP_STATIC = {
    'depth':               ('depth',               'out2d'),
    'SCHISM_hgrid_node_x': ('SCHISM_hgrid_node_x', 'out2d'),
    'SCHISM_hgrid_node_y': ('SCHISM_hgrid_node_y', 'out2d'),
}


def detect_rank_format(search_dir):
    """Detect local_to_global rank number format (4 or 6 digits)."""
    if os.path.exists(os.path.join(search_dir, 'local_to_global_000000')):
        return 6
    elif os.path.exists(os.path.join(search_dir, 'local_to_global_0000')):
        return 4
    return None


def find_l2g_dir(outputs_dir, run_dir=None):
    """Find directory containing local_to_global files."""
    candidates = [outputs_dir]
    if run_dir:
        candidates.append(run_dir)
    candidates.append(os.path.dirname(outputs_dir))
    for d in candidates:
        if d and os.path.isdir(d) and detect_rank_format(d) is not None:
            return d
    return None


def read_global_info(l2g_dir, rank_fmt):
    """Read global dimensions from local_to_global_000000 header."""
    rank_str = f'{0:0{rank_fmt}d}'
    fname = os.path.join(l2g_dir, f'local_to_global_{rank_str}')
    info = list(map(int, open(fname).readline().strip().split()))
    # Header: ns_global, ne_global, np_global, nvrt, nproc, ntracers, [tracer_sizes...]
    ns, ne, np_global, nvrt, nproc = info[0], info[1], info[2], info[3], info[4]
    return ns, ne, np_global, nvrt, nproc


def read_local_to_global(l2g_dir, rank, rank_fmt):
    """Read local-to-global node and element mappings for a single rank.

    Returns (iplg, ielg) — 0-based global indices for local nodes/elements.
    """
    rank_str = f'{rank:0{rank_fmt}d}'
    fname = os.path.join(l2g_dir, f'local_to_global_{rank_str}')
    lines = open(fname).readlines()[2:]  # skip header + blank line

    ne_local = int(lines[0].strip())
    ielg = np.array(
        [int(line.strip().split()[1]) - 1 for line in lines[1:ne_local + 1]]
    )

    np_local = int(lines[ne_local + 1].strip())
    iplg = np.array(
        [int(line.strip().split()[1]) - 1
         for line in lines[ne_local + 2:ne_local + np_local + 2]]
    )

    return iplg, ielg


def detect_stacks(outputs_dir, rank_fmt):
    """Detect available output stacks from schout files of rank 0."""
    rank_str = f'{0:0{rank_fmt}d}'
    pattern = os.path.join(outputs_dir, f'schout_{rank_str}_*.nc')
    files = sorted(glob.glob(pattern))
    stacks = []
    for f in files:
        match = re.search(r'_(\d+)\.nc$', f)
        if match:
            stacks.append(int(match.group(1)))
    return sorted(stacks)


def classify_variables(ds):
    """Classify variables in a schout file into 2D, 3D, and static categories.

    Returns dict with keys:
        '2d':     {schout_varname: new_io_varname, ...}
        '3d':     {schout_varname: new_io_varname, ...}
        'static': {schout_varname: new_io_varname, ...}
        'hvel':   True if combined hvel variable exists (split to VelX/VelY)
    """
    result = {'2d': {}, '3d': {}, 'static': {}, 'hvel': False}

    for vname, var in ds.variables.items():
        dims = var.dimensions
        ndims = len(dims)

        # Check static variables (1D, no time dimension)
        if vname in VAR_MAP_STATIC and ndims == 1 and 'time' not in dims:
            new_name, _ = VAR_MAP_STATIC[vname]
            result['static'][vname] = new_name

        # Check 2D time-varying variables
        elif vname in VAR_MAP_2D and ndims == 2:
            new_name, _ = VAR_MAP_2D[vname]
            result['2d'][vname] = new_name

        # Check 3D time-varying variables
        elif vname in VAR_MAP_3D and ndims == 3:
            new_name, _ = VAR_MAP_3D[vname]
            result['3d'][vname] = new_name

        # Check combined horizontal velocity (old SCHISM: hvel [time, node, level, 2])
        elif vname == 'hvel' and ndims == 4:
            result['hvel'] = True

    return result


def combine_stack(outputs_dir, stack, nproc, np_global, nvrt, rank_fmt, mappings, var_cls):
    """Combine all ranks for one output stack into new I/O format files.

    Args:
        outputs_dir: Path to directory with schout_*.nc files
        stack: Output stack number (1, 2, ...)
        nproc: Number of MPI ranks
        np_global: Global node count
        nvrt: Number of vertical layers
        rank_fmt: Rank string width (4 or 6)
        mappings: Dict of rank -> (iplg, ielg) arrays
        var_cls: Variable classification from classify_variables()
    """
    print(f"\n  Stack {stack}:")

    # Read time values from rank 0
    rank0_str = f'{0:0{rank_fmt}d}'
    ds0 = nc.Dataset(os.path.join(outputs_dir, f'schout_{rank0_str}_{stack}.nc'))
    time_vals = ds0.variables['time'][:]
    nt = len(time_vals)
    ds0.close()
    print(f"    Timesteps: {nt}")

    # Allocate global arrays
    g2d = {new: np.full((nt, np_global), np.nan, dtype=np.float32)
           for new in var_cls['2d'].values()}
    g3d = {new: np.full((nt, np_global, nvrt), np.nan, dtype=np.float32)
           for new in var_cls['3d'].values()}
    gstat = {new: np.full(np_global, np.nan, dtype=np.float32)
             for new in var_cls['static'].values()}

    # Handle combined velocity
    if var_cls['hvel']:
        g3d['horizontalVelX'] = np.full((nt, np_global, nvrt), np.nan, dtype=np.float32)
        g3d['horizontalVelY'] = np.full((nt, np_global, nvrt), np.nan, dtype=np.float32)

    # Read and scatter from each rank
    for rank in range(nproc):
        if rank % 50 == 0:
            print(f"    Reading rank {rank}/{nproc}...")
        rank_str = f'{rank:0{rank_fmt}d}'
        fname = os.path.join(outputs_dir, f'schout_{rank_str}_{stack}.nc')

        if not os.path.exists(fname):
            print(f"    WARNING: Missing {fname}, skipping")
            continue

        iplg, _ = mappings[rank]
        ds = nc.Dataset(fname)

        # Scatter 2D variables
        for old_name, new_name in var_cls['2d'].items():
            if old_name in ds.variables:
                g2d[new_name][:, iplg] = ds.variables[old_name][:]

        # Scatter 3D variables
        for old_name, new_name in var_cls['3d'].items():
            if old_name in ds.variables:
                g3d[new_name][:, iplg, :] = ds.variables[old_name][:]

        # Scatter combined velocity
        if var_cls['hvel'] and 'hvel' in ds.variables:
            hvel = ds.variables['hvel'][:]
            g3d['horizontalVelX'][:, iplg, :] = hvel[:, :, :, 0]
            g3d['horizontalVelY'][:, iplg, :] = hvel[:, :, :, 1]

        # Scatter static variables
        for old_name, new_name in var_cls['static'].items():
            if old_name in ds.variables:
                gstat[new_name][iplg] = ds.variables[old_name][:]

        ds.close()

    # Write output files
    print(f"    Writing combined output files...")

    # out2d_N.nc
    _write_out2d(outputs_dir, stack, time_vals, g2d, gstat, np_global, nvrt)

    # 3D variable files
    for varname in ['temperature', 'salinity', 'horizontalVelX',
                    'horizontalVelY', 'zCoordinates']:
        if varname in g3d:
            _write_3d_var(outputs_dir, stack, varname, time_vals,
                          g3d[varname], np_global, nvrt)

    return nt


def _write_out2d(outputs_dir, stack, time_vals, g2d, gstat, np_global, nvrt):
    """Write out2d_N.nc in new I/O format."""
    fname = os.path.join(outputs_dir, f'out2d_{stack}.nc')
    ds = nc.Dataset(fname, 'w', format='NETCDF4')

    ds.createDimension('time', None)
    ds.createDimension('nSCHISM_hgrid_node', np_global)
    ds.createDimension('nSCHISM_vgrid_layers', nvrt)

    tv = ds.createVariable('time', 'f8', ('time',))
    tv[:] = time_vals

    for name in ['depth', 'SCHISM_hgrid_node_x', 'SCHISM_hgrid_node_y']:
        if name in gstat:
            v = ds.createVariable(name, 'f4', ('nSCHISM_hgrid_node',))
            v[:] = gstat[name]

    for name in ['elevation', 'windSpeedX', 'windSpeedY']:
        if name in g2d:
            v = ds.createVariable(name, 'f4', ('time', 'nSCHISM_hgrid_node'))
            v[:] = g2d[name]

    ds.close()
    print(f"      {fname}")


def _write_3d_var(outputs_dir, stack, varname, time_vals, data, np_global, nvrt):
    """Write a 3D variable file (e.g., temperature_N.nc) in new I/O format."""
    fname = os.path.join(outputs_dir, f'{varname}_{stack}.nc')
    ds = nc.Dataset(fname, 'w', format='NETCDF4')

    ds.createDimension('time', None)
    ds.createDimension('nSCHISM_hgrid_node', np_global)
    ds.createDimension('nSCHISM_vgrid_layers', nvrt)

    tv = ds.createVariable('time', 'f8', ('time',))
    tv[:] = time_vals

    v = ds.createVariable(varname, 'f4',
                          ('time', 'nSCHISM_hgrid_node', 'nSCHISM_vgrid_layers'))
    v[:] = data

    ds.close()
    print(f"      {fname}")


def main():
    if len(sys.argv) < 2:
        print("Usage: schism_combine_distributed.py <outputs_dir> [<run_dir>]")
        print()
        print("  outputs_dir: Directory with schout_RRRRRR_N.nc files")
        print("  run_dir:     Directory with local_to_global_* files (optional)")
        sys.exit(1)

    outputs_dir = os.path.abspath(sys.argv[1])
    run_dir = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None

    print("=" * 60)
    print("SCHISM Distributed Output Combiner (schout -> new I/O)")
    print("=" * 60)
    print(f"  outputs_dir: {outputs_dir}")
    if run_dir:
        print(f"  run_dir:     {run_dir}")

    # --- Locate local_to_global files ---
    l2g_dir = find_l2g_dir(outputs_dir, run_dir)
    if l2g_dir is None:
        print("ERROR: Cannot find local_to_global_* files in any of:")
        print(f"  {outputs_dir}")
        if run_dir:
            print(f"  {run_dir}")
        print(f"  {os.path.dirname(outputs_dir)}")
        sys.exit(1)

    rank_fmt = detect_rank_format(l2g_dir)
    print(f"  l2g dir:     {l2g_dir}")
    print(f"  Rank format: {rank_fmt}-digit")

    # --- Read global dimensions ---
    ns, ne, np_global, nvrt, nproc = read_global_info(l2g_dir, rank_fmt)
    print(f"  Global: {np_global} nodes, {ne} elements, {nvrt} layers, {nproc} ranks")

    # --- Detect output stacks ---
    stacks = detect_stacks(outputs_dir, rank_fmt)
    if not stacks:
        print("ERROR: No schout output stacks found (schout_*_*.nc)")
        sys.exit(1)
    print(f"  Output stacks: {stacks}")

    # --- Read all local-to-global mappings ---
    print(f"\n  Reading local-to-global mappings for {nproc} ranks...")
    mappings = {}
    for rank in range(nproc):
        iplg, ielg = read_local_to_global(l2g_dir, rank, rank_fmt)
        mappings[rank] = (iplg, ielg)
    print(f"  Done reading mappings")

    # --- Classify variables from rank 0 ---
    rank0_str = f'{0:0{rank_fmt}d}'
    ds0 = nc.Dataset(os.path.join(outputs_dir,
                                  f'schout_{rank0_str}_{stacks[0]}.nc'))
    var_cls = classify_variables(ds0)
    ds0.close()

    print(f"  2D variables: {list(var_cls['2d'].values())}")
    print(f"  3D variables: {list(var_cls['3d'].values())}")
    print(f"  Static:       {list(var_cls['static'].values())}")
    if var_cls['hvel']:
        print(f"  Combined hvel -> horizontalVelX, horizontalVelY")

    if not var_cls['2d'] and not var_cls['3d'] and not var_cls['hvel']:
        print("ERROR: No recognized output variables found in schout files")
        print("  Available variables:", list(ds0.variables.keys()))
        sys.exit(1)

    # --- Combine each stack ---
    total_timesteps = 0
    for stack in stacks:
        nt = combine_stack(outputs_dir, stack, nproc, np_global, nvrt,
                           rank_fmt, mappings, var_cls)
        total_timesteps += nt

    print(f"\n{'=' * 60}")
    print(f"SUCCESS: Combined {len(stacks)} stacks, {total_timesteps} timesteps")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
