#!/usr/bin/env python3
"""
Verify DATM forcing files and ESMF meshes for UFS-Coastal ensemble.

Checks:
  1. Forcing file dimensions and variables
  2. ESMF mesh consistency (node count, elementMask, coordinates)
  3. datm_in nx_global/ny_global match forcing dims
  4. Member 000 vs DET forcing/mesh identity
  5. GEFS member mesh matches their forcing grid

Usage:
  python3 verify_datm.py --comout /path/to/comout/secofs_ufs.YYYYMMDD
  python3 verify_datm.py --comout /path/to/comout/secofs_ufs.YYYYMMDD --cycle t12z
  python3 verify_datm.py --workdir /path/to/work/member_000  # check single member workdir
"""

import argparse
import hashlib
import os
import re
import sys

try:
    from netCDF4 import Dataset
    import numpy as np
    HAS_NC = True
except ImportError:
    HAS_NC = False


def md5sum(filepath):
    """Compute MD5 checksum of a file."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_forcing_dims(nc_path):
    """Read forcing file dimensions. Returns (nx, ny, nt, dim_names)."""
    ds = Dataset(nc_path, "r")
    dims = list(ds.dimensions.keys())
    nx = ny = nt = None
    xname = yname = None

    for xn, yn in [("x", "y"), ("longitude", "latitude")]:
        if xn in ds.dimensions and yn in ds.dimensions:
            nx = len(ds.dimensions[xn])
            ny = len(ds.dimensions[yn])
            xname, yname = xn, yn
            break

    if "time" in ds.dimensions:
        nt = len(ds.dimensions["time"])

    variables = sorted(ds.variables.keys())
    ds.close()
    return nx, ny, nt, xname, yname, dims, variables


def get_mesh_info(nc_path):
    """Read ESMF mesh metadata."""
    ds = Dataset(nc_path, "r")
    info = {}
    info["nodeCount"] = len(ds.dimensions.get("nodeCount", []))
    info["elementCount"] = len(ds.dimensions.get("elementCount", []))
    info["has_elementMask"] = "elementMask" in ds.variables
    info["has_centerCoords"] = "centerCoords" in ds.variables
    info["has_nodeCoords"] = "nodeCoords" in ds.variables

    if info["has_elementMask"]:
        mask = ds.variables["elementMask"][:]
        info["mask_min"] = int(np.min(mask))
        info["mask_max"] = int(np.max(mask))
        info["mask_zeros"] = int(np.sum(mask == 0))

    if info["has_nodeCoords"]:
        coords = ds.variables["nodeCoords"][:]
        info["lon_min"] = float(np.min(coords[:, 0]))
        info["lon_max"] = float(np.max(coords[:, 0]))
        info["lat_min"] = float(np.min(coords[:, 1]))
        info["lat_max"] = float(np.max(coords[:, 1]))

    info["variables"] = sorted(ds.variables.keys())
    info["dimensions"] = {k: len(v) for k, v in ds.dimensions.items()}
    ds.close()
    return info


def parse_datm_in(filepath):
    """Parse datm_in for nx_global and ny_global."""
    nx = ny = None
    if not os.path.isfile(filepath):
        return nx, ny
    with open(filepath) as f:
        for line in f:
            m = re.search(r"nx_global\s*=\s*(\d+)", line)
            if m:
                nx = int(m.group(1))
            m = re.search(r"ny_global\s*=\s*(\d+)", line)
            if m:
                ny = int(m.group(1))
    return nx, ny


def check_dir(label, dirpath, expected_scrip_nodes=None):
    """Check a single DATM input directory (forcing + mesh + datm_in)."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    forcing = os.path.join(dirpath, "datm_forcing.nc")
    mesh = os.path.join(dirpath, "datm_esmf_mesh.nc")
    datm_in_candidates = [
        os.path.join(dirpath, "datm_in"),
        os.path.join(os.path.dirname(dirpath), "datm_in"),
    ]

    errors = []
    info = {"dir": dirpath}

    # --- Forcing file ---
    if not os.path.isfile(forcing):
        print(f"  FORCING:  MISSING — {forcing}")
        errors.append("forcing file missing")
    else:
        sz = os.path.getsize(forcing) / (1024 * 1024)
        info["forcing_md5"] = md5sum(forcing)
        print(f"  FORCING:  {forcing}")
        print(f"    Size:   {sz:.1f} MB")
        print(f"    MD5:    {info['forcing_md5']}")

        if HAS_NC:
            nx, ny, nt, xn, yn, dims, variables = get_forcing_dims(forcing)
            info["nx"] = nx
            info["ny"] = ny
            print(f"    Dims:   {xn}={nx}, {yn}={ny}, time={nt}")
            print(f"    Vars:   {', '.join(variables)}")

            # Check expected variables for DATM
            expected = {
                "UGRD_10maboveground", "VGRD_10maboveground",
                "TMP_2maboveground", "MSLMA_meansealevel",
            }
            missing_vars = expected - set(variables)
            if missing_vars:
                print(f"    WARN:   Missing expected vars: {missing_vars}")

    # --- ESMF mesh ---
    if not os.path.isfile(mesh):
        print(f"  MESH:     MISSING — {mesh}")
        errors.append("mesh file missing")
    else:
        sz = os.path.getsize(mesh) / (1024 * 1024)
        info["mesh_md5"] = md5sum(mesh)
        print(f"  MESH:     {mesh}")
        print(f"    Size:   {sz:.1f} MB")
        print(f"    MD5:    {info['mesh_md5']}")

        if HAS_NC:
            mi = get_mesh_info(mesh)
            info["mesh_info"] = mi
            print(f"    Nodes:  {mi['nodeCount']}")
            print(f"    Elems:  {mi['elementCount']}")

            if mi["has_elementMask"]:
                print(f"    Mask:   min={mi['mask_min']}, max={mi['mask_max']}, "
                      f"zeros={mi['mask_zeros']}")
                if mi["mask_zeros"] > 0:
                    pct = 100.0 * mi["mask_zeros"] / mi["elementCount"]
                    print(f"    WARN:   {mi['mask_zeros']} masked elements "
                          f"({pct:.1f}%) — check if intentional")
                if mi["mask_max"] == 0:
                    print(f"    ERROR:  ALL elements masked (mask=0) — "
                          f"ATM forcing will be zero!")
                    errors.append("all elements masked")
            else:
                print(f"    Mask:   ABSENT (ESMF defaults to all-active)")

            if mi["has_nodeCoords"]:
                print(f"    Lon:    [{mi['lon_min']:.4f}, {mi['lon_max']:.4f}]")
                print(f"    Lat:    [{mi['lat_min']:.4f}, {mi['lat_max']:.4f}]")

            # Check mesh vs forcing consistency
            if "nx" in info and info["nx"] is not None:
                fnx, fny = info["nx"], info["ny"]
                f_total = fnx * fny
                # SCRIP mesh: corner-based nodes = (nx+1)*(ny+1)
                scrip_nodes = (fnx + 1) * (fny + 1)
                # Center-based mesh: nodes = nx*ny
                center_nodes = f_total

                if mi["nodeCount"] == scrip_nodes:
                    print(f"    Match:  SCRIP corner-based ({fnx+1}x{fny+1} = "
                          f"{scrip_nodes} nodes) ✓")
                elif mi["nodeCount"] == center_nodes:
                    print(f"    Match:  Center-based ({fnx}x{fny} = "
                          f"{center_nodes} nodes)")
                    print(f"    WARN:   Not SCRIP method — may differ from prep mesh")
                else:
                    print(f"    WARN:   Node count {mi['nodeCount']} doesn't match "
                          f"forcing {fnx}x{fny} (expected SCRIP={scrip_nodes} "
                          f"or center={center_nodes})")
                    errors.append("mesh/forcing dimension mismatch")

    # --- datm_in ---
    for datm_in_path in datm_in_candidates:
        if os.path.isfile(datm_in_path):
            din_nx, din_ny = parse_datm_in(datm_in_path)
            print(f"  DATM_IN:  {datm_in_path}")
            print(f"    nx_global={din_nx}, ny_global={din_ny}")
            if HAS_NC and "nx" in info and info["nx"] is not None:
                if din_nx != info["nx"] or din_ny != info["ny"]:
                    print(f"    ERROR:  Mismatch! forcing={info['nx']}x{info['ny']}, "
                          f"datm_in={din_nx}x{din_ny}")
                    errors.append("datm_in dims mismatch")
                else:
                    print(f"    Match:  datm_in matches forcing dims ✓")
            break

    if errors:
        print(f"\n  *** {len(errors)} ERROR(S): {', '.join(errors)}")
    else:
        print(f"\n  All checks passed ✓")

    return info, errors


def main():
    parser = argparse.ArgumentParser(
        description="Verify DATM forcing and ESMF mesh for UFS-Coastal ensemble")
    parser.add_argument("--comout", help="COMOUT directory (e.g., .../secofs_ufs.20260311)")
    parser.add_argument("--cycle", default="t12z", help="Cycle (default: t12z)")
    parser.add_argument("--run", default="secofs_ufs", help="RUN prefix (default: secofs_ufs)")
    parser.add_argument("--workdir", help="Check a single member work directory")
    args = parser.parse_args()

    if not HAS_NC:
        print("WARNING: netCDF4 not available — skipping NetCDF checks")
        print("  Install: pip install netCDF4")

    all_errors = []

    if args.workdir:
        # Check a single work directory
        input_dir = os.path.join(args.workdir, "INPUT")
        if os.path.isdir(input_dir):
            info, errs = check_dir(f"WorkDir: {args.workdir}", input_dir)
        else:
            info, errs = check_dir(f"WorkDir: {args.workdir}", args.workdir)
        all_errors.extend(errs)

    elif args.comout:
        if not os.path.isdir(args.comout):
            print(f"ERROR: COMOUT directory not found: {args.comout}")
            sys.exit(1)

        prefix = f"{args.run}.{args.cycle}"

        # DET (control prep output)
        det_dir = os.path.join(args.comout, f"{prefix}.datm_input")
        det_info = None
        if os.path.isdir(det_dir):
            det_info, errs = check_dir("DET (prep output)", det_dir)
            all_errors.extend(errs)
        else:
            print(f"\nDET datm_input not found: {det_dir}")

        # Ensemble members
        member_infos = {}
        ens_dir = os.path.join(args.comout, "ensemble")

        # GEFS prep outputs
        for suffix in sorted(os.listdir(args.comout)):
            if suffix.startswith(f"{prefix}.datm_input_gefs_"):
                gefs_id = suffix.split("_gefs_")[-1]
                gefs_dir = os.path.join(args.comout, suffix)
                info, errs = check_dir(f"GEFS {gefs_id} (prep output)", gefs_dir)
                member_infos[f"gefs_{gefs_id}"] = info
                all_errors.extend(errs)

        # RRFS prep output
        rrfs_dir = os.path.join(args.comout, f"{prefix}.datm_input_rrfs")
        if os.path.isdir(rrfs_dir):
            info, errs = check_dir("RRFS (prep output)", rrfs_dir)
            member_infos["rrfs"] = info
            all_errors.extend(errs)

        # Member work directories (if ensemble ran)
        if os.path.isdir(ens_dir):
            for mdir in sorted(os.listdir(ens_dir)):
                if mdir.startswith("member_"):
                    mid = mdir.replace("member_", "")
                    input_dir = os.path.join(ens_dir, mdir, "INPUT")
                    if os.path.isdir(input_dir) and \
                       os.path.isfile(os.path.join(input_dir, "datm_forcing.nc")):
                        info, errs = check_dir(
                            f"Member {mid} (runtime INPUT)", input_dir)
                        member_infos[f"member_{mid}"] = info
                        all_errors.extend(errs)

        # --- Cross-checks ---
        print(f"\n{'='*60}")
        print(f"  Cross-checks")
        print(f"{'='*60}")

        # Member 000 vs DET forcing
        m000_keys = [k for k in member_infos if k in ("member_000",)]
        if det_info and m000_keys:
            m000 = member_infos[m000_keys[0]]
            if "forcing_md5" in det_info and "forcing_md5" in m000:
                if det_info["forcing_md5"] == m000["forcing_md5"]:
                    print(f"  DET vs member_000 forcing:  IDENTICAL ✓")
                else:
                    print(f"  DET vs member_000 forcing:  DIFFER")
                    print(f"    DET:  {det_info['forcing_md5']}")
                    print(f"    000:  {m000['forcing_md5']}")

            if "mesh_md5" in det_info and "mesh_md5" in m000:
                if det_info["mesh_md5"] == m000["mesh_md5"]:
                    print(f"  DET vs member_000 mesh:     IDENTICAL ✓")
                else:
                    print(f"  DET vs member_000 mesh:     DIFFER")
                    print(f"    DET:  {det_info['mesh_md5']}")
                    print(f"    000:  {m000['mesh_md5']}")
                    all_errors.append("DET and member_000 mesh differ")

        # Check all GEFS members share the same mesh
        gefs_meshes = {k: v.get("mesh_md5") for k, v in member_infos.items()
                       if k.startswith("gefs_") and "mesh_md5" in v}
        if len(set(gefs_meshes.values())) == 1 and gefs_meshes:
            print(f"  GEFS member meshes:         ALL IDENTICAL ✓ "
                  f"({len(gefs_meshes)} members)")
        elif len(set(gefs_meshes.values())) > 1:
            print(f"  GEFS member meshes:         DIFFER!")
            for k, v in gefs_meshes.items():
                print(f"    {k}: {v}")
            all_errors.append("GEFS member meshes differ")

    else:
        parser.print_help()
        sys.exit(1)

    # Summary
    print(f"\n{'='*60}")
    if all_errors:
        print(f"  RESULT: {len(all_errors)} error(s) found")
        for e in all_errors:
            print(f"    - {e}")
        sys.exit(1)
    else:
        print(f"  RESULT: All checks passed ✓")
        sys.exit(0)


if __name__ == "__main__":
    main()
