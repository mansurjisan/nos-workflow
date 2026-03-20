#!/usr/bin/env python3
"""Convert 3D bctides.in to 2D barotropic version.

Only strips true 3D ocean tracer sections (itetype=4 → 0, isatype=4 → 0).
River boundaries (itetype=1, isatype=2) are preserved as-is with their data.

Elevation: iettype=5 → 4 (with --with-elev2d) or 5 → 3 (tidal only).
Velocity:  ifltype=5 → 3 (tidal only, no uv3D.th.nc for barotropic).

Usage:
    python3 convert_bctides_2d.py <input_bctides.in> <output_bctides.in>
    python3 convert_bctides_2d.py --with-elev2d <input> <output>
    python3 convert_bctides_2d.py --needs-conversion <input>
"""

import sys
import re

# Boundary types that indicate unconverted 3D content
_3D_MARKERS = {
    'iettype': {5},       # needs conversion to 3 or 4
    'ifltype': {5},       # needs conversion to 3
    'itetype': {4},       # 3D T profiles → strip
    'isatype': {4},       # 3D S profiles → strip
}


def _parse_header(line):
    """Parse a boundary header line. Returns dict or None."""
    m = re.match(r'^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*(.*)', line.strip())
    if not m:
        return None
    return {
        'nond': int(m.group(1)),
        'iettype': int(m.group(2)),
        'ifltype': int(m.group(3)),
        'itetype': int(m.group(4)),
        'isatype': int(m.group(5)),
        'comment': m.group(6),
    }


def needs_conversion(input_path):
    """Check if bctides.in still has 3D boundary types that need conversion.

    Returns True if any boundary has iettype=5, ifltype=5, itetype=4, or isatype=4.
    """
    with open(input_path) as f:
        lines = f.readlines()

    i = 0
    # Skip header: date/time
    i += 1
    # Skip tidal potential
    ntip = int(lines[i].split()[0]); i += 1
    i += ntip * 2
    # Skip boundary forcing freqs
    nbfr = int(lines[i].split()[0]); i += 1
    i += nbfr * 2
    # Number of open boundaries
    nope = int(lines[i].split()[0]); i += 1

    for bnd in range(nope):
        if i >= len(lines):
            break
        hdr = _parse_header(lines[i])
        if hdr is None:
            break
        if (hdr['iettype'] in _3D_MARKERS['iettype'] or
            hdr['ifltype'] in _3D_MARKERS['ifltype'] or
            hdr['itetype'] in _3D_MARKERS['itetype'] or
            hdr['isatype'] in _3D_MARKERS['isatype']):
            return True
        # Skip past this boundary's data to find the next header
        # (rough skip — just need to check headers, not parse fully)
        i += 1
        # Skip elevation data
        if hdr['iettype'] in [2, 3, 4, 5]:
            for _ in range(nbfr):
                i += 1 + hdr['nond']
        # Skip velocity data
        if hdr['ifltype'] in [2, 3, 4, 5]:
            for _ in range(nbfr):
                i += 1 + hdr['nond']
        elif hdr['ifltype'] == -1:
            i += hdr['nond']
        # Skip T data
        if hdr['itetype'] == 4:
            i += 1
        elif hdr['itetype'] in [2, 3]:
            i += 1 + hdr['nond']
        elif hdr['itetype'] == 1:
            i += 1
        # Skip S data
        if hdr['isatype'] == 4:
            i += 1
        elif hdr['isatype'] in [2, 3]:
            i += 1 + hdr['nond']
        elif hdr['isatype'] == 2:
            i += 2  # constant + relax
        elif hdr['isatype'] == 1:
            i += 1

    return False


def convert_bctides_2d(input_path, output_path, with_elev2d=False):
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
        header = lines[i].strip()
        m = re.match(r'^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*(.*)', header)
        nond = int(m.group(1))
        iettype = int(m.group(2))
        ifltype = int(m.group(3))
        itetype = int(m.group(4))
        isatype = int(m.group(5))
        comment = m.group(6)
        i += 1

        # Elevation: 5→4 (with elev2D.th.nc) or 5→3 (tidal only); others unchanged
        if iettype == 5:
            new_iettype = 4 if with_elev2d else 3
        else:
            new_iettype = iettype

        # Velocity: 5→3 (tidal only); others unchanged
        new_ifltype = 3 if ifltype == 5 else ifltype

        # Temperature: only strip 3D ocean profiles (itetype=4→0); preserve rivers
        new_itetype = 0 if itetype == 4 else itetype

        # Salinity: only strip 3D ocean profiles (isatype=4→0); preserve rivers
        new_isatype = 0 if isatype == 4 else isatype

        out.append(f'{nond} {new_iettype} {new_ifltype} {new_itetype} {new_isatype} {comment}\n')
        print(f'  Boundary {bnd+1}: nond={nond} {comment.strip()} '
              f'iet={iettype}->{new_iettype} ifl={ifltype}->{new_ifltype} '
              f'ite={itetype}->{new_itetype} isa={isatype}->{new_isatype}')

        # --- Elevation data (always preserve) ---
        if iettype in [2, 3, 4, 5]:
            for _ in range(nbfr):
                out.append(lines[i]); i += 1  # constituent name
                for _ in range(nond):
                    out.append(lines[i]); i += 1  # amp phase
        elif iettype == 1:
            pass  # time-history: nothing in bctides.in
        elif iettype == 0:
            pass

        # --- Velocity data (always preserve) ---
        if ifltype in [2, 3, 4, 5]:
            for _ in range(nbfr):
                out.append(lines[i]); i += 1  # constituent name
                for _ in range(nond):
                    out.append(lines[i]); i += 1  # amp phase
        elif ifltype == 1:
            pass
        elif ifltype == -1:
            for _ in range(nond):
                out.append(lines[i]); i += 1
        elif ifltype == 0:
            pass

        # --- Temperature data ---
        if itetype == 4:
            # 3D ocean: SKIP relax line (strip from output)
            i += 1
        elif itetype == 3:
            i += 1  # relax
            for _ in range(nond):
                i += 1
        elif itetype == 2:
            i += 1  # relax
            for _ in range(nond):
                i += 1
        elif itetype == 1:
            # River constant T: PRESERVE in output
            out.append(lines[i]); i += 1
        elif itetype == 0:
            pass

        # --- Salinity data ---
        if isatype == 4:
            # 3D ocean: SKIP relax line (strip from output)
            i += 1
        elif isatype == 3:
            i += 1
            for _ in range(nond):
                i += 1
        elif isatype == 2:
            # River constant S + relax: PRESERVE in output
            out.append(lines[i]); i += 1  # S constant
            out.append(lines[i]); i += 1  # S relax
        elif isatype == 1:
            out.append(lines[i]); i += 1  # single constant S
        elif isatype == 0:
            pass

    # Any remaining lines
    while i < n_lines:
        out.append(lines[i])
        i += 1

    with open(output_path, 'w') as f:
        f.writelines(out)

    print(f'\nConverted: {input_path} -> {output_path}')
    print(f'  Input:  {n_lines} lines')
    print(f'  Output: {len(out)} lines')


if __name__ == '__main__':
    args = sys.argv[1:]

    # --needs-conversion mode: check and exit with 0 (needs) or 1 (already done)
    if '--needs-conversion' in args:
        args.remove('--needs-conversion')
        if not args:
            print(f'Usage: {sys.argv[0]} --needs-conversion <bctides.in>', file=sys.stderr)
            sys.exit(2)
        try:
            result = needs_conversion(args[0])
            if result:
                print('needs conversion')
                sys.exit(0)
            else:
                print('already converted')
                sys.exit(1)
        except Exception as e:
            print(f'ERROR: {e}', file=sys.stderr)
            sys.exit(2)

    # Normal conversion mode
    with_elev2d = '--with-elev2d' in args
    if with_elev2d:
        args.remove('--with-elev2d')
    if len(args) < 2:
        print(f'Usage: {sys.argv[0]} [--with-elev2d] <input_bctides.in> <output_bctides.in>')
        print(f'       {sys.argv[0]} --needs-conversion <bctides.in>')
        sys.exit(1)
    convert_bctides_2d(args[0], args[1], with_elev2d=with_elev2d)
