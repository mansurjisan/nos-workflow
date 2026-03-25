#!/usr/bin/env python3
"""Generate regionally-tuned rough.gr3 for 2D barotropic SCHISM (nchi=1).

Increases bottom roughness z0 on the West Florida shelf / Gulf to damp
over-energetic tides (amplitude ratio 1.5-3.5x vs 3D operational).
Leaves Atlantic coast / Chesapeake unchanged (already well-matched).

Does NOT modify South Florida / Keys east coast — those stations have
good tidal amplitude ratios (~1.0-1.15) but large mean bias (-1.2m).
The mean bias is a missing low-frequency SSH problem, not friction.

The roughness increase is applied with a smooth quadratic taper at
the boundary between Gulf and Atlantic regions.

Stays under nchi=1 (log-law), preserving the existing friction formulation.
Higher z0 → larger Cd via Cd = (κ / ln(dzb/z0))².

Usage:
    # Preview effect without writing (recommended first)
    python3 gen_regional_rough.py <rough.gr3> --stats --gulf-scale 2.0

    # Generate tuned file
    python3 gen_regional_rough.py <rough.gr3> <output_rough.gr3> --gulf-scale 2.0
"""

import argparse
import numpy as np

VONKAR = 0.4  # von Karman constant


def compute_cd(z0, dzb=5.0):
    """Vectorized Cd from log-law for display purposes."""
    cd = np.zeros_like(z0)
    pos = z0 > 0
    ratio = np.maximum(dzb / z0[pos], 1.001)
    cd[pos] = (VONKAR / np.log(ratio)) ** 2
    return cd


def west_florida_scale(lons, lats, gulf_scale, taper_deg=2.0):
    """Scale factor: >1 on West Florida shelf, 1.0 everywhere else.

    Region definition:
      Core Gulf:  lon <= -82°, lat 24°-31° (full scale)
      Taper zone: -82° to -(82-taper_deg)° longitude, quadratic blend
      South Florida / Keys east coast: EXCLUDED (no scaling)

    The taper prevents a sharp friction discontinuity at the region edge.
    """
    scale = np.ones(len(lons))

    # Only apply to West Florida shelf: west of -82°, between lat 24-31°
    # This covers Panama City, Cedar Key, Clearwater, Tampa, Naples
    core = (lons <= -82.0) & (lats >= 24.0) & (lats <= 31.0)
    scale[core] = gulf_scale

    # Taper zone: -82° to -(82 - taper_deg)° — smooth transition to baseline
    taper_east = -82.0
    taper_west = -82.0 + taper_deg  # e.g., -80° for taper_deg=2.0
    taper_mask = (lons > taper_east) & (lons < taper_west) & \
                 (lats >= 26.0) & (lats <= 31.0)  # lat >= 26 to exclude S.Florida
    if taper_mask.any():
        # Normalized distance: 1.0 at taper_east (-82), 0.0 at taper_west (-80)
        frac = (taper_west - lons[taper_mask]) / (taper_west - taper_east)
        frac = np.clip(frac, 0, 1)
        scale[taper_mask] = 1.0 + (gulf_scale - 1.0) * frac ** 2
    return scale


def read_gr3(path):
    """Read rough.gr3. Returns arrays + element lines."""
    with open(path) as f:
        header = f.readline()
        ne, np_ = map(int, f.readline().split())
        node_ids = np.zeros(np_, dtype=int)
        lons = np.zeros(np_)
        lats = np.zeros(np_)
        vals = np.zeros(np_)
        for i in range(np_):
            parts = f.readline().split()
            node_ids[i] = int(parts[0])
            lons[i] = float(parts[1])
            lats[i] = float(parts[2])
            vals[i] = float(parts[3])
            if i % 500000 == 0 and i > 0:
                print(f"  Read {i:,}/{np_:,} nodes...")
        elem_lines = f.readlines()
    return header, ne, np_, node_ids, lons, lats, vals, elem_lines


def main():
    parser = argparse.ArgumentParser(
        description='Generate regionally-tuned rough.gr3 for West Florida shelf')
    parser.add_argument('input', help='Input rough.gr3')
    parser.add_argument('output', nargs='?', help='Output rough.gr3')
    parser.add_argument('--gulf-scale', type=float, default=2.0,
                        help='z0 multiplier for West Florida shelf (default: 2.0). '
                             'Higher z0 → more friction → smaller tidal amplitudes.')
    parser.add_argument('--taper-deg', type=float, default=2.0,
                        help='Taper width in degrees longitude (default: 2.0)')
    parser.add_argument('--dzb', type=float, default=5.0,
                        help='Representative bottom layer thickness for Cd display')
    parser.add_argument('--stats', action='store_true',
                        help='Show statistics only, do not write')
    args = parser.parse_args()

    print(f"Reading: {args.input}")
    header, ne, np_, nids, lons, lats, z0, elem_lines = read_gr3(args.input)
    print(f"  Nodes: {np_:,}, Elements: {ne:,}")

    # Compute scale field
    scale = west_florida_scale(lons, lats, args.gulf_scale, args.taper_deg)

    # Apply: increase z0 in Gulf region
    z0_new = z0.copy()
    active = z0 > 0
    z0_new[active] = z0[active] * scale[active]

    # Compute Cd for display
    cd_old = compute_cd(z0, args.dzb)
    cd_new = compute_cd(z0_new, args.dzb)

    # Stats
    gulf_mask = scale > 1.01
    atl_mask = ~gulf_mask & active

    print(f"\n{'='*70}")
    print(f"  Gulf scale: {args.gulf_scale}x  (nchi=1 log-law preserved)")
    print(f"  Active nodes:        {active.sum():>10,}")
    print(f"  Gulf nodes (scaled): {gulf_mask.sum():>10,}")
    print(f"  Atlantic (unchanged):{atl_mask.sum():>10,}")
    print(f"  Frictionless (z0=0): {(z0 == 0).sum():>10,}")
    print(f"\n  Gulf region (West Florida shelf):")
    print(f"    z0:  {z0[gulf_mask & active].mean():.8f} → {z0_new[gulf_mask & active].mean():.8f}")
    print(f"    Cd:  {cd_old[gulf_mask & active].mean():.6f} → {cd_new[gulf_mask & active].mean():.6f}"
          f"  ({cd_new[gulf_mask & active].mean()/cd_old[gulf_mask & active].mean():.2f}x)")
    print(f"  Atlantic (unchanged):")
    print(f"    z0:  {z0[atl_mask].mean():.8f}")
    print(f"    Cd:  {cd_old[atl_mask].mean():.6f}")

    # Station check
    stations = [
        ("Panama City Beach", -85.878, 30.213),
        ("Cedar Key",         -83.102, 29.085),
        ("Clearwater Beach",  -82.832, 27.978),
        ("Old Port Tampa",    -82.553, 27.858),
        ("Naples",            -81.808, 26.132),
        ("Key West",          -81.808, 24.551),
        ("Virginia Key",      -80.162, 25.731),
        ("Norfolk",           -76.330, 36.947),
        ("Charleston",        -79.925, 32.782),
        ("Baltimore",         -76.579, 39.267),
    ]
    print(f"\n  Effect at key stations:")
    print(f"  {'Station':<25s} {'z0_old':>10s} {'z0_new':>10s} {'scale':>6s} {'Cd_old':>8s} {'Cd_new':>8s}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*6} {'-'*8} {'-'*8}")
    for name, slon, slat in stations:
        dist = np.sqrt((lons - slon)**2 + (lats - slat)**2)
        idx = dist.argmin()
        print(f"  {name:<25s} {z0[idx]:10.8f} {z0_new[idx]:10.8f} "
              f"{scale[idx]:5.2f}x {cd_old[idx]:.6f} {cd_new[idx]:.6f}")
    print(f"{'='*70}")

    if args.stats:
        return
    if not args.output:
        parser.error("Output file required (or use --stats)")

    print(f"\nWriting: {args.output}")
    with open(args.output, 'w') as f:
        f.write(f"! rough.gr3 regional tuning: Gulf z0 x{args.gulf_scale} (nchi=1)\n")
        f.write(f"{ne} {np_}\n")
        for i in range(np_):
            f.write(f"{nids[i]} {lons[i]:.8f} {lats[i]:.8f} {z0_new[i]:.8f}\n")
        for line in elem_lines:
            f.write(line)
    print(f"Done.")


if __name__ == '__main__':
    main()
