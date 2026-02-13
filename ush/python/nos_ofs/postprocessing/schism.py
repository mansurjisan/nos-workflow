"""
SCHISM Post-Processor

Handles post-processing for all SCHISM-based OFS systems:
- STOFS-3D Atlantic/Pacific (two-phase post-processing via shell scripts)
- SECOFS, CREOFS (single-phase COMF post-processing)

STOFS two-phase post-processing:
    Phase 1 (post_1):
        - Backup raw 2D/3D output files
        - Add variable attributes to out2d, temperature, salinity, velocity NetCDFs
        - Create AWIPS/SHEF station timeseries from staout_*
        - Create AWS/EC2 auto-validation NetCDF files
        - Create station profile NetCDF files
        - Create ADCIRC-format water level NetCDFs
        - Create AWIPS GRIB2 files

    Phase 2 (post_2):
        - Merge hotstart files (combine_hotstart executable)
        - Create 2D field NetCDF files from out2d_*.nc
        - Create GeoPackage (.gpkg) files for nowCOAST

COMF SCHISM post-processing (single-phase):
    - Extract 2D fields (water level, velocity, wind, pressure)
    - Extract 3D fields (temperature, salinity, velocity, elevation)
    - Station timeseries extraction
    - Standard NetCDF generation with CF conventions
    - Archive to COMOUT

SCHISM output files:
    - out2d_{1..N}.nc: 2D fields (elevation, velocity, wind, pressure, etc.)
    - horizontalVelX_{1..N}.nc, horizontalVelY_{1..N}.nc: 3D velocity
    - temperature_{1..N}.nc, salinity_{1..N}.nc: 3D tracers
    - zCoordinates_{1..N}.nc: 3D vertical coordinates
    - outputs/staout_*: Station timeseries (ASCII)
    - outputs/mirror.out: Model run status
"""

import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import BasePostProcessor, PostResult

log = logging.getLogger(__name__)


class SCHISMPostProcessor(BasePostProcessor):
    """
    Post-processor for SCHISM-based OFS systems.

    Supports two operational modes:
    - STOFS mode: Two-phase post-processing that dispatches to existing
      STOFS shell scripts (exstofs_3d_atl_post_1.sh, post_2.sh)
    - COMF mode: Single-phase Python-native post-processing for COMF
      SCHISM systems (SECOFS, CREOFS)

    The mode is determined by the framework attribute in the configuration
    or the OFS_FRAMEWORK environment variable.

    Attributes:
        framework: "stofs" or "comf"
        n_output_files: Number of SCHISM output file segments (typically 10)
        output_dir: Path to SCHISM outputs/ subdirectory
    """

    # SCHISM 2D output variables of interest
    SCHISM_2D_VARS = [
        "elevation",        # Water surface elevation (m)
        "dahv",             # Depth-averaged horizontal velocity
        "windSpeedX",       # Wind speed X-component (m/s)
        "windSpeedY",       # Wind speed Y-component (m/s)
        "airPressure",      # Atmospheric pressure (Pa)
        "precipitationRate",  # Precipitation rate
    ]

    # SCHISM 3D output variables
    SCHISM_3D_VARS = [
        "temperature",      # Water temperature (degC)
        "salinity",         # Salinity (PSU)
        "horizontalVelX",   # Horizontal velocity X (m/s)
        "horizontalVelY",   # Horizontal velocity Y (m/s)
        "zCoordinates",     # Vertical coordinates (m)
    ]

    # Standard CO-OPS variable mapping: SCHISM name -> CO-OPS standard name
    VAR_NAME_MAP = {
        "elevation": "zeta",
        "temperature": "temp",
        "salinity": "salt",
        "horizontalVelX": "u",
        "horizontalVelY": "v",
        "zCoordinates": "zcor",
        "windSpeedX": "uwind_stress",
        "windSpeedY": "vwind_stress",
        "airPressure": "air_pressure",
    }

    def __init__(self, config: Any, framework: Optional[str] = None):
        """
        Initialize SCHISM post-processor.

        Args:
            config: OFSConfig instance
            framework: Force framework ("stofs" or "comf"). If None, auto-detect.
        """
        super().__init__(config)

        # Determine framework
        if framework is None:
            framework = os.environ.get(
                "OFS_FRAMEWORK",
                getattr(config, "OFS_FRAMEWORK", None),
            )
            if framework is None:
                framework = getattr(config, "framework", "comf").lower()

        self.framework = framework.lower()

        # STOFS-specific paths
        if self.framework == "stofs":
            self.ush_stofs = Path(
                os.environ.get("USHstofs3d", str(self.ush_dir))
            )
            self.exec_stofs = Path(
                os.environ.get("EXECstofs3d", str(self.exec_dir))
            )
            self.fix_stofs = Path(
                os.environ.get("FIXstofs3d", str(self.fix_dir))
            )
            self.py_stofs = Path(
                os.environ.get("PYstofs3d", str(self.ush_dir.parent / "python"))
            )

        # SCHISM output configuration
        self.n_output_files = int(
            os.environ.get("N_SCHISM_OUTPUT_FILES", "10")
        )
        self.output_dir = self.data_dir / "outputs"

        self.logger.info(
            f"SCHISMPostProcessor initialized: framework={self.framework}, "
            f"ofs={self.ofs_name}"
        )

    def _get_model_type(self) -> str:
        """Return model type identifier."""
        return "SCHISM"

    def validate_model_output(self) -> Tuple[bool, List[str]]:
        """
        Validate SCHISM model output files exist.

        Checks for:
        - outputs/mirror.out containing "Run completed successfully"
        - out2d_*.nc files (2D output)
        - 3D variable files (temperature, salinity, velocity)
        - staout_* station output files

        Returns:
            Tuple of (is_valid, list_of_missing_files)
        """
        missing = []

        # Check mirror.out for successful completion
        mirror_file = self.output_dir / "mirror.out"
        if not mirror_file.exists():
            missing.append("outputs/mirror.out")
        else:
            try:
                content = mirror_file.read_text()
                if "Run completed successfully" not in content:
                    missing.append(
                        "outputs/mirror.out (does not contain success message)"
                    )
            except Exception as e:
                missing.append(f"outputs/mirror.out (read error: {e})")

        # Check 2D output files
        for i in range(1, self.n_output_files + 1):
            out2d = self.output_dir / f"out2d_{i}.nc"
            if not out2d.exists():
                missing.append(f"outputs/out2d_{i}.nc")

        # Check 3D output files
        for var in ["temperature", "salinity"]:
            for i in range(1, self.n_output_files + 1):
                fpath = self.output_dir / f"{var}_{i}.nc"
                if not fpath.exists():
                    missing.append(f"outputs/{var}_{i}.nc")

        # Check station output (staout_1 = elevation)
        staout_1 = self.output_dir / "staout_1"
        if not staout_1.exists():
            missing.append("outputs/staout_1")

        is_valid = len(missing) == 0
        if is_valid:
            self.logger.info("SCHISM model output validation passed")
        else:
            self.logger.warning(
                f"SCHISM model output validation: {len(missing)} issues found"
            )

        return is_valid, missing

    # ------------------------------------------------------------------
    # STOFS two-phase post-processing (dispatches to shell scripts)
    # ------------------------------------------------------------------

    def run_stofs_post_1(self) -> PostResult:
        """
        Run STOFS post-processing phase 1.

        Phase 1 includes:
        - Backup raw 2D/3D NetCDF files to Dir_backup_2d3d
        - Add variable attributes to 2D/3D NetCDFs (MPMD parallel)
        - Create AWIPS/SHEF station timeseries
        - Create AWS/EC2 auto-validation NetCDFs
        - Create station profile NetCDFs
        - Create ADCIRC-format water level NetCDFs
        - Create AWIPS GRIB2 files

        Returns:
            PostResult for phase 1
        """
        self.logger.info("Starting STOFS post-processing phase 1")
        start_time = __import__("time").time()

        errors = []
        warnings = []
        output_files = []
        step_results = {}

        # Validate model run completed
        is_valid, missing = self.validate_model_output()
        step_results["validate"] = is_valid
        if not is_valid:
            return PostResult(
                success=False,
                phase="post_1",
                total_duration_seconds=__import__("time").time() - start_time,
                errors=[f"Model output validation failed: {', '.join(missing[:5])}"],
                step_results=step_results,
            )

        # Backup raw output
        self.logger.info("Backing up raw 2D/3D output files")
        backup_dir = self.data_dir / "Dir_backup_2d3d"
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            for pattern in [
                "horizontalVelX", "horizontalVelY", "out2d",
                "salinity", "temperature", "zCoordinates",
            ]:
                for nc_file in sorted(self.output_dir.glob(f"{pattern}*.nc")):
                    dst = backup_dir / nc_file.name
                    if not dst.exists():
                        shutil.copy2(str(nc_file), str(dst))
            step_results["backup_raw"] = True
        except Exception as e:
            self.logger.warning(f"Backup of raw outputs failed: {e}")
            warnings.append(f"Backup failed: {e}")
            step_results["backup_raw"] = False

        # Add variable attributes to 2D/3D NetCDFs
        self.logger.info("Adding variable attributes to 2D/3D NetCDFs")
        script = self.ush_stofs / "stofs_3d_atl_add_attr_2d_3d_nc.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="add_attr_2d_3d_nc",
                timeout=1800,
            )
            step_results["add_attributes"] = ok
            if not ok:
                warnings.append(f"Add attributes failed: {stderr[:200]}")
        else:
            step_results["add_attributes"] = False
            warnings.append(f"Script not found: {script}")

        # Create AWIPS/SHEF station timeseries
        self.logger.info("Creating AWIPS/SHEF station timeseries")
        script = self.ush_stofs / "stofs_3d_atl_create_awips_shef.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="create_awips_shef",
                timeout=1800,
            )
            step_results["awips_shef"] = ok
            if not ok:
                warnings.append(f"AWIPS/SHEF creation failed: {stderr[:200]}")
        else:
            step_results["awips_shef"] = False
            warnings.append(f"Script not found: {script}")

        # Create AWS/EC2 auto-validation NetCDFs
        self.logger.info("Creating AWS auto-validation NetCDF files")
        script = self.ush_stofs / "stofs_3d_atl_create_AWS_autoval_nc.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="create_autoval_nc",
                timeout=1800,
            )
            step_results["autoval_nc"] = ok
            if not ok:
                warnings.append(f"Autoval NC creation failed: {stderr[:200]}")
        else:
            step_results["autoval_nc"] = False
            warnings.append(f"Script not found: {script}")

        # Create station profile NetCDFs
        self.logger.info("Creating station profile NetCDF files")
        script = self.ush_stofs / "stofs_3d_atl_create_station_profile_nc.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="create_station_profile",
                timeout=1800,
            )
            step_results["station_profile"] = ok
            if not ok:
                warnings.append(f"Station profile creation failed: {stderr[:200]}")
        else:
            step_results["station_profile"] = False
            warnings.append(f"Script not found: {script}")

        # Create ADCIRC-format water level NetCDFs
        self.logger.info("Creating ADCIRC-format water level NetCDFs")
        script = self.ush_stofs / "stofs_3d_atl_create_adcirc_nc.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="create_adcirc_nc",
                timeout=1800,
            )
            step_results["adcirc_nc"] = ok
            if not ok:
                warnings.append(f"ADCIRC NC creation failed: {stderr[:200]}")
        else:
            step_results["adcirc_nc"] = False
            warnings.append(f"Script not found: {script}")

        # Create AWIPS GRIB2 files
        self.logger.info("Creating AWIPS GRIB2 files")
        script = self.ush_stofs / "stofs_3d_atl_create_awips_grib2.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="create_awips_grib2",
                timeout=1800,
            )
            step_results["awips_grib2"] = ok
            if not ok:
                warnings.append(f"AWIPS GRIB2 creation failed: {stderr[:200]}")
        else:
            step_results["awips_grib2"] = False
            warnings.append(f"Script not found: {script}")

        # Collect output files from COMOUT
        if self.comout.exists():
            for f in sorted(self.comout.glob(f"{self.ofs_name}.{self.cycle}.*")):
                output_files.append(f)

        total_duration = __import__("time").time() - start_time

        # Phase 1 succeeds even if some non-critical steps fail (matching
        # the shell script behavior where warnings do not cause err_chk)
        overall_success = step_results.get("validate", False)

        return PostResult(
            success=overall_success,
            phase="post_1",
            total_duration_seconds=total_duration,
            output_files=output_files,
            errors=errors,
            warnings=warnings,
            step_results=step_results,
        )

    def run_stofs_post_2(self) -> PostResult:
        """
        Run STOFS post-processing phase 2.

        Phase 2 includes:
        - Merge hotstart files using combine_hotstart executable
        - Create 2D field NetCDF files from out2d_*.nc (MPMD parallel)
        - Create GeoPackage (.gpkg) files for nowCOAST

        Returns:
            PostResult for phase 2
        """
        self.logger.info("Starting STOFS post-processing phase 2")
        start_time = __import__("time").time()

        errors = []
        warnings = []
        output_files = []
        step_results = {}

        # Validate model run completed
        is_valid, missing = self.validate_model_output()
        step_results["validate"] = is_valid
        if not is_valid:
            return PostResult(
                success=False,
                phase="post_2",
                total_duration_seconds=__import__("time").time() - start_time,
                errors=[f"Model output validation failed: {', '.join(missing[:5])}"],
                step_results=step_results,
            )

        # Merge hotstart files
        self.logger.info("Merging hotstart files")
        idx_merge = int(os.environ.get("IDX_TIME_STEP_MERGE_HOTSTART", "576"))
        combine_exe = self.exec_stofs / "stofs_3d_atl_combine_hotstart"

        if combine_exe.exists():
            ok, stdout, stderr = self._run_subprocess(
                f"{combine_exe} -i {idx_merge}",
                step_name="combine_hotstart",
                cwd=self.output_dir,
                timeout=3600,
            )
            step_results["combine_hotstart"] = ok

            if ok:
                merged_file = self.output_dir / f"hotstart_it={idx_merge}.nc"
                if merged_file.exists():
                    # Set time=0 using ncap2
                    merged_t0 = Path(f"{merged_file}_time_00")
                    ok_ncap, _, stderr_ncap = self._run_subprocess(
                        f"ncap2 -O -s 'time=0.0' {merged_file} {merged_t0}",
                        step_name="ncap2_hotstart_time",
                        cwd=self.output_dir,
                        timeout=600,
                    )

                    if ok_ncap and merged_t0.exists():
                        std_name = f"{self.ofs_name}.{self.cycle}.hotstart.stofs3d.nc"
                        archived = self._copy_to_comout(merged_t0, std_name)
                        if archived:
                            output_files.append(archived)
                            self.logger.info(f"Hotstart archived: {std_name}")
                    else:
                        warnings.append("ncap2 time adjustment failed for hotstart")
                else:
                    warnings.append(
                        f"Merged hotstart file not found: {merged_file}"
                    )
            else:
                warnings.append(f"combine_hotstart failed: {stderr[:200]}")
        else:
            step_results["combine_hotstart"] = False
            warnings.append(f"combine_hotstart executable not found: {combine_exe}")

        # Create 2D field NetCDF files
        self.logger.info("Creating 2D field NetCDF files")
        script = self.ush_stofs / "stofs_3d_atl_create_2d_field_nc.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="create_2d_field_nc",
                timeout=3600,
            )
            step_results["create_2d_field"] = ok
            if not ok:
                warnings.append(f"2D field NC creation failed: {stderr[:200]}")
        else:
            step_results["create_2d_field"] = False
            warnings.append(f"Script not found: {script}")

        # Create GeoPackage files
        self.logger.info("Creating GeoPackage files")
        script = self.ush_stofs / "stofs_3d_atl_create_geopackage.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="create_geopackage",
                timeout=3600,
            )
            step_results["geopackage"] = ok
            if not ok:
                warnings.append(f"GeoPackage creation failed: {stderr[:200]}")
        else:
            step_results["geopackage"] = False
            warnings.append(f"Script not found: {script}")

        # Collect output files
        if self.comout.exists():
            for f in sorted(self.comout.glob(f"{self.ofs_name}.{self.cycle}.*")):
                if f not in output_files:
                    output_files.append(f)

        total_duration = __import__("time").time() - start_time

        return PostResult(
            success=step_results.get("validate", False),
            phase="post_2",
            total_duration_seconds=total_duration,
            output_files=output_files,
            errors=errors,
            warnings=warnings,
            step_results=step_results,
        )

    # ------------------------------------------------------------------
    # COMF SCHISM post-processing (Python-native, single phase)
    # ------------------------------------------------------------------

    def extract_fields(self) -> PostResult:
        """
        Extract 2D and 3D fields from SCHISM output.

        For STOFS: Dispatches to shell scripts (add_attr_2d_3d_nc.sh handles
        attribute addition and field extraction).

        For COMF SCHISM: Uses xarray to extract fields from out2d_*.nc and
        3D variable files, adding CF-compliant attributes.

        Returns:
            PostResult with extracted field files
        """
        self.logger.info("Extracting SCHISM fields")

        if self.framework == "stofs":
            return self._stofs_extract_fields()

        return self._comf_schism_extract_fields()

    def _stofs_extract_fields(self) -> PostResult:
        """Extract fields for STOFS (delegates to shell scripts)."""
        # For STOFS, field extraction is handled by the add_attr scripts
        # in post_1. When called from the generic pipeline, we run the
        # attribute addition step.
        script = self.ush_stofs / "stofs_3d_atl_add_attr_2d_3d_nc.sh"
        if not script.exists():
            return PostResult(
                success=True,
                phase="extract_fields",
                warnings=["STOFS attr script not found; field extraction skipped"],
            )

        ok, stdout, stderr = self._run_subprocess(
            str(script),
            step_name="stofs_extract_fields",
            timeout=1800,
        )

        return PostResult(
            success=ok,
            phase="extract_fields",
            errors=[stderr[:300]] if not ok and stderr else [],
        )

    def _comf_schism_extract_fields(self) -> PostResult:
        """
        Extract fields for COMF SCHISM systems using xarray.

        Reads SCHISM output NetCDFs, extracts key variables, adds
        CF-compliant attributes, and writes standardized field files.
        """
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

        # Extract 2D fields from out2d_*.nc
        self.logger.info("Extracting 2D fields from SCHISM output")
        out2d_files = sorted(self.output_dir.glob("out2d_*.nc"))

        if not out2d_files:
            return PostResult(
                success=False,
                phase="extract_fields",
                errors=["No out2d_*.nc files found in outputs/"],
            )

        try:
            ds_2d = xr.open_mfdataset(
                [str(f) for f in out2d_files],
                combine="nested",
                concat_dim="time",
                data_vars="minimal",
                coords="minimal",
                compat="override",
            )

            # Add CF attributes to 2D variables
            cf_attrs_2d = {
                "elevation": {
                    "standard_name": "sea_surface_height_above_geoid",
                    "long_name": "Water Surface Elevation",
                    "units": "m",
                },
                "dahv": {
                    "long_name": "Depth-Averaged Horizontal Velocity",
                    "units": "m/s",
                },
                "windSpeedX": {
                    "standard_name": "eastward_wind",
                    "long_name": "Eastward Wind Speed at 10m",
                    "units": "m/s",
                },
                "windSpeedY": {
                    "standard_name": "northward_wind",
                    "long_name": "Northward Wind Speed at 10m",
                    "units": "m/s",
                },
                "airPressure": {
                    "standard_name": "air_pressure_at_mean_sea_level",
                    "long_name": "Atmospheric Pressure",
                    "units": "Pa",
                },
            }

            for var_name, attrs in cf_attrs_2d.items():
                if var_name in ds_2d:
                    ds_2d[var_name].attrs.update(attrs)

            # Write 2D fields
            out_name = self._standard_output_name("fields", "2d", ".nc")
            out_path = self.data_dir / out_name
            ds_2d = self._add_cf_global_attributes(
                ds_2d,
                title=f"{self.ofs_name.upper()} 2D Fields",
                summary=f"2D field output from {self.ofs_name.upper()} SCHISM model",
            )
            ds_2d.to_netcdf(str(out_path))
            output_files.append(out_path)
            ds_2d.close()
            self.logger.info(f"2D fields written: {out_path}")

        except Exception as e:
            self.logger.error(f"Failed to extract 2D fields: {e}")
            errors.append(f"2D field extraction failed: {e}")

        # Extract 3D fields (temperature, salinity)
        for var_3d in ["temperature", "salinity"]:
            self.logger.info(f"Extracting 3D field: {var_3d}")
            var_files = sorted(self.output_dir.glob(f"{var_3d}_*.nc"))

            if not var_files:
                warnings.append(f"No {var_3d}_*.nc files found")
                continue

            try:
                ds_3d = xr.open_mfdataset(
                    [str(f) for f in var_files],
                    combine="nested",
                    concat_dim="time",
                    data_vars="minimal",
                    coords="minimal",
                    compat="override",
                )

                # Add CF attributes
                if var_3d == "temperature":
                    ds_3d[var_3d].attrs.update({
                        "standard_name": "sea_water_temperature",
                        "long_name": "Sea Water Temperature",
                        "units": "degC",
                    })
                elif var_3d == "salinity":
                    ds_3d[var_3d].attrs.update({
                        "standard_name": "sea_water_salinity",
                        "long_name": "Sea Water Salinity",
                        "units": "PSU",
                    })

                out_name = self._standard_output_name(var_3d, "3d", ".nc")
                out_path = self.data_dir / out_name
                ds_3d = self._add_cf_global_attributes(
                    ds_3d,
                    title=f"{self.ofs_name.upper()} {var_3d.capitalize()} Field",
                    summary=f"3D {var_3d} from {self.ofs_name.upper()} SCHISM model",
                )
                ds_3d.to_netcdf(str(out_path))
                output_files.append(out_path)
                ds_3d.close()
                self.logger.info(f"3D {var_3d} field written: {out_path}")

            except Exception as e:
                self.logger.error(f"Failed to extract {var_3d}: {e}")
                warnings.append(f"{var_3d} extraction failed: {e}")

        success = len(errors) == 0 and len(output_files) > 0

        return PostResult(
            success=success,
            phase="extract_fields",
            output_files=output_files,
            errors=errors,
            warnings=warnings,
            metadata={"n_2d_files": len(out2d_files), "n_3d_vars": 2},
        )

    def extract_stations(self) -> PostResult:
        """
        Extract station timeseries from SCHISM output.

        For STOFS: Calls stofs_3d_atl_create_awips_shef.sh and
        stofs_3d_atl_create_station_profile_nc.sh.

        For COMF SCHISM: Reads staout_* files and creates station
        timeseries NetCDF with CF conventions.

        Returns:
            PostResult with station timeseries files
        """
        self.logger.info("Extracting SCHISM station timeseries")

        if self.framework == "stofs":
            return self._stofs_extract_stations()

        return self._comf_schism_extract_stations()

    def _stofs_extract_stations(self) -> PostResult:
        """Extract stations for STOFS (delegates to shell scripts)."""
        warnings = []
        output_files = []

        # AWIPS/SHEF station timeseries
        script = self.ush_stofs / "stofs_3d_atl_create_awips_shef.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="stofs_create_awips_shef",
                timeout=1800,
            )
            if not ok:
                warnings.append(f"AWIPS/SHEF creation failed: {stderr[:200]}")
        else:
            warnings.append(f"AWIPS/SHEF script not found: {script}")

        # Station profile NetCDFs
        script = self.ush_stofs / "stofs_3d_atl_create_station_profile_nc.sh"
        if script.exists():
            ok, stdout, stderr = self._run_subprocess(
                str(script),
                step_name="stofs_create_station_profile",
                timeout=1800,
            )
            if not ok:
                warnings.append(f"Station profile creation failed: {stderr[:200]}")
        else:
            warnings.append(f"Station profile script not found: {script}")

        return PostResult(
            success=True,
            phase="extract_stations",
            output_files=output_files,
            warnings=warnings,
        )

    def _comf_schism_extract_stations(self) -> PostResult:
        """
        Extract station timeseries for COMF SCHISM.

        Reads SCHISM staout_* files (ASCII format) and converts to
        station timeseries NetCDF with CF conventions.

        staout file columns: time, station_1_value, station_2_value, ...
        staout_1: elevation
        staout_2: air pressure
        staout_3: wind u
        staout_4: wind v
        staout_5: temperature
        staout_6: salinity
        """
        output_files = []
        warnings = []
        errors = []

        try:
            import numpy as np
        except ImportError as e:
            return PostResult(
                success=False,
                phase="extract_stations",
                errors=[f"numpy not available: {e}"],
            )

        # Station variable mapping: staout index -> (variable_name, units, standard_name)
        staout_vars = {
            1: ("elevation", "m", "sea_surface_height_above_geoid"),
            2: ("air_pressure", "Pa", "air_pressure_at_mean_sea_level"),
            3: ("wind_u", "m/s", "eastward_wind"),
            4: ("wind_v", "m/s", "northward_wind"),
            5: ("temperature", "degC", "sea_water_temperature"),
            6: ("salinity", "PSU", "sea_water_salinity"),
        }

        # Load station.in for station coordinates (if available)
        station_in = self.data_dir / "station.in"
        station_coords = None
        n_stations = 0

        if station_in.exists():
            try:
                lines = station_in.read_text().strip().split("\n")
                # First line may be number of stations or header
                # Format varies; try to parse coordinates
                coord_lines = []
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            x, y = float(parts[0]), float(parts[1])
                            coord_lines.append((x, y))
                        except ValueError:
                            continue
                if coord_lines:
                    station_coords = np.array(coord_lines)
                    n_stations = len(coord_lines)
                    self.logger.info(f"Loaded {n_stations} station coordinates")
            except Exception as e:
                warnings.append(f"Failed to parse station.in: {e}")

        # Process each staout file
        for idx, (var_name, units, std_name) in staout_vars.items():
            staout_file = self.output_dir / f"staout_{idx}"

            if not staout_file.exists():
                warnings.append(f"staout_{idx} not found; skipping {var_name}")
                continue

            self.logger.info(f"Processing staout_{idx} ({var_name})")

            try:
                data = np.loadtxt(str(staout_file))
                if data.ndim < 2 or data.shape[0] == 0:
                    warnings.append(f"staout_{idx} is empty or malformed")
                    continue

                times = data[:, 0]  # First column is time (seconds)
                values = data[:, 1:]  # Remaining columns are station values

                # Try to create xarray dataset
                try:
                    import xarray as xr

                    # Convert seconds to datetime
                    base_time = datetime.strptime(self.pdy, "%Y%m%d")
                    time_delta = [timedelta(seconds=float(t)) for t in times]
                    time_coords = [base_time + td for td in time_delta]

                    station_ids = np.arange(1, values.shape[1] + 1)

                    ds = xr.Dataset(
                        {
                            var_name: xr.DataArray(
                                data=values,
                                dims=["time", "station"],
                                coords={
                                    "time": time_coords,
                                    "station": station_ids,
                                },
                                attrs={
                                    "standard_name": std_name,
                                    "long_name": var_name.replace("_", " ").title(),
                                    "units": units,
                                },
                            )
                        }
                    )

                    # Add station coordinates if available
                    if station_coords is not None and len(station_coords) == values.shape[1]:
                        ds["station_lon"] = xr.DataArray(
                            data=station_coords[:, 0],
                            dims=["station"],
                            attrs={
                                "standard_name": "longitude",
                                "units": "degrees_east",
                            },
                        )
                        ds["station_lat"] = xr.DataArray(
                            data=station_coords[:, 1],
                            dims=["station"],
                            attrs={
                                "standard_name": "latitude",
                                "units": "degrees_north",
                            },
                        )

                    ds = self._add_cf_global_attributes(
                        ds,
                        title=f"{self.ofs_name.upper()} Station {var_name.replace('_', ' ').title()}",
                        summary=f"Station timeseries of {var_name} from {self.ofs_name.upper()}",
                    )

                    out_name = self._standard_output_name(var_name, "stations", ".nc")
                    out_path = self.data_dir / out_name
                    ds.to_netcdf(str(out_path))
                    output_files.append(out_path)
                    ds.close()
                    self.logger.info(f"Station {var_name} written: {out_path}")

                except ImportError:
                    # xarray not available; save as raw numpy
                    out_name = self._standard_output_name(var_name, "stations", ".npy")
                    out_path = self.data_dir / out_name
                    np.save(str(out_path), data)
                    output_files.append(out_path)
                    warnings.append(
                        f"xarray not available; saved {var_name} as .npy"
                    )

            except Exception as e:
                self.logger.error(f"Failed to process staout_{idx}: {e}")
                warnings.append(f"staout_{idx} processing failed: {e}")

        success = len(output_files) > 0

        return PostResult(
            success=success,
            phase="extract_stations",
            output_files=output_files,
            errors=errors,
            warnings=warnings,
            metadata={"n_stations": n_stations, "n_variables": len(output_files)},
        )

    def create_standard_netcdf(self) -> PostResult:
        """
        Convert extracted fields to CO-OPS standard NetCDF format.

        For STOFS: Handled by ADCIRC-format creation and 2D field scripts.
        For COMF SCHISM: Fields already have CF attributes from extract_fields;
        this step performs final standardization.

        Returns:
            PostResult with standard NetCDF files
        """
        self.logger.info("Creating standard NetCDF output")

        if self.framework == "stofs":
            return self._stofs_create_standard_netcdf()

        return self._comf_schism_create_standard_netcdf()

    def _stofs_create_standard_netcdf(self) -> PostResult:
        """Create standard NetCDF for STOFS (ADCIRC format)."""
        script = self.ush_stofs / "stofs_3d_atl_create_adcirc_nc.sh"
        if not script.exists():
            return PostResult(
                success=True,
                phase="create_standard_netcdf",
                warnings=["STOFS ADCIRC script not found; skipping"],
            )

        ok, stdout, stderr = self._run_subprocess(
            str(script),
            step_name="stofs_create_adcirc_nc",
            timeout=1800,
        )

        return PostResult(
            success=ok,
            phase="create_standard_netcdf",
            errors=[stderr[:300]] if not ok and stderr else [],
        )

    def _comf_schism_create_standard_netcdf(self) -> PostResult:
        """
        Create standard NetCDF for COMF SCHISM.

        Reads the extracted field files and ensures they conform to
        CO-OPS standard format with proper coordinate variables,
        time encoding, and metadata.
        """
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

        # Find all extracted field files in data_dir
        field_patterns = [
            f"{self.ofs_name}.{self.cycle}.*.2d.nc",
            f"{self.ofs_name}.{self.cycle}.*.3d.nc",
        ]

        for pattern in field_patterns:
            for field_file in sorted(self.data_dir.glob(pattern)):
                self.logger.info(f"Standardizing: {field_file.name}")
                try:
                    ds = xr.open_dataset(str(field_file))

                    # Ensure time encoding uses standard calendar
                    if "time" in ds.dims:
                        ds["time"].encoding.update({
                            "units": f"seconds since {self.pdy[:4]}-{self.pdy[4:6]}-{self.pdy[6:8]} 00:00:00",
                            "calendar": "standard",
                            "dtype": "float64",
                        })

                    # Write standardized file
                    std_name = field_file.name.replace(".nc", ".standard.nc")
                    std_path = self.data_dir / std_name
                    ds.to_netcdf(str(std_path))
                    output_files.append(std_path)
                    ds.close()
                    self.logger.info(f"Standardized: {std_path}")

                except Exception as e:
                    warnings.append(f"Failed to standardize {field_file.name}: {e}")

        return PostResult(
            success=True,
            phase="create_standard_netcdf",
            output_files=output_files,
            warnings=warnings,
        )

    def create_grib2(self) -> PostResult:
        """
        Create GRIB2 output for AWIPS dissemination.

        Only applicable to STOFS systems. Calls the STOFS AWIPS GRIB2
        creation script.

        Returns:
            PostResult indicating GRIB2 creation status
        """
        if self.framework != "stofs":
            return PostResult(
                success=True,
                phase="create_grib2",
                warnings=["GRIB2 creation only applies to STOFS systems"],
            )

        self.logger.info("Creating STOFS AWIPS GRIB2 files")
        script = self.ush_stofs / "stofs_3d_atl_create_awips_grib2.sh"

        if not script.exists():
            return PostResult(
                success=True,
                phase="create_grib2",
                warnings=[f"GRIB2 script not found: {script}"],
            )

        ok, stdout, stderr = self._run_subprocess(
            str(script),
            step_name="create_awips_grib2",
            timeout=1800,
        )

        return PostResult(
            success=ok,
            phase="create_grib2",
            errors=[stderr[:300]] if not ok and stderr else [],
        )

    def create_awips(self) -> PostResult:
        """
        Create AWIPS-format output (SHEF bulletins).

        Only applicable to STOFS systems. Calls the STOFS AWIPS SHEF
        creation script.

        Returns:
            PostResult indicating AWIPS creation status
        """
        if self.framework != "stofs":
            return PostResult(
                success=True,
                phase="create_awips",
                warnings=["AWIPS/SHEF creation only applies to STOFS systems"],
            )

        self.logger.info("Creating STOFS AWIPS/SHEF output")
        script = self.ush_stofs / "stofs_3d_atl_create_awips_shef.sh"

        if not script.exists():
            return PostResult(
                success=True,
                phase="create_awips",
                warnings=[f"AWIPS/SHEF script not found: {script}"],
            )

        ok, stdout, stderr = self._run_subprocess(
            str(script),
            step_name="create_awips_shef",
            timeout=1800,
        )

        return PostResult(
            success=ok,
            phase="create_awips",
            errors=[stderr[:300]] if not ok and stderr else [],
        )

    def archive_outputs(self) -> PostResult:
        """
        Copy post-processed products to COMOUT.

        Archives all standard output files including:
        - Field NetCDFs (2D, 3D)
        - Station timeseries NetCDFs
        - GRIB2 files
        - SHEF bulletins
        - GeoPackage files
        - Hotstart/restart files

        Returns:
            PostResult with list of archived files
        """
        self.logger.info("Archiving SCHISM post-processed outputs to COMOUT")

        archived_files = []
        warnings = []

        self.comout.mkdir(parents=True, exist_ok=True)

        # Patterns to archive
        archive_patterns = [
            # Standard field files
            f"{self.ofs_name}.{self.cycle}.*.nc",
            # GRIB2 files
            f"{self.ofs_name}.{self.cycle}.*.grib2",
            # SHEF files
            f"{self.ofs_name}.{self.cycle}.*.shef",
            # GeoPackage files
            f"{self.ofs_name}.{self.cycle}.*.gpkg",
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

        self.logger.info(f"Archived {len(archived_files)} files to {self.comout}")

        return PostResult(
            success=True,
            phase="archive_outputs",
            archived_files=archived_files,
            warnings=warnings,
            metadata={"n_archived": len(archived_files)},
        )

    def run_all(self, fail_fast: bool = True) -> PostResult:
        """
        Execute the full post-processing pipeline.

        For STOFS: Runs both post_1 and post_2 phases.
        For COMF SCHISM: Runs the standard 6-step pipeline.

        Args:
            fail_fast: If True, stop on first failure.

        Returns:
            PostResult with overall status
        """
        if self.framework == "stofs":
            return self._run_stofs_pipeline(fail_fast)

        # COMF SCHISM: use base class pipeline
        return super().run_all(fail_fast)

    def _run_stofs_pipeline(self, fail_fast: bool = True) -> PostResult:
        """
        Run STOFS two-phase post-processing pipeline.

        Executes post_1 and post_2 in sequence.

        Args:
            fail_fast: If True, stop after post_1 failure.

        Returns:
            PostResult combining both phases
        """
        self.logger.info("Running STOFS two-phase post-processing pipeline")
        start_time = __import__("time").time()

        all_output_files = []
        all_archived_files = []
        all_errors = []
        all_warnings = []
        step_results = {}

        # Phase 1
        self.logger.info("--- STOFS Phase 1 ---")
        result_1 = self.run_stofs_post_1()
        step_results["post_1"] = result_1.success
        all_output_files.extend(result_1.output_files)
        all_errors.extend(result_1.errors)
        all_warnings.extend(result_1.warnings)

        if not result_1.success and fail_fast:
            return PostResult(
                success=False,
                phase="stofs_pipeline",
                total_duration_seconds=__import__("time").time() - start_time,
                output_files=all_output_files,
                errors=all_errors,
                warnings=all_warnings,
                step_results=step_results,
            )

        # Phase 2
        self.logger.info("--- STOFS Phase 2 ---")
        result_2 = self.run_stofs_post_2()
        step_results["post_2"] = result_2.success
        all_output_files.extend(result_2.output_files)
        all_errors.extend(result_2.errors)
        all_warnings.extend(result_2.warnings)

        total_duration = __import__("time").time() - start_time

        overall_success = result_1.success and result_2.success

        return PostResult(
            success=overall_success,
            phase="stofs_pipeline",
            total_duration_seconds=total_duration,
            output_files=all_output_files,
            archived_files=all_archived_files,
            errors=all_errors,
            warnings=all_warnings,
            step_results=step_results,
        )
