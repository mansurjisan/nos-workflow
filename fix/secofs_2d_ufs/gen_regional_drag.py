#!/usr/bin/env python3
"""Generate spatially-varying drag.gr3 for 2D barotropic SCHISM (nchi=0).

Creates a drag coefficient field with regional tuning:
  - West Florida shelf / Gulf: HIGHER drag to damp over-energetic tides
  - Atlantic coast / Chesapeake: baseline drag (already well-matched)
  - Deep ocean (z0=0 in rough.gr3): frictionless (Cd=0)

The drag coefficient is computed from rough.gr3 via log-law, then multiplied
by a spatially-varying scale factor. The West Florida region uses a smooth
Gaussian taper to avoid sharp discontinuities.

Usage:
    python3 gen_regional_drag.py <rough.gr3> <output_drag.gr3> [--gulf-scale 3.0]

    # Preview stats without writing
    python3 gen_regional_drag.py <rough.gr3> --stats
"""

import sys
import math
import argparse
import numpy as np

VONKAR = 0.4  # von Karman constant


def compute_cd_array(z0, dzb=5.0):
    """Vectorized Cd from log-law: Cd = (kappa / ln(dzb/z0))^2"""
    cd = np.zeros_like(z0)
    pos = z0 > 0
    ratio = dzb / z0[pos]
    ratio = np.maximum(ratio, 1.001)  # avoid log(<=1)
    cd[pos] = (VONKAR / np.log(ratio)) ** 2
    return cd


def gulf_scale_field(lons, lats, gulf_scale=3.0, taper_width=1.5):
    """Create spatially-varying scale factor.

    West Florida shelf / Gulf of Mexico gets higher drag.
    Smooth Gaussian taper from Gulf to Atlantic.

    Gulf region (high drag):
      - Panama City to Key West: lon < -80.5, lat 24-31
      - Transition zone: 1.5° wide Gaussian taper

    Returns array of scale factors (1.0 = baseline, gulf_scale = Gulf max).
    """
    scale = np.ones(len(lons))

    # Core Gulf region: nodes west of -82° and south of 31°
    # These are clearly on the West Florida shelf
    core_gulf = (lons <= -82.0) & (lats >= 24.0) & (lats <= 31.0)
    scale[core_gulf] = gulf_scale

    # Taper zone: -82° to -80° longitude (smooth transition)
    taper = (lons > -82.0) & (lons < -80.0) & (lats >= 24.0) & (lats <= 31.0)
    if taper.any():
        # Gaussian taper: full scale at -82, baseline at -80
        dist = (lons[taper] - (-80.0)) / (-82.0 - (-80.0))  # 0 at -80, 1 at -82
        dist = np.clip(dist, 0, 1)
        taper_factor = 1.0 + (gulf_scale - 1.0) * dist ** 2  # quadratic taper
        scale[taper] = taper_factor

    # South Florida tip (Key West to Miami): high drag too
    # Below lat 26, east of -82 but south of mainland
    s_florida = (lats < 26.0) & (lats >= 24.0) & (lons > -82.0) & (lons < -80.0)
    scale[s_florida] = np.maximum(scale[s_florida], gulf_scale * 0.8)

    return scale


def main():
    parser = argparse.ArgumentParser(
        description='Generate regional drag.gr3 for 2D barotropic SCHISM')
    parser.add_argument('input', help='Input rough.gr3 file')
    parser.add_argument('output', nargs='?', help='Output drag.gr3 file')
    parser.add_argument('--gulf-scale', type=float, default=3.0,
                        help='Drag scale factor for West Florida shelf (default: 3.0)')
    parser.add_argument('--dzb', type=float, default=5.0,
                        help='Bottom layer thickness for Cd calc (default: 5.0m)')
    parser.add_argument('--stats', action='store_true',
                        help='Show statistics only, no output')
    parser.add_argument('--taper-width', type=float, default=2.0,
                        help='Taper width in degrees (default: 2.0)')
    args = parser.parse_args()

    print(f"Reading: {args.input}")

    # Read gr3
    with open(args.input) as f:
        header = f.readline()
        ne, np_ = map(int, f.readline().split())
        print(f"  Nodes: {np_:,}, Elements: {ne:,}")

        node_ids = np.zeros(np_, dtype=int)
        lons = np.zeros(np_)
        lats = np.zeros(np_)
        z0 = np.zeros(np_)

        for i in range(np_):
            parts = f.readline().split()
            node_ids[i] = int(parts[0])
            lons[i] = float(parts[1])
            lats[i] = float(parts[2])
            z0[i] = float(parts[3])
            if i % 500000 == 0 and i > 0:
                print(f"  Read {i:,}/{np_:,} nodes...")

        # Read element lines
        elem_lines = []
        for _ in range(ne):
            elem_lines.append(f.readline())
        # Any remaining lines
        for line in f:
            elem_lines.append(line)

    # Compute baseline Cd from log-law
    cd_base = compute_cd_array(z0, args.dzb)

    # Apply regional scaling
    scale = gulf_scale_field(lons, lats, args.gulf_scale, args.taper_width)
    cd_regional = cd_base * scale

    # Stats
    active = z0 > 0
    frictionless = z0 == 0

    print(f"\n{'='*70}")
    print(f"  Baseline Cd (from log-law, dzb={args.dzb}m):")
    print(f"    Active nodes:      {active.sum():>10,}")
    print(f"    Frictionless:      {frictionless.sum():>10,}")
    print(f"    Cd min:            {cd_base[active].min():.6f}")
    print(f"    Cd max:            {cd_base[active].max():.6f}")
    print(f"    Cd mean:           {cd_base[active].mean():.6f}")

    print(f"\n  Regional scaling (gulf_scale={args.gulf_scale}):")
    gulf_nodes = scale > 1.01
    print(f"    Gulf nodes (scaled): {gulf_nodes.sum():>8,}")
    print(f"    Atlantic (unscaled): {(~gulf_nodes & active).sum():>8,}")
    print(f"    Gulf Cd mean:        {cd_regional[gulf_nodes & active].mean():.6f}")
    print(f"    Atlantic Cd mean:    {cd_regional[~gulf_nodes & active].mean():.6f}")
    print(f"    Gulf Cd max:         {cd_regional[gulf_nodes & active].max():.6f}")

    # Station-level check
    target_stations = [
        ("Panama City Beach", -85.878, 30.213),
        ("Cedar Key", -83.102, 29.085),
        ("Clearwater Beach", -82.832, 27.978),
        ("Old Port Tampa", -82.553, 27.858),
        ("Naples", -81.808, 26.132),
        ("Key West", -81.808, 24.551),
        ("Virginia Key", -80.162, 25.731),
        ("Norfolk", -76.330, 36.947),
        ("Charleston", -79.925, 32.782),
        ("Baltimore", -76.579, 39.267),
    ]
    print(f"\n  Drag at key stations (nearest node):")
    for name, slon, slat in target_stations:
        dist = np.sqrt((lons - slon)**2 + (lats - slat)**2)
        idx = dist.argmin()
        print(f"    {name:<25s} Cd_base={cd_base[idx]:.6f}  "
              f"scale={scale[idx]:.2f}  Cd_final={cd_regional[idx]:.6f}")

    print(f"{'='*70}")

    if args.stats:
        return

    if not args.output:
        parser.error("Output file required (or use --stats)")

    # Write drag.gr3
    print(f"\nWriting: {args.output}")
    with open(args.output, 'w') as f:
        f.write(f"! drag.gr3 for nchi=0, regional tuning (gulf_scale={args.gulf_scale})\n")
        f.write(f"{ne} {np_}\n")
        for i in range(np_):
            f.write(f"{node_ids[i]} {lons[i]:.8f} {lats[i]:.8f} {cd_regional[i]:.8f}\n")
        for line in elem_lines:
            f.write(line)

    print(f"Done: {args.output}")


if __name__ == '__main__':
    main()
