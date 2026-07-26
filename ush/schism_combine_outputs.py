#!/usr/bin/env python3
"""
schism_combine_outputs.py — Combine distributed SCHISM outputs into CO-OPS standard NetCDF products.

Parameterized version of schism_fields_station_redo.py from nosofs.v3.7.0.
Reads grid dimensions dynamically from output files instead of hardcoding them.

Reads control file: schism_standard_output.ctl (5 lines)
  Line 1: PREFIXNOS (e.g., secofs)
  Line 2: cyc (e.g., 00)
  Line 3: PDY (e.g., 20260228)
  Line 4: mode ("n" for nowcast, "f" for forecast)
  Line 5: timestart (e.g., 2026022806)

Products:
  - Per-timestep field files: {prefix}.t{cyc}z.{PDY}.fields.{n|f}{NNN}.nc
  - Station timeseries: {prefix}.t{cyc}z.{PDY}.stations.{nowcast|forecast}.nc
  - Renamed raw outputs: {prefix}.t{cyc}z.{PDY}.out2d_1.{stage}.nc, etc.

Usage:
  cd $DATA/outputs
  python schism_combine_outputs.py
"""

import shutil
import netCDF4 as nc
from netCDF4 import Dataset
import subprocess
import os
import sys
import glob
import numpy as np


def read_hgrid_gr3(prefixnos):
    """Read node coordinates and depth from hgrid.gr3.

    Searches for {prefixnos}.hgrid.gr3 or hgrid.gr3 in current directory.
    Returns (x, y, depth) as float32 arrays, or (None, None, None).
    """
    candidates = [f"{prefixnos}.hgrid.gr3", "hgrid.gr3"]
    # Also try any *.hgrid.gr3
    candidates.extend(glob.glob("*.hgrid.gr3"))

    hgrid_path = None
    for c in candidates:
        if os.path.exists(c):
            hgrid_path = c
            break

    if hgrid_path is None:
        return None, None, None

    print(f"  Reading static grid from: {hgrid_path}")
    with open(hgrid_path, 'r') as f:
        f.readline()  # comment
        ne, np_global = map(int, f.readline().split())
        x = np.empty(np_global, dtype=np.float64)
        y = np.empty(np_global, dtype=np.float64)
        depth = np.empty(np_global, dtype=np.float64)
        for i in range(np_global):
            parts = f.readline().split()
            x[i] = float(parts[1])
            y[i] = float(parts[2])
            depth[i] = float(parts[3])

    return x.astype(np.float32), y.astype(np.float32), depth.astype(np.float32)


def read_control_file(cfile="schism_standard_output.ctl"):
    """Read the 5-line control file."""
    with open(cfile, 'r') as f:
        lines = [line.strip() for line in f.readlines()]
    if len(lines) < 5:
        print(f"ERROR: Control file {cfile} must have 5 lines, got {len(lines)}")
        sys.exit(1)
    return {
        'PREFIXNOS': lines[0],
        'cyc': lines[1],
        'PDY': lines[2],
        'mode': lines[3],
        'timestart': lines[4],
    }


def get_grid_dimensions(prefixnos, fields_available=True):
    """Read grid dimensions dynamically from output files and FIX files.

    If fields_available=False, skip reading out2d_1.nc and nv.nc (needed
    only for field file creation). Station processing needs only station
    count and sigma levels from FIX files.
    """
    n_nodes = 0
    n_elements = 0
    nv = None

    if fields_available:
        # Node and element counts from out2d_1.nc
        ds = nc.Dataset("out2d_1.nc")
        n_nodes = len(ds.dimensions['nSCHISM_hgrid_node'])
        ds.close()

        # Element count from nv.nc
        nvfile = f"{prefixnos}.nv.nc"
        ds_nv = nc.Dataset(nvfile)
        nv = ds_nv.variables["nv"][:]
        n_elements = nv.shape[1]  # nv is (nface, nele)
        ds_nv.close()

    # Station count from station.lat.lon
    sta_file = f"{prefixnos}.station.lat.lon"
    with open(sta_file, 'r') as f:
        n_stations = sum(1 for line in f if line.strip())

    # Sigma levels from sigma.dat
    sigma_file = f"{prefixnos}.sigma.dat"
    if os.path.exists(sigma_file) and os.path.getsize(sigma_file) > 0:
        sigma_data = np.loadtxt(sigma_file, dtype=float)
        sigma = sigma_data.T
        n_levels = sigma.shape[1] if sigma.ndim == 2 else len(sigma)
    else:
        # No sigma.dat — detect levels from staout_5 format
        # For 2D barotropic (nvrt=3), 3D staout files have alternating lines:
        #   odd line: time + nsta*nvrt values
        #   even line: nsta*nvrt values
        # For pure 2D (nvrt=1 or no 3D output), fall back to 1 level
        n_levels = 1
        if os.path.exists("staout_5") and os.path.getsize("staout_5") > 0:
            with open("staout_5", 'r') as f:
                line1 = f.readline().strip().split()
                line2 = f.readline().strip().split()
            # line1 has time + data, line2 has data only
            # For 3D staout: ncols_line2 = nsta * 2 * nvrt
            ncols = len(line2)
            if ncols > 0 and n_stations > 0:
                nsta2 = n_stations * 2
                n_levels = max(1, ncols // nsta2)
        print(f"  No sigma.dat found, detected n_levels={n_levels} from staout_5")
        # Create uniform sigma for NetCDF output
        sigma = np.linspace(-1, 0, n_levels).reshape(1, -1)
        sigma = np.tile(sigma, (n_stations, 1)) if n_stations > 0 else sigma

    return {
        'n_nodes': n_nodes,
        'n_elements': n_elements,
        'n_stations': n_stations,
        'n_levels': n_levels,
        'nv': nv,
        'sigma': sigma,
    }


def process_field_files(ctl, dims):
    """Create per-timestep field files from distributed SCHISM outputs."""
    PREFIXNOS = ctl['PREFIXNOS']
    cyc = ctl['cyc']
    day = ctl['PDY']
    mode = ctl['mode']
    ts = ctl['timestart']
    yyyy, mm, dd, hh = ts[0:4], ts[4:6], ts[6:8], ts[8:10]

    n_nodes = dims['n_nodes']
    n_elements = dims['n_elements']
    n_levels = dims['n_levels']
    nv1 = dims['nv']
    sigma1 = dims['sigma']

    # Rename raw files for nowcast (only on first file iteration)
    nowcast_renamed = False

    for i in range(1, 999):  # iterate over output file groups
        file2d = f"out2d_{i}.nc"
        filetemp = f"temperature_{i}.nc"
        filesalt = f"salinity_{i}.nc"
        fileu = f"horizontalVelX_{i}.nc"
        filev = f"horizontalVelY_{i}.nc"

        if not os.path.exists(file2d):
            break

        print(f"Processing output group {i}: {file2d}")

        ds_grid = nc.Dataset(file2d)
        ds_temp = nc.Dataset(filetemp)
        ds_salt = nc.Dataset(filesalt)
        ds_u = nc.Dataset(fileu)
        ds_v = nc.Dataset(filev)

        time1 = ds_grid.variables["time"][:]
        zeta1 = ds_grid.variables["elevation"][:]
        nstep = len(time1)

        # Static variables: try out2d first, fall back to hgrid.gr3
        if "depth" in ds_grid.variables:
            h1 = ds_grid.variables["depth"][:]
            lon1 = ds_grid.variables["SCHISM_hgrid_node_x"][:]
            lat1 = ds_grid.variables["SCHISM_hgrid_node_y"][:]
        else:
            if i == 1:
                print("  depth/coordinates not in out2d, reading from hgrid.gr3...")
            hlon, hlat, hdepth = read_hgrid_gr3(PREFIXNOS)
            if hdepth is None:
                print("ERROR: No depth in out2d and no hgrid.gr3 found")
                sys.exit(1)
            lon1, lat1, h1 = hlon, hlat, hdepth

        # Wind variables: optional (may not exist in UFS-Coastal outputs)
        if "windSpeedX" in ds_grid.variables:
            uwind1 = ds_grid.variables["windSpeedX"][:]
            vwind1 = ds_grid.variables["windSpeedY"][:]
        else:
            uwind1 = np.zeros((nstep, n_nodes), dtype=np.float32)
            vwind1 = np.zeros((nstep, n_nodes), dtype=np.float32)
            if i == 1:
                print("  WARNING: windSpeedX/Y not in out2d, using zeros")

        temp1 = ds_temp.variables["temperature"][:]
        salt1 = ds_salt.variables["salinity"][:]
        u1 = ds_u.variables["horizontalVelX"][:]
        v1 = ds_v.variables["horizontalVelY"][:]

        # Rename raw files for nowcast (first iteration only)
        if mode == "n" and not nowcast_renamed:
            modefull = "nowcast"
            for raw_name, var_name in [
                ("out2d_1.nc", "out2d_1"),
                ("zCoordinates_1.nc", "zCoordinates_1"),
                ("temperature_1.nc", "temperature_1"),
                ("salinity_1.nc", "salinity_1"),
                ("horizontalVelX_1.nc", "horizontalVelX_1"),
                ("horizontalVelY_1.nc", "horizontalVelY_1"),
            ]:
                if os.path.exists(raw_name):
                    dest = f"{PREFIXNOS}.t{cyc}z.{day}.{var_name}.{modefull}.nc"
                    shutil.copyfile(raw_name, dest)
                    print(f"  Renamed: {raw_name} -> {dest}")

            for k in range(1, 9):
                src = f"staout_{k}"
                if os.path.exists(src):
                    dest = f"{PREFIXNOS}.t{cyc}z.{day}.{modefull}.staout_{k}"
                    shutil.copyfile(src, dest)
            nowcast_renamed = True

        # Create per-timestep field files
        for k in range(nstep):
            iii = (i - 1) * nstep + k + 1
            kkk = f"{iii:03d}"

            nfields_tmp = f"{PREFIXNOS}.t{cyc}z.{day}.fields.{mode}{kkk}.nc.old"
            nfields_out = f"{PREFIXNOS}.t{cyc}z.{day}.fields.{mode}{kkk}.nc"

            print(f"  Creating field file: {nfields_out}")

            ncfile = Dataset(nfields_tmp, mode='w', format='NETCDF4_CLASSIC')

            ncfile.createDimension('node', n_nodes)
            ncfile.createDimension('nele', n_elements)
            ncfile.createDimension('nface', 3)
            ncfile.createDimension('nv', n_levels)
            ncfile.createDimension('time', None)

            lon_var = ncfile.createVariable('lon', np.float32, ('node',))
            lat_var = ncfile.createVariable('lat', np.float32, ('node',))
            time_var = ncfile.createVariable('time', np.float32, ('time',))
            time_var.units = f"seconds since {yyyy}-{mm}-{dd} {hh}:00:00"

            ele_var = ncfile.createVariable('ele', 'i4', ('nface', 'nele'))
            h_var = ncfile.createVariable('h', np.float32, ('node',))

            zeta_var = ncfile.createVariable('zeta', np.float32, ('time', 'node'))
            uwind_var = ncfile.createVariable('uwind_speed', np.float32, ('time', 'node'))
            vwind_var = ncfile.createVariable('Vwind_speed', np.float32, ('time', 'node'))

            temp_var = ncfile.createVariable('temp', np.float32, ('time', 'nv', 'node'))
            salt_var = ncfile.createVariable('salinity', np.float32, ('time', 'nv', 'node'))
            u_var = ncfile.createVariable('u', np.float32, ('time', 'nv', 'node'))
            v_var = ncfile.createVariable('v', np.float32, ('time', 'nv', 'node'))
            sigma_var = ncfile.createVariable('sigma', np.float32, ('node', 'nv'))

            h_var[:] = h1[:]
            lon_var[:] = lon1[:]
            lat_var[:] = lat1[:]
            ele_var[:, :] = nv1[:, :]
            sigma_var[:, :] = sigma1[:, :]

            time_var[:] = time1[k]
            zeta_var[0, :] = zeta1[k, :]
            uwind_var[0, :] = uwind1[k, :]
            vwind_var[0, :] = vwind1[k, :]

            temp_var[0, :, :] = temp1[k, :, :].T
            salt_var[0, :, :] = salt1[k, :, :].T
            u_var[0, :, :] = u1[k, :, :].T
            v_var[0, :, :] = v1[k, :, :].T

            ncfile.close()

            # Compress with ncks
            try:
                subprocess.check_call(["ncks", "-4", "-L", "4", nfields_tmp, nfields_out])
                os.remove(nfields_tmp)
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print(f"  WARNING: ncks compression failed ({e}), using uncompressed file")
                if not os.path.exists(nfields_out):
                    os.rename(nfields_tmp, nfields_out)

        ds_grid.close()
        ds_temp.close()
        ds_salt.close()
        ds_u.close()
        ds_v.close()


def process_station_files(ctl, dims):
    """Create station timeseries NetCDF from staout text files."""
    PREFIXNOS = ctl['PREFIXNOS']
    cyc = ctl['cyc']
    day = ctl['PDY']
    mode = ctl['mode']
    ts = ctl['timestart']
    yyyy, mm, dd, hh = ts[0:4], ts[4:6], ts[6:8], ts[8:10]

    nsta = dims['n_stations']
    nver = dims['n_levels']
    nsta2 = nsta * 2

    # Read 2D station outputs (elevation, wind u, wind v)
    ele_values = None
    uwind_values = None
    vwind_values = None
    time_values = None

    for ind in [1, 3, 4]:
        file_name = f"staout_{ind}"
        if not os.path.exists(file_name):
            print(f"WARNING: {file_name} not found, skipping")
            continue

        all_numbers = []
        with open(file_name, 'r') as f:
            for line in f:
                numbers = [float(x) for x in line.strip().split()]
                all_numbers.append(numbers)

        arr = np.array(all_numbers)
        time_values = arr[:, 0]

        if ind == 1:
            ele_values = arr[:, 1:nsta + 1]
        elif ind == 3:
            uwind_values = arr[:, 1:nsta + 1]
        elif ind == 4:
            vwind_values = arr[:, 1:nsta + 1]

    if time_values is None:
        print("ERROR: No 2D staout files found, cannot create station file")
        return

    # Read 3D station outputs (temp, salt, u, v)
    # These files have alternating lines: odd=header, even=data
    temp_final = None
    salt_final = None
    u_final = None
    v_final = None

    for ind in [5, 6, 7, 8]:
        file_name = f"staout_{ind}"
        if not os.path.exists(file_name):
            print(f"WARNING: {file_name} not found, skipping 3D variable")
            continue

        # Skip empty files (barotropic 2D runs write empty staout_5-9)
        if os.path.getsize(file_name) == 0:
            print(f"WARNING: {file_name} is empty, skipping 3D variable")
            continue

        def _parse_fortran_float(s):
            """Parse Fortran-style floats like '-0.281012-220' (missing 'E')."""
            try:
                return float(s)
            except ValueError:
                # Insert 'E' before the last sign: '-0.281012-220' → '-0.281012E-220'
                for i in range(len(s) - 1, 0, -1):
                    if s[i] in '+-' and s[i-1] not in 'eEdD':
                        return float(s[:i] + 'E' + s[i:])
                return 0.0  # fallback

        all_numbers = []
        nline = 0
        with open(file_name, 'r') as f:
            for line in f:
                nline += 1
                if nline % 2 == 0:
                    numbers = [_parse_fortran_float(x) for x in line.strip().split()]
                    all_numbers.append(numbers)

        arr = np.array(all_numbers)
        nstep = len(arr)

        data0 = arr[:, 1:]
        data_reshaped = data0.reshape(nstep, nsta2, nver)
        data_real = data_reshaped[:, 0:nsta, :]
        data_final = np.swapaxes(data_real, 1, 2)

        if ind == 5:
            temp_final = data_final
        elif ind == 6:
            salt_final = data_final
        elif ind == 7:
            u_final = data_final
        elif ind == 8:
            v_final = data_final

    nstep = len(time_values)

    # Determine mode full name
    modefull = "nowcast" if mode == "n" else "forecast"

    # Read station locations
    sta_file = f"{PREFIXNOS}.station.lat.lon"
    all_from_file = []
    with open(sta_file, 'r') as f:
        for line in f:
            if line.strip():
                all_from_file.append(line.strip().split())

    sta_arr = np.array(all_from_file)

    # Create station NetCDF
    filesta = f"{PREFIXNOS}.t{cyc}z.{day}.stations.{modefull}.nc"
    print(f"Creating station file: {filesta}")

    name_length = 20
    ncfile = Dataset(filesta, mode='w', format='NETCDF4')

    ncfile.createDimension('station', nsta)
    ncfile.createDimension('clen', name_length)
    ncfile.createDimension('time', nstep)
    ncfile.createDimension('siglay', nver)
    ncfile.createDimension('num_entries', nsta)

    time_var = ncfile.createVariable('time', np.float32, ('time',))
    time_var.units = f"seconds since {yyyy}-{mm}-{dd} {hh}:00:00"

    lon_var = ncfile.createVariable('lon', np.float32, ('station',))
    lat_var = ncfile.createVariable('lat', np.float32, ('station',))

    name_station_var = ncfile.createVariable('name_station', 'S1', ('station', 'clen'))

    zeta_var = ncfile.createVariable('zeta', np.float32, ('time', 'station'))
    uwind_var = ncfile.createVariable('uwind_speed', np.float32, ('time', 'station'))
    vwind_var = ncfile.createVariable('vwind_speed', np.float32, ('time', 'station'))

    temp_var = ncfile.createVariable('temp', np.float32, ('time', 'siglay', 'station'))
    salt_var = ncfile.createVariable('salinity', np.float32, ('time', 'siglay', 'station'))
    u_var = ncfile.createVariable('u', np.float32, ('time', 'siglay', 'station'))
    v_var = ncfile.createVariable('v', np.float32, ('time', 'siglay', 'station'))

    # Station names
    station_names = [f'station_{PREFIXNOS}_{i+1:05d}' for i in range(nsta)]
    names_char_array = nc.stringtochar(np.array(station_names, dtype=f'S{name_length}'))
    name_station_var[:] = names_char_array

    # Station coordinates
    lon_var[:] = sta_arr[:, 1].astype(float)
    lat_var[:] = sta_arr[:, 2].astype(float)

    # Time and 2D variables
    time_var[:] = time_values[:]
    if ele_values is not None:
        zeta_var[:, :] = ele_values[:, :]
    if uwind_values is not None:
        uwind_var[:, :] = uwind_values[:, :]
    if vwind_values is not None:
        vwind_var[:, :] = vwind_values[:, :]

    # 3D variables
    if temp_final is not None:
        temp_var[:, :, :] = temp_final[:, :, :]
    if salt_final is not None:
        salt_var[:, :, :] = salt_final[:, :, :]
    if u_final is not None:
        u_var[:, :, :] = u_final[:, :, :]
    if v_final is not None:
        v_var[:, :, :] = v_final[:, :, :]

    ncfile.close()
    print(f"Station file created: {filesta} ({nsta} stations, {nstep} timesteps, {nver} levels)")


def convert_schout_to_split():
    """Convert combined schout_*.nc files to split format (out2d, temperature, etc.).

    SCHISM combined output (schout_*.nc) contains all variables in one file.
    This extracts them into the split format that process_field_files() expects:
      - out2d_{i}.nc:           elevation, windSpeedX/Y, depth, coordinates
      - temperature_{i}.nc:    temperature
      - salinity_{i}.nc:       salinity
      - horizontalVelX_{i}.nc: horizontalVelX
      - horizontalVelY_{i}.nc: horizontalVelY
    """
    # Variable name mapping: schout name -> (split file prefix, split var name)
    VAR_2D = {
        'elev': ('elevation', 'out2d'),
        'windSpeedX': ('windSpeedX', 'out2d'),
        'windSpeedY': ('windSpeedY', 'out2d'),
    }
    VAR_3D = {
        'temp': ('temperature', 'temperature'),
        'salt': ('salinity', 'salinity'),
        'zcor': ('zCoordinates', 'zCoordinates'),
        'horizontalVelX': ('horizontalVelX', 'horizontalVelX'),
        'horizontalVelY': ('horizontalVelY', 'horizontalVelY'),
    }
    # OLDIO combined schout stores vectors with a size-2 component axis:
    # hvel (3D velocity) and wind_speed (2D wind). Scribe-shaped output
    # wants per-component files/vars instead.
    VECTOR_3D = {
        'hvel': ('horizontalVelX', 'horizontalVelY'),
    }
    VECTOR_2D = {
        'wind_speed': ('windSpeedX', 'windSpeedY'),
    }
    # Variables that are consumed elsewhere or deliberately not split.
    KNOWN_STATIC = {
        'time', 'elev', 'elevation', 'depth',
        'SCHISM_hgrid_node_x', 'SCHISM_hgrid_node_y',
        'SCHISM_hgrid', 'SCHISM_hgrid_face_nodes', 'SCHISM_hgrid_edge_nodes',
        'SCHISM_hgrid_face_x', 'SCHISM_hgrid_face_y',
        'SCHISM_hgrid_edge_x', 'SCHISM_hgrid_edge_y',
        'node_bottom_index', 'bottom_index_node',
        'ele_bottom_index', 'edge_bottom_index',
        'sigma', 'Cs', 'coordinate_system_flag', 'minimum_depth',
        'sigma_h_c', 'sigma_theta_b', 'sigma_theta_f', 'sigma_maxdepth',
        'dry_value_flag', 'wetdry_node', 'wetdry_elem', 'wetdry_side',
    }

    def _component_axis(shape, dims=()):
        """Index of the size-2 vector-component axis, or None.

        Prefer the dimension NAME when available (SCHISM calls it 'two'),
        then search from the trailing axis inward, skipping axis 0. Taking
        the first size-2 axis instead would grab the TIME axis on a stack
        with exactly 2 records -- a real case for short legs and spill
        stacks -- silently dropping horizontalVelX/Y and, downstream,
        making slab2d skip the whole stack.
        """
        for ax, name in enumerate(dims):
            if name == 'two' and shape[ax] == 2:
                return ax
        for ax in range(len(shape) - 1, 0, -1):
            if shape[ax] == 2:
                return ax
        return None

    def _dims_for(shape, n_nodes, n_vert):
        """Map an array shape to canonical split-file dim names.

        Axis 0 is always time; remaining axes are matched by size.
        Returns None when an axis can't be identified.
        """
        dims = ['time']
        for size in shape[1:]:
            if size == n_nodes:
                dims.append('nSCHISM_hgrid_node')
            elif n_vert > 0 and size == n_vert:
                dims.append('nSCHISM_vgrid_layers')
            else:
                return None
        return tuple(dims)

    for i in range(1, 999):
        schout_file = f"schout_{i}.nc"
        if not os.path.exists(schout_file):
            break

        print(f"  Splitting {schout_file}...")
        ds = Dataset(schout_file, 'r')

        # Identify available variables
        schout_vars = list(ds.variables.keys())
        time_data = ds.variables['time'][:]
        nstep = len(time_data)

        # Get node dimension name
        node_dim = None
        for dname in ['nSCHISM_hgrid_node', 'node', 'nod2']:
            if dname in ds.dimensions:
                node_dim = dname
                break
        if node_dim is None:
            # Fallback: use first spatial dimension of elevation
            for vn in ['elev', 'elevation']:
                if vn in ds.variables:
                    node_dim = ds.variables[vn].dimensions[-1]
                    break

        n_nodes = len(ds.dimensions[node_dim]) if node_dim else 0

        # --- Create out2d_{i}.nc ---
        out2d_file = f"out2d_{i}.nc"
        ds_out = Dataset(out2d_file, 'w', format='NETCDF4')

        # Copy dimensions
        ds_out.createDimension('time', None)
        ds_out.createDimension('nSCHISM_hgrid_node', n_nodes)

        # Time
        tv = ds_out.createVariable('time', 'f8', ('time',))
        tv[:] = time_data
        if hasattr(ds.variables['time'], 'units'):
            tv.units = ds.variables['time'].units

        # Elevation
        for src_name in ['elev', 'elevation']:
            if src_name in ds.variables:
                elev = ds_out.createVariable('elevation', 'f4',
                                              ('time', 'nSCHISM_hgrid_node'))
                elev[:] = ds.variables[src_name][:]
                break

        # Wind (optional)
        for wvar in ['windSpeedX', 'windSpeedY']:
            if wvar in ds.variables:
                wv = ds_out.createVariable(wvar, 'f4',
                                            ('time', 'nSCHISM_hgrid_node'))
                wv[:] = ds.variables[wvar][:]

        # Coordinates and depth (from first schout only, or from schout if present)
        for coord in ['SCHISM_hgrid_node_x', 'SCHISM_hgrid_node_y']:
            if coord in ds.variables:
                cv = ds_out.createVariable(coord, 'f8', ('nSCHISM_hgrid_node',))
                cv[:] = ds.variables[coord][:]
        if 'depth' in ds.variables:
            dv = ds_out.createVariable('depth', 'f4', ('nSCHISM_hgrid_node',))
            dv[:] = ds.variables['depth'][:]

        # Mesh topology: scribed out2d files carry the element table, so the
        # split files must too or downstream products that triangulate the
        # domain (geopkg contours, adcirc, slab2d) break on the coupled path
        # only. combine_output11 puts these in the combined schout.
        if 'SCHISM_hgrid_face_nodes' in ds.variables:
            src = ds.variables['SCHISM_hgrid_face_nodes']
            for dname, dsize in zip(src.dimensions, src.shape):
                if dname not in ds_out.dimensions:
                    ds_out.createDimension(dname, dsize)
            _fill = getattr(src, '_FillValue', None)
            fv = ds_out.createVariable(
                'SCHISM_hgrid_face_nodes', src.dtype, src.dimensions,
                **({'fill_value': _fill} if _fill is not None else {}))
            fv[:] = src[:]
            for att in src.ncattrs():
                if att != '_FillValue':
                    fv.setncattr(att, src.getncattr(att))
        # The two engines spell this differently: scribe_io writes
        # 'bottom_index_node', combine_output11 (the coupled/OLDIO path)
        # writes 'node_bottom_index'. Accept either, always emit the
        # scribe name, or slab2d silently produces nothing on the
        # coupled path while passing every scribe-shaped test.
        for _bsrc in ('bottom_index_node', 'node_bottom_index'):
            if _bsrc in ds.variables:
                bv = ds_out.createVariable(
                    'bottom_index_node', 'i4', ('nSCHISM_hgrid_node',))
                bv[:] = ds.variables[_bsrc][:]
                break

        ds_out.close()

        # --- Create 3D split files ---
        # Determine vertical dimension
        vert_dim = None
        for dname in ['nSCHISM_vgrid_layers', 'nVert', 'sigma']:
            if dname in ds.dimensions:
                vert_dim = dname
                break

        n_vert = len(ds.dimensions[vert_dim]) if vert_dim else 0

        for src_name, (split_var, split_prefix) in VAR_3D.items():
            if src_name not in ds.variables:
                continue
            split_file = f"{split_prefix}_{i}.nc"
            ds_split = Dataset(split_file, 'w', format='NETCDF4')

            ds_split.createDimension('time', None)
            ds_split.createDimension('nSCHISM_hgrid_node', n_nodes)
            if n_vert > 0:
                ds_split.createDimension('nSCHISM_vgrid_layers', n_vert)

            tv = ds_split.createVariable('time', 'f8', ('time',))
            tv[:] = time_data

            # Preserve the SOURCE's dimension order rather than assuming one.
            # combine_output11 and the scribe writer do not necessarily agree
            # on whether 3D vars are (time, node, layers) or
            # (time, layers, node); hardcoding either silently transposes the
            # data (or raises deep inside a downstream writer).
            src_var = ds.variables[src_name]
            src_dims = []
            for dname, dsize in zip(src_var.dimensions, src_var.shape):
                if dname == 'time' or dsize == len(time_data) and dname not in ds_split.dimensions:
                    src_dims.append('time')
                elif dsize == n_nodes:
                    src_dims.append('nSCHISM_hgrid_node')
                elif n_vert > 0 and dsize == n_vert:
                    src_dims.append('nSCHISM_vgrid_layers')
                else:
                    # Unrecognized axis: carry it through under its own name.
                    if dname not in ds_split.dimensions:
                        ds_split.createDimension(dname, dsize)
                    src_dims.append(dname)
            var = ds_split.createVariable(split_var, 'f4', tuple(src_dims))
            var[:] = src_var[:]

            ds_split.close()

        # --- Vector variables: split the size-2 component axis ---
        import numpy as _np

        for src_name, comps in VECTOR_3D.items():
            if src_name not in ds.variables:
                continue
            arr = ds.variables[src_name][:]
            ax = _component_axis(arr.shape, ds.variables[src_name].dimensions)
            if ax is None or ax == 0:
                print(f"    WARNING: {src_name}: no component axis, skipped")
                continue
            for ci, comp_name in enumerate(comps):
                comp = _np.take(arr, ci, axis=ax)
                dims = _dims_for(comp.shape, n_nodes, n_vert)
                if dims is None:
                    print(f"    WARNING: {src_name}[{comp_name}]: "
                          f"unrecognized shape {comp.shape}, skipped")
                    break
                ds_split = Dataset(f"{comp_name}_{i}.nc", 'w',
                                   format='NETCDF4')
                ds_split.createDimension('time', None)
                ds_split.createDimension('nSCHISM_hgrid_node', n_nodes)
                if 'nSCHISM_vgrid_layers' in dims:
                    ds_split.createDimension('nSCHISM_vgrid_layers', n_vert)
                tv = ds_split.createVariable('time', 'f8', ('time',))
                tv[:] = time_data
                var = ds_split.createVariable(comp_name, 'f4', dims)
                var[:] = comp
                ds_split.close()

        for src_name, comps in VECTOR_2D.items():
            if src_name not in ds.variables:
                continue
            arr = ds.variables[src_name][:]
            ax = _component_axis(arr.shape, ds.variables[src_name].dimensions)
            if ax is None or ax == 0:
                print(f"    WARNING: {src_name}: no component axis, skipped")
                continue
            ds_out2 = Dataset(out2d_file, 'a')
            for ci, comp_name in enumerate(comps):
                comp = _np.take(arr, ci, axis=ax)
                dims = _dims_for(comp.shape, n_nodes, 0)
                if dims != ('time', 'nSCHISM_hgrid_node'):
                    print(f"    WARNING: {src_name}[{comp_name}]: "
                          f"unrecognized shape {comp.shape}, skipped")
                    break
                wv = ds_out2.createVariable(comp_name, 'f4', dims)
                wv[:] = comp
            ds_out2.close()

        # Anything time-varying we didn't split gets named, never lost silently.
        handled = (set(VAR_2D) | set(VAR_3D) | set(VECTOR_3D)
                   | set(VECTOR_2D) | KNOWN_STATIC)
        unmapped = [v for v in schout_vars if v not in handled]
        if unmapped:
            print(f"    NOTE: unmapped schout variables (not split): {unmapped}")

        ds.close()
        print(f"    -> {out2d_file} + 3D split files created")


def main():
    print("=" * 60)
    print("SCHISM Combine Outputs — CO-OPS Standard NetCDF Products")
    print("=" * 60)

    # Read control file
    ctl = read_control_file()
    print(f"  PREFIXNOS: {ctl['PREFIXNOS']}")
    print(f"  Cycle:     {ctl['cyc']}")
    print(f"  PDY:       {ctl['PDY']}")
    print(f"  Mode:      {ctl['mode']} ({'nowcast' if ctl['mode'] == 'n' else 'forecast'})")
    print(f"  TimeStart: {ctl['timestart']}")

    # Check what output files are available
    has_split_fields = os.path.exists("out2d_1.nc")
    has_schout = os.path.exists("schout_1.nc")
    has_fields = has_split_fields or has_schout
    has_stations = os.path.exists("staout_1")

    if not has_fields and not has_stations:
        print("ERROR: No output files found (neither out2d_1.nc, schout_1.nc, nor staout_1)")
        sys.exit(1)

    if has_split_fields:
        print("\n  Field output files detected (out2d_*.nc — split format)")
    elif has_schout:
        print("\n  Field output files detected (schout_*.nc — combined format)")
        # Convert schout to split format for uniform processing
        print("  Converting schout_*.nc to split format...")
        convert_schout_to_split()
        has_split_fields = True
    else:
        print("\n  No field output files (out2d_*.nc / schout_*.nc) — stations-only mode")

    if has_stations:
        print(f"  Station output files detected (staout_*)")

    # Get grid dimensions dynamically
    print("\nReading grid dimensions...")
    dims = get_grid_dimensions(ctl['PREFIXNOS'], fields_available=has_split_fields)
    if has_split_fields:
        print(f"  Nodes:    {dims['n_nodes']}")
        print(f"  Elements: {dims['n_elements']}")
    print(f"  Stations: {dims['n_stations']}")
    print(f"  Levels:   {dims['n_levels']}")

    # Process field files (only if out2d_*.nc available)
    if has_split_fields:
        print("\n--- Processing Field Files ---")
        process_field_files(ctl, dims)
    else:
        print("\n--- Skipping Field Files (no out2d_*.nc) ---")

    # Process station files (only if staout_* available)
    if has_stations:
        print("\n--- Processing Station Files ---")
        process_station_files(ctl, dims)
    else:
        print("\n--- Skipping Station Files (no staout_*) ---")

    print("\n" + "=" * 60)
    print("SCHISM output combining completed successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()
