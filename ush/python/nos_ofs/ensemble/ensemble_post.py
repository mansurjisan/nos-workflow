"""
Ensemble Post-Processing

Reads outputs from all ensemble members and computes statistics:
  - Ensemble mean
  - Ensemble spread (standard deviation)
  - Min/max envelope
  - Percentiles (10, 25, 50, 75, 90)

Writes results to ensemble statistics NetCDF files.

Usage:
    # From Python
    post = EnsemblePost(member_dirs=[...], output_dir="ensemble_stats/")
    post.compute_statistics(variables=["elevation", "temperature"])

    # From command line
    python -m nos_ofs.ensemble.ensemble_post \\
        --member-dirs /path/to/member_000 /path/to/member_001 ... \\
        --output-dir /path/to/ensemble_stats
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class EnsemblePost:
    """Compute ensemble statistics from member outputs.

    This class handles both the file discovery and statistical computation
    for ensemble post-processing. It works with SCHISM output NetCDF files
    (outputs/schout_*.nc) or station output files.

    When netCDF4/numpy are not available (e.g., on login nodes), the class
    can still be instantiated for file discovery and member validation.
    Statistics computation requires netCDF4 and numpy.
    """

    # Default SCHISM output variables to process
    DEFAULT_VARIABLES = [
        "elevation",      # Sea surface height
        "temperature",    # Water temperature
        "salinity",       # Salinity
    ]

    # Percentiles to compute
    PERCENTILES = [10, 25, 50, 75, 90]

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

        Args:
            comout: Path to $COMOUT (e.g., /com/nosofs/v3.7.0/secofs.20250504)
            n_members: Expected number of members
            variables: Variable names to process

        Returns:
            EnsemblePost instance
        """
        ens_dir = os.path.join(comout, "ensemble")
        member_dirs = []
        for i in range(n_members):
            mid = f"{i:03d}"
            mdir = os.path.join(ens_dir, f"member_{mid}")
            if os.path.isdir(mdir):
                member_dirs.append(mdir)
            else:
                print(f"WARNING: Member directory not found: {mdir}", file=sys.stderr)

        output_dir = os.path.join(ens_dir, "stats")
        return cls(member_dirs, output_dir, variables)

    def validate_members(self) -> Tuple[bool, List[str]]:
        """Check that all member directories exist and contain outputs.

        Returns:
            Tuple of (all_valid, list_of_issues)
        """
        issues = []
        for mdir in self.member_dirs:
            if not os.path.isdir(mdir):
                issues.append(f"Directory not found: {mdir}")
                continue

            # Check for SCHISM output files
            outputs_dir = os.path.join(mdir, "outputs")
            if not os.path.isdir(outputs_dir):
                issues.append(f"No outputs/ directory in {mdir}")
                continue

            # Check for at least one schout file
            schout_files = [
                f for f in os.listdir(outputs_dir)
                if f.startswith("schout_") and f.endswith(".nc")
            ]
            if not schout_files:
                issues.append(f"No schout_*.nc files in {outputs_dir}")

        return (len(issues) == 0, issues)

    def discover_output_files(self) -> Dict[str, List[str]]:
        """Find matching output files across all members.

        Returns:
            Dict mapping filename to list of full paths (one per member).
            Only includes files present in ALL members.
        """
        # Get file lists for each member
        member_files = {}
        for mdir in self.member_dirs:
            outputs_dir = os.path.join(mdir, "outputs")
            if os.path.isdir(outputs_dir):
                files = set(
                    f for f in os.listdir(outputs_dir)
                    if f.startswith("schout_") and f.endswith(".nc")
                )
                member_files[mdir] = files
            else:
                member_files[mdir] = set()

        # Find intersection (files present in all members)
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

    def compute_statistics(self) -> List[str]:
        """Compute ensemble statistics for all output files and variables.

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
            raise RuntimeError("No common output files found across members.")

        generated = []

        for fname, member_paths in output_files.items():
            stats_path = os.path.join(self.output_dir, fname.replace("schout_", "ens_stats_"))
            print(f"Processing {fname} ({self.n_members} members)...")

            # Open reference file to get dimensions and metadata
            with nc.Dataset(member_paths[0], "r") as ref_ds:
                dims = {name: len(dim) for name, dim in ref_ds.dimensions.items()}
                time_var = ref_ds.variables.get("time")
                time_data = time_var[:] if time_var is not None else None
                time_units = getattr(time_var, "units", "") if time_var is not None else ""

                # Create output statistics file
                with nc.Dataset(stats_path, "w", format="NETCDF4") as out_ds:
                    # Copy dimensions
                    for dname, dsize in dims.items():
                        out_ds.createDimension(dname, dsize)

                    # Copy time variable
                    if time_data is not None:
                        t = out_ds.createVariable("time", "f8", ("time",))
                        t[:] = time_data
                        if time_units:
                            t.units = time_units

                    # Global attributes
                    out_ds.title = f"NOS-OFS Ensemble Statistics ({self.n_members} members)"
                    out_ds.source = "nos_ofs.ensemble.ensemble_post"
                    out_ds.n_members = self.n_members
                    out_ds.member_dirs = json.dumps(
                        [os.path.basename(d) for d in self.member_dirs]
                    )

                    # Process each requested variable
                    for varname in self.variables:
                        if varname not in ref_ds.variables:
                            continue

                        ref_var = ref_ds.variables[varname]
                        var_dims = ref_var.dimensions
                        var_shape = ref_var.shape

                        print(f"  Variable: {varname} {var_shape}")

                        # Stack all member data along a new axis
                        all_data = np.empty(
                            (self.n_members,) + var_shape,
                            dtype=np.float64,
                        )
                        all_data[0, :] = ref_var[:]

                        for m_idx in range(1, self.n_members):
                            with nc.Dataset(member_paths[m_idx], "r") as m_ds:
                                if varname in m_ds.variables:
                                    all_data[m_idx, :] = m_ds.variables[varname][:]
                                else:
                                    all_data[m_idx, :] = np.nan

                        # Compute statistics along member axis (axis=0)
                        fill = getattr(ref_var, "_FillValue", None)

                        ens_mean = np.nanmean(all_data, axis=0)
                        ens_std = np.nanstd(all_data, axis=0, ddof=1)
                        ens_min = np.nanmin(all_data, axis=0)
                        ens_max = np.nanmax(all_data, axis=0)

                        # Write statistics variables
                        kw = {"zlib": True, "complevel": 4}
                        if fill is not None:
                            kw["fill_value"] = fill

                        v = out_ds.createVariable(
                            f"{varname}_mean", "f4", var_dims, **kw,
                        )
                        v[:] = ens_mean
                        v.long_name = f"Ensemble mean of {varname}"

                        v = out_ds.createVariable(
                            f"{varname}_spread", "f4", var_dims, **kw,
                        )
                        v[:] = ens_std
                        v.long_name = f"Ensemble spread (std dev) of {varname}"

                        v = out_ds.createVariable(
                            f"{varname}_min", "f4", var_dims, **kw,
                        )
                        v[:] = ens_min
                        v.long_name = f"Ensemble minimum of {varname}"

                        v = out_ds.createVariable(
                            f"{varname}_max", "f4", var_dims, **kw,
                        )
                        v[:] = ens_max
                        v.long_name = f"Ensemble maximum of {varname}"

                        # Percentiles
                        for pct in self.PERCENTILES:
                            pct_data = np.nanpercentile(all_data, pct, axis=0)
                            v = out_ds.createVariable(
                                f"{varname}_p{pct:02d}", "f4", var_dims, **kw,
                            )
                            v[:] = pct_data
                            v.long_name = f"Ensemble {pct}th percentile of {varname}"

            generated.append(stats_path)
            print(f"  Wrote: {stats_path}")

        return generated

    def format_summary(self) -> str:
        """Format a human-readable summary of ensemble outputs."""
        lines = []
        lines.append(f"Ensemble Post-Processing Summary")
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
        for fname in list(output_files.keys())[:5]:
            lines.append(f"    - {fname}")
        if len(output_files) > 5:
            lines.append(f"    ... and {len(output_files) - 5} more")

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
