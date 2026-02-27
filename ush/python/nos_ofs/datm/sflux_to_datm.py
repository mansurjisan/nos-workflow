#!/usr/bin/env python3
"""
Convert COMF sflux files to DATM forcing format for strict UFS-Coastal validation.

Creates datm_forcing.nc from COMF's Fortran-processed sflux output, ensuring
identical atmospheric forcing between standalone SCHISM and UFS-Coastal.

Usage (standalone):
    python3 sflux_to_datm.py --sflux-dir /path/to/sflux \
                              --output /path/to/INPUT/datm_forcing.nc \
                              --pdy 20260224 --cyc 12

Usage (from prep script):
    Called by exnos_ofs_prep.sh when DATM_FORCING_SOURCE=sflux
"""

import argparse
import os
import sys
import netCDF4 as nc
import numpy as np
from scipy.spatial import Delaunay
from scipy.interpolate import RegularGridInterpolator
from datetime import datetime, timezone


# Variable mapping: DATM name → (sflux file type, sflux variable name)
VAR_MAP = {
    'UGRD_10maboveground': ('air', 'uwind'),
    'VGRD_10maboveground': ('air', 'vwind'),
    'TMP_2maboveground':   ('air', 'stmp'),
    'SPFH_2maboveground':  ('air', 'spfh'),
    'MSLMA_meansealevel':  ('air', 'prmsl'),
    'PRATE_surface':       ('prc', 'prate'),
    'DSWRF_surface':       ('rad', 'dswrf'),
    'DLWRF_surface':       ('rad', 'dlwrf'),
}


def load_sflux(sflux_dir):
    """Load all 6 sflux files (air/prc/rad × GFS/HRRR)."""
    sflux = {}
    for ftype in ['air', 'prc', 'rad']:
        sflux[ftype] = {}
        for src, label in [('1', 'GFS'), ('2', 'HRRR')]:
            path = os.path.join(sflux_dir, f'sflux_{ftype}_{src}.1.nc')
            if not os.path.exists(path):
                print(f"ERROR: Missing {path}")
                sys.exit(1)
            ds = nc.Dataset(path)
            sflux[ftype][src] = {
                'ds': ds,
                'time': np.asarray(ds.variables['time'][:]),
                'lat': np.asarray(ds.variables['lat'][:]),
                'lon': np.asarray(ds.variables['lon'][:]),
            }
            nt = len(sflux[ftype][src]['time'])
            print(f"  sflux_{ftype}_{src} ({label}): {nt} steps, "
                  f"shape={sflux[ftype][src]['lat'].shape}")
    return sflux


def build_hrrr_interpolator(sflux, target_lat_2d, target_lon_2d):
    """Build Delaunay triangulation for HRRR LCC → regular grid."""
    print("Building HRRR Delaunay triangulation...")
    hrrr_lat = sflux['air']['2']['lat']
    hrrr_lon = sflux['air']['2']['lon']
    ny, nx = target_lat_2d.shape

    hrrr_pts = np.column_stack([hrrr_lon.ravel(), hrrr_lat.ravel()])
    tri = Delaunay(hrrr_pts)

    target_pts = np.column_stack([target_lon_2d.ravel(), target_lat_2d.ravel()])
    simplices = tri.find_simplex(target_pts)
    coverage = (simplices >= 0)
    n_cov = np.sum(coverage)
    print(f"  HRRR coverage: {n_cov}/{len(target_pts)} points "
          f"({100 * n_cov / len(target_pts):.1f}%)")

    # Precompute barycentric coordinates
    valid_s = simplices[coverage]
    valid_t = target_pts[coverage]
    tri_vi = tri.simplices[valid_s]
    v0 = hrrr_pts[tri_vi[:, 0]]
    v1 = hrrr_pts[tri_vi[:, 1]]
    v2 = hrrr_pts[tri_vi[:, 2]]
    det = ((v1[:, 1] - v2[:, 1]) * (v0[:, 0] - v2[:, 0]) +
           (v2[:, 0] - v1[:, 0]) * (v0[:, 1] - v2[:, 1]))
    lam0 = ((v1[:, 1] - v2[:, 1]) * (valid_t[:, 0] - v2[:, 0]) +
            (v2[:, 0] - v1[:, 0]) * (valid_t[:, 1] - v2[:, 1])) / det
    lam1 = ((v2[:, 1] - v0[:, 1]) * (valid_t[:, 0] - v2[:, 0]) +
            (v0[:, 0] - v2[:, 0]) * (valid_t[:, 1] - v2[:, 1])) / det
    bary = np.column_stack([lam0, lam1, 1 - lam0 - lam1]).astype(np.float32)
    valid_idx = np.where(coverage)[0]

    return {
        'tri_vi': tri_vi,
        'bary': bary,
        'valid_idx': valid_idx,
        'coverage_2d': coverage.reshape(ny, nx),
        'n_target': len(target_pts),
        'ny': ny, 'nx': nx,
    }


def interp_hrrr(data_2d, interp_info):
    """Bilinear interpolation of HRRR field to target grid."""
    vals = np.asarray(data_2d).ravel()[interp_info['tri_vi']]
    interp_vals = np.sum(vals * interp_info['bary'], axis=1)
    result = np.full(interp_info['n_target'], np.nan, dtype=np.float32)
    result[interp_info['valid_idx']] = interp_vals
    return result.reshape(interp_info['ny'], interp_info['nx'])


def interp_gfs(data_2d, gfs_lat_1d, gfs_lon_1d, target_pts, ny, nx):
    """Bilinear interpolation of GFS field to target grid."""
    fn = RegularGridInterpolator(
        (gfs_lat_1d, gfs_lon_1d), np.asarray(data_2d),
        method='linear', bounds_error=False, fill_value=np.nan
    )
    return fn(target_pts).reshape(ny, nx).astype(np.float32)


def convert(sflux_dir, output_path, pdy, cyc,
            lat_min=17.0, lat_max=40.0, lon_min=-88.0, lon_max=-63.0,
            dx=0.025, scrip_path=None):
    """Main conversion: sflux files → datm_forcing.nc."""

    print(f"Converting sflux → DATM forcing")
    print(f"  sflux_dir: {sflux_dir}")
    print(f"  output: {output_path}")
    print(f"  PDY={pdy} cyc={cyc}")

    # Load sflux files
    sflux = load_sflux(sflux_dir)

    # Target grid
    target_lat_1d = np.arange(lat_min, lat_max + dx / 2, dx, dtype=np.float64)
    target_lon_1d = np.arange(lon_min, lon_max + dx / 2, dx, dtype=np.float64)
    ny, nx = len(target_lat_1d), len(target_lon_1d)
    target_lon_2d, target_lat_2d = np.meshgrid(target_lon_1d, target_lat_1d)
    print(f"\nTarget grid: {ny} x {nx}")

    # Build interpolators
    hrrr_interp = build_hrrr_interpolator(sflux, target_lat_2d, target_lon_2d)

    gfs_lat_1d = sflux['air']['1']['lat'][:, 0]
    gfs_lon_1d = sflux['air']['1']['lon'][0, :]
    target_pts_latlon = np.column_stack([target_lat_2d.ravel(),
                                         target_lon_2d.ravel()])

    # Time axis
    base_date = datetime(int(pdy[:4]), int(pdy[4:6]), int(pdy[6:8]),
                         tzinfo=timezone.utc)
    base_epoch = base_date.timestamp()

    hrrr_times = sflux['air']['2']['time']  # days
    gfs_times = sflux['air']['1']['time']   # days
    hrrr_hours = hrrr_times * 24.0
    gfs_hours = gfs_times * 24.0

    # Output: hourly from first to last sflux hour
    h_start = int(np.floor(hrrr_hours[0]))
    h_end = int(np.ceil(hrrr_hours[-1]))
    out_hours = np.arange(h_start, h_end + 1, dtype=np.float64)
    out_times_epoch = base_epoch + out_hours * 3600.0
    nt = len(out_hours)
    print(f"Output: {nt} hourly steps, h{h_start} to h{h_end}")

    # HRRR time lookup
    hrrr_hour_to_idx = {}
    for i, h in enumerate(hrrr_hours):
        hrrr_hour_to_idx[int(round(h))] = i

    # Create output NetCDF
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    ds_out = nc.Dataset(output_path, 'w', format='NETCDF4')
    ds_out.createDimension('time', None)
    ds_out.createDimension('latitude', ny)
    ds_out.createDimension('longitude', nx)

    v_time = ds_out.createVariable('time', 'f8', ('time',))
    v_time.units = 'seconds since 1970-01-01T00:00:00Z'
    v_time.calendar = 'standard'
    v_time[:] = out_times_epoch

    v_lat = ds_out.createVariable('latitude', 'f8', ('latitude',))
    v_lat.units = 'degrees_north'
    v_lat[:] = target_lat_1d

    v_lon = ds_out.createVariable('longitude', 'f8', ('longitude',))
    v_lon.units = 'degrees_east'
    v_lon[:] = target_lon_1d

    v_src = ds_out.createVariable('data_source', 'i1', ('latitude', 'longitude'),
                                   zlib=True, complevel=4)
    v_src.long_name = 'data source (1=sflux_HRRR, 0=sflux_GFS)'
    v_src[:] = hrrr_interp['coverage_2d'].astype(np.int8)

    datm_vars = {}
    for name in VAR_MAP:
        v = ds_out.createVariable(name, 'f4', ('time', 'latitude', 'longitude'),
                                   zlib=True, complevel=4)
        datm_vars[name] = v

    ds_out.title = 'DATM forcing from COMF sflux (strict validation)'
    ds_out.source = 'sflux_air/prc/rad_1.1.nc (GFS) + _2.1.nc (HRRR)'
    ds_out.conventions = 'CF-1.6'
    ds_out.base_date = base_date.strftime('%Y-%m-%d %H:%M:%S UTC')

    # Process timesteps
    print(f"\nProcessing {nt} timesteps...")
    for ti, hour in enumerate(out_hours):
        hour_int = int(round(hour))
        hi = hrrr_hour_to_idx.get(hour_int, -1)

        # GFS temporal interpolation
        gi_lo = max(0, np.searchsorted(gfs_hours, hour, side='right') - 1)
        gi_hi = min(gi_lo + 1, len(gfs_hours) - 1)
        if gi_lo == gi_hi or gfs_hours[gi_lo] == gfs_hours[gi_hi]:
            gfs_w = 0.0
        else:
            gfs_w = (hour - gfs_hours[gi_lo]) / (gfs_hours[gi_hi] - gfs_hours[gi_lo])

        if ti % 6 == 0:
            tag = f"HRRR[{hi}]" if hi >= 0 else "GFS_ONLY"
            print(f"  t={ti:3d} h={hour_int:02d}: {tag}")

        for datm_name, (ftype, svar) in VAR_MAP.items():
            # GFS (temporally interpolated, spatially regridded)
            gfs_lo = np.asarray(sflux[ftype]['1']['ds'].variables[svar][gi_lo])
            if gi_lo != gi_hi:
                gfs_hi_data = np.asarray(
                    sflux[ftype]['1']['ds'].variables[svar][gi_hi])
                gfs_data = gfs_lo * (1 - gfs_w) + gfs_hi_data * gfs_w
            else:
                gfs_data = gfs_lo
            output = interp_gfs(gfs_data, gfs_lat_1d, gfs_lon_1d,
                                target_pts_latlon, ny, nx)

            # HRRR override where available (hard boundary, matches SCHISM)
            if hi >= 0:
                hrrr_data = np.asarray(
                    sflux[ftype]['2']['ds'].variables[svar][hi])
                hrrr_regrid = interp_hrrr(hrrr_data, hrrr_interp)
                output[hrrr_interp['coverage_2d']] = \
                    hrrr_regrid[hrrr_interp['coverage_2d']]

            datm_vars[datm_name][ti, :, :] = output

    ds_out.close()
    fsize = os.path.getsize(output_path) / (1024**3)
    print(f"\nWrote: {output_path} ({fsize:.2f} GB)")

    # Close sflux files
    for ftype in sflux:
        for src in sflux[ftype]:
            sflux[ftype][src]['ds'].close()

    # Generate SCRIP grid
    if scrip_path is None:
        scrip_path = output_path.replace('.nc', '_scrip.nc')
    generate_scrip(scrip_path, target_lat_2d, target_lon_2d, dx)

    return output_path, scrip_path


def generate_scrip(scrip_path, lat_2d, lon_2d, dx):
    """Generate SCRIP grid description file."""
    ny, nx = lat_2d.shape
    grid_size = ny * nx
    print(f"Generating SCRIP grid: {scrip_path} ({ny}x{nx})")

    ds = nc.Dataset(scrip_path, 'w', format='NETCDF4')
    ds.createDimension('grid_size', grid_size)
    ds.createDimension('grid_corners', 4)
    ds.createDimension('grid_rank', 2)

    v = ds.createVariable('grid_dims', 'i4', ('grid_rank',))
    v[:] = [nx, ny]

    v = ds.createVariable('grid_center_lat', 'f8', ('grid_size',))
    v.units = 'degrees'
    v[:] = lat_2d.ravel()

    v = ds.createVariable('grid_center_lon', 'f8', ('grid_size',))
    v.units = 'degrees'
    v[:] = lon_2d.ravel()

    v = ds.createVariable('grid_imask', 'i4', ('grid_size',))
    v.units = 'unitless'
    v[:] = np.ones(grid_size, dtype=np.int32)

    half = dx / 2.0
    lat_f = lat_2d.ravel()
    lon_f = lon_2d.ravel()

    v = ds.createVariable('grid_corner_lat', 'f8', ('grid_size', 'grid_corners'))
    v.units = 'degrees'
    v[:, 0] = lat_f - half
    v[:, 1] = lat_f - half
    v[:, 2] = lat_f + half
    v[:, 3] = lat_f + half

    v = ds.createVariable('grid_corner_lon', 'f8', ('grid_size', 'grid_corners'))
    v.units = 'degrees'
    v[:, 0] = lon_f - half
    v[:, 1] = lon_f + half
    v[:, 2] = lon_f + half
    v[:, 3] = lon_f - half

    ds.title = 'SCRIP grid for DATM forcing from sflux'
    ds.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Convert COMF sflux files to DATM forcing format')
    parser.add_argument('--sflux-dir', required=True,
                        help='Directory containing sflux_*.1.nc files')
    parser.add_argument('--output', required=True,
                        help='Output datm_forcing.nc path')
    parser.add_argument('--pdy', required=True,
                        help='Prediction day (YYYYMMDD)')
    parser.add_argument('--cyc', required=True,
                        help='Cycle hour (00/06/12/18)')
    parser.add_argument('--lat-min', type=float, default=17.0)
    parser.add_argument('--lat-max', type=float, default=40.0)
    parser.add_argument('--lon-min', type=float, default=-88.0)
    parser.add_argument('--lon-max', type=float, default=-63.0)
    parser.add_argument('--dx', type=float, default=0.025)
    parser.add_argument('--scrip', default=None,
                        help='Output SCRIP grid path')
    args = parser.parse_args()

    convert(args.sflux_dir, args.output, args.pdy, args.cyc,
            lat_min=args.lat_min, lat_max=args.lat_max,
            lon_min=args.lon_min, lon_max=args.lon_max,
            dx=args.dx, scrip_path=args.scrip)
