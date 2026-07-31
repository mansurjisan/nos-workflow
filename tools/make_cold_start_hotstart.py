#!/usr/bin/env python3
"""Write a rest-state SCHISM hotstart.nc so a new domain can run its first cycle.

There is no working cold-start path in the workflow: stage_hotstart's only
nowcast candidate is $COMOUT/<prefix>.t<cyc>z.<PDY>.init.nowcast.nc, and
nothing generates it for a domain that has never run. This produces that file.

Rest state means elevation 0, velocity 0, turbulence 0, and a uniform T/S
profile -- which is exactly what the operational Fortran generator
(stofs_3d_atl_gen_hot_from_hycom) writes when iuv=0, so SCHISM accepts it by
construction. With ihot=1 the hotstart is the sole initial condition: the
ts.ic / temp.ic / salt.ic path is `if(ihot==0)` in schism_init.F90 and never
runs. Uniform T/S gives zero baroclinic gradient, which is what you want for
a first tides + atmosphere smoke test; swap in RTOFS fields once it runs.

The variable set and dimension ORDER are taken from the Fortran that reads
the file (schism_init.F90) and the one that writes it
(stofs_3d_atl_gen_hot_from_hycom.f90:910+). The order matters and is easy to
invert: Fortran declares dimids fastest-varying first, so

    var3d_dims(1)=ntr_dim; (2)=nv_dim; (3)=node_dim

is (node, nVert, ntracers) as netCDF4-python and ncdump see it. Reversed,
SCHISM reads garbage without raising.

Usage:
    make_cold_start_hotstart.py --hgrid hgrid.gr3 --nvrt 51 --out hotstart.nc
    make_cold_start_hotstart.py ... --temp 5.0 --salt 32.0 --ntracers 2
    make_cold_start_hotstart.py --verify hotstart.nc --hgrid hgrid.gr3 --nvrt 51

Then stage it (the consumer requires NETCDF4_CLASSIC, which this writes):
    cp hotstart.nc $COMOUT/<prefix>.t<cyc>z.<PDY>.init.nowcast.nc

TWO THINGS TO CONFIRM ON THE TARGET MACHINE BEFORE TRUSTING THE OUTPUT:
  * ntracers -- 2 assumes a plain TEM+SAL build. A binary compiled with
    USE_GEN / USE_AGE carries more, and schism_init aborts on a dim mismatch.
  * ns_global -- this computes it from the element table, but SCHISM's own
    count is authoritative. Both are printed in mirror.out as
    "Global Grid Size (ne,np,ns,nvrt)"; a 1-node test run reports it in
    seconds. A mismatch aborts at init rather than corrupting anything.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    from netCDF4 import Dataset
except ImportError:  # pragma: no cover
    sys.exit("netCDF4 is required: module load python, or pip install netCDF4")


def read_hgrid_elements(path: Path):
    """Return (np_global, ne_global, i34, elnode) from an hgrid.gr3.

    Only the header counts and the element table are read; node coordinates
    are skipped, since a rest state needs no geometry.
    """
    with open(path) as fh:
        fh.readline()                                   # comment
        ne, npo = (int(x) for x in fh.readline().split()[:2])
        for _ in range(npo):                            # skip node block
            fh.readline()
        i34 = np.empty(ne, dtype=np.int32)
        elnode = np.full((ne, 4), -1, dtype=np.int64)
        for k in range(ne):
            parts = fh.readline().split()
            n = int(parts[1])
            i34[k] = n
            elnode[k, :n] = [int(v) for v in parts[2:2 + n]]
    return npo, ne, i34, elnode


def count_sides(i34, elnode) -> int:
    """Number of unique element edges -- SCHISM's ns_global.

    grid_subs.F90 counts a side once per element pair, which is exactly the
    number of distinct (min,max) node pairs over every element edge.
    """
    pairs = []
    for n in (3, 4):
        sel = i34 == n
        if not sel.any():
            continue
        block = elnode[sel, :n]
        for j in range(n):
            pairs.append(np.column_stack([block[:, j], block[:, (j + 1) % n]]))
    edges = np.vstack(pairs)
    edges.sort(axis=1)                                  # undirected
    # void-view unique is ~4x faster than np.unique(axis=0) at 10M edges
    view = np.ascontiguousarray(edges).view(
        np.dtype((np.void, edges.dtype.itemsize * 2))
    )
    return int(np.unique(view).size)


def write_hotstart(out: Path, np_global: int, ne_global: int, ns_global: int,
                   nvrt: int, ntracers: int, temp: float, salt: float,
                   block: int = 200_000) -> None:
    ds = Dataset(str(out), "w", format="NETCDF4_CLASSIC")
    try:
        for name, size in (("node", np_global), ("elem", ne_global),
                           ("side", ns_global), ("nVert", nvrt),
                           ("ntracers", ntracers), ("one", 1)):
            ds.createDimension(name, size)

        # ihot=1 discards time/iths/ifile (schism_init.F90:6082-6086, :6114),
        # but they must exist -- every inq_varid is checked.
        for name, dtype, value in (("time", "f8", 0.0), ("iths", "i4", 0),
                                   ("ifile", "i4", 1),
                                   ("nsteps_from_cold", "i4", 0)):
            ds.createVariable(name, dtype, ("one",))[:] = value

        for name, dims, dtype, value in (
            ("idry_e", ("elem",), "i4", 0),
            ("idry_s", ("side",), "i4", 0),
            ("idry", ("node",), "i4", 0),
            ("eta2", ("node",), "f8", 0.0),
            ("cumsum_eta", ("node",), "f8", 0.0),
        ):
            ds.createVariable(name, dtype, dims)[:] = value

        def slab(name, dims, nrow, trailing, fill):
            """Write row-blocks so peak RSS stays ~1 GB instead of ~12."""
            var = ds.createVariable(name, "f8", dims)
            step = max(1, block if not trailing else block // max(1, trailing[0]))
            for i0 in range(0, nrow, step):
                i1 = min(i0 + step, nrow)
                var[i0:i1] = np.full((i1 - i0,) + trailing, fill, dtype="f8")

        slab("we", ("elem", "nVert"), ne_global, (nvrt,), 0.0)
        slab("su2", ("side", "nVert"), ns_global, (nvrt,), 0.0)
        slab("sv2", ("side", "nVert"), ns_global, (nvrt,), 0.0)
        # q2/xl are clamped to their floors at misc_subs.F90:117-122 on the
        # first step, so zeros are safe even with itur=3.
        for name in ("q2", "xl", "dfv", "dfh", "dfq1", "dfq2"):
            slab(name, ("node", "nVert"), np_global, (nvrt,), 0.0)

        # No compression on the tracer arrays: schism_init reads them one
        # element/node at a time from every rank, so compressed chunks would
        # force a full chunk inflate per element across thousands of ranks.
        for name, dims, nrow in (
            ("tr_el", ("elem", "nVert", "ntracers"), ne_global),
            ("tr_nd", ("node", "nVert", "ntracers"), np_global),
            ("tr_nd0", ("node", "nVert", "ntracers"), np_global),
        ):
            var = ds.createVariable(name, "f8", dims)
            for i0 in range(0, nrow, block):
                i1 = min(i0 + block, nrow)
                buf = np.empty((i1 - i0, nvrt, ntracers), dtype="f8")
                buf[..., 0] = temp
                if ntracers > 1:
                    buf[..., 1] = salt
                if ntracers > 2:
                    buf[..., 2:] = 0.0
                var[i0:i1] = buf
    finally:
        ds.close()


_EXPECTED_DIMS = {
    "time": ("one",),
    "iths": ("one",),
    "ifile": ("one",),
    "nsteps_from_cold": ("one",),
    "idry_e": ("elem",),
    "idry_s": ("side",),
    "idry": ("node",),
    "eta2": ("node",),
    "cumsum_eta": ("node",),
    "we": ("elem", "nVert"),
    "su2": ("side", "nVert"),
    "sv2": ("side", "nVert"),
    "tr_el": ("elem", "nVert", "ntracers"),
    "tr_nd": ("node", "nVert", "ntracers"),
    "tr_nd0": ("node", "nVert", "ntracers"),
    "q2": ("node", "nVert"),
    "xl": ("node", "nVert"),
    "dfv": ("node", "nVert"),
    "dfh": ("node", "nVert"),
    "dfq1": ("node", "nVert"),
    "dfq2": ("node", "nVert"),
}
_REQUIRED = tuple(_EXPECTED_DIMS)


def verify(path: Path, np_global: int, ne_global: int, ns_global: int,
           nvrt: int, ntracers: int) -> int:
    ds = Dataset(str(path))
    try:
        problems = []
        for name, size in (("node", np_global), ("elem", ne_global),
                           ("side", ns_global), ("nVert", nvrt),
                           ("ntracers", ntracers)):
            got = len(ds.dimensions[name]) if name in ds.dimensions else None
            if got != size:
                problems.append(f"dim {name}: {got} != {size}")
        for name in _REQUIRED:
            if name not in ds.variables:
                problems.append(f"missing variable {name}")
        for name, dims in _EXPECTED_DIMS.items():
            if name in ds.variables and ds.variables[name].dimensions != dims:
                problems.append(
                    f"{name} dim order {ds.variables[name].dimensions} != {dims}"
                )
        fmt = ds.data_model
        if fmt != "NETCDF4_CLASSIC":
            problems.append(f"format {fmt} != NETCDF4_CLASSIC")
    finally:
        ds.close()

    for p in problems:
        print(f"  FAIL {p}")
    if not problems:
        print("  OK: dims, variable set, dim order and format all as SCHISM expects")
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hgrid", required=True, type=Path)
    ap.add_argument("--nvrt", required=True, type=int)
    ap.add_argument("--out", type=Path, default=Path("hotstart.nc"))
    ap.add_argument("--temp", type=float, default=5.0, help="uniform T (degC)")
    ap.add_argument("--salt", type=float, default=32.0, help="uniform S (psu)")
    ap.add_argument("--ntracers", type=int, default=2)
    ap.add_argument("--ns", type=int, default=None,
                    help="override the computed ns_global (use mirror.out's value)")
    ap.add_argument("--verify", type=Path, default=None,
                    help="check an existing file instead of writing one")
    a = ap.parse_args(argv)

    np_global, ne_global, i34, elnode = read_hgrid_elements(a.hgrid)
    ns_global = a.ns if a.ns is not None else count_sides(i34, elnode)
    print(f"  mesh: np={np_global:,} ne={ne_global:,} ns={ns_global:,} nvrt={a.nvrt}")

    if a.verify is not None:
        return verify(a.verify, np_global, ne_global, ns_global, a.nvrt, a.ntracers)

    gb = (
        (ne_global + 2 * np_global) * a.nvrt * a.ntracers
        + (ne_global + 2 * ns_global + 6 * np_global) * a.nvrt
    ) * 8 / 1e9
    print(f"  writing {a.out} (~{gb:.1f} GB, T={a.temp} S={a.salt}, "
          f"ntracers={a.ntracers})")
    write_hotstart(a.out, np_global, ne_global, ns_global, a.nvrt,
                   a.ntracers, a.temp, a.salt)
    print(f"  wrote {a.out} ({a.out.stat().st_size / 1e9:.2f} GB)")
    return verify(a.out, np_global, ne_global, ns_global, a.nvrt, a.ntracers)


if __name__ == "__main__":
    sys.exit(main())
