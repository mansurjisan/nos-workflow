#!/usr/bin/env python3
"""Scale rough.gr3 roughness values for 2D barotropic SCHISM.

Problem: The 3D SECOFS uses nchi=1 (log-law) with rough.gr3 specifying bottom
roughness z0. In the 3D model (63 vertical levels), the near-bed velocity used
for friction is much smaller than the depth-averaged velocity (log-layer profile).
In 2D (3 levels), the "bottom" velocity is essentially depth-averaged, resulting
in ~50-60% higher effective friction and over-damped tides.

This script scales z0 values to compensate. Nodes with z0=0 (frictionless, deep
ocean) are preserved as-is. Nodes with negative values (interpreted by SCHISM as
time-independent Cd, not roughness) are also preserved.

Alternatively, can generate a drag.gr3 for use with nchi=0 (direct Cd specification),
computing Cd from the log-law with a representative bottom-layer thickness.

Usage:
    # Scale roughness by factor (recommended: try 0.01, 0.05, 0.10)
    python3 scale_roughness_2d.py --scale 0.05 <input_rough.gr3> <output_rough.gr3>

    # Generate drag.gr3 with explicit Cd (for nchi=0)
    python3 scale_roughness_2d.py --to-drag --dzb 5.0 <input_rough.gr3> <output_drag.gr3>

    # Generate drag.gr3 with uniform Cd
    python3 scale_roughness_2d.py --uniform-cd 0.001 <input_rough.gr3> <output_drag.gr3>

    # Show statistics only
    python3 scale_roughness_2d.py --stats <input_rough.gr3>
"""

import sys
import math
import argparse


VONKAR = 0.4  # von Karman constant


def read_gr3(path):
    """Read a GR3 file. Returns header lines, node data, and element lines."""
    with open(path) as f:
        lines = f.readlines()

    header = lines[0]  # description
    ne, np_ = map(int, lines[1].split())

    nodes = []
    for i in range(2, 2 + np_):
        parts = lines[i].split()
        node_id = int(parts[0])
        x = float(parts[1])
        y = float(parts[2])
        val = float(parts[3])
        nodes.append((node_id, x, y, val))

    # Element lines (everything after nodes)
    elem_start = 2 + np_
    elem_lines = lines[elem_start:]

    return header, ne, np_, nodes, elem_lines


def write_gr3(path, header, ne, np_, nodes, elem_lines):
    """Write a GR3 file."""
    with open(path, 'w') as f:
        f.write(header)
        f.write(f'{ne} {np_}\n')
        for nid, x, y, val in nodes:
            f.write(f'{nid} {x:.8f} {y:.8f} {val:.8f}\n')
        for line in elem_lines:
            f.write(line)


def compute_cd(z0, dzb):
    """Compute drag coefficient from log-law: Cd = (kappa / ln(dzb/z0))^2"""
    if z0 <= 0:
        return 0.0
    ratio = dzb / z0
    if ratio <= 1:
        return 0.01  # cap at high friction
    return (VONKAR / math.log(ratio)) ** 2


def get_stats(nodes, label=""):
    """Print statistics of node values."""
    vals = [v for _, _, _, v in nodes]
    nonzero = [v for v in vals if v > 0]
    negative = [v for v in vals if v < 0]
    zero = [v for v in vals if v == 0]

    print(f"\n{'='*60}")
    if label:
        print(f"  {label}")
    print(f"  Total nodes:    {len(vals):>10,}")
    print(f"  Zero (no fric): {len(zero):>10,}")
    print(f"  Negative (Cd):  {len(negative):>10,}")
    print(f"  Positive (z0):  {len(nonzero):>10,}")
    if nonzero:
        print(f"  z0 min:         {min(nonzero):>14.8f} m")
        print(f"  z0 max:         {max(nonzero):>14.8f} m")
        print(f"  z0 mean:        {sum(nonzero)/len(nonzero):>14.8f} m")
        # Show Cd for typical depths
        z0_mean = sum(nonzero) / len(nonzero)
        print(f"\n  Log-law Cd at representative depths (z0_mean={z0_mean:.6f}):")
        for dzb in [0.3, 1.0, 2.0, 5.0, 10.0]:
            cd = compute_cd(z0_mean, dzb)
            print(f"    dzb={dzb:5.1f}m  →  Cd = {cd:.6f}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description='Scale rough.gr3 for 2D barotropic SCHISM')
    parser.add_argument('input', help='Input rough.gr3 file')
    parser.add_argument('output', nargs='?', help='Output file')

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--scale', type=float,
                       help='Scale factor for z0 values (e.g., 0.05)')
    group.add_argument('--to-drag', action='store_true',
                       help='Convert rough.gr3 to drag.gr3 (Cd values)')
    group.add_argument('--uniform-cd', type=float,
                       help='Create drag.gr3 with uniform Cd value')
    group.add_argument('--stats', action='store_true',
                       help='Show statistics only, no output file')

    parser.add_argument('--dzb', type=float, default=5.0,
                        help='Bottom layer thickness for Cd calculation '
                             '(default: 5.0m, typical for 2D)')
    parser.add_argument('--min-z0', type=float, default=1e-8,
                        help='Minimum z0 value to prevent numerical issues '
                             '(default: 1e-8)')

    args = parser.parse_args()

    print(f"Reading: {args.input}")
    header, ne, np_, nodes, elem_lines = read_gr3(args.input)

    get_stats(nodes, f"Input: {args.input}")

    if args.stats:
        return

    if not args.output:
        parser.error("Output file required for --scale, --to-drag, --uniform-cd")

    if args.scale is not None:
        # Scale z0 values
        new_nodes = []
        for nid, x, y, val in nodes:
            if val > 0:
                new_val = max(val * args.scale, args.min_z0)
            else:
                new_val = val  # preserve 0 (frictionless) and negative (Cd)
            new_nodes.append((nid, x, y, new_val))

        get_stats(new_nodes, f"Output (scale={args.scale}): {args.output}")

        # Show equivalent Cd comparison
        z0_old = 0.0001  # typical value
        z0_new = z0_old * args.scale
        print(f"\n  For typical z0={z0_old:.6f} → {z0_new:.8f}:")
        for dzb in [2.0, 5.0, 10.0]:
            cd_old = compute_cd(z0_old, dzb)
            cd_new = compute_cd(z0_new, dzb)
            print(f"    dzb={dzb:.0f}m: Cd {cd_old:.6f} → {cd_new:.6f} "
                  f"(ratio={cd_new/cd_old:.3f})")

        write_gr3(args.output,
                  f"! 2D barotropic rough.gr3 (scaled by {args.scale})\n",
                  ne, np_, new_nodes, elem_lines)

    elif args.to_drag:
        # Convert z0 → Cd using log-law
        new_nodes = []
        for nid, x, y, val in nodes:
            if val > 0:
                cd = compute_cd(val, args.dzb)
            elif val < 0:
                cd = abs(val)  # already a Cd
            else:
                cd = 0.0  # frictionless
            new_nodes.append((nid, x, y, cd))

        get_stats(new_nodes, f"Output (drag.gr3, dzb={args.dzb}m): {args.output}")
        write_gr3(args.output,
                  f"! drag.gr3 for nchi=0, computed from rough.gr3 with dzb={args.dzb}m\n",
                  ne, np_, new_nodes, elem_lines)

    elif args.uniform_cd is not None:
        # Uniform Cd
        new_nodes = []
        for nid, x, y, val in nodes:
            if val == 0:
                new_val = 0.0  # keep frictionless nodes
            else:
                new_val = args.uniform_cd
            new_nodes.append((nid, x, y, new_val))

        get_stats(new_nodes, f"Output (uniform Cd={args.uniform_cd}): {args.output}")
        write_gr3(args.output,
                  f"! drag.gr3 for nchi=0, uniform Cd={args.uniform_cd}\n",
                  ne, np_, new_nodes, elem_lines)

    print(f"\nWritten: {args.output}")


if __name__ == '__main__':
    main()
