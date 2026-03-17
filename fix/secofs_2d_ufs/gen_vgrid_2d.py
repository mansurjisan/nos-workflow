#!/usr/bin/env python3
"""Generate LSC2 (ivcor=1) vgrid.in for 2D barotropic SCHISM.

Reads the node count from hgrid.gr3 and creates a 3-level vgrid.in
with uniform sigma levels (-1.0, -0.5, 0.0) at every node.

Usage:
    python3 gen_vgrid_2d.py [HGRID_PATH] [OUTPUT_PATH]

Defaults:
    HGRID_PATH: secofs_2d_ufs.hgrid.gr3 (in current directory or FIXofs)
    OUTPUT_PATH: secofs_2d_ufs.vgrid.in
"""

import sys
import os
import numpy as np


def get_node_count(hgrid_path):
    """Read node count from line 2 of hgrid.gr3."""
    with open(hgrid_path) as f:
        f.readline()  # comment line
        ne, np_nodes = map(int, f.readline().split())
    return np_nodes


def gen_vgrid_2d(np_nodes, output_path, nvrt=3):
    """Generate ivcor=1 (LSC2) vgrid.in with nvrt levels.

    All nodes get kbp=2 (bottom level is dry fill, 2 wet sigma levels).
    Level 1: -9 (dry fill, below kbp)
    Level 2: -1.0 (bottom)
    Level 3: 0.0 (surface)

    This gives a true 2D barotropic setup matching how the 3D grid
    handles shallow nodes (kbp=62 out of nvrt=63 = 2 wet levels).
    """
    with open(output_path, 'w') as f:
        f.write('1\n')        # ivcor = 1 (LSC2)
        f.write(f'{nvrt}\n')  # nvrt

        # kbp array: all nodes = 2 (2 wet levels: levels 2 and 3)
        kbp = np.full(np_nodes, 2, dtype=int)
        row_size = 20
        for i in range(0, np_nodes, row_size):
            chunk = kbp[i:i + row_size]
            f.write(''.join(f'{v:>11d}' for v in chunk) + '\n')

        # Sigma levels for each node
        # Format: node_index  sigma_1(-9=dry)  sigma_2(-1=bottom)  sigma_3(0=surface)
        sigma_str = f'{"  -9.000000":>14s}{"  -1.000000":>14s}{"   0.000000":>14s}'
        for i in range(np_nodes):
            f.write(f'{i+1:>10d}{sigma_str}\n')

    print(f'Generated: {output_path}')
    print(f'  ivcor=1 (LSC2), nvrt={nvrt}, nodes={np_nodes}')
    print(f'  sigma levels: [-9 (dry), -1.0, 0.0], kbp=2')
    print(f'  file size: {os.path.getsize(output_path) / 1e6:.1f} MB')


if __name__ == '__main__':
    # Parse args
    hgrid = sys.argv[1] if len(sys.argv) > 1 else None
    output = sys.argv[2] if len(sys.argv) > 2 else 'secofs_2d_ufs.vgrid.in'

    # Find hgrid.gr3
    if hgrid is None:
        candidates = [
            'secofs_2d_ufs.hgrid.gr3',
            'hgrid.gr3',
            os.path.join(os.environ.get('FIXofs', '.'), 'secofs_2d_ufs.hgrid.gr3'),
        ]
        for c in candidates:
            if os.path.isfile(c):
                hgrid = c
                break

    if hgrid is None or not os.path.isfile(hgrid):
        print(f'ERROR: hgrid.gr3 not found. Usage: {sys.argv[0]} <hgrid.gr3> [output.vgrid.in]')
        sys.exit(1)

    print(f'Reading node count from: {hgrid}')
    np_nodes = get_node_count(hgrid)
    print(f'  nodes: {np_nodes}')

    gen_vgrid_2d(np_nodes, output)
