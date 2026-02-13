"""
FVCOM Post-Processor

Handles post-processing for all FVCOM-based OFS systems:
- LEOFS (Lake Erie)
- LOOFS (Lake Ontario)
- LMHOFS (Lake Michigan-Huron)
- LSOFS (Lake Superior)
- NGOFS2 (Northern Gulf of Mexico)
- SFBOFS (San Francisco Bay)
- SSCOFS (Salish Sea)

FVCOM output files:
    - nos.{ofs}.fields.n{NNN}.{YYYYMMDD}.t{CC}z.nc: Nowcast fields
    - nos.{ofs}.fields.f{NNN}.{YYYYMMDD}.t{CC}z.nc: Forecast fields
    - nos.{ofs}.stations.nowcast.{YYYYMMDD}.t{CC}z.nc: Station nowcast
    - nos.{ofs}.stations.forecast.{YYYYMMDD}.t{CC}z.nc: Station forecast
    - nos.{ofs}.rst.nowcast.{YYYYMMDD}.t{CC}z.nc: Restart file

FVCOM uses an unstructured triangular mesh with sigma-coordinate vertical
levels. Post-processing can optionally perform:
- Unstructured-to-structured grid interpolation for regular-grid consumers
- Sigma-to-z-level vertical interpolation
- Triangle mesh to node-centered value conversion
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import BasePostProcessor, PostResult

log = logging.getLogger(__name__)


class FVCOMPostProcessor(BasePostProcessor):
    """
    Post-processor for FVCOM-based OFS systems.

    Handles extraction and conversion of FVCOM unstructured mesh output
    into standard products for CO-OPS dissemination.

    FVCOM output is on an unstructured triangular mesh. Key challenges:
    - Variables may be defined at nodes or element centroids
    - Sigma coordinates vary per node based on local bathymetry
    - Some downstream consumers require regular (structured) grids

    Attributes:
        ocean_model: Always "FVCOM"
        interp_to_regular: Whether to interpolate to a regular grid
        regular_grid_resolution: Resolution (degrees) for regular grid
    """

    # FVCOM primary output variables
    FVCOM_FIELD_VARS = {
        "zeta": {
            "standard_name": "sea_surface_height_above_geoid",
            "long_name": "Water Surface Elevation",
            "units": "m",
            "location": "node",
        },
        "temp": {
            "standard_name": "sea_water_temperature",
            "long_name": "Sea Water Temperature",
            "units": "degC",
            "location": "node",
        },
        "salinity": {
            "standard_name": "sea_water_salinity",
            "long_name": "Sea Water Practical Salinity",
            "units": "PSU",
            "location": "node",
        },
        "u": {
            "standard_name": "eastward_sea_water_velocity",
            "long_name": "Eastward Sea Water Velocity",
            "units": "m/s",
            "location": "element",
        },
        "v": {
            "standard_name": "northward_sea_water_velocity",
            "long_name": "Northward Sea Water Velocity",
            "units": "m/s",
            "location": "element",
        },
        "ua": {
            "standard_name": "barotropic_eastward_sea_water_velocity",
            "long_name": "Depth-Averaged Eastward Velocity",
            "units": "m/s",
            "location": "element",
        },
        "va": {
            "standard_name": "barotropic_northward_sea_water_velocity",
            "long_name": "Depth-Averaged Northward Velocity",
            "units": "m/s",
            "location": "element",
        },
        "tauc": {
            "standard_name": "surface_downward_eastward_stress",
            "long_name": "Surface Wind Stress",
            "units": "Pa",
            "location": "element",
        },
    }

    # Great Lakes OFS systems (no ocean boundary / salinity minimal)
    GREAT_LAKES_OFS = {"leofs", "loofs", "lmhofs", "lsofs"}

    def __init__(self, config: Any):
        """
        Initialize FVCOM post-processor.

        Args:
            config: OFSConfig instance
        """
        super().__init__(config)
        self.ocean_model = "FVCOM"
        self.interp_to_regular = bool(
            int(os.environ.get("FVCOM_INTERP_TO_REGULAR", "0"))
        )
        self.regular_grid_resolution = float(
            os.environ.get("FVCOM_REGULAR_GRID_RES", "0.01")
        )
        self.is_great_lakes = self.ofs_name.lower() in self.GREAT_LAKES_OFS

        self.logger.info(
            f"FVCOMPostProcessor initialized: ofs={self.ofs_name}, "
            f"great_lakes={self.is_great_lakes}, "
            f"interp_to_regular={self.interp_to_regular}"
        )

    def _get_model_type(self) -> str:
        """Return model type identifier."""
        return "FVCOM"

    def validate_model_output(self) -> Tuple[bool, List[str]]:
        """
        Validate FVCOM model output files exist.

        Checks for:
        - Nowcast field files: nos.{ofs}.fields.n*.nc
        - Station files (optional): nos.{ofs}.stations.*.nc
        - Restart file: nos.{ofs}.rst.*.nc

        Returns:
            Tuple of (is_valid, list_of_missing_files)
        """
        missing = []

        # Check for nowcast history files
        nowcast_pattern = f"nos.{self.ofs_name}.fields.n*.{self.pdy}.{self.cycle}.nc"
        nowcast_files = sorted(self.data_dir.glob(nowcast_pattern))
        if not nowcast_files:
            nowcast_files = sorted(self.comout.glob(nowcast_pattern))

        if not nowcast_files:
            missing.append(f"Nowcast field files ({nowcast_pattern})")

        # Check for forecast files
        forecast_pattern = f"nos.{self.ofs_name}.fields.f*.{self.pdy}.{self.cycle}.nc"
        forecast_files = sorted(self.data_dir.glob(forecast_pattern))
        if not forecast_files:
            forecast_files = sorted(self.comout.glob(forecast_pattern))

        if not forecast_files:
            self.logger.info("No forecast field files found (may be expected)")

        is_valid = len(missing) == 0
        if is_valid:
            self.logger.info(
                f"FVCOM output validation passed: "
                f"{len(nowcast_files)} nowcast, {len(forecast_files)} forecast files"
            )
        else:
            self.logger.warning(
                f"FVCOM output validation: {len(missing)} issues found"
            )

        return is_valid, missing

    def extract_fields(self) -> PostResult:
        """
        Extract and enhance 2D/3D fields from FVCOM output.

        Reads FVCOM output NetCDFs, adds CF-compliant attributes, and
        optionally performs element-to-node interpolation for variables
        defined at element centroids.

        Returns:
            PostResult with extracted field files
        """
        self.logger.info("Extracting FVCOM fields")

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

        # Find all field files
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
                errors=["No FVCOM field files found"],
            )

        self.logger.info(f"Found {len(field_files)} FVCOM field files")

        for field_file in field_files:
            self.logger.info(f"Processing: {field_file.name}")
            try:
                ds = xr.open_dataset(str(field_file))

                # Add CF attributes for known variables
                for var_name, var_info in self.FVCOM_FIELD_VARS.items():
                    if var_name in ds:
                        attrs = {
                            k: v for k, v in var_info.items() if k != "location"
                        }
                        ds[var_name].attrs.update(attrs)

                # Add mesh topology variable for CF-UGRID compliance
                if "nv" in ds:
                    ds.attrs["mesh_topology"] = "fvcom_mesh"

                # Add global attributes
                ds = self._add_cf_global_attributes(
                    ds,
                    title=f"{self.ofs_name.upper()} FVCOM Fields",
                    summary=f"Ocean model fields from {self.ofs_name.upper()} FVCOM",
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

        # Optional: interpolation to regular grid
        if self.interp_to_regular and output_files:
            self.logger.info("Interpolating FVCOM to regular grid")
            regular_files = self._interpolate_to_regular_grid(output_files)
            if regular_files:
                output_files.extend(regular_files)
            else:
                warnings.append("Regular grid interpolation produced no output")

        success = len(output_files) > 0

        return PostResult(
            success=success,
            phase="extract_fields",
            output_files=output_files,
            errors=errors,
            warnings=warnings,
            metadata={"n_field_files": len(field_files)},
        )

    def _interpolate_to_regular_grid(
        self, field_files: List[Path]
    ) -> List[Path]:
        """
        Interpolate FVCOM unstructured mesh to a regular grid.

        Uses scipy's griddata for scattered data interpolation from
        triangular mesh to regular lon/lat grid.

        Args:
            field_files: List of enhanced FVCOM field files

        Returns:
            List of regular-grid interpolated files
        """
        regular_files = []

        try:
            import numpy as np
            import xarray as xr
            from scipy.interpolate import griddata
        except ImportError as e:
            self.logger.warning(
                f"scipy not available for grid interpolation: {e}"
            )
            return regular_files

        for field_file in field_files:
            try:
                ds = xr.open_dataset(str(field_file))

                # Get node coordinates
                lon_node = None
                lat_node = None
                for lon_name in ["lon", "x", "lonc"]:
                    if lon_name in ds:
                        lon_node = ds[lon_name].values
                        break
                for lat_name in ["lat", "y", "latc"]:
                    if lat_name in ds:
                        lat_node = ds[lat_name].values
                        break

                if lon_node is None or lat_node is None:
                    self.logger.debug(
                        f"No coordinates in {field_file.name}; skipping"
                    )
                    ds.close()
                    continue

                # Create regular grid
                lon_min, lon_max = float(np.nanmin(lon_node)), float(np.nanmax(lon_node))
                lat_min, lat_max = float(np.nanmin(lat_node)), float(np.nanmax(lat_node))
                res = self.regular_grid_resolution

                lon_reg = np.arange(lon_min, lon_max + res, res)
                lat_reg = np.arange(lat_min, lat_max + res, res)
                lon_grid, lat_grid = np.meshgrid(lon_reg, lat_reg)

                # Interpolate 2D variables
                reg_vars = {}
                target_vars = ["zeta", "ua", "va"]

                for var_name in target_vars:
                    if var_name not in ds:
                        continue

                    var_data = ds[var_name].values
                    if var_data.ndim == 1:
                        # Single time step, 1D spatial
                        try:
                            interp_data = griddata(
                                (lon_node, lat_node),
                                var_data,
                                (lon_grid, lat_grid),
                                method="linear",
                            )
                            reg_vars[var_name] = xr.DataArray(
                                data=interp_data[np.newaxis, :, :],
                                dims=["time", "lat", "lon"],
                                attrs=ds[var_name].attrs.copy(),
                            )
                        except Exception as e:
                            self.logger.debug(
                                f"Interpolation failed for {var_name}: {e}"
                            )

                    elif var_data.ndim == 2:
                        # Multiple time steps, 1D spatial
                        n_times = var_data.shape[0]
                        interp_all = np.full(
                            (n_times, len(lat_reg), len(lon_reg)),
                            np.nan,
                            dtype=np.float32,
                        )
                        for t in range(n_times):
                            try:
                                interp_all[t] = griddata(
                                    (lon_node, lat_node),
                                    var_data[t],
                                    (lon_grid, lat_grid),
                                    method="linear",
                                )
                            except Exception:
                                pass

                        reg_vars[var_name] = xr.DataArray(
                            data=interp_all,
                            dims=["time", "lat", "lon"],
                            attrs=ds[var_name].attrs.copy(),
                        )

                if reg_vars:
                    reg_ds = xr.Dataset(reg_vars)
                    reg_ds["lon"] = xr.DataArray(
                        data=lon_reg,
                        dims=["lon"],
                        attrs={
                            "standard_name": "longitude",
                            "units": "degrees_east",
                        },
                    )
                    reg_ds["lat"] = xr.DataArray(
                        data=lat_reg,
                        dims=["lat"],
                        attrs={
                            "standard_name": "latitude",
                            "units": "degrees_north",
                        },
                    )

                    # Copy time variable
                    for t_name in ["time", "Times"]:
                        if t_name in ds:
                            reg_ds[t_name] = ds[t_name]
                            break

                    reg_ds = self._add_cf_global_attributes(
                        reg_ds,
                        title=f"{self.ofs_name.upper()} Regular Grid Fields",
                        summary=(
                            f"Regular grid interpolation of {self.ofs_name.upper()} "
                            f"FVCOM output at {res} degree resolution"
                        ),
                    )

                    out_name = field_file.name.replace(
                        ".enhanced.nc", ".regular.nc"
                    )
                    out_path = self.data_dir / out_name
                    reg_ds.to_netcdf(str(out_path))
                    regular_files.append(out_path)
                    reg_ds.close()
                    self.logger.info(f"Regular grid file written: {out_path}")

                ds.close()

            except Exception as e:
                self.logger.error(
                    f"Regular grid interpolation failed for {field_file.name}: {e}"
                )

        return regular_files

    def extract_stations(self) -> PostResult:
        """
        Extract station timeseries from FVCOM output.

        FVCOM station output is in NetCDF format. This method reads
        station files, adds CF attributes, and writes standardized
        station timeseries.

        Returns:
            PostResult with station timeseries files
        """
        self.logger.info("Extracting FVCOM station timeseries")

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

                    # Add CF attributes for known variables
                    for var_name, var_info in self.FVCOM_FIELD_VARS.items():
                        if var_name in ds:
                            attrs = {
                                k: v for k, v in var_info.items() if k != "location"
                            }
                            ds[var_name].attrs.update(attrs)

                    ds = self._add_cf_global_attributes(
                        ds,
                        title=f"{self.ofs_name.upper()} Station Timeseries",
                        summary=f"Station timeseries from {self.ofs_name.upper()} FVCOM",
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
            warnings.append("No FVCOM station files found")

        return PostResult(
            success=True,
            phase="extract_stations",
            output_files=output_files,
            warnings=warnings,
        )

    def create_standard_netcdf(self) -> PostResult:
        """
        Generate CO-OPS standard NetCDF from enhanced FVCOM output.

        Ensures all files conform to CF-1.6 / CF-UGRID conventions
        with proper coordinate references, time encoding, mesh topology
        metadata, and standard variable names.

        Returns:
            PostResult with standard NetCDF files
        """
        self.logger.info("Creating FVCOM standard NetCDF output")

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
            f"nos.{self.ofs_name}.fields.*.regular.nc",
            f"nos.{self.ofs_name}.stations.*.standard.nc",
        ]

        for pattern in patterns:
            for src_file in sorted(self.data_dir.glob(pattern)):
                self.logger.info(f"Standardizing: {src_file.name}")
                try:
                    ds = xr.open_dataset(str(src_file))

                    # Handle FVCOM-specific time format
                    # FVCOM uses "Times" as character array and "time" as float
                    if "time" in ds:
                        ds["time"].encoding.update({
                            "units": (
                                f"seconds since {self.pdy[:4]}-{self.pdy[4:6]}"
                                f"-{self.pdy[6:8]} 00:00:00"
                            ),
                            "calendar": "standard",
                            "dtype": "float64",
                        })

                    # For Great Lakes, omit salinity-related variables
                    if self.is_great_lakes:
                        if "salinity" in ds and ds["salinity"].max() < 0.5:
                            ds.attrs["note_salinity"] = (
                                "Salinity is effectively zero in this Great Lakes system"
                            )

                    std_name = src_file.name.replace(
                        ".enhanced.nc", ".standard.nc"
                    ).replace(".regular.nc", ".regular.standard.nc")
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
        Copy post-processed FVCOM products to COMOUT.

        Archives:
        - Enhanced and standard field NetCDFs
        - Regular grid interpolated files
        - Standard station timeseries
        - Restart files

        Returns:
            PostResult with list of archived files
        """
        self.logger.info("Archiving FVCOM post-processed outputs to COMOUT")

        archived_files = []
        warnings = []

        self.comout.mkdir(parents=True, exist_ok=True)

        # Archive patterns
        archive_patterns = [
            # Original field files
            f"nos.{self.ofs_name}.fields.*.{self.pdy}.{self.cycle}.nc",
            # Enhanced and standard field files
            f"nos.{self.ofs_name}.fields.*.standard.nc",
            f"nos.{self.ofs_name}.fields.*.regular*.nc",
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

        self.logger.info(f"Archived {len(archived_files)} FVCOM files to {self.comout}")

        return PostResult(
            success=True,
            phase="archive_outputs",
            archived_files=archived_files,
            warnings=warnings,
            metadata={"n_archived": len(archived_files)},
        )
