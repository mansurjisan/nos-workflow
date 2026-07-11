"""Fabricate a tiny 2-rank SCHISM OLDIO output set for combine_output11.

Global mesh: 4 nodes, 2 triangles sharing edge (2,3), 5 unique edges.
  nodes: 1(0,0) 2(1,0) 3(0,1) 4(1,1), depth 5 m, kbp=1
  elem1 = (1,2,3)   owned by rank 0
  elem2 = (2,4,3)   owned by rank 1
Vertical: pure sigma, nvrt=2, kz=1, sigma = -1, 0.

Emits ``local_to_global_00000{0,1}`` (format per combine_output11.f90's
reader: global header, elem/node/side maps, 'Header:' block, vertical
line, then the coords+connectivity blob) and per-rank
``schout_00000{0,1}_1.nc`` with time (i23d=0) and elev (i23d=1, ivs=1).
Node values are ``global_node_id + t/86400`` so the combined result is
value-verifiable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

NP_G, NE_G, NS_G, NVRT, NPROC, KZ = 4, 2, 5, 2, 2, 1
X = {1: 0.0, 2: 1.0, 3: 0.0, 4: 1.0}
Y = {1: 0.0, 2: 0.0, 3: 1.0, 4: 1.0}
DP = 5.0
TIMES: List[float] = [3600.0, 7200.0, 10800.0]

RANKS: Dict[int, dict] = {
    0: {"elems": [1], "nodes": [1, 2, 3], "sides": [1, 2, 3],
        "conn_local": [(3, [1, 2, 3])]},
    1: {"elems": [2], "nodes": [2, 4, 3], "sides": [3, 4, 5],
        "conn_local": [(3, [1, 2, 3])]},
}


def expected_elev():
    """Global (time, node) array the combined/published product must hold."""
    import numpy as np

    return np.array(
        [[g + t / 86400.0 for g in (1, 2, 3, 4)] for t in TIMES],
        dtype="f4",
    )


def generate(out_dir: Path) -> None:
    """Write the full per-rank fixture set into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for rank, spec in RANKS.items():
        _write_l2g(out_dir, rank, spec)
        _write_schout(out_dir, rank, spec)


def _write_l2g(out_dir: Path, rank: int, spec: dict) -> None:
    lines = [f"{NS_G} {NE_G} {NP_G} {NVRT} {NPROC}",
             "local to global mapping:"]
    lines.append(str(len(spec["elems"])))
    lines.extend(f"{i + 1} {g}" for i, g in enumerate(spec["elems"]))
    lines.append(str(len(spec["nodes"])))
    lines.extend(f"{i + 1} {g}" for i, g in enumerate(spec["nodes"]))
    lines.append(str(len(spec["sides"])))
    lines.extend(f"{i + 1} {g}" for i, g in enumerate(spec["sides"]))
    lines.append("Header:")
    lines.append("2026 7 10 0.0 0.0")
    # nrec dtout nspool nvrt kz h0 h_s h_c theta_b theta_f ics
    lines.append(f"{len(TIMES)} 3600.0 1 {NVRT} {KZ} 0.01 1.e6 10.0 0.0 1.0 2")
    # ztot(1..kz-1) empty for kz=1; sigma(1..nvrt-kz+1)
    lines.append("-1.0 0.0")
    conn = [str(len(spec["nodes"])), str(len(spec["elems"]))]
    for g in spec["nodes"]:
        conn.append(f"{X[g]} {Y[g]} {DP} 1")
    for i34, local_nodes in spec["conn_local"]:
        conn.append(f"{i34} " + " ".join(str(n) for n in local_nodes))
    lines.append(" ".join(conn))
    (out_dir / f"local_to_global_{rank:06d}").write_text(
        "\n".join(lines) + "\n"
    )


def _write_schout(out_dir: Path, rank: int, spec: dict) -> None:
    from netCDF4 import Dataset

    with Dataset(out_dir / f"schout_{rank:06d}_1.nc", "w",
                 format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", len(spec["nodes"]))
        tv = ds.createVariable("time", "f8", ("time",))
        tv.setncattr("i23d", 0)
        tv.units = "seconds since 2026-07-10 00:00:00"
        tv[:] = TIMES
        ev = ds.createVariable("elev", "f4", ("time", "nSCHISM_hgrid_node"))
        ev.setncattr("i23d", 1)
        ev.setncattr("ivs", 1)
        for it, t in enumerate(TIMES):
            ev[it, :] = [g + t / 86400.0 for g in spec["nodes"]]


__all__ = ["RANKS", "TIMES", "expected_elev", "generate"]
