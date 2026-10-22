#!/usr/bin/env python3
"""Sanity-check ensemble sflux files: compare members, verify time axis, check variables."""
import os
import sys
import hashlib
import argparse
import numpy as np

def md5_file(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def check_sflux_dir(sflux_dir, label=""):
    """Check a single sflux directory for file inventory and naming."""
    info = {"label": label, "dir": sflux_dir, "files": {}}
    if not os.path.isdir(sflux_dir):
        info["error"] = "directory not found"
        return info
    for f in sorted(os.listdir(sflux_dir)):
        if f.endswith(".nc"):
            fp = os.path.join(sflux_dir, f)
            sz = os.path.getsize(fp)
            info["files"][f] = {"size": sz, "path": fp}
    return info


def check_nc_metadata(path):
    """Read NetCDF metadata: dimensions, variables, time values."""
    try:
        import netCDF4 as nc
    except ImportError:
        return {"error": "netCDF4 not available"}

    meta = {}
    with nc.Dataset(path) as ds:
        meta["dimensions"] = {k: len(v) for k, v in ds.dimensions.items()}
        meta["variables"] = list(ds.variables.keys())
        if "time" in ds.variables:
            t = ds.variables["time"]
            tv = t[:].data.astype(float)
            meta["time_values"] = tv
            meta["time_units"] = getattr(t, "units", "N/A")
            meta["time_base_date"] = getattr(t, "base_date", "N/A")
            # Monotonicity check
            diffs = np.diff(tv)
            meta["time_monotonic"] = bool(np.all(diffs > 0))
            if not meta["time_monotonic"]:
                bad = np.where(diffs <= 0)[0]
                meta["time_non_monotonic_at"] = bad.tolist()
        if "lon" in ds.variables:
            lon = ds.variables["lon"][:].data
            lat = ds.variables["lat"][:].data
            meta["grid_shape"] = lon.shape
            meta["lon_range"] = (float(np.nanmin(lon)), float(np.nanmax(lon)))
            meta["lat_range"] = (float(np.nanmin(lat)), float(np.nanmax(lat)))
        elif "longitude" in ds.variables:
            lon = ds.variables["longitude"][:].data
            lat = ds.variables["latitude"][:].data
            meta["grid_shape"] = lon.shape
            meta["lon_range"] = (float(np.nanmin(lon)), float(np.nanmax(lon)))
            meta["lat_range"] = (float(np.nanmin(lat)), float(np.nanmax(lat)))
    return meta


def compare_nc_variables(path_a, path_b, variables=None):
    """Compare variable data between two NetCDF files."""
    try:
        import netCDF4 as nc
    except ImportError:
        return {"error": "netCDF4 not available"}

    results = {}
    with nc.Dataset(path_a) as da, nc.Dataset(path_b) as db:
        vars_a = set(da.variables.keys())
        vars_b = set(db.variables.keys())
        results["vars_only_in_a"] = sorted(vars_a - vars_b)
        results["vars_only_in_b"] = sorted(vars_b - vars_a)

        check_vars = variables or ["uwind", "vwind", "stmp", "spfh", "prmsl", "prate",
                                    "dlwrf", "dswrf"]
        for v in check_vars:
            if v not in vars_a or v not in vars_b:
                continue
            a = da.variables[v][:].data.astype(float)
            b = db.variables[v][:].data.astype(float)
            if a.shape != b.shape:
                results[v] = {"error": f"shape mismatch: {a.shape} vs {b.shape}"}
                continue

            diff = a - b
            identical = np.array_equal(a, b)
            results[v] = {
                "identical": identical,
                "max_abs_diff": float(np.nanmax(np.abs(diff))),
                "mean_abs_diff": float(np.nanmean(np.abs(diff))),
                "rmsd": float(np.sqrt(np.nanmean(diff ** 2))),
                "a_range": (float(np.nanmin(a)), float(np.nanmax(a))),
                "b_range": (float(np.nanmin(b)), float(np.nanmax(b))),
            }
    return results


def discover_members(base_dir):
    """Find ensemble member directories with sflux subdirectories."""
    members = []
    for d in sorted(os.listdir(base_dir)):
        dp = os.path.join(base_dir, d)
        if not os.path.isdir(dp):
            continue
        # Pattern 1: member_NNN/sflux/
        sflux = os.path.join(dp, "sflux")
        if os.path.isdir(sflux):
            members.append({"name": d, "sflux_dir": sflux})
            continue
        # Pattern 2: NNN/ with sflux files directly
        ncs = [f for f in os.listdir(dp) if f.startswith("sflux_") and f.endswith(".nc")]
        if ncs:
            members.append({"name": d, "sflux_dir": dp})
    return members


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main():
    parser = argparse.ArgumentParser(
        description="Sanity-check ensemble sflux files across members")
    parser.add_argument("base_dir",
                        help="Base directory containing member_NNN/ subdirectories, "
                             "OR two sflux file paths for direct comparison")
    parser.add_argument("--file2", help="Second file for direct two-file comparison")
    parser.add_argument("--vars", nargs="*",
                        help="Variables to compare (default: uwind vwind stmp spfh prmsl prate)")
    parser.add_argument("--md5", action="store_true", help="Compute MD5 checksums (slow for large files)")
    parser.add_argument("--skip-data", action="store_true", help="Skip variable data comparison")
    args = parser.parse_args()

    # --- Mode 1: Direct two-file comparison ---
    if args.file2 or (args.base_dir.endswith(".nc") and os.path.isfile(args.base_dir)):
        if not args.file2:
            print("ERROR: Provide --file2 for direct comparison mode")
            sys.exit(1)
        fa, fb = args.base_dir, args.file2
        print(f"=== Direct File Comparison ===")
        print(f"  A: {fa} ({fmt_size(os.path.getsize(fa))})")
        print(f"  B: {fb} ({fmt_size(os.path.getsize(fb))})")
        if args.md5:
            ma, mb = md5_file(fa), md5_file(fb)
            print(f"  MD5 A: {ma}")
            print(f"  MD5 B: {mb}")
            print(f"  Identical bytes: {ma == mb}")

        print("\n--- File A metadata ---")
        meta_a = check_nc_metadata(fa)
        _print_metadata(meta_a)

        print("\n--- File B metadata ---")
        meta_b = check_nc_metadata(fb)
        _print_metadata(meta_b)

        if not args.skip_data:
            print("\n--- Variable comparison ---")
            cmp = compare_nc_variables(fa, fb, args.vars)
            _print_comparison(cmp)
        return

    # --- Mode 2: Ensemble member comparison ---
    base_dir = args.base_dir
    if not os.path.isdir(base_dir):
        print(f"ERROR: {base_dir} not found")
        sys.exit(1)

    members = discover_members(base_dir)
    if not members:
        print(f"No members found in {base_dir}")
        sys.exit(1)

    print(f"=== Ensemble Sflux Sanity Check ===")
    print(f"Directory: {base_dir}")
    print(f"Members found: {len(members)}\n")

    # --- Phase 1: File inventory ---
    print("--- File Inventory ---")
    all_inventories = {}
    for m in members:
        inv = check_sflux_dir(m["sflux_dir"], m["name"])
        all_inventories[m["name"]] = inv
        nc_files = inv["files"]
        total_sz = sum(f["size"] for f in nc_files.values())
        print(f"\n  {m['name']}/ ({len(nc_files)} NC files, {fmt_size(total_sz)} total)")
        for fn, finfo in sorted(nc_files.items()):
            flag = ""
            if ".0001." in fn:
                flag = " [STOFS naming]"
            elif ".1." in fn:
                flag = " [COMF naming]"
            print(f"    {fn:40s} {fmt_size(finfo['size']):>10s}{flag}")

    # --- Phase 2: MD5 checksums ---
    if args.md5:
        print("\n--- MD5 Checksums ---")
        md5s = {}  # {filename: {member: hash}}
        for m in members:
            inv = all_inventories[m["name"]]
            for fn, finfo in inv["files"].items():
                md5s.setdefault(fn, {})[m["name"]] = md5_file(finfo["path"])

        for fn in sorted(md5s):
            hashes = md5s[fn]
            unique = set(hashes.values())
            status = "IDENTICAL" if len(unique) == 1 else f"DIFFERENT ({len(unique)} unique)"
            print(f"\n  {fn}: {status}")
            for mname, h in sorted(hashes.items()):
                print(f"    {mname}: {h}")

    # --- Phase 3: Time axis check ---
    print("\n--- Time Axis Check ---")
    # Pick one representative air file per member
    for m in members:
        inv = all_inventories[m["name"]]
        air_files = [fn for fn in inv["files"] if fn.startswith("sflux_air")]
        if not air_files:
            print(f"  {m['name']}: no sflux_air file found")
            continue
        for af in sorted(air_files):
            fp = inv["files"][af]["path"]
            meta = check_nc_metadata(fp)
            if "error" in meta:
                print(f"  {m['name']}/{af}: {meta['error']}")
                continue
            tv = meta.get("time_values")
            mono = meta.get("time_monotonic", "N/A")
            units = meta.get("time_units", "N/A")
            bdate = meta.get("time_base_date", "N/A")
            grid = meta.get("grid_shape", "N/A")

            status = "OK" if mono else "NON-MONOTONIC"
            n_times = len(tv) if tv is not None else 0
            t0 = f"{tv[0]:.6f}" if tv is not None and len(tv) > 0 else "?"
            t1 = f"{tv[1]:.6f}" if tv is not None and len(tv) > 1 else "?"
            tn = f"{tv[-1]:.6f}" if tv is not None and len(tv) > 0 else "?"

            print(f"  {m['name']}/{af}:")
            print(f"    grid={grid}, n_times={n_times}, units={units}")
            print(f"    base_date={bdate}")
            print(f"    time[0]={t0}, time[1]={t1}, time[-1]={tn}")
            print(f"    monotonic: {status}")
            if not mono and "time_non_monotonic_at" in meta:
                idxs = meta["time_non_monotonic_at"][:5]
                print(f"    violations at indices: {idxs}")

    # --- Phase 4: Cross-member variable comparison ---
    if not args.skip_data and len(members) >= 2:
        print("\n--- Cross-Member Variable Comparison ---")
        # Find common air file pattern
        ref_inv = all_inventories[members[0]["name"]]
        ref_air = [fn for fn in ref_inv["files"] if fn.startswith("sflux_air")]

        if ref_air:
            ref_fn = sorted(ref_air)[0]  # e.g. sflux_air_1.1.nc or sflux_air_1.0001.nc

            # Build file map: find matching air file in each member
            file_map = {}
            for m in members:
                inv = all_inventories[m["name"]]
                # Try exact match first, then any sflux_air
                if ref_fn in inv["files"]:
                    file_map[m["name"]] = inv["files"][ref_fn]["path"]
                else:
                    candidates = sorted([fn for fn in inv["files"] if fn.startswith("sflux_air")])
                    if candidates:
                        # Prefer the largest file (likely the member-specific one, not GFS fallback)
                        best = max(candidates, key=lambda fn: inv["files"][fn]["size"])
                        file_map[m["name"]] = inv["files"][best]["path"]
                        print(f"  NOTE: {m['name']} using {best} (no {ref_fn})")

            # Compare all pairs
            mnames = sorted(file_map.keys())
            for i in range(len(mnames)):
                for j in range(i + 1, len(mnames)):
                    ma, mb = mnames[i], mnames[j]
                    print(f"\n  {ma} vs {mb}:")
                    cmp = compare_nc_variables(file_map[ma], file_map[mb], args.vars)
                    _print_comparison(cmp, indent=4)

    # --- Phase 5: Summary ---
    print("\n--- Summary ---")
    issues = []

    # Check for .0001.nc and .1.nc coexistence
    for m in members:
        inv = all_inventories[m["name"]]
        prefixes = set()
        for fn in inv["files"]:
            base = fn.rsplit(".", 2)[0]  # e.g. sflux_air_1
            prefixes.add(base)
        for pfx in prefixes:
            has_0001 = f"{pfx}.0001.nc" in inv["files"]
            has_1 = f"{pfx}.1.nc" in inv["files"]
            if has_0001 and has_1:
                issues.append(f"{m['name']}: BOTH {pfx}.0001.nc and {pfx}.1.nc exist "
                              f"(COMF SCHISM reads .1.nc, ignoring .0001.nc)")
            elif has_0001 and not has_1:
                issues.append(f"{m['name']}: Only {pfx}.0001.nc exists "
                              f"(OK for STOFS, WRONG for COMF)")

    if issues:
        print("  ISSUES FOUND:")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("  No naming conflicts detected.")


def _print_metadata(meta):
    if "error" in meta:
        print(f"  Error: {meta['error']}")
        return
    if "dimensions" in meta:
        print(f"  Dimensions: {meta['dimensions']}")
    if "variables" in meta:
        print(f"  Variables: {', '.join(meta['variables'])}")
    if "grid_shape" in meta:
        print(f"  Grid: {meta['grid_shape']}")
    if "lon_range" in meta:
        print(f"  Lon: [{meta['lon_range'][0]:.4f}, {meta['lon_range'][1]:.4f}]")
        print(f"  Lat: [{meta['lat_range'][0]:.4f}, {meta['lat_range'][1]:.4f}]")
    if "time_values" in meta:
        tv = meta["time_values"]
        print(f"  Time: {len(tv)} steps, [{tv[0]:.4f} ... {tv[-1]:.4f}]")
        print(f"  Time units: {meta.get('time_units', 'N/A')}")
        print(f"  Base date: {meta.get('time_base_date', 'N/A')}")
        mono = meta.get("time_monotonic")
        print(f"  Monotonic: {'YES' if mono else 'NO'}")


def _print_comparison(cmp, indent=2):
    pad = " " * indent
    if "error" in cmp:
        print(f"{pad}Error: {cmp['error']}")
        return
    if cmp.get("vars_only_in_a"):
        print(f"{pad}Vars only in A: {cmp['vars_only_in_a']}")
    if cmp.get("vars_only_in_b"):
        print(f"{pad}Vars only in B: {cmp['vars_only_in_b']}")
    for v in sorted(cmp):
        if v.startswith("vars_only"):
            continue
        info = cmp[v]
        if isinstance(info, dict) and "error" in info:
            print(f"{pad}{v}: {info['error']}")
            continue
        if isinstance(info, dict) and "identical" in info:
            if info["identical"]:
                print(f"{pad}{v}: IDENTICAL  range={info['a_range']}")
            else:
                print(f"{pad}{v}: DIFFERENT  max_diff={info['max_abs_diff']:.6g}  "
                      f"mean_diff={info['mean_abs_diff']:.6g}  rmsd={info['rmsd']:.6g}")
                print(f"{pad}  A range: [{info['a_range'][0]:.4f}, {info['a_range'][1]:.4f}]")
                print(f"{pad}  B range: [{info['b_range'][0]:.4f}, {info['b_range'][1]:.4f}]")


if __name__ == "__main__":
    main()
