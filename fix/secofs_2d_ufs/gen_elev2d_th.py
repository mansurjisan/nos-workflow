#!/usr/bin/env python3
"""Generate elev2D.th.nc from RTOFS SSH data for SCHISM open boundaries.

Reads RTOFS 2D diagnostic files and interpolates SSH to SCHISM open boundary
nodes, producing the elev2D.th.nc boundary condition file.

This is a Python replacement for the Fortran gen_3Dth_from_hycom executable
(SSH component only), suitable for barotropic (2D) SCHISM runs that need
iettype=4 or iettype=5 elevation boundary conditions.

Input files:
    - hgrid.ll: SCHISM grid in lon/lat (open boundary section required)
    - RTOFS 2D diagnostic files: rtofs_glo_2ds_{n,f}HHH_diag.nc

Output:
    - elev2D.th.nc matching Fortran format:
      Dims: time(UNLIMITED), nOpenBndNodes, nLevels(1), nComponents(1)
      Vars: time_step(one), time(time),
            time_series(time, nOpenBndNodes, nLevels, nComponents)

Usage:
    python3 gen_elev2d_th.py hgrid.ll /path/to/rtofs 20260318 00 2.5 \\
        [--dt 21600] [--ssh-offset 0.04] [--boundaries 1] [-o elev2D.th.nc]
"""

import argparse
import glob
import os
import re
import sys
import numpy as np

try:
    from netCDF4 import Dataset
except ImportError:
    print("ERROR: netCDF4 is required. Install with: pip install netCDF4", file=sys.stderr)
    sys.exit(1)

try:
    from scipy.interpolate import RegularGridInterpolator
except ImportError:
    RegularGridInterpolator = None


# ---------------------------------------------------------------------------
# hgrid.ll reader
# ---------------------------------------------------------------------------

def read_hgrid_boundary(hgrid_file, boundary_ids=None):
    """Read open boundary node coordinates from hgrid.ll.

    Args:
        hgrid_file: Path to hgrid.ll (lon/lat format).
        boundary_ids: List of 1-based boundary segment IDs to include.
                      None means all open boundaries.

    Returns:
        (lons, lats): 1-D arrays of boundary node coordinates.
    """
    with open(hgrid_file) as f:
        f.readline()  # header
        ne, np_ = [int(x) for x in f.readline().split()[:2]]

        # Read all node coordinates
        node_lon = np.zeros(np_)
        node_lat = np.zeros(np_)
        for i in range(np_):
            parts = f.readline().split()
            node_lon[i] = float(parts[1])
            node_lat[i] = float(parts[2])

        # Skip elements
        for _ in range(ne):
            f.readline()

        # Open boundaries
        nope = int(f.readline().split()[0])
        neta = int(f.readline().split()[0])  # total open bnd nodes

        boundaries = []
        for k in range(nope):
            n_bnd = int(f.readline().split()[0])
            nodes = []
            for _ in range(n_bnd):
                nodes.append(int(f.readline().split()[0]))
            boundaries.append(np.array(nodes))

    # Select requested boundaries (1-based IDs)
    if boundary_ids is None:
        selected = boundaries
    else:
        selected = [boundaries[i - 1] for i in boundary_ids
                    if 1 <= i <= len(boundaries)]

    if not selected:
        print("ERROR: No open boundary segments found", file=sys.stderr)
        sys.exit(1)

    # Concatenate and get coordinates (node IDs are 1-based in hgrid)
    all_nodes = np.concatenate(selected)
    lons = node_lon[all_nodes - 1]
    lats = node_lat[all_nodes - 1]

    seg_desc = ', '.join(f'seg {i+1}: {len(b)} nodes'
                         for i, b in enumerate(boundaries)
                         if boundary_ids is None or (i + 1) in boundary_ids)
    print(f"  Open boundaries: {seg_desc}")
    print(f"  Total boundary nodes: {len(lons)}")

    return lons, lats


# ---------------------------------------------------------------------------
# RTOFS file discovery
# ---------------------------------------------------------------------------

def find_rtofs_files(rtofs_dir, pdy, cyc, ndays):
    """Find RTOFS 2D diagnostic files covering the requested period.

    Searches for rtofs_glo_2ds_{n,f}HHH_diag.nc files. Falls back to
    previous day's forecast files if current-day files are insufficient.

    Returns:
        List of (filepath, offset_seconds) sorted by time, where
        offset_seconds is relative to pdy+cyc (the analysis time).
    """
    cyc_int = int(cyc)
    needed_hours = int(np.ceil(ndays * 24))

    # RTOFS analysis time is always 00Z regardless of cycle
    # Nowcast files: n000=T-24h, n006=T-18h, ..., n024=T+0h
    # Forecast files: f000=T+0h, f006=T+6h, ..., f192=T+192h

    results = []

    # Today's directory
    today_dir = os.path.join(rtofs_dir, f"rtofs.{pdy}")
    # Previous day for fallback
    from datetime import datetime, timedelta
    prev_date = (datetime.strptime(pdy, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    prev_dir = os.path.join(rtofs_dir, f"rtofs.{prev_date}")

    # Helper to extract forecast hour offset from filename
    def parse_fhr(fname):
        """Return (type, hour) from RTOFS filename."""
        m = re.search(r'_([nf])(\d{3})_', fname)
        if m:
            kind = m.group(1)
            hour = int(m.group(2))
            if kind == 'n':
                # Nowcast: n024 is T+0, n018 is T-6, n012 is T-12
                return hour - 24  # relative to analysis time
            else:
                return hour  # forecast hour relative to analysis time
        return None

    # Collect files from today's run
    for pat in ['rtofs_glo_2ds_n*_diag.nc', 'rtofs_glo_2ds_f*_diag.nc']:
        for fpath in sorted(glob.glob(os.path.join(today_dir, pat))):
            fhr = parse_fhr(os.path.basename(fpath))
            if fhr is not None:
                # offset_seconds relative to analysis time (pdy 00Z)
                offset = (fhr - cyc_int) * 3600
                results.append((fpath, offset))

    # Fallback: previous day's forecasts (shifted by +24h)
    if len(results) < 3:
        for fpath in sorted(glob.glob(os.path.join(prev_dir, 'rtofs_glo_2ds_f*_diag.nc'))):
            fhr = parse_fhr(os.path.basename(fpath))
            if fhr is not None:
                offset = (fhr + 24 - cyc_int) * 3600
                results.append((fpath, offset))

    # Sort by offset time
    results.sort(key=lambda x: x[1])

    # Filter to needed window: slightly before 0 through ndays
    min_t = -7 * 3600  # start a bit before model start
    max_t = needed_hours * 3600 + 3600  # small buffer
    results = [(f, t) for f, t in results if min_t <= t <= max_t]

    if not results:
        print(f"ERROR: No RTOFS files found in {today_dir} or {prev_dir}",
              file=sys.stderr)
        sys.exit(1)

    print(f"  Found {len(results)} RTOFS files spanning "
          f"{results[0][1]/3600:.0f}h to {results[-1][1]/3600:.0f}h "
          f"(relative to {pdy} {cyc}Z)")

    return results


# ---------------------------------------------------------------------------
# RTOFS SSH reading
# ---------------------------------------------------------------------------

def read_rtofs_ssh(filepath, roi=None):
    """Read SSH from an RTOFS 2D diagnostic file.

    Args:
        filepath: Path to rtofs_glo_2ds_*_diag.nc.
        roi: Optional (lon_min, lon_max, lat_min, lat_max) to subset.

    Returns:
        (ssh_2d, lats_1d, lons_1d) where ssh_2d[lat, lon] is masked
        where invalid, and lats/lons are 1-D coordinate arrays.
    """
    nc = Dataset(filepath, 'r')

    # Read coordinate arrays - handle 1D or 2D
    if 'Longitude' in nc.variables:
        lon_var = nc.variables['Longitude']
        lat_var = nc.variables['Latitude']
    elif 'lon' in nc.variables:
        lon_var = nc.variables['lon']
        lat_var = nc.variables['lat']
    else:
        nc.close()
        raise ValueError(f"Cannot find lon/lat variables in {filepath}")

    lon_raw = lon_var[:]
    lat_raw = lat_var[:]

    # Extract 1D coordinates from 2D arrays if needed
    if lon_raw.ndim == 2:
        # Curvilinear grid - extract representative 1D arrays
        # For RTOFS/HYCOM, rows have nearly constant latitude
        lons_1d = np.ma.filled(lon_raw[0, :], np.nan)
        lats_1d = np.ma.filled(lat_raw[:, 0], np.nan)
    else:
        lons_1d = np.ma.filled(lon_raw[:], np.nan)
        lats_1d = np.ma.filled(lat_raw[:], np.nan)

    # Normalize longitude to [-180, 180]
    lons_1d = np.where(lons_1d > 180, lons_1d - 360, lons_1d)

    # Read SSH (first time step if multiple)
    ssh_var = nc.variables['ssh']
    if ssh_var.ndim == 3:
        ssh = ssh_var[0, :, :]  # (MT, Y, X) -> (Y, X)
    else:
        ssh = ssh_var[:, :]

    ssh = np.ma.filled(ssh, np.nan)
    nc.close()

    # Subset to ROI if specified
    if roi is not None:
        lon_min, lon_max, lat_min, lat_max = roi
        # Find indices (with small buffer)
        buf = 0.5  # degrees
        ix = np.where((lons_1d >= lon_min - buf) & (lons_1d <= lon_max + buf))[0]
        iy = np.where((lats_1d >= lat_min - buf) & (lats_1d <= lat_max + buf))[0]

        if len(ix) == 0 or len(iy) == 0:
            raise ValueError(
                f"ROI ({lon_min},{lon_max},{lat_min},{lat_max}) "
                f"outside RTOFS domain ({lons_1d.min():.1f},{lons_1d.max():.1f},"
                f"{lats_1d.min():.1f},{lats_1d.max():.1f})")

        ssh = ssh[iy[0]:iy[-1]+1, ix[0]:ix[-1]+1]
        lats_1d = lats_1d[iy[0]:iy[-1]+1]
        lons_1d = lons_1d[ix[0]:ix[-1]+1]

    return ssh, lats_1d, lons_1d


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------

def interpolate_ssh_to_boundary(ssh, lats, lons, bnd_lons, bnd_lats):
    """Interpolate SSH from RTOFS grid to boundary node locations.

    Uses scipy RegularGridInterpolator (bilinear) if available,
    otherwise falls back to simple nearest-neighbor.

    Args:
        ssh: 2D array [nlat, nlon] of SSH values (NaN for missing).
        lats: 1D array of latitudes (must be monotonic).
        lons: 1D array of longitudes (must be monotonic).
        bnd_lons: 1D array of boundary node longitudes.
        bnd_lats: 1D array of boundary node latitudes.

    Returns:
        1D array of SSH at boundary nodes.
    """
    n_bnd = len(bnd_lons)

    # Fill NaN with nearest valid value (extrapolation for coastal nodes)
    ssh_filled = _fill_nearest(ssh)

    if RegularGridInterpolator is not None:
        # Ensure monotonically increasing coordinates
        if lats[0] > lats[-1]:
            lats = lats[::-1]
            ssh_filled = ssh_filled[::-1, :]
        if lons[0] > lons[-1]:
            lons = lons[::-1]
            ssh_filled = ssh_filled[:, ::-1]

        interp = RegularGridInterpolator(
            (lats, lons), ssh_filled,
            method='linear',
            bounds_error=False,
            fill_value=None  # extrapolate
        )
        points = np.column_stack([bnd_lats, bnd_lons])
        ssh_bnd = interp(points)
    else:
        # Fallback: nearest-neighbor
        ssh_bnd = np.zeros(n_bnd)
        for i in range(n_bnd):
            iy = np.argmin(np.abs(lats - bnd_lats[i]))
            ix = np.argmin(np.abs(lons - bnd_lons[i]))
            ssh_bnd[i] = ssh_filled[iy, ix]

    return ssh_bnd.astype(np.float32)


def _fill_nearest(data):
    """Fill NaN values with nearest valid neighbor.

    RTOFS has land-masked (NaN) cells. Boundary nodes near the coast
    may fall in masked cells. Fill NaN with nearest valid value to
    ensure interpolation works everywhere.
    """
    from scipy.ndimage import distance_transform_edt

    mask = np.isnan(data)
    if not mask.any():
        return data.copy()

    filled = data.copy()
    # distance_transform_edt returns indices of nearest non-NaN cell
    _, nearest_idx = distance_transform_edt(mask, return_distances=True,
                                            return_indices=True)
    filled[mask] = data[nearest_idx[0][mask], nearest_idx[1][mask]]
    return filled


def _fill_nearest_simple(data):
    """Simple NaN fill without scipy.ndimage (fallback)."""
    filled = data.copy()
    mask = np.isnan(filled)
    if not mask.any():
        return filled

    # Iterative fill: expand valid values to neighbors
    for _ in range(max(data.shape)):
        if not mask.any():
            break
        # Shift in 4 directions and fill
        for dy, dx in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            shifted = np.roll(np.roll(filled, -dy, axis=0), -dx, axis=1)
            shifted_valid = ~np.isnan(shifted)
            update = mask & shifted_valid
            filled[update] = shifted[update]
            mask = np.isnan(filled)

    return filled


# Override _fill_nearest if scipy.ndimage not available
try:
    from scipy.ndimage import distance_transform_edt
except ImportError:
    _fill_nearest = _fill_nearest_simple


# ---------------------------------------------------------------------------
# elev2D.th.nc writer
# ---------------------------------------------------------------------------

def write_elev2d_th(output_file, times_sec, ssh_data, dt_seconds):
    """Write elev2D.th.nc matching the Fortran gen_3Dth_from_hycom format.

    NetCDF4 format with dimensions:
        one(1), time(UNLIMITED), nOpenBndNodes(N), nLevels(1), nComponents(1)
    Variables:
        time_step(one):    float32, output time step in seconds
        time(time):        float64, time in seconds from model start
        time_series(time, nOpenBndNodes, nLevels, nComponents): float32, SSH

    Args:
        output_file: Output path.
        times_sec: 1D array of time values in seconds.
        ssh_data: 2D array [ntime, nOpenBndNodes] of SSH.
        dt_seconds: Output time step in seconds.
    """
    ntime, n_bnd = ssh_data.shape

    nc = Dataset(output_file, 'w', format='NETCDF4')

    # Dimensions (matching Fortran order)
    nc.createDimension('one', 1)
    nc.createDimension('time', None)  # UNLIMITED
    nc.createDimension('nOpenBndNodes', n_bnd)
    nc.createDimension('nLevels', 1)
    nc.createDimension('nComponents', 1)

    # time_step variable
    ts_var = nc.createVariable('time_step', 'f4', ('one',))
    ts_var[:] = dt_seconds

    # time variable (seconds from model start)
    time_var = nc.createVariable('time', 'f8', ('time',))
    time_var[:] = times_sec

    # time_series: SSH at boundary nodes
    # Fortran dims: (nComponents, nLevels, nOpenBndNodes, time)
    # NetCDF C order: (time, nOpenBndNodes, nLevels, nComponents)
    data_var = nc.createVariable('time_series', 'f4',
                                 ('time', 'nOpenBndNodes', 'nLevels', 'nComponents'))

    for t in range(ntime):
        data_var[t, :, 0, 0] = ssh_data[t, :]

    nc.close()
    print(f"\n  Wrote {output_file}")
    print(f"    nOpenBndNodes = {n_bnd}")
    print(f"    time records  = {ntime}")
    print(f"    time range    = {times_sec[0]:.0f} to {times_sec[-1]:.0f} sec "
          f"({times_sec[-1]/86400:.2f} days)")
    print(f"    time_step     = {dt_seconds:.0f} sec")
    print(f"    SSH range     = {np.nanmin(ssh_data):.4f} to {np.nanmax(ssh_data):.4f} m")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate elev2D.th.nc from RTOFS SSH for SCHISM boundaries")
    parser.add_argument('hgrid', help='Path to hgrid.ll (lon/lat format)')
    parser.add_argument('rtofs_dir', help='RTOFS data directory (contains rtofs.YYYYMMDD/)')
    parser.add_argument('pdy', help='Cycle date YYYYMMDD')
    parser.add_argument('cyc', help='Cycle hour (00, 06, 12, 18)')
    parser.add_argument('ndays', type=float, help='Number of days of output needed')
    parser.add_argument('--dt', type=float, default=21600.0,
                        help='Output time step in seconds (default: 21600 = 6hr)')
    parser.add_argument('--ssh-offset', type=float, default=0.04,
                        help='SSH offset in meters (default: 0.04)')
    parser.add_argument('--boundaries', type=int, nargs='+', default=None,
                        help='Open boundary segment IDs (1-based, default: all)')
    parser.add_argument('-o', '--output', default='elev2D.th.nc',
                        help='Output filename (default: elev2D.th.nc)')
    parser.add_argument('--roi', type=float, nargs=4, default=None,
                        metavar=('LON_MIN', 'LON_MAX', 'LAT_MIN', 'LAT_MAX'),
                        help='RTOFS subsetting ROI (default: auto from boundary nodes)')

    args = parser.parse_args()

    print(f"=== gen_elev2d_th.py ===")
    print(f"  hgrid:      {args.hgrid}")
    print(f"  RTOFS dir:  {args.rtofs_dir}")
    print(f"  Cycle:      {args.pdy} {args.cyc}Z")
    print(f"  Duration:   {args.ndays} days")
    print(f"  dt:         {args.dt} sec")
    print(f"  SSH offset: {args.ssh_offset} m")

    # 1. Read boundary nodes
    print("\n--- Reading boundary nodes ---")
    bnd_lons, bnd_lats = read_hgrid_boundary(args.hgrid, args.boundaries)

    # Determine ROI from boundary nodes if not specified
    if args.roi is not None:
        roi = tuple(args.roi)
    else:
        buf = 2.0  # degree buffer around boundary nodes
        roi = (bnd_lons.min() - buf, bnd_lons.max() + buf,
               bnd_lats.min() - buf, bnd_lats.max() + buf)
    print(f"  ROI: lon=[{roi[0]:.1f}, {roi[1]:.1f}] lat=[{roi[2]:.1f}, {roi[3]:.1f}]")

    # 2. Find RTOFS files
    print("\n--- Finding RTOFS files ---")
    rtofs_files = find_rtofs_files(args.rtofs_dir, args.pdy, args.cyc, args.ndays)

    # 3. Interpolate SSH at each time step
    print("\n--- Interpolating SSH to boundary nodes ---")
    n_bnd = len(bnd_lons)
    all_times = []
    all_ssh = []

    for i, (fpath, offset_sec) in enumerate(rtofs_files):
        try:
            ssh, lats, lons = read_rtofs_ssh(fpath, roi=roi)
            ssh_bnd = interpolate_ssh_to_boundary(ssh, lats, lons, bnd_lons, bnd_lats)

            # Apply SSH offset
            ssh_bnd += args.ssh_offset

            all_times.append(offset_sec)
            all_ssh.append(ssh_bnd)

            fname = os.path.basename(fpath)
            print(f"  [{i+1:3d}/{len(rtofs_files)}] {fname}: "
                  f"t={offset_sec/3600:+7.1f}h  "
                  f"SSH=[{ssh_bnd.min():.3f}, {ssh_bnd.max():.3f}] m")

        except Exception as e:
            print(f"  WARNING: Skipping {fpath}: {e}", file=sys.stderr)
            continue

    if not all_ssh:
        print("ERROR: No SSH data could be read", file=sys.stderr)
        sys.exit(1)

    # 4. Build regular time grid if dt differs from RTOFS interval
    times_sec = np.array(all_times, dtype=np.float64)
    ssh_data = np.array(all_ssh, dtype=np.float32)

    # Check if we need to interpolate to a regular time grid
    actual_dt = np.diff(times_sec)
    if len(actual_dt) > 0 and not np.allclose(actual_dt, args.dt, atol=60):
        print(f"\n  RTOFS interval varies ({actual_dt.min():.0f}-{actual_dt.max():.0f} sec), "
              f"interpolating to dt={args.dt:.0f} sec")
        t_regular = np.arange(times_sec[0], times_sec[-1] + 1, args.dt)
        ssh_regular = np.zeros((len(t_regular), n_bnd), dtype=np.float32)
        for j in range(n_bnd):
            ssh_regular[:, j] = np.interp(t_regular, times_sec, ssh_data[:, j])
        times_sec = t_regular
        ssh_data = ssh_regular

    # Shift time so first record is at t=0
    if times_sec[0] != 0:
        print(f"  Shifting time origin by {times_sec[0]:.0f} sec so first record is t=0")
        times_sec = times_sec - times_sec[0]

    # 5. Write output
    print("\n--- Writing elev2D.th.nc ---")
    write_elev2d_th(args.output, times_sec, ssh_data, args.dt)

    print("\nDone.")


if __name__ == '__main__':
    main()
