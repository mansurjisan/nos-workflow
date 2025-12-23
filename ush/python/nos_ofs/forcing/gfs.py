"""
GFS (Global Forecast System) Forcing Processor

Processes GFS atmospheric data for SCHISM ocean model forcing including:
- Wind (u, v components at 10m)
- Sea level pressure (PRMSL)
- Air temperature (TMP at 2m)
- Specific humidity (SPFH at 2m)
- Downward shortwave radiation (DSWRF)
- Downward longwave radiation (DLWRF)
- Precipitation rate (PRATE)

Output: SCHISM sflux NetCDF files
- sflux_air_1.XXXX.nc - wind, temperature, humidity, pressure
- sflux_rad_1.XXXX.nc - shortwave, longwave radiation
- sflux_prc_1.XXXX.nc - precipitation
"""

import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from ..base import ForcingProcessor, ForcingResult

log = logging.getLogger(__name__)

# Try to import netCDF4, handle gracefully if not available
try:
    from netCDF4 import Dataset
    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False
    log.warning("netCDF4 not available - GFS processing will be limited")


class GFSProcessor(ForcingProcessor):
    """
    GFS atmospheric forcing processor for SCHISM.

    Processes GFS GRIB2 files and creates SCHISM-compatible sflux NetCDF files.
    Uses wgrib2 for GRIB2 extraction and netCDF4 for output generation.
    """

    # GRIB2 variable mapping: SCHISM name -> (GFS GRIB2 name, level)
    GRIB2_VARIABLES = {
        "uwind": ("UGRD", "10 m above ground"),
        "vwind": ("VGRD", "10 m above ground"),
        "prmsl": ("PRMSL", "mean sea level"),
        "stmp": ("TMP", "2 m above ground"),
        "spfh": ("SPFH", "2 m above ground"),
        "dlwrf": ("DLWRF", "surface"),
        "dswrf": ("DSWRF", "surface"),
        "prate": ("PRATE", "surface"),
    }

    DEFAULT_VARIABLES = list(GRIB2_VARIABLES.keys())

    # GFS grid resolution options
    GFS_0P25 = "0p25"  # 0.25 degree
    GFS_0P50 = "0p50"  # 0.50 degree

    @property
    def source_name(self) -> str:
        return "GFS"

    def __init__(
        self,
        config,
        input_path: Path,
        output_path: Path,
        variables: Optional[List[str]] = None,
        forecast_hours: int = 180,
        resolution: str = "0p25",
    ):
        """
        Initialize GFS processor.

        Args:
            config: StofsConfig instance
            input_path: Path to GFS GRIB2 files (COMINgfs)
            output_path: Path for sflux output files (DATA/sflux)
            variables: List of variables to process
            forecast_hours: Number of forecast hours to process
            resolution: GFS resolution ("0p25" or "0p50")
        """
        super().__init__(config, input_path, output_path, variables)
        self.forecast_hours = forecast_hours
        self.resolution = resolution
        if not self.variables:
            self.variables = self.DEFAULT_VARIABLES

        # Get cycle info from config
        self.cyc = config.cyc
        self.pdy = config.PDY

    def process(self) -> ForcingResult:
        """
        Process GFS forcing data and create SCHISM sflux files.

        Returns:
            ForcingResult with processed files
        """
        log.info(f"Processing {self.source_name} forcing data")
        log.info(f"Input path: {self.input_path}")
        log.info(f"Output path: {self.output_path}")
        log.info(f"Forecast hours: {self.forecast_hours}")

        if not self.validate_input():
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[f"Input path not found: {self.input_path}"],
            )

        self.create_output_dir()
        output_files = []
        errors = []
        warnings = []

        try:
            # Find GFS GRIB2 files
            gfs_files = self._find_gfs_files()

            if not gfs_files:
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["No GFS input files found"],
                )

            log.info(f"Found {len(gfs_files)} GFS files")

            # Extract variables from GRIB2 files
            extracted_data = self._extract_grib2_data(gfs_files)

            if not extracted_data:
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["Failed to extract data from GFS files"],
                )

            # Create SCHISM sflux NetCDF files
            sflux_files = self._create_sflux_files(extracted_data)
            output_files.extend(sflux_files)

            # Create sflux_inputs.txt
            inputs_file = self._create_sflux_inputs()
            if inputs_file:
                output_files.append(inputs_file)

            log.info(f"GFS processing complete: {len(output_files)} files created")

            return ForcingResult(
                success=True,
                source=self.source_name,
                output_files=output_files,
                warnings=warnings,
                metadata={
                    "forecast_hours": self.forecast_hours,
                    "variables": self.variables,
                    "num_input_files": len(gfs_files),
                    "resolution": self.resolution,
                },
            )

        except Exception as e:
            log.error(f"GFS processing failed: {e}")
            import traceback
            log.error(traceback.format_exc())
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[str(e)],
            )

    def _find_gfs_files(self) -> List[Path]:
        """
        Find GFS GRIB2 files for the forecast period.

        Following shell script logic, this method:
        1. Builds primary file list from multiple cycles for nowcast coverage
        2. Uses backup file list from previous day if primary is incomplete
        3. Merges lists to ensure complete temporal coverage

        Target: ~121 files for 5-day run (24hr nowcast + 96hr forecast)
        """
        # Build primary file list from multiple GFS cycles
        primary_files = self._build_gfs_file_list()

        # Target number of files (hourly for ~5 days)
        n_target = 121

        if len(primary_files) >= n_target:
            log.info(f"Found {len(primary_files)} GFS files (target: {n_target})")
            return primary_files

        # If primary list is incomplete, try backup from previous cycle
        log.warning(f"Primary GFS list incomplete ({len(primary_files)}/{n_target}), checking backup")
        backup_files = self._build_backup_file_list()

        if backup_files:
            merged = self._merge_file_lists(primary_files, backup_files, n_target)
            log.info(f"After merge: {len(merged)} GFS files")
            return merged

        return primary_files

    def _build_gfs_file_list(self) -> List[Path]:
        """
        Build primary GFS file list from multiple cycles.

        Shell script logic (lines 69-95):
        LIST_fn_all_1 = yest_t06z + yest_t12z + yest_t18z + today_t00z + today_t06z + today_t12z

        This provides overlapping coverage for nowcast initialization.
        """
        gfs_files = []
        base_date = datetime.strptime(self.pdy, "%Y%m%d")
        prev_date = base_date - timedelta(days=1)

        # Build list of (date, cycle) pairs to check
        # Yesterday t06z, t12z, t18z + Today t00z, t06z, t12z
        cycle_list = [
            (prev_date, 6),
            (prev_date, 12),
            (prev_date, 18),
            (base_date, 0),
            (base_date, 6),
            (base_date, 12),
        ]

        # GFS directory structure: gfs.YYYYMMDD/HH/atmos/
        for date, cyc in cycle_list:
            date_str = date.strftime("%Y%m%d")
            gfs_path = self.input_path / f"gfs.{date_str}" / f"{cyc:02d}" / "atmos"

            # Also check alternative structures
            if not gfs_path.exists():
                gfs_path = self.input_path / f"gfs.{date_str}" / f"{cyc:02d}"
            if not gfs_path.exists():
                gfs_path = self.input_path

            if not gfs_path.exists():
                continue

            # Find forecast files for this cycle
            pattern = f"gfs.t{cyc:02d}z.pgrb2.{self.resolution}.f*"
            found = sorted(gfs_path.glob(pattern))

            for f in found:
                try:
                    fhr = int(f.name.split('.f')[-1])
                    if fhr <= self.forecast_hours:
                        gfs_files.append(f)
                except (ValueError, IndexError):
                    continue

        # Remove duplicates while preserving order
        seen = set()
        unique_files = []
        for f in gfs_files:
            if f not in seen:
                seen.add(f)
                unique_files.append(f)

        return unique_files

    def _build_backup_file_list(self) -> List[Path]:
        """
        Build backup file list from previous day's t12z cycle.

        Shell script logic (lines 169-210):
        LIST_fn_all_2 = backup from yesterday's t12z cycle
        """
        base_date = datetime.strptime(self.pdy, "%Y%m%d")
        prev_date = base_date - timedelta(days=1)

        # Yesterday's t12z cycle
        date_str = prev_date.strftime("%Y%m%d")
        backup_path = self.input_path / f"gfs.{date_str}" / "12" / "atmos"

        if not backup_path.exists():
            backup_path = self.input_path / f"gfs.{date_str}" / "12"
        if not backup_path.exists():
            return []

        backup_files = []
        pattern = f"gfs.t12z.pgrb2.{self.resolution}.f*"
        found = sorted(backup_path.glob(pattern))

        for f in found:
            try:
                fhr = int(f.name.split('.f')[-1])
                if fhr <= self.forecast_hours:
                    backup_files.append(f)
            except (ValueError, IndexError):
                continue

        return backup_files

    def _merge_file_lists(
        self, primary_files: List[Path], backup_files: List[Path], n_target: int
    ) -> List[Path]:
        """
        Merge primary and backup file lists for operational robustness.

        If primary list is incomplete, supplement with backup files.
        This matches shell script logic at lines 169-210.

        Args:
            primary_files: Primary file list (may be incomplete)
            backup_files: Backup file list from previous cycle
            n_target: Target number of files

        Returns:
            Merged file list
        """
        if len(primary_files) >= n_target:
            return primary_files

        if not backup_files:
            return primary_files

        # If backup has more files, use backup for the missing portion
        if len(backup_files) > len(primary_files):
            n_diff = min(n_target - len(primary_files), len(backup_files) - len(primary_files))
            merged = primary_files + backup_files[len(primary_files):len(primary_files) + n_diff]
            log.info(f"Merged {n_diff} backup files into primary list")
            return merged

        return primary_files

    def _find_gfs_files_simple(self) -> List[Path]:
        """
        Simple file finder for current cycle only (fallback method).

        Use this for testing or when multi-cycle files are not needed.
        """
        gfs_files = []

        # GFS file pattern: gfs.t{cyc}z.pgrb2.{res}.f{fhr}
        pattern = f"gfs.t{self.cyc:02d}z.pgrb2.{self.resolution}.f*"

        # Search for files
        found_files = sorted(self.input_path.glob(pattern))

        # Filter to forecast hours we need
        for f in found_files:
            try:
                # Extract forecast hour from filename
                fhr = int(f.name.split('.f')[-1])
                if fhr <= self.forecast_hours:
                    gfs_files.append(f)
            except (ValueError, IndexError):
                continue

        return gfs_files

    def _extract_grib2_data(self, gfs_files: List[Path]) -> dict:
        """
        Extract variables from GFS GRIB2 files using wgrib2.

        Args:
            gfs_files: List of GFS GRIB2 file paths

        Returns:
            Dictionary of extracted data arrays
        """
        extracted_data = {
            "times": [],
            "lons": None,
            "lats": None,
        }

        for var in self.variables:
            extracted_data[var] = []

        # Get domain bounds from config
        lon_min = self.config.lon_min
        lon_max = self.config.lon_max
        lat_min = self.config.lat_min
        lat_max = self.config.lat_max

        log.info(f"Extracting data for domain: lon[{lon_min}, {lon_max}], lat[{lat_min}, {lat_max}]")

        for gfs_file in gfs_files:
            try:
                # Extract forecast hour for time calculation
                fhr = int(gfs_file.name.split('.f')[-1])
                base_time = datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc)
                valid_time = base_time + timedelta(hours=fhr)
                extracted_data["times"].append(valid_time)

                # Extract each variable using wgrib2
                for var in self.variables:
                    if var in self.GRIB2_VARIABLES:
                        grib_var, level = self.GRIB2_VARIABLES[var]
                        data = self._wgrib2_extract(
                            gfs_file, grib_var, level,
                            lon_min, lon_max, lat_min, lat_max
                        )
                        if data is not None:
                            extracted_data[var].append(data)
                        else:
                            log.warning(f"Failed to extract {var} from {gfs_file.name}")

            except Exception as e:
                log.warning(f"Error processing {gfs_file}: {e}")
                continue

        # Get grid coordinates from first file
        if gfs_files and extracted_data["lons"] is None:
            extracted_data["lons"], extracted_data["lats"] = self._get_gfs_grid(
                gfs_files[0], lon_min, lon_max, lat_min, lat_max
            )

        return extracted_data

    def _wgrib2_extract(
        self,
        grib_file: Path,
        variable: str,
        level: str,
        lon_min: float,
        lon_max: float,
        lat_min: float,
        lat_max: float,
    ) -> Optional[np.ndarray]:
        """
        Extract a variable from GRIB2 file using wgrib2.

        Args:
            grib_file: Path to GRIB2 file
            variable: GRIB2 variable name
            level: Level specification
            lon_min, lon_max, lat_min, lat_max: Domain bounds

        Returns:
            Numpy array of extracted data or None if failed
        """
        try:
            # Create temporary output file
            tmp_file = self.output_path / f"tmp_{variable}_{grib_file.stem}.bin"

            # Build wgrib2 command for extraction
            # -match to select variable, -small_grib for subsetting, -bin for binary output
            match_str = f":{variable}:{level}:"

            # First, extract the matching record to a small grib
            subset_file = self.output_path / f"tmp_{variable}_{grib_file.stem}.grb2"

            cmd = [
                "wgrib2", str(grib_file),
                "-match", match_str,
                "-small_grib",
                f"{lon_min}:{lon_max}",
                f"{lat_min}:{lat_max}",
                str(subset_file)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                log.debug(f"wgrib2 extraction failed: {result.stderr}")
                return None

            # Now convert to binary for reading
            cmd2 = [
                "wgrib2", str(subset_file),
                "-no_header",
                "-bin", str(tmp_file)
            ]

            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)

            if result2.returncode == 0 and tmp_file.exists():
                # Read binary data
                data = np.fromfile(tmp_file, dtype=np.float32)

                # Get grid dimensions from wgrib2 output
                cmd3 = ["wgrib2", str(subset_file), "-nxny"]
                result3 = subprocess.run(cmd3, capture_output=True, text=True, timeout=30)

                if result3.returncode == 0:
                    # Parse nx ny from output
                    parts = result3.stdout.strip().split(":")
                    for part in parts:
                        if "x" in part and "(" in part:
                            dims = part.split("(")[1].split(")")[0]
                            nx, ny = map(int, dims.split(" x "))
                            data = data.reshape((ny, nx))
                            break

                # Cleanup temp files
                tmp_file.unlink(missing_ok=True)
                subset_file.unlink(missing_ok=True)

                return data

        except subprocess.TimeoutExpired:
            log.warning(f"wgrib2 timeout for {variable}")
        except Exception as e:
            log.debug(f"wgrib2 extraction error: {e}")

        # Cleanup on failure
        for f in [tmp_file, subset_file]:
            if isinstance(f, Path):
                f.unlink(missing_ok=True)

        return None

    def _get_gfs_grid(
        self,
        grib_file: Path,
        lon_min: float,
        lon_max: float,
        lat_min: float,
        lat_max: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get grid coordinates for the subsetted domain.

        Returns:
            Tuple of (lons, lats) arrays
        """
        # Calculate grid based on GFS resolution
        if self.resolution == "0p25":
            dx = dy = 0.25
        else:
            dx = dy = 0.50

        lons = np.arange(lon_min, lon_max + dx, dx)
        lats = np.arange(lat_min, lat_max + dy, dy)

        return lons, lats

    def _create_sflux_files(self, data: dict, day_split: bool = True) -> List[Path]:
        """
        Create SCHISM sflux NetCDF files.

        SCHISM requires:
        - sflux_air_1.XXXX.nc: uwind, vwind, prmsl, stmp, spfh
        - sflux_rad_1.XXXX.nc: dlwrf, dswrf
        - sflux_prc_1.XXXX.nc: prate

        Args:
            data: Dictionary of extracted data
            day_split: If True, create separate files for each day (operational mode)

        Returns:
            List of created file paths
        """
        if not HAS_NETCDF4:
            log.error("netCDF4 required for sflux file creation")
            return []

        output_files = []
        times = data["times"]
        lons = data["lons"]
        lats = data["lats"]

        if lons is None or lats is None:
            log.error("Grid coordinates not available")
            return []

        # Calculate base date for SCHISM time reference
        # SCHISM typically uses the nowcast begin date as base
        base_date = datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc) - timedelta(hours=24)

        if day_split:
            # Create day-split files (operational mode)
            output_files.extend(self._create_day_split_sflux(data, times, lons, lats, base_date))
        else:
            # Create single files (development mode)
            air_file = self._create_sflux_air(data, times, lons, lats, base_date)
            if air_file:
                output_files.append(air_file)

            rad_file = self._create_sflux_rad(data, times, lons, lats, base_date)
            if rad_file:
                output_files.append(rad_file)

            prc_file = self._create_sflux_prc(data, times, lons, lats, base_date)
            if prc_file:
                output_files.append(prc_file)

        return output_files

    def _create_day_split_sflux(
        self, data: dict, times: list, lons: np.ndarray, lats: np.ndarray, base_date: datetime
    ) -> List[Path]:
        """
        Create day-split sflux files (one file per day).

        This matches the operational STOFS workflow where each day of the
        model run has separate sflux_air_1.XXXX.nc, sflux_rad_1.XXXX.nc,
        and sflux_prc_1.XXXX.nc files.

        Args:
            data: Extracted forcing data
            times: List of datetime objects
            lons: Longitude array
            lats: Latitude array
            base_date: Base datetime for time reference

        Returns:
            List of created file paths
        """
        output_files = []

        # Group times by day relative to base_date
        day_groups = {}
        for i, t in enumerate(times):
            day_num = (t - base_date).days + 1  # Day 1, 2, 3, ...
            if day_num < 1:
                day_num = 1  # Handle times before base_date

            if day_num not in day_groups:
                day_groups[day_num] = []
            day_groups[day_num].append(i)

        log.info(f"Creating day-split sflux files for {len(day_groups)} days")

        for day_num, indices in sorted(day_groups.items()):
            file_num = f"{day_num:04d}"

            # Extract data for this day
            day_times = [times[i] for i in indices]

            day_data = {}
            for var in self.variables:
                if var in data and data[var]:
                    day_data[var] = [data[var][i] for i in indices if i < len(data[var])]

            if not day_times:
                continue

            # Create sflux_air for this day
            air_file = self._create_sflux_air_day(
                day_data, day_times, lons, lats, base_date, file_num
            )
            if air_file:
                output_files.append(air_file)

            # Create sflux_rad for this day
            rad_file = self._create_sflux_rad_day(
                day_data, day_times, lons, lats, base_date, file_num
            )
            if rad_file:
                output_files.append(rad_file)

            # Create sflux_prc for this day
            prc_file = self._create_sflux_prc_day(
                day_data, day_times, lons, lats, base_date, file_num
            )
            if prc_file:
                output_files.append(prc_file)

        return output_files

    def _create_sflux_air_day(
        self, data: dict, times: list, lons: np.ndarray, lats: np.ndarray,
        base_date: datetime, file_num: str
    ) -> Optional[Path]:
        """Create sflux_air NetCDF file for a single day."""
        output_file = self.output_path / f"sflux_air_1.{file_num}.nc"

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            nc.createDimension('nx_grid', len(lons))
            nc.createDimension('ny_grid', len(lats))
            nc.createDimension('ntime', len(times))

            # Time variable (days since base_date)
            time_var = nc.createVariable('time', 'f8', ('ntime',))
            time_var.units = f"days since {base_date.strftime('%Y-%m-%d')} 00:00:00"
            time_var.calendar = "standard"
            time_var.long_name = "Time"
            time_var[:] = [(t - base_date).total_seconds() / 86400.0 for t in times]

            # Coordinates
            lon_var = nc.createVariable('lon', 'f4', ('ny_grid', 'nx_grid'))
            lon_var.units = "degrees_east"
            lat_var = nc.createVariable('lat', 'f4', ('ny_grid', 'nx_grid'))
            lat_var.units = "degrees_north"
            lon_2d, lat_2d = np.meshgrid(lons, lats)
            lon_var[:] = lon_2d
            lat_var[:] = lat_2d

            # Air forcing variables
            var_specs = {
                'uwind': ('f4', 'm/s', 'U-wind velocity at 10m'),
                'vwind': ('f4', 'm/s', 'V-wind velocity at 10m'),
                'prmsl': ('f4', 'Pa', 'Pressure reduced to mean sea level'),
                'stmp': ('f4', 'K', 'Surface air temperature at 2m'),
                'spfh': ('f4', 'kg/kg', 'Specific humidity at 2m'),
            }

            for varname, (dtype, units, long_name) in var_specs.items():
                if varname in data and data[varname]:
                    var = nc.createVariable(varname, dtype, ('ntime', 'ny_grid', 'nx_grid'),
                                          fill_value=-9999.0)
                    var.units = units
                    var.long_name = long_name
                    try:
                        var[:] = np.stack(data[varname], axis=0)
                    except Exception as e:
                        log.warning(f"Could not write {varname}: {e}")

            nc.title = "SCHISM sflux air forcing from GFS"
            nc.source = f"GFS {self.resolution}"
            nc.history = f"Created {datetime.now().isoformat()}"
            nc.conventions = "CF-1.6"
            nc.close()

            log.debug(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create sflux_air {file_num}: {e}")
            return None

    def _create_sflux_rad_day(
        self, data: dict, times: list, lons: np.ndarray, lats: np.ndarray,
        base_date: datetime, file_num: str
    ) -> Optional[Path]:
        """Create sflux_rad NetCDF file for a single day."""
        output_file = self.output_path / f"sflux_rad_1.{file_num}.nc"

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            nc.createDimension('nx_grid', len(lons))
            nc.createDimension('ny_grid', len(lats))
            nc.createDimension('ntime', len(times))

            time_var = nc.createVariable('time', 'f8', ('ntime',))
            time_var.units = f"days since {base_date.strftime('%Y-%m-%d')} 00:00:00"
            time_var.calendar = "standard"
            time_var[:] = [(t - base_date).total_seconds() / 86400.0 for t in times]

            lon_var = nc.createVariable('lon', 'f4', ('ny_grid', 'nx_grid'))
            lat_var = nc.createVariable('lat', 'f4', ('ny_grid', 'nx_grid'))
            lon_2d, lat_2d = np.meshgrid(lons, lats)
            lon_var[:] = lon_2d
            lat_var[:] = lat_2d

            var_specs = {
                'dlwrf': ('f4', 'W/m^2', 'Downward longwave radiation flux'),
                'dswrf': ('f4', 'W/m^2', 'Downward shortwave radiation flux'),
            }

            for varname, (dtype, units, long_name) in var_specs.items():
                if varname in data and data[varname]:
                    var = nc.createVariable(varname, dtype, ('ntime', 'ny_grid', 'nx_grid'),
                                          fill_value=-9999.0)
                    var.units = units
                    var.long_name = long_name
                    try:
                        var[:] = np.stack(data[varname], axis=0)
                    except Exception as e:
                        log.warning(f"Could not write {varname}: {e}")

            nc.title = "SCHISM sflux radiation forcing from GFS"
            nc.source = f"GFS {self.resolution}"
            nc.close()

            log.debug(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create sflux_rad {file_num}: {e}")
            return None

    def _create_sflux_prc_day(
        self, data: dict, times: list, lons: np.ndarray, lats: np.ndarray,
        base_date: datetime, file_num: str
    ) -> Optional[Path]:
        """Create sflux_prc NetCDF file for a single day."""
        output_file = self.output_path / f"sflux_prc_1.{file_num}.nc"

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            nc.createDimension('nx_grid', len(lons))
            nc.createDimension('ny_grid', len(lats))
            nc.createDimension('ntime', len(times))

            time_var = nc.createVariable('time', 'f8', ('ntime',))
            time_var.units = f"days since {base_date.strftime('%Y-%m-%d')} 00:00:00"
            time_var.calendar = "standard"
            time_var[:] = [(t - base_date).total_seconds() / 86400.0 for t in times]

            lon_var = nc.createVariable('lon', 'f4', ('ny_grid', 'nx_grid'))
            lat_var = nc.createVariable('lat', 'f4', ('ny_grid', 'nx_grid'))
            lon_2d, lat_2d = np.meshgrid(lons, lats)
            lon_var[:] = lon_2d
            lat_var[:] = lat_2d

            if 'prate' in data and data['prate']:
                var = nc.createVariable('prate', 'f4', ('ntime', 'ny_grid', 'nx_grid'),
                                      fill_value=-9999.0)
                var.units = 'kg/m^2/s'
                var.long_name = 'Precipitation rate'
                try:
                    var[:] = np.stack(data['prate'], axis=0)
                except Exception as e:
                    log.warning(f"Could not write prate: {e}")

            nc.title = "SCHISM sflux precipitation forcing from GFS"
            nc.source = f"GFS {self.resolution}"
            nc.close()

            log.debug(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create sflux_prc {file_num}: {e}")
            return None

    def _create_sflux_air(
        self, data: dict, times: list, lons: np.ndarray, lats: np.ndarray, base_date: datetime
    ) -> Optional[Path]:
        """Create sflux_air NetCDF file with wind, temperature, humidity, pressure."""
        output_file = self.output_path / "sflux_air_1.0001.nc"

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            # Dimensions
            nc.createDimension('nx_grid', len(lons))
            nc.createDimension('ny_grid', len(lats))
            nc.createDimension('ntime', len(times))

            # Time variable
            time_var = nc.createVariable('time', 'f8', ('ntime',))
            time_var.units = f"days since {base_date.strftime('%Y-%m-%d')} 00:00:00"
            time_var.calendar = "standard"
            time_var.long_name = "Time"

            # Calculate time values in days since base_date
            time_vals = [(t - base_date).total_seconds() / 86400.0 for t in times]
            time_var[:] = time_vals

            # Coordinate variables
            lon_var = nc.createVariable('lon', 'f4', ('ny_grid', 'nx_grid'))
            lon_var.units = "degrees_east"
            lon_var.long_name = "Longitude"

            lat_var = nc.createVariable('lat', 'f4', ('ny_grid', 'nx_grid'))
            lat_var.units = "degrees_north"
            lat_var.long_name = "Latitude"

            # Create 2D coordinate arrays
            lon_2d, lat_2d = np.meshgrid(lons, lats)
            lon_var[:] = lon_2d
            lat_var[:] = lat_2d

            # Data variables
            var_specs = {
                'uwind': ('f4', 'm/s', 'U-wind velocity at 10m'),
                'vwind': ('f4', 'm/s', 'V-wind velocity at 10m'),
                'prmsl': ('f4', 'Pa', 'Pressure reduced to mean sea level'),
                'stmp': ('f4', 'K', 'Surface air temperature at 2m'),
                'spfh': ('f4', 'kg/kg', 'Specific humidity at 2m'),
            }

            for varname, (dtype, units, long_name) in var_specs.items():
                if varname in data and data[varname]:
                    var = nc.createVariable(varname, dtype, ('ntime', 'ny_grid', 'nx_grid'),
                                          fill_value=-9999.0)
                    var.units = units
                    var.long_name = long_name

                    # Stack time slices
                    try:
                        var_data = np.stack(data[varname], axis=0)
                        var[:] = var_data
                    except Exception as e:
                        log.warning(f"Could not write {varname}: {e}")

            # Global attributes
            nc.title = "SCHISM sflux air forcing from GFS"
            nc.source = "GFS " + self.resolution
            nc.history = f"Created {datetime.now().isoformat()}"
            nc.conventions = "CF-1.6"

            nc.close()
            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create sflux_air: {e}")
            return None

    def _create_sflux_rad(
        self, data: dict, times: list, lons: np.ndarray, lats: np.ndarray, base_date: datetime
    ) -> Optional[Path]:
        """Create sflux_rad NetCDF file with radiation data."""
        output_file = self.output_path / "sflux_rad_1.0001.nc"

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            # Dimensions
            nc.createDimension('nx_grid', len(lons))
            nc.createDimension('ny_grid', len(lats))
            nc.createDimension('ntime', len(times))

            # Time variable
            time_var = nc.createVariable('time', 'f8', ('ntime',))
            time_var.units = f"days since {base_date.strftime('%Y-%m-%d')} 00:00:00"
            time_var.calendar = "standard"
            time_vals = [(t - base_date).total_seconds() / 86400.0 for t in times]
            time_var[:] = time_vals

            # Coordinates
            lon_var = nc.createVariable('lon', 'f4', ('ny_grid', 'nx_grid'))
            lat_var = nc.createVariable('lat', 'f4', ('ny_grid', 'nx_grid'))
            lon_2d, lat_2d = np.meshgrid(lons, lats)
            lon_var[:] = lon_2d
            lat_var[:] = lat_2d

            # Radiation variables
            var_specs = {
                'dlwrf': ('f4', 'W/m^2', 'Downward longwave radiation flux'),
                'dswrf': ('f4', 'W/m^2', 'Downward shortwave radiation flux'),
            }

            for varname, (dtype, units, long_name) in var_specs.items():
                if varname in data and data[varname]:
                    var = nc.createVariable(varname, dtype, ('ntime', 'ny_grid', 'nx_grid'),
                                          fill_value=-9999.0)
                    var.units = units
                    var.long_name = long_name
                    try:
                        var[:] = np.stack(data[varname], axis=0)
                    except Exception as e:
                        log.warning(f"Could not write {varname}: {e}")

            nc.title = "SCHISM sflux radiation forcing from GFS"
            nc.source = "GFS " + self.resolution
            nc.close()
            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create sflux_rad: {e}")
            return None

    def _create_sflux_prc(
        self, data: dict, times: list, lons: np.ndarray, lats: np.ndarray, base_date: datetime
    ) -> Optional[Path]:
        """Create sflux_prc NetCDF file with precipitation data."""
        output_file = self.output_path / "sflux_prc_1.0001.nc"

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            # Dimensions
            nc.createDimension('nx_grid', len(lons))
            nc.createDimension('ny_grid', len(lats))
            nc.createDimension('ntime', len(times))

            # Time variable
            time_var = nc.createVariable('time', 'f8', ('ntime',))
            time_var.units = f"days since {base_date.strftime('%Y-%m-%d')} 00:00:00"
            time_var.calendar = "standard"
            time_vals = [(t - base_date).total_seconds() / 86400.0 for t in times]
            time_var[:] = time_vals

            # Coordinates
            lon_var = nc.createVariable('lon', 'f4', ('ny_grid', 'nx_grid'))
            lat_var = nc.createVariable('lat', 'f4', ('ny_grid', 'nx_grid'))
            lon_2d, lat_2d = np.meshgrid(lons, lats)
            lon_var[:] = lon_2d
            lat_var[:] = lat_2d

            # Precipitation variable
            if 'prate' in data and data['prate']:
                var = nc.createVariable('prate', 'f4', ('ntime', 'ny_grid', 'nx_grid'),
                                      fill_value=-9999.0)
                var.units = 'kg/m^2/s'
                var.long_name = 'Precipitation rate'
                try:
                    var[:] = np.stack(data['prate'], axis=0)
                except Exception as e:
                    log.warning(f"Could not write prate: {e}")

            nc.title = "SCHISM sflux precipitation forcing from GFS"
            nc.source = "GFS " + self.resolution
            nc.close()
            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create sflux_prc: {e}")
            return None

    def _create_sflux_inputs(self) -> Optional[Path]:
        """Create sflux_inputs.txt file for SCHISM."""
        output_file = self.output_path / "sflux_inputs.txt"

        try:
            with open(output_file, 'w') as f:
                f.write("&sflux_inputs\n")
                f.write("air_1_relative_weight=1.0,\n")
                f.write("air_2_relative_weight=0.0,\n")
                f.write("air_1_max_window_hours=120.0,\n")
                f.write("air_1_fail_if_missing=.true.,\n")
                f.write("air_2_fail_if_missing=.false.,\n")
                f.write("rad_1_relative_weight=1.0,\n")
                f.write("rad_1_max_window_hours=120.0,\n")
                f.write("prc_1_relative_weight=1.0,\n")
                f.write("prc_1_max_window_hours=120.0,\n")
                f.write("/\n")

            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create sflux_inputs.txt: {e}")
            return None
