"""Lightweight fort.14 summary for fort.15 generation.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/stofs_2d_global), models/adcirc/mesh.py. His Mesh reads every node and
element into Python lists on each prep; the fort.15 writer only needs the
mean position and the land-boundary type counts, so this reads the nodes with
a vectorised parser, skips the elements, and caches the summary by file
identity.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass
from itertools import islice
from pathlib import Path
from typing import Optional

import numpy as np

RIVER_CODES = (22, 32, 52)
TYPE52_CODE = 52


@dataclass(frozen=True)
class MeshInfo:
    n_nodes: int
    n_elements: int
    mean_lon: float
    mean_lat: float
    n_rivers: int
    n_type52: int


def _read_nodes_lonlat(path: Path, n_nodes: int) -> np.ndarray:
    try:
        import pandas as pd

        df = pd.read_csv(
            path, sep=r"\s+", header=None, skiprows=2, nrows=n_nodes,
            usecols=(1, 2), dtype=np.float64,
        )
        return df.to_numpy()
    except ImportError:
        return np.loadtxt(path, skiprows=2, max_rows=n_nodes, usecols=(1, 2))


def _count_boundaries(path: Path, n_nodes: int, n_elements: int):
    n_rivers = n_type52 = 0
    with open(path) as fh:
        deque(islice(fh, 2 + n_nodes + n_elements), maxlen=0)
        n_open = int(fh.readline().split()[0])
        fh.readline()
        for _ in range(n_open):
            size = int(fh.readline().split()[0])
            deque(islice(fh, size), maxlen=0)
        n_land = int(fh.readline().split()[0])
        fh.readline()
        for _ in range(n_land):
            parts = fh.readline().split()
            size, code = int(parts[0]), int(parts[1])
            if code in RIVER_CODES:
                n_rivers += 1
            if code == TYPE52_CODE:
                n_type52 += 1
            deque(islice(fh, size), maxlen=0)
    return n_rivers, n_type52


def _identity(path: Path) -> dict:
    st = path.stat()
    return {"path": str(path), "size": st.st_size, "mtime": int(st.st_mtime)}


def read_mesh_info(mesh_file, cache_file: Optional[Path] = None) -> MeshInfo:
    """Summarise ``mesh_file``; reuse ``cache_file`` when it matches the file identity."""
    path = Path(mesh_file).resolve()
    ident = _identity(path)
    if cache_file is not None and Path(cache_file).is_file():
        try:
            cached = json.loads(Path(cache_file).read_text())
            if cached.get("identity") == ident:
                return MeshInfo(**cached["info"])
        except (ValueError, TypeError, KeyError):
            pass

    with open(path) as fh:
        fh.readline()
        n_elements, n_nodes = (int(v) for v in fh.readline().split()[:2])
    lonlat = _read_nodes_lonlat(path, n_nodes)
    n_rivers, n_type52 = _count_boundaries(path, n_nodes, n_elements)
    info = MeshInfo(
        n_nodes=n_nodes,
        n_elements=n_elements,
        mean_lon=float(lonlat[:, 0].sum() / n_nodes),
        mean_lat=float(lonlat[:, 1].sum() / n_nodes),
        n_rivers=n_rivers,
        n_type52=n_type52,
    )
    if cache_file is not None:
        try:
            Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_file).write_text(
                json.dumps({"identity": ident, "info": asdict(info)}) + "\n")
        except OSError:
            pass
    return info
