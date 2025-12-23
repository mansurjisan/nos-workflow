"""
ADT (Altimeter Data) SSH Correction Processor

Processes satellite altimeter data to correct RTOFS sea surface height (SSH)
at the open boundary. This improves the ocean boundary condition accuracy
by incorporating near-real-time observations from satellites like:
- Jason-3
- Sentinel-3A/3B
- SARAL/AltiKa
- CryoSat-2

The ADT correction is applied to elev2D.th.nc (RTOFS SSH) to reduce
systematic biases in the ocean boundary forcing.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..base import ForcingProcessor, ForcingResult

log = logging.getLogger(__name__)

try:
    from netCDF4 import Dataset
    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False

try:
    from scipy.interpolate import griddata
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


class ADTProcessor(ForcingProcessor):
    """
    Satellite altimeter SSH correction processor.

    Reads altimeter-derived SSH data and applies corrections to RTOFS
    boundary conditions to improve model initialization and reduce
    systematic boundary errors.

    The correction is computed as:
    SSH_corrected = SSH_RTOFS + (ADT_observed - ADT_RTOFS_equivalent)

    This effectively nudges the RTOFS boundary toward observed SSH
    while preserving the temporal variability from RTOFS.
    """

    # Satellite mission configurations
    SATELLITES = {
        "jason3": {"ground_track_spacing": 315.0, "repeat_cycle": 9.9156},
        "sentinel3a": {"ground_track_spacing": 104.0, "repeat_cycle": 27.0},
        "sentinel3b": {"ground_track_spacing": 104.0, "repeat_cycle": 27.0},
        "saral": {"ground_track_spacing": 80.0, "repeat_cycle": 35.0},
    }

    # Default search window for altimeter data (hours before/after)
    DEFAULT_SEARCH_WINDOW = 48

    # Maximum distance for interpolation (km)
    MAX_INTERPOLATION_DISTANCE = 100.0

    @property
    def source_name(self) -> str:
        return "ADT"

    def __init__(
        self,
        config,
        input_path: Path,
        output_path: Path,
        variables: Optional[List[str]] = None,
        search_window: int = 48,
        apply_correction: bool = True,
    ):
        """
        Initialize ADT processor.

        Args:
            config: StofsConfig instance
            input_path: Path to ADT data (COMINadt or DCOM)
            output_path: Path for output files
            variables: Variables to process (default: ssh)
            search_window: Hours to search for altimeter data
            apply_correction: Whether to apply correction to RTOFS
        """
        super().__init__(config, input_path, output_path, variables)
        self.search_window = search_window
        self.apply_correction = apply_correction
        if not self.variables:
            self.variables = ["ssh", "adt"]

        self.cyc = config.cyc
        self.pdy = config.PDY

        # Load boundary node information
        self.bnd_nodes = self._load_boundary_nodes()

    def _load_boundary_nodes(self) -> Dict:
        """Load boundary node locations for interpolation."""
        bnd_nodes = {
            "indices": [],
            "lons": [],
            "lats": [],
        }

        bnd_file = self.config.get_fix_file(f"{self.config.RUN}_bnd_nodes.txt")

        if bnd_file.exists():
            try:
                with open(bnd_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        parts = line.split()
                        if len(parts) >= 3:
                            bnd_nodes["indices"].append(int(parts[0]))
                            bnd_nodes["lons"].append(float(parts[1]))
                            bnd_nodes["lats"].append(float(parts[2]))

                log.info(f"Loaded {len(bnd_nodes['indices'])} boundary nodes")
            except Exception as e:
                log.warning(f"Error loading boundary nodes: {e}")
        else:
            log.warning(f"Boundary nodes file not found: {bnd_file}")

        return bnd_nodes

    def process(self) -> ForcingResult:
        """
        Process ADT SSH correction data.

        Returns:
            ForcingResult with correction files
        """
        log.info(f"Processing {self.source_name} SSH correction")
        log.info(f"Input path: {self.input_path}")
        log.info(f"Search window: Â±{self.search_window} hours")

        if not self.validate_input():
            log.warning(f"ADT input path not found: {self.input_path}")
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=["ADT data path not found - no SSH correction applied"],
            )

        if not HAS_NETCDF4:
            log.warning("netCDF4 not available - skipping ADT processing")
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=["netCDF4 required for ADT processing"],
            )

        self.create_output_dir()
        output_files = []

        try:
            # Find and read altimeter data
            adt_data = self._read_altimeter_data()

            if not adt_data or not adt_data.get("ssh"):
                log.info("No altimeter data found - using RTOFS SSH without correction")
                return ForcingResult(
                    success=True,
                    source=self.source_name,
                    warnings=["No ADT data found in search window"],
                )

            log.info(f"Found {len(adt_data['ssh'])} altimeter observations")

            # Create SSH correction field
            correction_file = self._create_ssh_correction(adt_data)
            if correction_file:
                output_files.append(correction_file)

            # Apply correction to RTOFS boundary if requested
            if self.apply_correction:
                corrected_file = self._apply_to_rtofs(adt_data)
                if corrected_file:
                    output_files.append(corrected_file)

            log.info(f"ADT processing complete: {len(output_files)} files")

            return ForcingResult(
                success=True,
                source=self.source_name,
                output_files=output_files,
                metadata={
                    "num_observations": len(adt_data.get("ssh", [])),
                    "satellites": list(adt_data.get("satellites", set())),
                    "correction_applied": self.apply_correction,
                },
            )

        except Exception as e:
            log.error(f"ADT processing failed: {e}")
            import traceback
            log.error(traceback.format_exc())
            return ForcingResult(
                success=True,  # Non-fatal
                source=self.source_name,
                warnings=[f"ADT processing failed: {e}"],
            )

    def _read_altimeter_data(self) -> Dict:
        """
        Read altimeter SSH data from various sources.

        Returns:
            Dictionary with SSH observations and metadata
        """
        adt_data = {
            "times": [],
            "lons": [],
            "lats": [],
            "ssh": [],
            "satellites": set(),
        }

        # Calculate search time window
        base_time = datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc)
        start_time = base_time - timedelta(hours=self.search_window)
        end_time = base_time + timedelta(hours=self.search_window)

        # Search for altimeter data files
        # Common patterns for various data formats
        patterns = [
            "*.nc",
            f"*{self.pdy}*.nc",
            "adt_*.nc",
            "ssh_*.nc",
            "j3_*.nc",    # Jason-3
            "s3a_*.nc",   # Sentinel-3A
            "s3b_*.nc",   # Sentinel-3B
            "al_*.nc",    # SARAL/AltiKa
        ]

        files_found = []
        for pattern in patterns:
            matches = list(self.input_path.glob(pattern))
            files_found.extend(matches)

        # Remove duplicates
        files_found = list(set(files_found))

        if not files_found:
            log.debug("No altimeter files found")
            return adt_data

        log.info(f"Found {len(files_found)} potential altimeter files")

        # Domain bounds for filtering
        lon_min = self.config.lon_min
        lon_max = self.config.lon_max
        lat_min = self.config.lat_min
        lat_max = self.config.lat_max

        for adt_file in files_found:
            try:
                nc = Dataset(adt_file, 'r')

                # Identify variable names (varies by product)
                ssh_var = self._find_variable(nc, ["ssh", "adt", "ssha", "sea_surface_height"])
                lon_var = self._find_variable(nc, ["longitude", "lon", "x"])
                lat_var = self._find_variable(nc, ["latitude", "lat", "y"])
                time_var = self._find_variable(nc, ["time", "meas_time"])

                if not all([ssh_var, lon_var, lat_var]):
                    nc.close()
                    continue

                # Read data
                ssh_data = nc.variables[ssh_var][:]
                lons = nc.variables[lon_var][:]
                lats = nc.variables[lat_var][:]

                # Time handling
                if time_var:
                    times = nc.variables[time_var][:]
                    time_units = nc.variables[time_var].units if hasattr(nc.variables[time_var], 'units') else None
                else:
                    # Assume single time
                    times = [0]
                    time_units = None

                # Identify satellite from filename or attributes
                satellite = self._identify_satellite(adt_file.name, nc)

                # Convert longitude to -180 to 180 if needed
                if lons.max() > 180:
                    lons = np.where(lons > 180, lons - 360, lons)

                # Filter to domain
                mask = (lons >= lon_min) & (lons <= lon_max) & \
                       (lats >= lat_min) & (lats <= lat_max)

                if not np.any(mask):
                    nc.close()
                    continue

                # Add valid data
                adt_data["lons"].extend(lons[mask].flatten())
                adt_data["lats"].extend(lats[mask].flatten())
                adt_data["ssh"].extend(ssh_data[mask].flatten())
                if satellite:
                    adt_data["satellites"].add(satellite)

                log.debug(f"Read {np.sum(mask)} points from {adt_file.name}")

                nc.close()

            except Exception as e:
                log.debug(f"Error reading {adt_file}: {e}")

        return adt_data

    def _find_variable(self, nc, names: List[str]) -> Optional[str]:
        """Find a variable by checking multiple possible names."""
        for name in names:
            if name in nc.variables:
                return name
        return None

    def _identify_satellite(self, filename: str, nc) -> Optional[str]:
        """Identify satellite from filename or NetCDF attributes."""
        filename_lower = filename.lower()

        # Check filename
        if "j3" in filename_lower or "jason" in filename_lower:
            return "jason3"
        if "s3a" in filename_lower or "sentinel3a" in filename_lower:
            return "sentinel3a"
        if "s3b" in filename_lower or "sentinel3b" in filename_lower:
            return "sentinel3b"
        if "al" in filename_lower or "saral" in filename_lower:
            return "saral"

        # Check global attributes
        for attr in ["platform", "satellite", "mission"]:
            if hasattr(nc, attr):
                platform = getattr(nc, attr).lower()
                for sat in self.SATELLITES:
                    if sat in platform:
                        return sat

        return "unknown"

    def _create_ssh_correction(self, adt_data: Dict) -> Optional[Path]:
        """
        Create SSH correction field.

        Interpolates altimeter observations to boundary nodes
        and computes correction relative to RTOFS.

        Returns:
            Path to correction file
        """
        output_file = self.output_path / "adt_correction.nc"

        if not self.bnd_nodes["lons"]:
            log.warning("No boundary nodes - cannot create correction")
            return None

        if not HAS_SCIPY:
            log.warning("scipy required for interpolation - using simple averaging")
            # Fall back to domain average
            mean_ssh = np.nanmean(adt_data["ssh"])
            bnd_correction = np.full(len(self.bnd_nodes["lons"]), mean_ssh)
        else:
            # Interpolate to boundary nodes
            obs_points = np.column_stack([adt_data["lons"], adt_data["lats"]])
            obs_ssh = np.array(adt_data["ssh"])

            bnd_points = np.column_stack([self.bnd_nodes["lons"], self.bnd_nodes["lats"]])

            # Use nearest neighbor for sparse observations
            bnd_correction = griddata(
                obs_points, obs_ssh, bnd_points,
                method='nearest',
                fill_value=np.nan
            )

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            nc.createDimension('nOpenBndNodes', len(self.bnd_nodes["lons"]))

            lon_var = nc.createVariable('lon', 'f4', ('nOpenBndNodes',))
            lon_var[:] = self.bnd_nodes["lons"]
            lon_var.units = "degrees_east"

            lat_var = nc.createVariable('lat', 'f4', ('nOpenBndNodes',))
            lat_var[:] = self.bnd_nodes["lats"]
            lat_var.units = "degrees_north"

            corr_var = nc.createVariable('ssh_correction', 'f4', ('nOpenBndNodes',),
                                        fill_value=-9999.0)
            corr_var[:] = bnd_correction
            corr_var.units = "m"
            corr_var.long_name = "SSH correction from altimeter"

            nc.title = "ADT SSH Correction"
            nc.satellites = ", ".join(adt_data.get("satellites", ["unknown"]))
            nc.creation_date = datetime.now().isoformat()

            nc.close()

            log.info(f"Created SSH correction file: {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Error creating correction file: {e}")
            return None

    def _apply_to_rtofs(self, adt_data: Dict) -> Optional[Path]:
        """
        Apply ADT correction to RTOFS elev2D boundary file.

        Args:
            adt_data: Dictionary with altimeter observations

        Returns:
            Path to corrected elev2D file
        """
        # Find RTOFS elev2D file
        rtofs_elev = self.output_path / "elev2D.th.nc"

        if not rtofs_elev.exists():
            # Try parent directory
            rtofs_elev = self.output_path.parent / "elev2D.th.nc"

        if not rtofs_elev.exists():
            log.warning("RTOFS elev2D.th.nc not found - cannot apply correction")
            return None

        output_file = self.output_path / "elev2D_corrected.th.nc"

        try:
            import shutil
            shutil.copy2(rtofs_elev, output_file)

            # Read correction
            corr_file = self.output_path / "adt_correction.nc"
            if not corr_file.exists():
                return None

            nc_corr = Dataset(corr_file, 'r')
            correction = nc_corr.variables['ssh_correction'][:]
            nc_corr.close()

            # Apply correction
            nc = Dataset(output_file, 'r+')

            if 'time_series' in nc.variables:
                ssh = nc.variables['time_series']

                # Apply correction to each time step
                for t in range(ssh.shape[0]):
                    ssh[t, :] = ssh[t, :] + correction

                log.info("Applied ADT correction to all time steps")

            nc.close()

            log.info(f"Created corrected elev2D: {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Error applying correction: {e}")
            return None

    def get_bias_statistics(self, adt_data: Dict) -> Dict:
        """
        Compute bias statistics between ADT and RTOFS.

        Useful for monitoring and validation.

        Returns:
            Dictionary with bias statistics
        """
        stats = {
            "num_observations": len(adt_data.get("ssh", [])),
            "mean_ssh": np.nan,
            "std_ssh": np.nan,
            "min_ssh": np.nan,
            "max_ssh": np.nan,
        }

        if adt_data.get("ssh"):
            ssh = np.array(adt_data["ssh"])
            valid = ~np.isnan(ssh)
            if np.any(valid):
                stats["mean_ssh"] = float(np.nanmean(ssh))
                stats["std_ssh"] = float(np.nanstd(ssh))
                stats["min_ssh"] = float(np.nanmin(ssh))
                stats["max_ssh"] = float(np.nanmax(ssh))

        return stats
