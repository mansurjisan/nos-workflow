"""
Ensemble Post-Processing

Reads outputs from all ensemble members and computes statistics:
  - Ensemble mean
  - Ensemble spread (standard deviation)
  - Min/max envelope
  - Percentiles (10, 25, 50, 75, 90)

Writes results to ensemble statistics NetCDF files.

Supports SCHISM split output format:
  - out2d_*.nc     -> elevation, windSpeedX, windSpeedY
  - temperature_*.nc -> temperature
  - salinity_*.nc    -> salinity
  - schout_*.nc      -> combined format (legacy)

Usage:
    # From Python
    post = EnsemblePost(member_dirs=[...], output_dir="ensemble_stats/")
    post.compute_statistics()

    # From command line
    python -m nos_ofs.ensemble.ensemble_post \\
        --member-dirs /path/to/member_000 /path/to/member_001 ... \\
        --output-dir /path/to/ensemble_stats
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Map variable names to the SCHISM split output file prefix.
# SCHISM writes each output group to separate files: out2d_N.nc,
# temperature_N.nc, salinity_N.nc, etc.
VARIABLE_FILE_MAP = {
    "elevation": "out2d",
    "windSpeedX": "out2d",
    "windSpeedY": "out2d",
    "dryFlagNode": "out2d",
    "temperature": "temperature",
    "salinity": "salinity",
    "horizontalVelX": "horizontalVelX",
    "horizontalVelY": "horizontalVelY",
}


class EnsemblePost:
    """Compute ensemble statistics from member outputs.

    Handles SCHISM split output format where each variable group is
    written to separate files (out2d_*.nc, temperature_*.nc, etc.)
    as well as the legacy combined schout_*.nc format.

    When netCDF4/numpy are not available (e.g., on login nodes), the class
    can still be instantiated for file discovery and member validation.
    Statistics computation requires netCDF4 and numpy.
    """

    # Default SCHISM output variables to process
    DEFAULT_VARIABLES = [
        "elevation",      # Sea surface height (in out2d_*.nc)
        "temperature",    # Water temperature (in temperature_*.nc)
        "salinity",       # Salinity (in salinity_*.nc)
    ]

    # Percentiles to compute
    PERCENTILES = [10, 25, 50, 75, 90]

    # Recognized SCHISM output file prefixes
    OUTPUT_PREFIXES = [
        "out2d", "temperature", "salinity",
        "horizontalVelX", "horizontalVelY",
        "schout",
    ]

    def __init__(
        self,
        member_dirs: List[str],
        output_dir: str,
        variables: Optional[List[str]] = None,
    ):
        """Initialize ensemble post-processor.

        Args:
            member_dirs: List of paths to member output directories.
                         Each should contain SCHISM outputs/ subdirectory.
            output_dir: Directory to write ensemble statistics.
            variables: List of variable names to process. Defaults to
                       DEFAULT_VARIABLES.
        """
        self.member_dirs = sorted(member_dirs)
        self.output_dir = output_dir
        self.variables = variables or self.DEFAULT_VARIABLES
        self.n_members = len(member_dirs)

        if self.n_members < 2:
            raise ValueError(
                f"Need at least 2 members for ensemble statistics "
                f"(got {self.n_members})"
            )

    @classmethod
    def from_comout(
        cls,
        comout: str,
        n_members: int,
        variables: Optional[List[str]] = None,
    ) -> "EnsemblePost":
        """Create from standard COMOUT ensemble directory layout.

        Expects: $COMOUT/ensemble/member_000/, member_001/, etc.
        """
        ens_dir = os.path.join(comout, "ensemble")
        member_dirs = []
        for i in range(n_members):
            mid = f"{i:03d}"
            mdir = os.path.join(ens_dir, f"member_{mid}")
            if os.path.isdir(mdir):
                member_dirs.append(mdir)
            else:
                print(f"WARNING: Member directory not found: {mdir}",
                      file=sys.stderr)

        output_dir = os.path.join(ens_dir, "stats")
        return cls(member_dirs, output_dir, variables)

    @staticmethod
    def _is_schism_output(filename: str) -> bool:
        """Check if a filename matches SCHISM output naming patterns."""
        if not filename.endswith(".nc"):
            return False
        for prefix in EnsemblePost.OUTPUT_PREFIXES:
            if filename.startswith(f"{prefix}_"):
                return True
        return False

    def validate_members(self) -> Tuple[bool, List[str]]:
        """Check that all member directories exist and contain outputs."""
        issues = []
        for mdir in self.member_dirs:
            if not os.path.isdir(mdir):
                issues.append(f"Directory not found: {mdir}")
                continue

            outputs_dir = os.path.join(mdir, "outputs")
            if not os.path.isdir(outputs_dir):
                issues.append(f"No outputs/ directory in {mdir}")
                continue

            nc_files = [
                f for f in os.listdir(outputs_dir)
                if self._is_schism_output(f)
            ]
            if not nc_files:
                issues.append(
                    f"No SCHISM output files in {outputs_dir} "
                    f"(expected out2d_*.nc, temperature_*.nc, "
                    f"salinity_*.nc, or schout_*.nc)"
                )

        return (len(issues) == 0, issues)

    def discover_output_files(self) -> Dict[str, List[str]]:
        """Find matching output files across all members.

        Returns:
            Dict mapping filename to list of full paths (one per member).
            Only includes files present in ALL members.
        """
        member_files = {}
        for mdir in self.member_dirs:
            outputs_dir = os.path.join(mdir, "outputs")
            if os.path.isdir(outputs_dir):
                files = set(
                    f for f in os.listdir(outputs_dir)
                    if self._is_schism_output(f)
                )
                member_files[mdir] = files
            else:
                member_files[mdir] = set()

        if not member_files:
            return {}

        common_files = set.intersection(*member_files.values())

        result = {}
        for fname in sorted(common_files):
            result[fname] = [
                os.path.join(mdir, "outputs", fname)
                for mdir in self.member_dirs
            ]

        return result

    def _get_file_prefix(self, varname: str) -> str:
        """Get the SCHISM output file prefix for a given variable."""
        return VARIABLE_FILE_MAP.get(varname, varname)

    def _group_files_by_variable(
        self, output_files: Dict[str, List[str]]
    ) -> Dict[str, Dict[str, List[str]]]:
        """Group discovered files by the variable they contain.

        Returns:
            Dict mapping variable name to {filename: [member_paths]}.
        """
        # Determine which variables map to which file prefixes
        var_to_prefix = {}
        for var in self.variables:
            var_to_prefix[var] = self._get_file_prefix(var)

        # Group files by prefix
        result = {}
        for var, prefix in var_to_prefix.items():
            matching = {}
            for fname, paths in output_files.items():
                if fname.startswith(f"{prefix}_"):
                    matching[fname] = paths
            if matching:
                result[var] = matching

        return result

    def compute_statistics(self) -> List[str]:
        """Compute ensemble statistics for all output files and variables.

        Handles SCHISM split output: each variable is in its own file
        series (out2d_N.nc, temperature_N.nc, etc.). Statistics are
        computed per-file to manage memory on large grids.

        Requires netCDF4 and numpy.

        Returns:
            List of paths to generated statistics files.
        """
        try:
            import netCDF4 as nc
            import numpy as np
        except ImportError as e:
            raise RuntimeError(
                f"Ensemble statistics require netCDF4 and numpy: {e}\n"
                "Install with: pip install netCDF4 numpy"
            )

        os.makedirs(self.output_dir, exist_ok=True)

        output_files = self.discover_output_files()
        if not output_files:
            raise RuntimeError(
                "No common output files found across members. "
                "Check that all member outputs/ directories contain "
                "matching SCHISM output files."
            )

        # Group files by variable to process each variable's file series
        var_files = self._group_files_by_variable(output_files)

        if not var_files:
            # Fallback: process all files and look for variables inside
            print("No variable-to-file mapping matched. "
                  "Processing all output files...")
            var_files = {"_all": output_files}

        generated = []

        for varname, file_dict in var_files.items():
            for fname, member_paths in sorted(file_dict.items()):
                stats_fname = f"ens_stats_{fname}"
                stats_path = os.path.join(self.output_dir, stats_fname)
                print(f"Processing {fname} ({self.n_members} members)...")

                # Determine which variables to extract from this file
                if varname == "_all":
                    target_vars = list(self.variables)
                else:
                    target_vars = [varname]

                with nc.Dataset(member_paths[0], "r") as ref_ds:
                    dims = {
                        name: (len(dim) if not dim.isunlimited() else None)
                        for name, dim in ref_ds.dimensions.items()
                    }
                    time_var = ref_ds.variables.get("time")
                    time_data = time_var[:] if time_var is not None else None
                    time_units = (
                        getattr(time_var, "units", "")
                        if time_var is not None else ""
                    )

                    # Find which target variables exist in this file
                    found_vars = [
                        v for v in target_vars
                        if v in ref_ds.variables
                    ]
                    if not found_vars:
                        print(f"  Skipping {fname}: none of "
                              f"{target_vars} found")
                        continue

                    with nc.Dataset(stats_path, "w",
                                    format="NETCDF4") as out_ds:
                        # Copy dimensions
                        for dname, dsize in dims.items():
                            out_ds.createDimension(dname, dsize)

                        # Copy time variable
                        if time_data is not None:
                            t = out_ds.createVariable(
                                "time", "f8", ("time",)
                            )
                            t[:] = time_data
                            if time_units:
                                t.units = time_units

                        # Copy coordinate variables (lon, lat, depth)
                        for coord in [
                            "SCHISM_hgrid_node_x",
                            "SCHISM_hgrid_node_y",
                            "depth",
                        ]:
                            if coord in ref_ds.variables:
                                cv = ref_ds.variables[coord]
                                ov = out_ds.createVariable(
                                    coord, cv.dtype, cv.dimensions,
                                    zlib=True,
                                )
                                ov[:] = cv[:]
                                for attr in cv.ncattrs():
                                    if attr != "_FillValue":
                                        setattr(ov, attr, getattr(cv, attr))

                        # Global attributes
                        out_ds.title = (
                            f"NOS-OFS Ensemble Statistics "
                            f"({self.n_members} members)"
                        )
                        out_ds.source = "nos_ofs.ensemble.ensemble_post"
                        out_ds.source_file = fname
                        out_ds.n_members = self.n_members
                        out_ds.member_dirs = json.dumps(
                            [os.path.basename(d) for d in self.member_dirs]
                        )

                        for vname in found_vars:
                            ref_var = ref_ds.variables[vname]
                            var_dims = ref_var.dimensions
                            var_shape = ref_var.shape

                            print(f"  {vname} {var_dims} {var_shape}")

                            # Load all member data for this variable
                            all_data = np.empty(
                                (self.n_members,) + var_shape,
                                dtype=np.float64,
                            )
                            all_data[0, :] = ref_var[:]

                            for m_idx in range(1, self.n_members):
                                with nc.Dataset(
                                    member_paths[m_idx], "r"
                                ) as m_ds:
                                    if vname in m_ds.variables:
                                        all_data[m_idx, :] = (
                                            m_ds.variables[vname][:]
                                        )
                                    else:
                                        all_data[m_idx, :] = np.nan

                            # Compute statistics along member axis
                            fill = getattr(ref_var, "_FillValue", None)
                            kw = {"zlib": True, "complevel": 4}
                            if fill is not None:
                                kw["fill_value"] = fill

                            stats = {
                                "mean": np.nanmean(all_data, axis=0),
                                "spread": np.nanstd(
                                    all_data, axis=0, ddof=1
                                ),
                                "min": np.nanmin(all_data, axis=0),
                                "max": np.nanmax(all_data, axis=0),
                            }

                            for stat_name, stat_data in stats.items():
                                v = out_ds.createVariable(
                                    f"{vname}_{stat_name}", "f4",
                                    var_dims, **kw,
                                )
                                v[:] = stat_data
                                v.long_name = (
                                    f"Ensemble {stat_name} of {vname}"
                                )

                            # Percentiles
                            for pct in self.PERCENTILES:
                                pct_data = np.nanpercentile(
                                    all_data, pct, axis=0
                                )
                                v = out_ds.createVariable(
                                    f"{vname}_p{pct:02d}", "f4",
                                    var_dims, **kw,
                                )
                                v[:] = pct_data
                                v.long_name = (
                                    f"Ensemble {pct}th percentile "
                                    f"of {vname}"
                                )

                            # Free memory before next variable
                            del all_data

                generated.append(stats_path)
                print(f"  Wrote: {stats_path}")

        return generated

    def format_summary(self) -> str:
        """Format a human-readable summary of ensemble outputs."""
        lines = []
        lines.append("Ensemble Post-Processing Summary")
        lines.append(f"  Members: {self.n_members}")
        lines.append(f"  Variables: {', '.join(self.variables)}")
        lines.append(f"  Output: {self.output_dir}")
        lines.append(f"  Percentiles: {self.PERCENTILES}")
        lines.append("")

        valid, issues = self.validate_members()
        if valid:
            lines.append("  Status: All members validated")
        else:
            lines.append(f"  Status: {len(issues)} issue(s)")
            for issue in issues:
                lines.append(f"    - {issue}")

        output_files = self.discover_output_files()
        lines.append(f"  Common output files: {len(output_files)}")
        for fname in list(output_files.keys())[:10]:
            lines.append(f"    - {fname}")
        if len(output_files) > 10:
            lines.append(f"    ... and {len(output_files) - 10} more")

        return "\n".join(lines)


def main():
    """Command-line interface for ensemble post-processing."""
    parser = argparse.ArgumentParser(
        description="Compute ensemble statistics from NOS-OFS member outputs"
    )
    parser.add_argument(
        "--member-dirs",
        nargs="+",
        required=True,
        help="Paths to ensemble member output directories",
    )
    parser.add_argument(
        "--output-dir", "-o",
        required=True,
        help="Directory for ensemble statistics output",
    )
    parser.add_argument(
        "--variables",
        nargs="+",
        default=None,
        help=f"Variables to process (default: {EnsemblePost.DEFAULT_VARIABLES})",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate members, don't compute statistics",
    )
    args = parser.parse_args()

    post = EnsemblePost(
        member_dirs=args.member_dirs,
        output_dir=args.output_dir,
        variables=args.variables,
    )

    print(post.format_summary())
    print()

    if args.validate_only:
        valid, issues = post.validate_members()
        if not valid:
            for issue in issues:
                print(f"ERROR: {issue}", file=sys.stderr)
            return 1
        print("Validation passed.")
        return 0

    generated = post.compute_statistics()
    print(f"\nGenerated {len(generated)} statistics files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
