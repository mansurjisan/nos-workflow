"""
HRRR (High-Resolution Rapid Refresh) Forcing Processor

Processes HRRR atmospheric data for SCHISM ocean model forcing.
HRRR provides high-resolution (3km) atmospheric data for the CONUS domain.

Used by STOFS 3D Atlantic as a regional atmospheric forcing source
with higher priority than GFS in the overlap region.
NOT used by SECOFS (limited SE coastal coverage offshore).

Output: SCHISM sflux NetCDF files (as secondary/air_2 source)
"""

import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from ..base import ForcingProcessor, ForcingResult

log = logging.getLogger(__name__)

try:
    from netCDF4 import Dataset
    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False


class HRRRProcessor(ForcingProcessor):
    """
    HRRR atmospheric forcing processor for SCHISM.

    Processes HRRR GRIB2 files and creates SCHISM-compatible sflux NetCDF files.
    HRRR is used as a secondary (higher-resolution) atmospheric source.
    """

    # GRIB2 variable mapping for HRRR
    GRIB2_VARIABLES = {
        "uwind": ("UGRD", "10 m above ground"),
        "vwind": ("VGRD", "10 m above ground"),
        "prmsl": ("MSLMA", "mean sea level"),  # HRRR uses MSLMA
        "stmp": ("TMP", "2 m above ground"),
        "spfh": ("SPFH", "2 m above ground"),
        "dlwrf": ("DLWRF", "surface"),
        "dswrf": ("DSWRF", "surface"),
        "prate": ("PRATE", "surface"),
    }

    DEFAULT_VARIABLES = ["uwind", "vwind", "prmsl"]

    @property
    def source_name(self) -> str:
        return "HRRR"

    def __init__(
        self,
        config,
        input_path: Path,
        output_path: Path,
        variables: Optional[List[str]] = None,
        forecast_hours: int = 48,
        priority: str = "high",
    ):
        """
        Initialize HRRR processor.

        Args:
            config: StofsConfig instance
            input_path: Path to HRRR GRIB2 files (COMINhrrr)
            output_path: Path for sflux output files
            variables: List of variables to process
            forecast_hours: Number of forecast hours (HRRR max is 48)
            priority: "high" uses sflux index 2 for blending with GFS
        """
        super().__init__(config, input_path, output_path, variables)
        self.forecast_hours = min(forecast_hours, 48)
        self.priority = priority
        if not self.variables:
            self.variables = self.DEFAULT_VARIABLES

        self.cyc = config.cyc
        self.pdy = config.PDY

    def process(self) -> ForcingResult:
        """
        Process HRRR forcing data.

        Returns:
            ForcingResult with processed files
        """
        log.info(f"Processing {self.source_name} forcing data")
        log.info(f"Input path: {self.input_path}")
        log.info(f"Forecast hours: {self.forecast_hours}")

        if not self.validate_input():
            # HRRR is optional - return success with warning
            log.warning(f"HRRR input path not found: {self.input_path}")
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=["HRRR input path not found - using GFS only"],
            )

        self.create_output_dir()
        output_files = []

        try:
            # Find HRRR files
            hrrr_files = self._find_hrrr_files()

            if not hrrr_files:
                log.warning("No HRRR files found - this is acceptable if GFS is primary")
                return ForcingResult(
                    success=True,
                    source=self.source_name,
                    warnings=["No HRRR input files found"],
                )

            log.info(f"Found {len(hrrr_files)} HRRR files")

            # Extract data
            extracted_data = self._extract_grib2_data(hrrr_files)

            if not extracted_data or not extracted_data.get("times"):
                return ForcingResult(
                    success=True,
                    source=self.source_name,
                    warnings=["Could not extract HRRR data"],
                )

            # Create sflux files (as air_2 for secondary source)
            sflux_files = self._create_sflux_files(extracted_data)
            output_files.extend(sflux_files)

            return ForcingResult(
                success=True,
                source=self.source_name,
                output_files=output_files,
                metadata={
                    "forecast_hours": self.forecast_hours,
                    "priority": self.priority,
                    "num_files": len(hrrr_files),
                },
            )

        except Exception as e:
            log.error(f"HRRR processing failed: {e}")
            import traceback
            log.error(traceback.format_exc())
            # HRRR failure is non-fatal
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=[f"HRRR processing failed: {e}"],
            )

    def _find_hrrr_files(self) -> List[Path]:
        """
        Find HRRR GRIB2 files following operational file sequence.

        The shell script collects files in this sequence for t12z cycle:
        - Yesterday t11-t23 f01 (13 files) - nowcast hours -25 to -13
        - Today t00-t11 f01 (12 files) - nowcast hours -12 to -1
        - Today t12 f01-f48 (48 files) - forecast hours 1 to 48

        Total: 73 files for complete nowcast+forecast coverage.

        This ensures continuous atmospheric forcing from nowcast begin
        (24 hours before forecast start) through forecast end.
        """
        hrrr_files = []

        base_date = datetime.strptime(self.pdy, "%Y%m%d")
        prev_date = base_date - timedelta(days=1)

        # Build input paths for yesterday and today
        # HRRR directory structure: hrrr.YYYYMMDD/conus/
        prev_path = self.input_path / f"hrrr.{prev_date.strftime('%Y%m%d')}" / "conus"
        today_path = self.input_path / f"hrrr.{self.pdy}" / "conus"

        # Also check if files are directly in input_path (alternative structure)
        if not prev_path.exists():
            prev_path = self.input_path
        if not today_path.exists():
            today_path = self.input_path

        log.debug(f"HRRR prev path: {prev_path}")
        log.debug(f"HRRR today path: {today_path}")

        # Part 1: Yesterday t11-t23 f01 (13 files for nowcast)
        # These cover hours -25 to -13 relative to t12z forecast start
        for hr in range(11, 24):
            patterns = [
                f"hrrr.t{hr:02d}z.wrfsfcf01.grib2",
                f"hrrr.t{hr:02d}z.wrfsfcf01.*.grib2",  # With subgrid
            ]
            for pattern in patterns:
                files = sorted(prev_path.glob(pattern))
                if files:
                    hrrr_files.append(files[0])
                    break

        # Part 2: Today t00-t11 f01 (12 files for nowcast)
        # These cover hours -12 to -1 relative to t12z forecast start
        for hr in range(0, 12):
            patterns = [
                f"hrrr.t{hr:02d}z.wrfsfcf01.grib2",
                f"hrrr.t{hr:02d}z.wrfsfcf01.*.grib2",
            ]
            for pattern in patterns:
                files = sorted(today_path.glob(pattern))
                if files:
                    hrrr_files.append(files[0])
                    break

        # Part 3: Today t{cyc}z f01-f48 (forecast files)
        # These cover hours 1 to 48 of the forecast
        for fhr in range(1, min(self.forecast_hours + 1, 49)):
            patterns = [
                f"hrrr.t{self.cyc:02d}z.wrfsfcf{fhr:02d}.grib2",
                f"hrrr.t{self.cyc:02d}z.wrfsfcf{fhr:02d}.*.grib2",
            ]
            for pattern in patterns:
                files = sorted(today_path.glob(pattern))
                if files:
                    hrrr_files.append(files[0])
                    break

        log.info(f"Found {len(hrrr_files)} HRRR files (target: ~73 for complete coverage)")

        return hrrr_files

    def _find_hrrr_files_simple(self) -> List[Path]:
        """
        Simple file finder for current cycle only (fallback method).

        Use this when multi-day files are not available or for testing.
        """
        hrrr_files = []
        pattern = f"hrrr.t{self.cyc:02d}z.wrfsfcf*.grib2"

        found_files = sorted(self.input_path.glob(pattern))

        for f in found_files:
            try:
                fhr_str = f.name.split("wrfsfcf")[1].split(".")[0]
                fhr = int(fhr_str)
                if fhr <= self.forecast_hours:
                    hrrr_files.append(f)
            except (ValueError, IndexError):
                continue

        return hrrr_files

    def _extract_grib2_data(self, hrrr_files: List[Path]) -> dict:
        """Extract variables from HRRR GRIB2 files."""
        extracted_data = {"times": [], "lons": None, "lats": None}

        for var in self.variables:
            extracted_data[var] = []

        lon_min = self.config.lon_min
        lon_max = self.config.lon_max
        lat_min = self.config.lat_min
        lat_max = self.config.lat_max

        log.info(f"Extracting HRRR for domain: lon[{lon_min},{lon_max}], lat[{lat_min},{lat_max}]")

        for hrrr_file in hrrr_files:
            try:
                fhr_str = hrrr_file.name.split("wrfsfcf")[1].split(".")[0]
                fhr = int(fhr_str)
                base_time = datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc)
                valid_time = base_time + timedelta(hours=fhr)
                extracted_data["times"].append(valid_time)

                for var in self.variables:
                    if var in self.GRIB2_VARIABLES:
                        grib_var, level = self.GRIB2_VARIABLES[var]
                        data = self._wgrib2_extract(
                            hrrr_file, grib_var, level,
                            lon_min, lon_max, lat_min, lat_max
                        )
                        if data is not None:
                            extracted_data[var].append(data)

            except Exception as e:
                log.warning(f"Error processing {hrrr_file}: {e}")

        if hrrr_files and extracted_data["lons"] is None:
            extracted_data["lons"], extracted_data["lats"] = self._get_hrrr_grid(
                lon_min, lon_max, lat_min, lat_max
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
        """Extract variable from HRRR GRIB2 using wgrib2."""
        tmp_file = self.output_path / f"tmp_hrrr_{variable}_{grib_file.stem}.bin"
        subset_file = self.output_path / f"tmp_hrrr_{variable}_{grib_file.stem}.grb2"

        try:
            match_str = f":{variable}:{level}:"

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
                return None

            cmd2 = ["wgrib2", str(subset_file), "-no_header", "-bin", str(tmp_file)]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)

            if result2.returncode == 0 and tmp_file.exists():
                data = np.fromfile(tmp_file, dtype=np.float32)

                cmd3 = ["wgrib2", str(subset_file), "-nxny"]
                result3 = subprocess.run(cmd3, capture_output=True, text=True, timeout=30)

                if result3.returncode == 0:
                    for part in result3.stdout.strip().split(":"):
                        if "x" in part and "(" in part:
                            dims = part.split("(")[1].split(")")[0]
                            nx, ny = map(int, dims.split(" x "))
                            data = data.reshape((ny, nx))
                            break

                tmp_file.unlink(missing_ok=True)
                subset_file.unlink(missing_ok=True)
                return data

        except subprocess.TimeoutExpired:
            log.warning(f"wgrib2 timeout for HRRR {variable}")
        except Exception as e:
            log.debug(f"wgrib2 HRRR extraction error: {e}")

        for f in [tmp_file, subset_file]:
            if isinstance(f, Path) and f.exists():
                f.unlink(missing_ok=True)

        return None

    def _get_hrrr_grid(
        self,
        lon_min: float,
        lon_max: float,
        lat_min: float,
        lat_max: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Get HRRR grid coordinates (~3km resolution)."""
        dx = dy = 0.03  # ~3km in degrees
        lons = np.arange(lon_min, lon_max + dx, dx)
        lats = np.arange(lat_min, lat_max + dy, dy)
        return lons, lats

    def _create_sflux_files(self, data: dict) -> List[Path]:
        """Create SCHISM sflux files for HRRR (as air_2 secondary source)."""
        if not HAS_NETCDF4:
            log.error("netCDF4 required for sflux file creation")
            return []

        output_files = []
        times = data["times"]
        lons = data["lons"]
        lats = data["lats"]

        if lons is None or lats is None or not times:
            return []

        base_date = datetime.strptime(self.pdy, "%Y%m%d")

        # Create sflux_air_2 (secondary/high-res source)
        air_file = self._create_sflux_air(data, times, lons, lats, base_date)
        if air_file:
            output_files.append(air_file)

        return output_files

    def _create_sflux_air(
        self, data: dict, times: list, lons: np.ndarray, lats: np.ndarray, base_date: datetime
    ) -> Optional[Path]:
        """Create sflux_air_2 file for HRRR."""
        output_file = self.output_path / "sflux_air_2.0001.nc"

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            nc.createDimension('nx_grid', len(lons))
            nc.createDimension('ny_grid', len(lats))
            nc.createDimension('ntime', len(times))

            time_var = nc.createVariable('time', 'f8', ('ntime',))
            time_var.units = f"days since {base_date.strftime('%Y-%m-%d')} 00:00:00"
            time_var.calendar = "standard"
            time_vals = [(t - base_date).total_seconds() / 86400.0 for t in times]
            time_var[:] = time_vals

            lon_var = nc.createVariable('lon', 'f4', ('ny_grid', 'nx_grid'))
            lat_var = nc.createVariable('lat', 'f4', ('ny_grid', 'nx_grid'))
            lon_2d, lat_2d = np.meshgrid(lons, lats)
            lon_var[:] = lon_2d
            lat_var[:] = lat_2d

            var_specs = {
                'uwind': ('f4', 'm/s', 'U-wind velocity at 10m'),
                'vwind': ('f4', 'm/s', 'V-wind velocity at 10m'),
                'prmsl': ('f4', 'Pa', 'Pressure reduced to mean sea level'),
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

            nc.title = "SCHISM sflux air forcing from HRRR"
            nc.source = "HRRR 3km"
            nc.history = f"Created {datetime.now().isoformat()}"
            nc.conventions = "CF-1.6"
            nc.close()

            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create sflux_air_2: {e}")
            return None
