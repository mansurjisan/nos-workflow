#!/usr/bin/env python3
"""Precompute the isolated-pond seed set for a STOFS mesh.

Production's filter_isolated_ponds.py rebuilds this every cycle: the mesh
nodes that lie inside the coastal and lakes shapefile polygons. It depends
only on the fixed mesh and shapefiles, so it is computed once here and
stored bit-packed as ``stofs_3d_atl_pond_seed.npz`` next to the other fix
files; nos_workflow.post.products.ops_fields reads it at post time and
needs neither geopandas nor mpi4py. Run on a machine with geopandas:

    tools/gen_stofs_pond_seed.py HGRID.gr3 coastal.shp lakes.shp OUT.npz

Inputs for the committed file: stofs.v3.1.5 fix/stofs_3d_atl/
stofs_3d_atl_hgrid.gr3, stofs_3d_atl_coastal.shp, stofs_3d_atl_lakes.shp
(https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/stofs.v3.1.5/fix/stofs_3d_atl/).
The source version and sha256 of each input are stored inside the npz
(prov_* arrays); regenerate it whenever the mesh or polygons change.

MJ (10/05/26)
"""
import hashlib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "ush" / "python")
)
from nos_workflow.post.products.ops_fields import save_pond_seed  # noqa: E402


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    import geopandas as gpd

    hgrid, out = Path(argv[0]), Path(argv[-1])
    with open(hgrid) as f:
        f.readline()
        nnode = int(f.readline().split()[1])
    xy = np.loadtxt(hgrid, skiprows=2, max_rows=nnode, usecols=(1, 2))
    pts = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(xy[:, 0], xy[:, 1]), crs="EPSG:4326"
    )
    seed = np.zeros(nnode, dtype=bool)
    for shp in argv[1:-1]:
        poly = gpd.read_file(shp).to_crs("EPSG:4326")
        hit = gpd.sjoin(pts, poly, how="inner", predicate="within").index.values
        seed[hit] = True
        print(f"{Path(shp).name}: {np.unique(hit).size} nodes")
    prov = {"source": "stofs.v3.1.5 fix/stofs_3d_atl"}
    hashed = [hgrid]
    for a in argv[1:-1]:
        # the .prj drives to_crs, so every shapefile sidecar is hashed
        hashed += [Path(a).with_suffix(x) for x in (".shp", ".shx", ".dbf", ".prj")]
    for path in hashed:
        prov[f"sha256_{path.name}"] = _sha256(path)
    save_pond_seed(out, seed, prov)
    print(f"{int(seed.sum())} seed nodes of {nnode} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
