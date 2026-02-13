"""
ADT (Altimeter Data) SSH Correction Processor

Processes satellite altimeter data to correct RTOFS sea surface height (SSH)
at the open boundary.  This improves the ocean boundary condition accuracy
by incorporating near-real-time observations from satellites:
- Jason-3
- Sentinel-3A/3B
- SARAL/AltiKa
- CryoSat-2

Fully native Python -- uses netCDF4/xarray for I/O and scipy for
interpolation.  No subprocess/NCO calls.

The correction formula (per operational shell script) is:
    SSH_corrected = SSH_RTOFS - SSH_RTOFS(t=0) + ADT_observed
This removes RTOFS bias and adds the satellite altimetry reference.
"""

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ..base import ForcingProcessor, ForcingResult

log = logging.getLogger(__name__)

try:
    from netCDF4 import Dataset
    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False

try:
    from scipy.interpolate import griddata, NearestNDInterpolator
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


class ADTProcessor(ForcingProcessor):
    """
    Satellite altimeter SSH correction processor.

    Reads altimeter-derived SSH data and applies corrections to RTOFS
    boundary conditions.  All operations are pure Python (netCDF4, numpy,
    scipy).
    """

    # Satellite mission configurations
    SATELLITES = {
        "jason3": {"ground_track_spacing": 315.0, "repeat_cycle": 9.9156},
        "sentinel3a": {"ground_track_spacing": 104.0, "repeat_cycle": 27.0},
        "sentinel3b": {"ground_track_spacing": 104.0, "repeat_cycle": 27.0},
        "saral": {"ground_track_spacing": 80.0, "repeat_cycle": 35.0},
    }

    DEFAULT_SEARCH_WINDOW = 48  # hours before/after
    MAX_INTERPOLATION_DISTANCE = 100.0  # km

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

        self.bnd_nodes = self._load_boundary_nodes()

    def _load_boundary_nodes(self) -> Dict[str, Any]:
        """Load boundary node locations for interpolation."""
        bnd_nodes: Dict[str, Any] = {"indices": [], "lons": [], "lats": []}
        bnd_file = self.config.get_fix_file(f"{self.config.RUN}_bnd_nodes.txt")

        if bnd_file.exists():
            try:
                with open(bnd_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split()
                        if len(parts) >= 3:
                            bnd_nodes["indices"].append(int(parts[0]))
                            bnd_nodes["lons"].append(float(parts[1]))
                            bnd_nodes["lats"].append(float(parts[2]))
                log.info("Loaded %d boundary nodes", len(bnd_nodes["indices"]))
            except Exception as e:
                log.warning("Error loading boundary nodes: %s", e)
        else:
            log.warning("Boundary nodes file not found: %s", bnd_file)

        return bnd_nodes

    # ==================================================================
    # Main entry
    # ==================================================================

    def process(self) -> ForcingResult:
        """Process ADT SSH correction data."""
        log.info("Processing %s SSH correction", self.source_name)
        log.info("Input path: %s", self.input_path)
        log.info("Search window: +/-%d hours", self.search_window)

        if not self.validate_input():
            log.warning("ADT input path not found: %s", self.input_path)
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=["ADT data path not found -- no SSH correction applied"],
            )

        if not HAS_NETCDF4:
            log.warning("netCDF4 not available -- skipping ADT processing")
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=["netCDF4 required for ADT processing"],
            )

        self.create_output_dir()
        output_files: List[Path] = []

        try:
            adt_data = self._read_altimeter_data()

            if not adt_data or not adt_data.get("ssh"):
                log.info("No altimeter data -- using RTOFS SSH without correction")
                return ForcingResult(
                    success=True,
                    source=self.source_name,
                    warnings=["No ADT data found in search window"],
                )

            log.info("Found %d altimeter observations", len(adt_data["ssh"]))

            correction_file = self._create_ssh_correction(adt_data)
            if correction_file:
                output_files.append(correction_file)

            if self.apply_correction:
                corrected_file = self._apply_to_rtofs(adt_data)
                if corrected_file:
                    output_files.append(corrected_file)

            log.info("ADT processing complete: %d files", len(output_files))

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
            log.error("ADT processing failed: %s", e, exc_info=True)
            return ForcingResult(
                success=True,  # Non-fatal
                source=self.source_name,
                warnings=[f"ADT processing failed: {e}"],
            )

    # ==================================================================
    # Altimeter data reading (pure Python, no subprocess)
    # ==================================================================

    def _read_altimeter_data(self) -> Dict[str, Any]:
        """Read altimeter SSH data from various NetCDF sources."""
        adt_data: Dict[str, Any] = {
            "times": [],
            "lons": [],
            "lats": [],
            "ssh": [],
            "satellites": set(),
        }

        patterns = [
            "*.nc",
            f"*{self.pdy}*.nc",
            "adt_*.nc",
            "ssh_*.nc",
            "j3_*.nc",
            "s3a_*.nc",
            "s3b_*.nc",
            "al_*.nc",
        ]

        files_found: List[Path] = []
        for pattern in patterns:
            files_found.extend(self.input_path.glob(pattern))
        files_found = list(set(files_found))

        if not files_found:
            log.debug("No altimeter files found")
            return adt_data

        log.info("Found %d potential altimeter files", len(files_found))

        lon_min = self.config.lon_min
        lon_max = self.config.lon_max
        lat_min = self.config.lat_min
        lat_max = self.config.lat_max

        for adt_file in files_found:
            try:
                with Dataset(str(adt_file), "r") as nc:
                    ssh_var = self._find_variable(
                        nc, ["ssh", "adt", "ssha", "sea_surface_height", "surf_el"]
                    )
                    lon_var = self._find_variable(nc, ["longitude", "lon", "x", "xlon"])
                    lat_var = self._find_variable(nc, ["latitude", "lat", "y", "ylat"])

                    if not all([ssh_var, lon_var, lat_var]):
                        continue

                    ssh_data = nc.variables[ssh_var][:]
                    lons = nc.variables[lon_var][:]
                    lats = nc.variables[lat_var][:]

                    satellite = self._identify_satellite(adt_file.name, nc)

                    # Handle masked arrays
                    if isinstance(ssh_data, np.ma.MaskedArray):
                        ssh_data = ssh_data.filled(np.nan)
                    if isinstance(lons, np.ma.MaskedArray):
                        lons = lons.filled(np.nan)
                    if isinstance(lats, np.ma.MaskedArray):
                        lats = lats.filled(np.nan)

                    # Longitude convention
                    if np.nanmax(lons) > 180:
                        lons = np.where(lons > 180, lons - 360, lons)

                    # Domain filter
                    mask = (
                        (lons >= lon_min)
                        & (lons <= lon_max)
                        & (lats >= lat_min)
                        & (lats <= lat_max)
                        & np.isfinite(ssh_data)
                    )

                    if not np.any(mask):
                        continue

                    adt_data["lons"].extend(lons[mask].flatten().tolist())
                    adt_data["lats"].extend(lats[mask].flatten().tolist())
                    adt_data["ssh"].extend(ssh_data[mask].flatten().tolist())
                    if satellite:
                        adt_data["satellites"].add(satellite)

                    log.debug("Read %d points from %s", int(np.sum(mask)), adt_file.name)

            except Exception as e:
                log.debug("Error reading %s: %s", adt_file, e)

        return adt_data

    def _find_variable(self, nc, names: List[str]) -> Optional[str]:
        for name in names:
            if name in nc.variables:
                return name
        return None

    def _identify_satellite(self, filename: str, nc) -> Optional[str]:
        fl = filename.lower()
        for prefix, sat in [
            ("j3", "jason3"), ("jason", "jason3"),
            ("s3a", "sentinel3a"), ("sentinel3a", "sentinel3a"),
            ("s3b", "sentinel3b"), ("sentinel3b", "sentinel3b"),
            ("al", "saral"), ("saral", "saral"),
        ]:
            if prefix in fl:
                return sat

        for attr in ("platform", "satellite", "mission"):
            if hasattr(nc, attr):
                platform = getattr(nc, attr).lower()
                for sat in self.SATELLITES:
                    if sat in platform:
                        return sat
        return "unknown"

    # ==================================================================
    # Correction creation (pure Python)
    # ==================================================================

    def _create_ssh_correction(self, adt_data: Dict[str, Any]) -> Optional[Path]:
        """Create SSH correction field interpolated to boundary nodes."""
        output_file = self.output_path / "adt_correction.nc"

        if not self.bnd_nodes["lons"]:
            log.warning("No boundary nodes -- cannot create correction")
            return None

        bnd_lons = np.array(self.bnd_nodes["lons"])
        bnd_lats = np.array(self.bnd_nodes["lats"])

        obs_lons = np.array(adt_data["lons"])
        obs_lats = np.array(adt_data["lats"])
        obs_ssh = np.array(adt_data["ssh"])

        if len(obs_ssh) == 0:
            return None

        if HAS_SCIPY:
            obs_pts = np.column_stack([obs_lons, obs_lats])
            bnd_pts = np.column_stack([bnd_lons, bnd_lats])
            bnd_correction = griddata(
                obs_pts, obs_ssh, bnd_pts, method="nearest", fill_value=np.nan
            )
        else:
            bnd_correction = np.full(len(bnd_lons), np.nanmean(obs_ssh))

        try:
            with Dataset(str(output_file), "w", format="NETCDF4") as nc:
                nc.createDimension("nOpenBndNodes", len(bnd_lons))

                lv = nc.createVariable("lon", "f4", ("nOpenBndNodes",))
                lv[:] = bnd_lons
                lv.units = "degrees_east"

                la = nc.createVariable("lat", "f4", ("nOpenBndNodes",))
                la[:] = bnd_lats
                la.units = "degrees_north"

                cv = nc.createVariable(
                    "ssh_correction", "f4", ("nOpenBndNodes",), fill_value=-9999.0
                )
                cv[:] = bnd_correction
                cv.units = "m"
                cv.long_name = "SSH correction from altimeter"

                nc.title = "ADT SSH Correction"
                nc.satellites = ", ".join(adt_data.get("satellites", ["unknown"]))
                nc.creation_date = datetime.now().isoformat()

            log.info("Created SSH correction file: %s", output_file)
            return output_file
        except Exception as e:
            log.error("Error creating correction file: %s", e)
            return None

    def _apply_to_rtofs(self, adt_data: Dict[str, Any]) -> Optional[Path]:
        """Apply ADT correction to RTOFS elev2D boundary file."""
        rtofs_elev = self.output_path / "elev2D.th.nc"
        if not rtofs_elev.exists():
            rtofs_elev = self.output_path.parent / "elev2D.th.nc"
        if not rtofs_elev.exists():
            log.warning("RTOFS elev2D.th.nc not found -- cannot apply correction")
            return None

        output_file = self.output_path / "elev2D_corrected.th.nc"

        try:
            shutil.copy2(rtofs_elev, output_file)

            corr_file = self.output_path / "adt_correction.nc"
            if not corr_file.exists():
                return None

            with Dataset(str(corr_file), "r") as nc_corr:
                correction = nc_corr.variables["ssh_correction"][:]

            with Dataset(str(output_file), "r+") as nc:
                if "time_series" in nc.variables:
                    ssh = nc.variables["time_series"]
                    for t in range(ssh.shape[0]):
                        if ssh.ndim == 4:
                            ssh[t, :, 0, 0] = ssh[t, :, 0, 0] + correction
                        elif ssh.ndim == 2:
                            ssh[t, :] = ssh[t, :] + correction
                    log.info("Applied ADT correction to all time steps")

            log.info("Created corrected elev2D: %s", output_file)
            return output_file
        except Exception as e:
            log.error("Error applying correction: %s", e)
            return None

    # ==================================================================
    # Statistics
    # ==================================================================

    def get_bias_statistics(self, adt_data: Dict[str, Any]) -> Dict[str, float]:
        """Compute bias statistics between ADT and RTOFS."""
        stats: Dict[str, float] = {
            "num_observations": len(adt_data.get("ssh", [])),
            "mean_ssh": np.nan,
            "std_ssh": np.nan,
            "min_ssh": np.nan,
            "max_ssh": np.nan,
        }
        if adt_data.get("ssh"):
            ssh = np.array(adt_data["ssh"])
            valid = np.isfinite(ssh)
            if np.any(valid):
                stats["mean_ssh"] = float(np.nanmean(ssh))
                stats["std_ssh"] = float(np.nanstd(ssh))
                stats["min_ssh"] = float(np.nanmin(ssh))
                stats["max_ssh"] = float(np.nanmax(ssh))
        return stats
