#!/usr/bin/env python3
"""Convert 3D bctides.in to 2D barotropic version.

Only strips true 3D ocean tracer sections (itetype=4 → 0, isatype=4 → 0).
All other boundary types (rivers, etc.) are preserved exactly as-is.

Elevation: iettype=5 → 4 (with --with-elev2d) or 5 → 3 (tidal only).
Velocity:  ifltype=5 → 3 (tidal only, no uv3D.th.nc for barotropic).

Usage:
    python3 convert_bctides_2d.py <input_bctides.in> <output_bctides.in>
    python3 convert_bctides_2d.py --with-elev2d <input> <output>
    python3 convert_bctides_2d.py --needs-conversion <input>
        Exit codes: 0 = needs conversion, 1 = already converted, 2 = error
"""

import sys
import re

# Boundary types that indicate unconverted 3D content.
# Note: iettype=5 is valid for 2D (tidal+subtidal with elev2D.th.nc),
# so it is NOT a 3D marker. The true 3D markers are ifltype=5 (needs
# uv3D.th.nc), itetype=4 (3D T profiles), and isatype=4 (3D S profiles).
_3D_MARKERS = {
    'ifltype': {5},
    'itetype': {4},
    'isatype': {4},
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


def _skip_iet(iettype, nbfr, nond):
    """Return number of lines to skip for elevation data."""
    if iettype in [2, 3, 4, 5]:
        return nbfr * (1 + nond)
    return 0


def _skip_ifl(ifltype, nbfr, nond):
    """Return number of lines to skip for velocity data."""
    if ifltype in [2, 3, 4, 5]:
        return nbfr * (1 + nond)
    elif ifltype == -1:
        return nond
    return 0


def _skip_ite(itetype, nond):
    """Return number of lines to skip for temperature data."""
    if itetype == 4:
        return 1  # relax only
    elif itetype in [2, 3]:
        return 1 + nond  # relax + per-node
    elif itetype == 1:
        return 1  # single constant
    return 0


def _skip_isa(isatype, nond):
    """Return number of lines to skip for salinity data."""
    if isatype == 4:
        return 1  # relax only
    elif isatype == 3:
        return 1 + nond  # relax + per-node
    elif isatype == 2:
        return 2  # constant + relax
    elif isatype == 1:
        return 1  # single constant
    return 0


def needs_conversion(input_path):
    """Check if bctides.in still has 3D boundary types that need conversion.

    Returns True if any boundary has iettype=5, ifltype=5, itetype=4, or isatype=4.
    Raises on parse errors.
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
            raise ValueError(f"Unexpected EOF at boundary {bnd+1}, line {i}")
        hdr = _parse_header(lines[i])
        if hdr is None:
            raise ValueError(f"Cannot parse boundary header at line {i+1}: {lines[i].strip()}")
        if (hdr['ifltype'] in _3D_MARKERS['ifltype'] or
            hdr['itetype'] in _3D_MARKERS['itetype'] or
            hdr['isatype'] in _3D_MARKERS['isatype']):
            return True
        i += 1
        i += _skip_iet(hdr['iettype'], nbfr, hdr['nond'])
        i += _skip_ifl(hdr['ifltype'], nbfr, hdr['nond'])
        i += _skip_ite(hdr['itetype'], hdr['nond'])
        i += _skip_isa(hdr['isatype'], hdr['nond'])

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
    ntip = int(lines[i].split()[0])
    out.append(lines[i]); i += 1
    for _ in range(ntip):
        out.append(lines[i]); i += 1
        out.append(lines[i]); i += 1

    # Boundary forcing frequencies
    nbfr = int(lines[i].split()[0])
    out.append(lines[i]); i += 1
    for _ in range(nbfr):
        out.append(lines[i]); i += 1
        out.append(lines[i]); i += 1

    # Number of open boundaries
    nope = int(lines[i].split()[0])
    out.append(lines[i]); i += 1

    for bnd in range(nope):
        m = re.match(r'^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*(.*)', lines[i].strip())
        nond = int(m.group(1))
        iettype = int(m.group(2))
        ifltype = int(m.group(3))
        itetype = int(m.group(4))
        isatype = int(m.group(5))
        comment = m.group(6)
        i += 1

        # Compute new types: only change 3D-specific values
        # iettype=5: tidal (bctides.in) + subtidal (elev2D.th.nc) — keep as 5
        # if elev2D.th.nc exists; otherwise downgrade to 3 (tidal only)
        new_iettype = iettype if (iettype == 5 and with_elev2d) else (3 if iettype == 5 else iettype)
        new_ifltype = 3 if ifltype == 5 else ifltype
        new_itetype = 0 if itetype == 4 else itetype  # only strip 3D ocean
        new_isatype = 0 if isatype == 4 else isatype  # only strip 3D ocean

        out.append(f'{nond} {new_iettype} {new_ifltype} {new_itetype} {new_isatype} {comment}\n')
        print(f'  Boundary {bnd+1}: nond={nond} {comment.strip()} '
              f'iet={iettype}->{new_iettype} ifl={ifltype}->{new_ifltype} '
              f'ite={itetype}->{new_itetype} isa={isatype}->{new_isatype}')

        # --- Elevation data: always preserve ---
        n = _skip_iet(iettype, nbfr, nond)
        for _ in range(n):
            out.append(lines[i]); i += 1

        # --- Velocity data: always preserve ---
        n = _skip_ifl(ifltype, nbfr, nond)
        for _ in range(n):
            out.append(lines[i]); i += 1

        # --- Temperature data ---
        n = _skip_ite(itetype, nond)
        if itetype == 4:
            # 3D ocean: discard payload
            i += n
        else:
            # All other types (0, 1, 2, 3): preserve payload
            for _ in range(n):
                out.append(lines[i]); i += 1

        # --- Salinity data ---
        n = _skip_isa(isatype, nond)
        if isatype == 4:
            # 3D ocean: discard payload
            i += n
        else:
            # All other types (0, 1, 2, 3): preserve payload
            for _ in range(n):
                out.append(lines[i]); i += 1

    # Remaining lines
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

    # --needs-conversion mode
    if '--needs-conversion' in args:
        args.remove('--needs-conversion')
        if not args:
            print(f'Usage: {sys.argv[0]} --needs-conversion <bctides.in>', file=sys.stderr)
            sys.exit(2)
        try:
            result = needs_conversion(args[0])
        except Exception as e:
            print(f'ERROR: {e}', file=sys.stderr)
            sys.exit(2)
        if result:
            print('needs conversion')
            sys.exit(0)
        else:
            print('already converted')
            sys.exit(1)

    # Normal conversion mode
    with_elev2d = '--with-elev2d' in args
    if with_elev2d:
        args.remove('--with-elev2d')
    if len(args) < 2:
        print(f'Usage: {sys.argv[0]} [--with-elev2d] <input_bctides.in> <output_bctides.in>')
        print(f'       {sys.argv[0]} --needs-conversion <bctides.in>')
        sys.exit(1)
    convert_bctides_2d(args[0], args[1], with_elev2d=with_elev2d)
