#!/usr/bin/env python3
"""Parameterized SCHISM Output Combiner

Combines SCHISM split outputs (out2d_*.nc, temperature_*.nc, etc.) into
CO-OPS standard per-timestep field files and station timeseries NetCDF.

Reads grid dimensions dynamically from output files — works for any
SCHISM-based OFS (SECOFS, STOFS-3D-ATL, etc.) without hardcoded values.

Outputs:
  {PREFIX}.t{cyc}z.{PDY}.fields.{mode}NNN.nc  (one per timestep)
  {PREFIX}.t{cyc}z.{PDY}.stations.{nowcast|forecast}.nc

Based on nosofs.v3.7.0/ush/pysh/schism_fields_station_redo.py but
parameterized (no hardcoded dimensions, uses PREFIXNOS consistently).
"""

import argparse
import os
import shutil
import subprocess
import sys

import netCDF4 as nc
import numpy as np


def read_control_file(ctl_path="schism_standard_output.ctl"):
    """Read the 5-line SCHISM standard output control file."""
    with open(ctl_path, 'r') as f:
        lines = [line.strip() for line in f.readlines()]
    return {
        'prefix': lines[0],
        'cyc': lines[1],
        'pdy': lines[2],
        'mode': lines[3],
        'timestart': lines[4],
    }


def combine_schism_outputs(prefix, cyc, pdy, mode, timestart, workdir=None,
                           fixdir=None, compress=True):
    """Combine SCHISM split outputs into field/station products.

    Args:
        prefix: OFS prefix (e.g., 'secofs', 'secofs_ufs')
        cyc: Cycle hour string (e.g., '12')
        pdy: Date string YYYYMMDD
        mode: 'n' for nowcast, 'f' for forecast
        timestart: Start time YYYYMMDDHH
        workdir: Directory containing SCHISM outputs (default: cwd)
        fixdir: Directory with FIX files to copy (optional)
        compress: Whether to compress output with ncks (default: True)

    Returns:
        0 on success, non-zero on error.
    """
    if workdir:
        os.chdir(workdir)

    yyyy = timestart[:4]
    mm = timestart[4:6]
    dd = timestart[6:8]
    hh = timestart[8:10]

    # --- Copy FIX files if fixdir provided ---
    if fixdir:
        for fname in [f"{prefix}.nv.nc", f"{prefix}.hgrid.gr3",
                      f"{prefix}.station.lat.lon", f"{prefix}.sigma.dat"]:
            src = os.path.join(fixdir, fname)
            if os.path.exists(src) and not os.path.exists(fname):
                shutil.copy2(src, ".")
                print(f"  Copied {fname} from {fixdir}")

    # --- Read sigma data ---
    sigma_file = f"{prefix}.sigma.dat"
    if not os.path.exists(sigma_file):
        print(f"ERROR: {sigma_file} not found in {os.getcwd()}", file=sys.stderr)
        return 1
    sigma_data = np.loadtxt(sigma_file, dtype=float)
    sigma1 = sigma_data.T
    if sigma1.ndim == 2:
        nver = sigma1.shape[1]
    else:
        nver = sigma1.shape[0]
    print(f"  Sigma levels (nver): {nver}")

    # --- Read nv connectivity ---
    nvfile = f"{prefix}.nv.nc"
    if not os.path.exists(nvfile):
        print(f"ERROR: {nvfile} not found in {os.getcwd()}", file=sys.stderr)
        return 1
    ds_nv = nc.Dataset(nvfile)
    nv1 = ds_nv.variables["nv"][:]
    nele_count = nv1.shape[1] if nv1.ndim == 2 else nv1.shape[0]
    ds_nv.close()

    # --- Read node count from first output file ---
    if not os.path.exists("out2d_1.nc"):
        print("ERROR: out2d_1.nc not found in " + os.getcwd(), file=sys.stderr)
        return 1
    ds_test = nc.Dataset("out2d_1.nc")
    node_count = None
    for dim_name in ["nSCHISM_hgrid_node", "node"]:
        if dim_name in ds_test.dimensions:
            node_count = len(ds_test.dimensions[dim_name])
            break
    if node_count is None:
        node_count = ds_test.variables["SCHISM_hgrid_node_x"].shape[0]
    ds_test.close()

    print(f"  Nodes: {node_count}, Elements: {nele_count}, Sigma: {nver}")

    # === FIELD FILES ===
    field_count = 0
    i = 1
    while True:
        file2d = f"out2d_{i}.nc"
        if not os.path.exists(file2d):
            break

        filetemp = f"temperature_{i}.nc"
        filesalt = f"salinity_{i}.nc"
        fileu = f"horizontalVelX_{i}.nc"
        filev = f"horizontalVelY_{i}.nc"

        print(f"  Processing output set {i}: {file2d}")

        ds_grid = nc.Dataset(file2d)
        ds_temp = nc.Dataset(filetemp)
        ds_salt = nc.Dataset(filesalt)
        ds_u = nc.Dataset(fileu)
        ds_v = nc.Dataset(filev)

        time1 = ds_grid.variables["time"][:]
        nstep = len(time1)

        h1 = ds_grid.variables["depth"][:]
        lon1 = ds_grid.variables["SCHISM_hgrid_node_x"][:]
        lat1 = ds_grid.variables["SCHISM_hgrid_node_y"][:]
        zeta1 = ds_grid.variables["elevation"][:]
        uwind1 = ds_grid.variables["windSpeedX"][:]
        vwind1 = ds_grid.variables["windSpeedY"][:]

        temp1 = ds_temp.variables["temperature"][:]
        salt1 = ds_salt.variables["salinity"][:]
        u1 = ds_u.variables["horizontalVelX"][:]
        v1 = ds_v.variables["horizontalVelY"][:]

        # Copy raw files with named format (nowcast only, first set)
        if i == 1 and mode == "n":
            for src, var in [("out2d_1.nc", "out2d_1"),
                             ("zCoordinates_1.nc", "zCoordinates_1"),
                             ("temperature_1.nc", "temperature_1"),
                             ("salinity_1.nc", "salinity_1"),
                             ("horizontalVelX_1.nc", "horizontalVelX_1"),
                             ("horizontalVelY_1.nc", "horizontalVelY_1")]:
                if os.path.exists(src):
                    dst = f"{prefix}.t{cyc}z.{pdy}.{var}.nowcast.nc"
                    shutil.copyfile(src, dst)
            for k in range(1, 9):
                src = f"staout_{k}"
                if os.path.exists(src):
                    dst = f"{prefix}.t{cyc}z.{pdy}.nowcast.staout_{k}"
                    shutil.copyfile(src, dst)

        # Create per-timestep field files
        for k in range(nstep):
            iii = (i - 1) * nstep + k + 1
            kkk = f"{iii:03d}"

            tmp_file = f"{prefix}.t{cyc}z.{pdy}.fields.{mode}{kkk}.nc.tmp"
            final_file = f"{prefix}.t{cyc}z.{pdy}.fields.{mode}{kkk}.nc"

            ncfile = nc.Dataset(tmp_file, mode='w', format='NETCDF4_CLASSIC')

            ncfile.createDimension('node', node_count)
            ncfile.createDimension('nele', nele_count)
            ncfile.createDimension('nface', 3)
            ncfile.createDimension('nv', nver)
            ncfile.createDimension('time', None)

            lon_v = ncfile.createVariable('lon', np.float32, ('node',))
            lat_v = ncfile.createVariable('lat', np.float32, ('node',))
            time_v = ncfile.createVariable('time', np.float32, ('time',))
            time_v.units = f"seconds since {yyyy}-{mm}-{dd} {hh}:00:00"

            ele_v = ncfile.createVariable('ele', 'i4', ('nface', 'nele'))
            h_v = ncfile.createVariable('h', np.float32, ('node',))

            zeta_v = ncfile.createVariable('zeta', np.float32, ('time', 'node'))
            uwind_v = ncfile.createVariable('uwind_speed', np.float32, ('time', 'node'))
            vwind_v = ncfile.createVariable('Vwind_speed', np.float32, ('time', 'node'))

            temp_v = ncfile.createVariable('temp', np.float32, ('time', 'nv', 'node'))
            salt_v = ncfile.createVariable('salinity', np.float32, ('time', 'nv', 'node'))
            u_v = ncfile.createVariable('u', np.float32, ('time', 'nv', 'node'))
            v_v = ncfile.createVariable('v', np.float32, ('time', 'nv', 'node'))

            sigma_v = ncfile.createVariable('sigma', np.float32, ('node', 'nv'))

            h_v[:] = h1[:]
            lon_v[:] = lon1[:]
            lat_v[:] = lat1[:]
            ele_v[:, :] = nv1[:, :]
            sigma_v[:, :] = sigma1[:, :]

            time_v[:] = time1[k]
            zeta_v[0, :] = zeta1[k, :]
            uwind_v[0, :] = uwind1[k, :]
            vwind_v[0, :] = vwind1[k, :]

            temp_v[0, :, :] = temp1[k, :, :].T
            salt_v[0, :, :] = salt1[k, :, :].T
            u_v[0, :, :] = u1[k, :, :].T
            v_v[0, :, :] = v1[k, :, :].T

            ncfile.close()

            # Compress with ncks (deflation level 4)
            if compress:
                try:
                    subprocess.check_call(
                        ["ncks", "-4", "-L", "4", tmp_file, final_file],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    os.remove(tmp_file)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    os.rename(tmp_file, final_file)
            else:
                os.rename(tmp_file, final_file)

            field_count += 1

        ds_grid.close()
        ds_temp.close()
        ds_salt.close()
        ds_u.close()
        ds_v.close()

        i += 1

    print(f"  Created {field_count} field files")

    # === STATION FILE ===
    sta_file = f"{prefix}.station.lat.lon"
    if not os.path.exists(sta_file):
        print(f"WARNING: {sta_file} not found — skipping station output")
        return 0

    with open(sta_file, 'r') as f:
        sta_lines = [line.strip() for line in f if line.strip()]
    nsta = len(sta_lines)
    nsta2 = nsta * 2
    print(f"  Stations: {nsta}")

    modefull = "nowcast" if mode == "n" else "forecast"

    # Read 2D station outputs (elevation, wind u, wind v)
    ele_values = uwind_values = vwind_values = time_values = None

    for ind in [1, 3, 4]:
        fname = f"staout_{ind}"
        if not os.path.exists(fname):
            print(f"WARNING: {fname} not found — skipping station output")
            return 0

        with open(fname, 'r') as f:
            all_numbers = []
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

    # Read 3D station outputs (T, S, u, v) — every other line
    temp_final = salt_final = u_final = v_final = None

    for ind in [5, 6, 7, 8]:
        fname = f"staout_{ind}"
        if not os.path.exists(fname):
            print(f"WARNING: {fname} not found — skipping 3D station variables")
            break

        with open(fname, 'r') as f:
            all_numbers = []
            nline = 0
            for line in f:
                nline += 1
                if nline % 2 == 0:
                    numbers = [float(x) for x in line.strip().split()]
                    all_numbers.append(numbers)

        arr = np.array(all_numbers)
        nstep_sta = len(arr)

        data0 = arr[:, 1:]
        data_reshape = data0.reshape(nstep_sta, nsta2, nver)
        data_real = data_reshape[:, :nsta, :]
        data_final = np.swapaxes(data_real, 1, 2)

        if ind == 5:
            temp_final = data_final
        elif ind == 6:
            salt_final = data_final
        elif ind == 7:
            u_final = data_final
        elif ind == 8:
            v_final = data_final

    nstep_sta = len(time_values)

    # Create station NetCDF
    sta_nc = f"{prefix}.t{cyc}z.{pdy}.stations.{modefull}.nc"
    ncfile = nc.Dataset(sta_nc, mode='w', format='NETCDF4')

    name_length = 20
    ncfile.createDimension('station', nsta)
    ncfile.createDimension('clen', name_length)
    ncfile.createDimension('time', nstep_sta)
    ncfile.createDimension('siglay', nver)
    ncfile.createDimension('num_entries', nsta)

    time_v = ncfile.createVariable('time', np.float32, ('time',))
    time_v.units = f"seconds since {yyyy}-{mm}-{dd} {hh}:00:00"

    lon_v = ncfile.createVariable('lon', np.float32, ('station',))
    lat_v = ncfile.createVariable('lat', np.float32, ('station',))

    name_v = ncfile.createVariable('name_station', 'S1', ('station', 'clen'))

    zeta_v = ncfile.createVariable('zeta', np.float32, ('time', 'station'))
    uwind_v = ncfile.createVariable('uwind_speed', np.float32, ('time', 'station'))
    vwind_v = ncfile.createVariable('vwind_speed', np.float32, ('time', 'station'))

    temp_v = ncfile.createVariable('temp', np.float32, ('time', 'siglay', 'station'))
    salt_v = ncfile.createVariable('salinity', np.float32, ('time', 'siglay', 'station'))
    u_v = ncfile.createVariable('u', np.float32, ('time', 'siglay', 'station'))
    v_v = ncfile.createVariable('v', np.float32, ('time', 'siglay', 'station'))

    # Read station coordinates
    sta_data = np.array([line.split() for line in sta_lines])
    lon_v[:] = sta_data[:, 1].astype(float)
    lat_v[:] = sta_data[:, 2].astype(float)

    # Station names
    station_names = [f'station_{prefix}_{i + 1:05d}' for i in range(nsta)]
    names_char = nc.stringtochar(np.array(station_names, dtype=f'S{name_length}'))
    name_v[:] = names_char

    time_v[:] = time_values[:]
    zeta_v[:, :] = ele_values[:, :]
    uwind_v[:, :] = uwind_values[:, :]
    vwind_v[:, :] = vwind_values[:, :]

    if temp_final is not None:
        temp_v[:, :, :] = temp_final[:, :, :]
    if salt_final is not None:
        salt_v[:, :, :] = salt_final[:, :, :]
    if u_final is not None:
        u_v[:, :, :] = u_final[:, :, :]
    if v_final is not None:
        v_v[:, :, :] = v_final[:, :, :]

    ncfile.close()
    print(f"  Created station file: {sta_nc}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Combine SCHISM split outputs into field/station products"
    )
    parser.add_argument("--prefix", help="OFS prefix (e.g., secofs, secofs_ufs)")
    parser.add_argument("--cyc", help="Cycle hour (e.g., 12)")
    parser.add_argument("--pdy", help="Date YYYYMMDD")
    parser.add_argument("--mode", choices=["n", "f"], help="n=nowcast, f=forecast")
    parser.add_argument("--timestart", help="Start time YYYYMMDDHH")
    parser.add_argument("--workdir", default=".", help="Directory with SCHISM outputs")
    parser.add_argument("--fixdir", help="FIX directory for grid/station files")
    parser.add_argument("--no-compress", action="store_true",
                        help="Skip ncks compression")
    parser.add_argument("--ctl", help="Control file path (alternative to args)")

    args = parser.parse_args()

    if args.ctl:
        cfg = read_control_file(args.ctl)
        prefix = cfg['prefix']
        cyc = cfg['cyc']
        pdy = cfg['pdy']
        mode = cfg['mode']
        timestart = cfg['timestart']
    else:
        prefix = args.prefix or os.environ.get('PREFIXNOS', 'secofs')
        cyc = args.cyc or os.environ.get('cyc', '00')
        pdy = args.pdy or os.environ.get('PDY', '')
        mode = args.mode or 'f'
        timestart = args.timestart or f"{pdy}{cyc}"

    if not pdy:
        print("ERROR: --pdy or PDY env var required", file=sys.stderr)
        return 1

    print(f"SCHISM Output Combiner: prefix={prefix} cyc={cyc} pdy={pdy} "
          f"mode={mode} timestart={timestart}")

    return combine_schism_outputs(
        prefix=prefix, cyc=cyc, pdy=pdy, mode=mode, timestart=timestart,
        workdir=args.workdir, fixdir=args.fixdir, compress=not args.no_compress,
    )


if __name__ == "__main__":
    sys.exit(main())
