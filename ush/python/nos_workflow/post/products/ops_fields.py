"""Production STOFS-3D-ATL field-stack masking and attributes.

Port of ``stofs_3d_atl_add_attr_2d_3d_nc.sh`` (v3.1.5, lines 44-135) plus
``pysh/filter_isolated_ponds.py``, applied IN PLACE to the staged
per-variable stacks so every later product (maxele, adcirc, slab2d,
geopkg, profiles) reads the masked field exactly as production's do.

What production does to each stack, and what this module does:

* ``time`` gets ``units`` "seconds since Y-MM-DD HH:00:00 +U" and
  ``base_date`` "Y MM DD HH U", read from param.nml in production and
  from the stack's own SCHISM ``base_date`` here (the same numbers);
* each data variable gets units, ``data_horizontal_center`` "node",
  ``data_vertical_center`` "full" and ``mesh`` "SCHISM_hgrid"
  (elevation also the xGEOID20B ``long_name``);
* out2d only: ``idmask`` is appended from the fix mask file,
  ``elevation`` is set to -99999 where ``idmask == 1``
  (``missing_value`` -99999), ``vgrid_dummy(nSCHISM_vgrid_layers)`` is
  added, and ``isolatedPondNode(time, node)`` is appended.

``isolatedPondNode`` is a wet node with no path of wet mesh sides to a
wet seed node. Production seeds from the nodes inside the coastal and
lakes shapefile polygons (geopandas + mpi4py + pylib per run); the seed
set is a property of the fixed mesh, so it is precomputed once into
``stofs_3d_atl_pond_seed.npz`` (``tools/gen_stofs_pond_seed.py``) and the
per-record flood fill becomes scipy connected components over the sides
the out2d file already carries. Python 3.8 compatible. MJ (10/05/26)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

FILL_VALUE = -99999.0

_COMMON = {
    "data_horizontal_center": "node",
    "data_vertical_center": "full",
    "mesh": "SCHISM_hgrid",
}

#: file prefix -> {variable: attributes}; production add_attr:72-139
_VAR_ATTRS: Dict[str, Dict[str, Dict[str, str]]] = {
    "out2d": {
        "elevation": dict(
            _COMMON, units="m",
            long_name="water surface elevation above xgeoid20b",
        ),
        "windSpeedX": dict(_COMMON, units="m/s"),
        "windSpeedY": dict(_COMMON, units="m/s"),
    },
    "temperature": {"temperature": dict(_COMMON, units="Degree C")},
    "salinity": {"salinity": dict(_COMMON, units="PSU")},
    "horizontalVelX": {"horizontalVelX": dict(_COMMON, units="m/s")},
    "horizontalVelY": {"horizontalVelY": dict(_COMMON, units="m/s")},
    "zCoordinates": {"zCoordinates": dict(_COMMON, units="m")},
    "verticalVelocity": {"verticalVelocity": dict(_COMMON, units="m/s")},
    "diffusivity": {"diffusivity": dict(_COMMON, units="m2/s")},
}

_NUM = r"[-+]?\d+(?:\.\d*)?"
_BASE_RE = re.compile(
    rf"^\s*(\d{{4}})\D+(\d{{1,2}})\D+(\d{{1,2}})\s+({_NUM})\s*(?:({_NUM}))?\s*$"
)
_ISO_RE = re.compile(
    r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2})(?::\d{2}(?::\d{2})?)?"
)


def parse_base_date(text: str) -> Optional[Tuple[int, int, int, float, float]]:
    """``(Y, M, D, hour, utc)`` from a SCHISM ``base_date`` or ISO-ish text.

    SCHISM writes ``' 2026  9 30      12.00       0.00'``; the post
    stage's fallback is ``'2026-09-30 12:00:00'``. None when neither.
    """
    m = _BASE_RE.match(text or "")
    if m:
        y, mo, d = (int(m.group(i)) for i in (1, 2, 3))
        return y, mo, d, float(m.group(4)), float(m.group(5) or 0.0)
    m = _ISO_RE.match(text or "")
    if m:
        y, mo, d, h = (int(g) for g in m.groups())
        return y, mo, d, float(h), 0.0
    return None


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def time_attrs(parts: Tuple[int, int, int, float, float]) -> Dict[str, str]:
    """Production's ``units`` / ``base_date`` strings for the time variable."""
    y, mo, d, h, utc = parts
    if not float(h).is_integer():
        raise ValueError(f"fractional start hour {h}")
    return {
        "units": f"seconds since {y}-{mo:02d}-{d:02d} {int(h):02d}:00:00 +{_num(utc)}",
        "base_date": f"{y} {mo:02d} {d:02d} {int(h):02d} {_num(utc)}",
    }


def read_idmask(path: Path) -> np.ndarray:
    from netCDF4 import Dataset

    with Dataset(path, "r") as ds:
        return np.asarray(ds.variables["idmask"][:], dtype=np.int32)


def read_pond_seed(path: Path) -> np.ndarray:
    """Seed-node boolean mask from the precomputed npz (bit-packed)."""
    with np.load(path) as z:
        n = int(z["n_nodes"])
        return np.unpackbits(z["seed_bits"])[:n].astype(bool)


def save_pond_seed(path: Path, seed: np.ndarray) -> None:
    np.savez_compressed(
        path,
        n_nodes=np.int64(seed.size),
        seed_bits=np.packbits(np.asarray(seed, dtype=bool)),
    )


def isolated_ponds(
    wet: np.ndarray, seed: np.ndarray, edges: np.ndarray
) -> np.ndarray:
    """Wet nodes not joined to any wet seed through wet-wet mesh sides.

    ``edges`` is (nside, 2) zero-based. Same set as production's BFS over
    ``hg.isidenode`` (``flood_fill_connected_wet_sides``): a node is
    connected iff its component of the wet-side graph holds a wet seed.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    n = wet.size
    both = wet[edges[:, 0]] & wet[edges[:, 1]]
    e = edges[both]
    graph = coo_matrix(
        (np.ones(len(e), dtype=np.int8), (e[:, 0], e[:, 1])), shape=(n, n)
    )
    ncomp, label = connected_components(graph, directed=False)
    reached = np.zeros(ncomp, dtype=bool)
    reached[label[wet & seed]] = True
    return wet & ~reached[label]


def _set_attrs(var, attrs: Dict[str, str]) -> None:
    for key, value in attrs.items():
        var.setncattr(key, value)


def stamp_stack(
    Dataset,
    path: Path,
    prefix: str,
    fallback_base_date: str = "",
    idmask: Optional[np.ndarray] = None,
    pond_seed: Optional[np.ndarray] = None,
    log: Callable[[str], None] = print,
) -> None:
    """Apply the production add_attr step to one staged stack, in place.

    Safe to repeat: attributes are overwritten, ``elevation`` is masked
    to the same value, and the added variables are reused when present.
    ``idmask`` / ``pond_seed`` only matter for ``out2d``; without
    ``idmask`` the file is stamped but not masked.
    """
    with Dataset(path, "a") as ds:
        ds.set_auto_mask(False)
        if "time" in ds.variables:
            tvar = ds.variables["time"]
            parts = parse_base_date(
                str(getattr(tvar, "base_date", ""))
            ) or parse_base_date(fallback_base_date)
            if parts is None:
                log(f"ops_fields: {path.name}: no usable base date; time attrs kept")
            else:
                _set_attrs(tvar, time_attrs(parts))

        for name, attrs in _VAR_ATTRS.get(prefix, {}).items():
            if name in ds.variables:
                _set_attrs(ds.variables[name], attrs)

        if prefix != "out2d":
            return

        nnode = len(ds.dimensions["nSCHISM_hgrid_node"])
        if "nSCHISM_vgrid_layers" not in ds.dimensions:
            ds.createDimension("nSCHISM_vgrid_layers", 49)
        if "vgrid_dummy" not in ds.variables:
            dummy = ds.createVariable(
                "vgrid_dummy", "f8", ("nSCHISM_vgrid_layers",)
            )
            dummy[:] = 0.0

        if idmask is not None:
            if idmask.size != nnode:
                raise ValueError(
                    f"{path.name}: idmask has {idmask.size} nodes, file {nnode}"
                )
            if "idmask" not in ds.variables:
                idv = ds.createVariable("idmask", "i4", ("nSCHISM_hgrid_node",))
                idv.long_name = "Node mask"
                idv[:] = idmask
            masked = idmask == 1
            elev = ds.variables["elevation"]
            for it in range(elev.shape[0]):
                row = elev[it, :]
                row[masked] = FILL_VALUE
                elev[it, :] = row
            elev.setncattr("missing_value", np.float32(FILL_VALUE))

        if pond_seed is not None:
            _append_ponds(ds, nnode, pond_seed, path.name, log)


def _append_ponds(ds, nnode, pond_seed, name, log) -> None:
    if pond_seed.size != nnode:
        log(f"ops_fields: {name}: pond seed has {pond_seed.size} nodes, file {nnode}; skipped")
        return
    needed = ("dryFlagNode", "SCHISM_hgrid_edge_nodes")
    if any(v not in ds.variables for v in needed):
        log(f"ops_fields: {name}: no dryFlagNode/edge table; isolatedPondNode skipped")
        return
    try:
        import scipy.sparse.csgraph  # noqa: F401
    except ImportError as exc:
        log(f"ops_fields: {name}: scipy unavailable ({exc}); isolatedPondNode skipped")
        return

    edges = np.asarray(ds.variables["SCHISM_hgrid_edge_nodes"][:], dtype=np.int64) - 1
    dry = ds.variables["dryFlagNode"]
    nt = dry.shape[0]
    if "isolatedPondNode" in ds.variables:
        pv = ds.variables["isolatedPondNode"]
    else:
        pv = ds.createVariable(
            "isolatedPondNode", "i1", ("time", "nSCHISM_hgrid_node"),
            zlib=True, complevel=4, chunksizes=(1, nnode),
        )
        pv.long_name = "isolated pond node mask"
        pv.flag_values = np.array([0, 1], dtype=np.int8)
        pv.flag_meanings = (
            "0: not an isolated pond node; 1: isolated pond node"
        )
    for it in range(nt):
        wet = np.asarray(dry[it, :]) == 0
        pv[it, :] = isolated_ponds(wet, pond_seed, edges).astype(np.int8)
