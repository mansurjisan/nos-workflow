"""
ROMS Post-Processor

Handles post-processing for all ROMS-based OFS systems:
- CBOFS (Chesapeake Bay)
- DBOFS (Delaware Bay)
- TBOFS (Tampa Bay)
- GOMOFS (Gulf of Maine)
- CIOFS (Cook Inlet)
- WCOFS (West Coast)

ROMS output files:
    - nos.{ofs}.fields.n{NNN}.{YYYYMMDD}.t{CC}z.nc: Nowcast history files
    - nos.{ofs}.fields.f{NNN}.{YYYYMMDD}.t{CC}z.nc: Forecast history files
    - nos.{ofs}.stations.nowcast.{YYYYMMDD}.t{CC}z.nc: Station nowcast
    - nos.{ofs}.stations.forecast.{YYYYMMDD}.t{CC}z.nc: Station forecast
    - nos.{ofs}.rst.nowcast.{YYYYMMDD}.t{CC}z.nc: Restart file
    - nos.{ofs}.avg.nowcast.{YYYYMMDD}.t{CC}z.nc: Averaged fields

ROMS uses sigma (terrain-following) vertical coordinates. Post-processing
includes optional sigma-to-z-level interpolation for standard depth levels.

Standard depth levels (m): 0, 2.5, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100,
                           150, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 4000
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import BasePostProcessor, PostResult

log = logging.getLogger(__name__)

# Standard depth levels for z-level interpolation (meters, positive down)
STANDARD_DEPTHS = [
    0.0, 2.5, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0,
    75.0, 100.0, 150.0, 200.0, 300.0, 500.0, 750.0, 1000.0,
    1500.0, 2000.0, 3000.0, 4000.0,
]


class ROMSPostProcessor(BasePostProcessor):
    """
    Post-processor for ROMS-based OFS systems.

    Handles extraction of fields from ROMS history files, sigma-to-z
    interpolation, station extraction, and standard NetCDF generation.

    ROMS outputs are already in NetCDF format with some CF conventions.
    Post-processing primarily adds missing attributes, performs coordinate
    transformations, and generates derived products.

    Attributes:
        ocean_model: Always "ROMS" for this processor
        sigma_to_z: Whether to perform sigma-to-z interpolation
        standard_depths: List of target z-levels for interpolation
    """

    # ROMS primary output variables
    ROMS_FIELD_VARS = {
        "zeta": {
            "standard_name": "sea_surface_height_above_geoid",
            "long_name": "Water Surface Elevation",
            "units": "m",
        },
        "temp": {
            "standard_name": "sea_water_temperature",
            "long_name": "Sea Water Temperature",
            "units": "degC",
        },
        "salt": {
            "standard_name": "sea_water_salinity",
            "long_name": "Sea Water Practical Salinity",
            "units": "PSU",
        },
        "u": {
            "standard_name": "eastward_sea_water_velocity",
            "long_name": "Eastward Sea Water Velocity",
            "units": "m/s",
        },
        "v": {
            "standard_name": "northward_sea_water_velocity",
            "long_name": "Northward Sea Water Velocity",
            "units": "m/s",
        },
        "ubar": {
            "standard_name": "barotropic_eastward_sea_water_velocity",
            "long_name": "Depth-Averaged Eastward Velocity",
            "units": "m/s",
        },
        "vbar": {
            "standard_name": "barotropic_northward_sea_water_velocity",
            "long_name": "Depth-Averaged Northward Velocity",
            "units": "m/s",
        },
    }

    def __init__(self, config: Any):
        """
        Initialize ROMS post-processor.

        Args:
            config: OFSConfig instance
        """
        super().__init__(config)
        self.ocean_model = "ROMS"
        self.sigma_to_z = bool(
            int(os.environ.get("ROMS_SIGMA_TO_Z", "1"))
        )
        self.standard_depths = STANDARD_DEPTHS

        self.logger.info(
            f"ROMSPostProcessor initialized: ofs={self.ofs_name}, "
            f"sigma_to_z={self.sigma_to_z}"
        )

    def _get_model_type(self) -> str:
        """Return model type identifier."""
        return "ROMS"

    def validate_model_output(self) -> Tuple[bool, List[str]]:
        """
        Validate ROMS model output files exist.

        Checks for:
        - History (field) files: nos.{ofs}.fields.{n/f}NNN.*.nc
        - Station files: nos.{ofs}.stations.*.nc (optional)
        - Restart file: nos.{ofs}.rst.*.nc

        Returns:
            Tuple of (is_valid, list_of_missing_files)
        """
        missing = []

        # Check for nowcast history files
        nowcast_pattern = f"nos.{self.ofs_name}.fields.n*.{self.pdy}.{self.cycle}.nc"
        nowcast_files = sorted(self.data_dir.glob(nowcast_pattern))
        if not nowcast_files:
            # Also check COMOUT for already-archived files
            nowcast_files = sorted(self.comout.glob(nowcast_pattern))

        if not nowcast_files:
            missing.append(f"Nowcast history files ({nowcast_pattern})")

        # Check for forecast history files
        forecast_pattern = f"nos.{self.ofs_name}.fields.f*.{self.pdy}.{self.cycle}.nc"
        forecast_files = sorted(self.data_dir.glob(forecast_pattern))
        if not forecast_files:
            forecast_files = sorted(self.comout.glob(forecast_pattern))

        if not forecast_files:
            # Forecast files are optional (may not have been generated yet)
            self.logger.info("No forecast history files found (may be expected)")

        # Check for restart file
        rst_pattern = f"nos.{self.ofs_name}.rst.*.{self.pdy}.{self.cycle}.nc"
        rst_files = sorted(self.data_dir.glob(rst_pattern))
        if not rst_files:
            rst_files = sorted(self.comout.glob(rst_pattern))

        if not rst_files:
            self.logger.warning("No restart file found")

        is_valid = len(missing) == 0
        if is_valid:
            self.logger.info(
                f"ROMS output validation passed: "
                f"{len(nowcast_files)} nowcast, {len(forecast_files)} forecast files"
            )
        else:
            self.logger.warning(
                f"ROMS output validation: {len(missing)} issues found"
            )

        return is_valid, missing

    def extract_fields(self) -> PostResult:
        """
        Extract and enhance 2D/3D fields from ROMS history files.

        Reads ROMS history (field) files, adds CF-compliant attributes,
        and optionally performs sigma-to-z-level interpolation for 3D
        variables.

        Returns:
            PostResult with extracted field files
        """
        self.logger.info("Extracting ROMS fields")

        output_files = []
        warnings = []
        errors = []

        try:
            import numpy as np
            import xarray as xr
        except ImportError as e:
            return PostResult(
                success=False,
                phase="extract_fields",
                errors=[
                    f"Required package not available: {e}. "
                    "Install with: pip install xarray netCDF4 numpy"
                ],
            )

        # Find all history (field) files
        field_files = sorted(
            self.data_dir.glob(
                f"nos.{self.ofs_name}.fields.*.{self.pdy}.{self.cycle}.nc"
            )
        )
        if not field_files:
            field_files = sorted(
                self.comout.glob(
                    f"nos.{self.ofs_name}.fields.*.{self.pdy}.{self.cycle}.nc"
                )
            )

        if not field_files:
            return PostResult(
                success=False,
                phase="extract_fields",
                errors=["No ROMS history field files found"],
            )

        self.logger.info(f"Found {len(field_files)} ROMS field files")

        # Process each field file
        for field_file in field_files:
            self.logger.info(f"Processing: {field_file.name}")
            try:
                ds = xr.open_dataset(str(field_file))

                # Add/update CF attributes for known variables
                for var_name, attrs in self.ROMS_FIELD_VARS.items():
                    if var_name in ds:
                        ds[var_name].attrs.update(attrs)

                # Add global attributes
                ds = self._add_cf_global_attributes(
                    ds,
                    title=f"{self.ofs_name.upper()} ROMS Fields",
                    summary=f"Ocean model fields from {self.ofs_name.upper()} ROMS",
                )

                # Write enhanced file
                out_name = field_file.name.replace(".nc", ".enhanced.nc")
                out_path = self.data_dir / out_name
                ds.to_netcdf(str(out_path))
                output_files.append(out_path)
                ds.close()

            except Exception as e:
                self.logger.error(f"Failed to process {field_file.name}: {e}")
                warnings.append(f"{field_file.name}: {e}")

        # Sigma to z-level interpolation (if enabled)
        if self.sigma_to_z and output_files:
            self.logger.info("Performing sigma-to-z-level interpolation")
            z_files = self._sigma_to_z_interpolation(output_files)
            if z_files:
                output_files.extend(z_files)
            else:
                warnings.append("Sigma-to-z interpolation produced no output")

        success = len(output_files) > 0

        return PostResult(
            success=success,
            phase="extract_fields",
            output_files=output_files,
            errors=errors,
            warnings=warnings,
            metadata={"n_field_files": len(field_files)},
        )

    def _sigma_to_z_interpolation(
        self, field_files: List[Path]
    ) -> List[Path]:
        """
        Interpolate ROMS sigma-coordinate fields to standard z-levels.

        Uses scipy's RegularGridInterpolator for vertical interpolation
        from terrain-following sigma coordinates to fixed depth levels.

        Args:
            field_files: List of enhanced ROMS field files

        Returns:
            List of z-level interpolated files
        """
        z_files = []

        try:
            import numpy as np
            import xarray as xr
            from scipy.interpolate import interp1d
        except ImportError as e:
            self.logger.warning(
                f"scipy not available for sigma-to-z interpolation: {e}"
            )
            return z_files

        for field_file in field_files:
            try:
                ds = xr.open_dataset(str(field_file))

                # Check for required sigma coordinate variables
                has_sigma = any(
                    v in ds for v in ["s_rho", "Cs_r", "hc", "h"]
                )

                if not has_sigma:
                    self.logger.debug(
                        f"No sigma coordinates in {field_file.name}; skipping"
                    )
                    ds.close()
                    continue

                # Extract sigma coordinate parameters
                s_rho = ds["s_rho"].values if "s_rho" in ds else None
                cs_r = ds["Cs_r"].values if "Cs_r" in ds else None
                hc = float(ds["hc"].values) if "hc" in ds else 0.0
                h = ds["h"].values if "h" in ds else None
                zeta = ds["zeta"].values if "zeta" in ds else None

                if s_rho is None or h is None:
                    self.logger.debug(
                        f"Missing sigma params in {field_file.name}; skipping"
                    )
                    ds.close()
                    continue

                n_sigma = len(s_rho)
                target_depths = np.array(
                    [d for d in self.standard_depths if d >= 0]
                )

                # Interpolate 3D variables
                vars_3d = ["temp", "salt", "u", "v"]
                z_ds_vars = {}

                for var_name in vars_3d:
                    if var_name not in ds:
                        continue

                    var_data = ds[var_name].values
                    if var_data.ndim < 3:
                        continue

                    self.logger.debug(
                        f"Interpolating {var_name} from sigma to z-levels"
                    )

                    # var_data shape: (time, s_rho, eta_rho, xi_rho)
                    # or (time, s_rho, eta_v, xi_v) for v-points
                    n_time = var_data.shape[0]
                    n_eta = var_data.shape[2] if var_data.ndim > 2 else 1
                    n_xi = var_data.shape[3] if var_data.ndim > 3 else 1

                    z_data = np.full(
                        (n_time, len(target_depths), n_eta, n_xi),
                        np.nan,
                        dtype=np.float32,
                    )

                    # Compute sigma depths at each point
                    # z = hc*s + (h - hc)*Cs (simplified Vtransform=2)
                    if cs_r is not None:
                        for t in range(n_time):
                            zeta_t = zeta[t] if zeta is not None else np.zeros_like(h)
                            for j in range(min(n_eta, h.shape[0])):
                                for i in range(min(n_xi, h.shape[1] if h.ndim > 1 else 1)):
                                    h_ij = h[j, i] if h.ndim > 1 else h[j]
                                    z_ij = zeta_t[j, i] if zeta_t.ndim > 1 else 0.0

                                    # Compute sigma depths
                                    sigma_depths = (
                                        hc * s_rho + h_ij * cs_r
                                    ) / (hc + h_ij) * (h_ij + z_ij) + z_ij

                                    # Extract profile
                                    profile = var_data[t, :, j, i] if var_data.ndim > 3 else var_data[t, :, j]

                                    # Skip all-NaN profiles
                                    valid = ~np.isnan(profile)
                                    if np.sum(valid) < 2:
                                        continue

                                    # Interpolate to target depths
                                    try:
                                        f_interp = interp1d(
                                            -sigma_depths[valid],
                                            profile[valid],
                                            kind="linear",
                                            bounds_error=False,
                                            fill_value=np.nan,
                                        )
                                        z_data[t, :, j, i] = f_interp(target_depths)
                                    except Exception:
                                        pass

                    z_ds_vars[var_name] = xr.DataArray(
                        data=z_data,
                        dims=["time", "depth", "eta_rho", "xi_rho"],
                        attrs=ds[var_name].attrs.copy(),
                    )

                if z_ds_vars:
                    z_ds = xr.Dataset(z_ds_vars)
                    z_ds["depth"] = xr.DataArray(
                        data=target_depths,
                        dims=["depth"],
                        attrs={
                            "standard_name": "depth",
                            "long_name": "Depth Below Mean Sea Level",
                            "units": "m",
                            "positive": "down",
                        },
                    )

                    # Copy coordinate variables
                    for coord in ["lon_rho", "lat_rho", "time"]:
                        if coord in ds:
                            z_ds[coord] = ds[coord]

                    z_ds = self._add_cf_global_attributes(
                        z_ds,
                        title=f"{self.ofs_name.upper()} ROMS Z-Level Fields",
                        summary=f"Z-level interpolated fields from {self.ofs_name.upper()} ROMS",
                    )

                    out_name = field_file.name.replace(
                        ".enhanced.nc", ".zlevel.nc"
                    )
                    out_path = self.data_dir / out_name
                    z_ds.to_netcdf(str(out_path))
                    z_files.append(out_path)
                    z_ds.close()
                    self.logger.info(f"Z-level file written: {out_path}")

                ds.close()

            except Exception as e:
                self.logger.error(
                    f"Sigma-to-z interpolation failed for {field_file.name}: {e}"
                )

        return z_files

    def extract_stations(self) -> PostResult:
        """
        Extract station timeseries from ROMS station output.

        ROMS station output is already in NetCDF format. This method
        reads the station files, adds CF attributes, and writes
        standardized station timeseries.

        Returns:
            PostResult with station timeseries files
        """
        self.logger.info("Extracting ROMS station timeseries")

        output_files = []
        warnings = []

        try:
            import xarray as xr
        except ImportError as e:
            return PostResult(
                success=True,
                phase="extract_stations",
                warnings=[f"xarray not available: {e}; station extraction skipped"],
            )

        # Find station files
        station_patterns = [
            f"nos.{self.ofs_name}.stations.nowcast.{self.pdy}.{self.cycle}.nc",
            f"nos.{self.ofs_name}.stations.forecast.{self.pdy}.{self.cycle}.nc",
        ]

        for pattern in station_patterns:
            station_files = sorted(self.data_dir.glob(pattern))
            if not station_files:
                station_files = sorted(self.comout.glob(pattern))

            for station_file in station_files:
                self.logger.info(f"Processing station file: {station_file.name}")
                try:
                    ds = xr.open_dataset(str(station_file))

                    # Add CF attributes to station variables
                    for var_name, attrs in self.ROMS_FIELD_VARS.items():
                        if var_name in ds:
                            ds[var_name].attrs.update(attrs)

                    ds = self._add_cf_global_attributes(
                        ds,
                        title=f"{self.ofs_name.upper()} Station Timeseries",
                        summary=f"Station timeseries from {self.ofs_name.upper()} ROMS",
                    )

                    out_name = station_file.name.replace(".nc", ".standard.nc")
                    out_path = self.data_dir / out_name
                    ds.to_netcdf(str(out_path))
                    output_files.append(out_path)
                    ds.close()

                except Exception as e:
                    warnings.append(
                        f"Failed to process {station_file.name}: {e}"
                    )

        if not output_files:
            warnings.append("No ROMS station files found")

        return PostResult(
            success=True,
            phase="extract_stations",
            output_files=output_files,
            warnings=warnings,
        )

    def create_standard_netcdf(self) -> PostResult:
        """
        Generate CO-OPS standard NetCDF from enhanced ROMS output.

        Ensures all files conform to CF-1.6 conventions with proper
        coordinate references, time encoding, and standard variable names.

        Returns:
            PostResult with standard NetCDF files
        """
        self.logger.info("Creating ROMS standard NetCDF output")

        output_files = []
        warnings = []

        try:
            import xarray as xr
        except ImportError:
            return PostResult(
                success=True,
                phase="create_standard_netcdf",
                warnings=["xarray not available; standard NetCDF creation skipped"],
            )

        # Find enhanced field files
        patterns = [
            f"nos.{self.ofs_name}.fields.*.enhanced.nc",
            f"nos.{self.ofs_name}.fields.*.zlevel.nc",
            f"nos.{self.ofs_name}.stations.*.standard.nc",
        ]

        for pattern in patterns:
            for src_file in sorted(self.data_dir.glob(pattern)):
                self.logger.info(f"Standardizing: {src_file.name}")
                try:
                    ds = xr.open_dataset(str(src_file))

                    # Ensure proper time encoding
                    if "ocean_time" in ds or "time" in ds:
                        time_var = "ocean_time" if "ocean_time" in ds else "time"
                        ds[time_var].encoding.update({
                            "units": f"seconds since {self.pdy[:4]}-{self.pdy[4:6]}-{self.pdy[6:8]} 00:00:00",
                            "calendar": "standard",
                            "dtype": "float64",
                        })

                    # Rename ocean_time to time for CF compliance
                    if "ocean_time" in ds and "time" not in ds:
                        ds = ds.rename({"ocean_time": "time"})

                    std_name = src_file.name.replace(
                        ".enhanced.nc", ".standard.nc"
                    ).replace(".zlevel.nc", ".zlevel.standard.nc")
                    std_path = self.data_dir / std_name
                    ds.to_netcdf(str(std_path))
                    output_files.append(std_path)
                    ds.close()

                except Exception as e:
                    warnings.append(f"Failed to standardize {src_file.name}: {e}")

        return PostResult(
            success=True,
            phase="create_standard_netcdf",
            output_files=output_files,
            warnings=warnings,
        )

    def archive_outputs(self) -> PostResult:
        """
        Copy post-processed ROMS products to COMOUT.

        Archives:
        - Enhanced and standard field NetCDFs
        - Z-level interpolated files
        - Standard station timeseries
        - Restart files

        Returns:
            PostResult with list of archived files
        """
        self.logger.info("Archiving ROMS post-processed outputs to COMOUT")

        archived_files = []
        warnings = []

        self.comout.mkdir(parents=True, exist_ok=True)

        # Archive patterns
        archive_patterns = [
            # Original field files (these may already be in COMOUT)
            f"nos.{self.ofs_name}.fields.*.{self.pdy}.{self.cycle}.nc",
            # Enhanced and standard field files
            f"nos.{self.ofs_name}.fields.*.standard.nc",
            f"nos.{self.ofs_name}.fields.*.zlevel*.nc",
            # Station files
            f"nos.{self.ofs_name}.stations.*.standard.nc",
            # Restart files
            f"nos.{self.ofs_name}.rst.*.nc",
        ]

        for pattern in archive_patterns:
            for src_file in sorted(self.data_dir.glob(pattern)):
                archived = self._copy_to_comout(src_file)
                if archived:
                    archived_files.append(archived)
                else:
                    warnings.append(f"Failed to archive: {src_file.name}")

        # Set directory permissions
        try:
            os.chmod(str(self.comout), 0o755)
        except OSError:
            pass

        self.logger.info(f"Archived {len(archived_files)} ROMS files to {self.comout}")

        return PostResult(
            success=True,
            phase="archive_outputs",
            archived_files=archived_files,
            warnings=warnings,
            metadata={"n_archived": len(archived_files)},
        )
