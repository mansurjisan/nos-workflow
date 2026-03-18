#!/usr/bin/env python3
"""Convert 3D bctides.in to 2D barotropic version.

Changes ocean boundary types from itetype=4/isatype=4 (3D T/S) to
itetype=0/isatype=0 (no T/S), removing all 3D T/S profile data.
River boundaries with itetype=1/isatype=2 are also simplified to 0/0.

Usage:
    python3 convert_bctides_2d.py <input_bctides.in> <output_bctides.in>
"""

import sys
import re


def convert_bctides_2d(input_path, output_path):
    with open(input_path) as f:
        lines = f.readlines()

    out = []
    i = 0
    n_lines = len(lines)

    # Line 1: date/time
    out.append(lines[i]); i += 1

    # Tidal potential section
    parts = lines[i].split()
    ntip = int(parts[0])
    out.append(lines[i]); i += 1
    # Each tidal potential: name line + data line
    for _ in range(ntip):
        out.append(lines[i]); i += 1  # constituent name
        out.append(lines[i]); i += 1  # data

    # Boundary forcing frequencies
    parts = lines[i].split()
    nbfr = int(parts[0])
    out.append(lines[i]); i += 1
    for _ in range(nbfr):
        out.append(lines[i]); i += 1  # constituent name
        out.append(lines[i]); i += 1  # freq, nodal, greenwich

    # Number of open boundaries
    parts = lines[i].split()
    nope = int(parts[0])
    out.append(lines[i]); i += 1

    # Process each open boundary
    for bnd in range(nope):
        # Boundary header: nond iettype ifltype itetype isatype !comment
        header = lines[i].strip()
        m = re.match(r'^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*(.*)', header)
        nond = int(m.group(1))
        iettype = int(m.group(2))
        ifltype = int(m.group(3))
        itetype = int(m.group(4))
        isatype = int(m.group(5))
        comment = m.group(6)
        i += 1

        # For barotropic: zero out T/S types, change elev/flow from
        # type 5 (tidal+subtidal from .th.nc) to type 3 (tidal only from bctides)
        # to avoid needing elev2D.th.nc from RTOFS
        new_iettype = 3 if iettype == 5 else iettype
        new_ifltype = 3 if ifltype == 5 else ifltype
        new_itetype = 0
        new_isatype = 0

        out.append(f'{nond} {new_iettype} {new_ifltype} {new_itetype} {new_isatype} {comment}\n')
        print(f'  Boundary {bnd+1}: nond={nond} {comment.strip()} '
              f'iet={iettype}->{new_iettype} ifl={ifltype}->{new_ifltype} '
              f'ite={itetype}->{new_itetype} isa={isatype}->{new_isatype}')

        # --- Process iettype data (elevation) ---
        if iettype in [2, 3, 4, 5]:
            # Tidal elevation: nbfr constituents, each with nond amp/phase pairs
            for _ in range(nbfr):
                out.append(lines[i]); i += 1  # constituent name
                for _ in range(nond):
                    out.append(lines[i]); i += 1  # amp phase
        elif iettype == 1:
            # Time-history: nothing in bctides.in (read from elev.th)
            pass
        elif iettype == 0:
            pass

        # --- Process ifltype data (flow/velocity) ---
        if ifltype in [2, 3, 4, 5]:
            # Tidal velocity: nbfr constituents, each with nond amp/phase pairs
            for _ in range(nbfr):
                out.append(lines[i]); i += 1  # constituent name
                for _ in range(nond):
                    out.append(lines[i]); i += 1  # amp phase
        elif ifltype == 1:
            # Time-history: nothing in bctides.in
            pass
        elif ifltype == -1:
            # Flanther: one value per node
            for _ in range(nond):
                out.append(lines[i]); i += 1
        elif ifltype == 0:
            pass

        # --- SKIP itetype data (temperature) ---
        # itetype=4: relaxation constant line only (3D profiles in .th.nc files)
        # itetype=3: relax + nond initial values
        # itetype=2: relax + nond initial values
        # itetype=1: nond constant values
        if itetype == 4:
            i += 1  # T relax line
        elif itetype == 3:
            i += 1  # relax
            for _ in range(nond):
                i += 1
        elif itetype == 2:
            i += 1  # relax
            for _ in range(nond):
                i += 1
        elif itetype == 1:
            i += 1  # single constant T value
        elif itetype == 0:
            pass

        # --- SKIP isatype data (salinity) ---
        if isatype == 4:
            i += 1  # S relax line
        elif isatype == 3:
            i += 1
            for _ in range(nond):
                i += 1
        elif isatype == 2:
            i += 1  # S constant value
            i += 1  # S relax
        elif isatype == 1:
            i += 1  # single constant S value
        elif isatype == 0:
            pass

    # Any remaining lines (shouldn't be many)
    while i < n_lines:
        out.append(lines[i])
        i += 1

    with open(output_path, 'w') as f:
        f.writelines(out)

    print(f'\nConverted: {input_path} -> {output_path}')
    print(f'  Input:  {n_lines} lines')
    print(f'  Output: {len(out)} lines')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f'Usage: {sys.argv[0]} <input_bctides.in> <output_bctides.in>')
        sys.exit(1)
    convert_bctides_2d(sys.argv[1], sys.argv[2])
