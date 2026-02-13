"""
HRRR (High-Resolution Rapid Refresh) Forcing Processor

Processes HRRR atmospheric data for SCHISM ocean model forcing.
HRRR provides high-resolution (3km) atmospheric data for the CONUS domain.

Used by STOFS 3D Atlantic as a regional atmospheric forcing source
with higher priority than GFS in the overlap region.
NOT used by SECOFS (limited SE coastal coverage offshore).

Output: SCHISM sflux NetCDF files (as secondary/air_2 source)
- sflux_air_2.XXXX.nc
- sflux_rad_2.XXXX.nc
- sflux_prc_2.XXXX.nc

Native Python implementation using cfgrib/xarray for GRIB2 reading
and netCDF4 for output generation. No subprocess calls.
"""

import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..base import ForcingProcessor, ForcingResult

log = logging.getLogger(__name__)

# Optional dependency: netCDF4
try:
    from netCDF4 import Dataset

    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False

# Optional dependency: xarray + cfgrib
try:
    import xarray as xr

    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False

try:
    import cfgrib  # noqa: F401

    HAS_CFGRIB = True
except ImportError:
    HAS_CFGRIB = False

# GRIB2 filter keys for HRRR variables
# HRRR uses MSLMA for sea level pressure instead of PRMSL
HRRR_GRIB2_FILTER_KEYS: Dict[str, dict] = {
    "uwind": {
        "shortName": "10u",
        "typeOfLevel": "heightAboveGround",
        "level": 10,
    },
    "vwind": {
        "shortName": "10v",
        "typeOfLevel": "heightAboveGround",
        "level": 10,
    },
    "prmsl": {
        "shortName": "mslma",
        "typeOfLevel": "meanSea",
    },
    "stmp": {
        "shortName": "2t",
        "typeOfLevel": "heightAboveGround",
        "level": 2,
    },
    "spfh": {
        "shortName": "2sh",
        "typeOfLevel": "heightAboveGround",
        "level": 2,
    },
    "rh": {
        "shortName": "2r",
        "typeOfLevel": "heightAboveGround",
        "level": 2,
    },
    "dlwrf": {
        "shortName": "dlwrf",
        "typeOfLevel": "surface",
    },
    "dswrf": {
        "shortName": "dswrf",
        "typeOfLevel": "surface",
    },
    "ulwrf": {
        "shortName": "ulwrf",
        "typeOfLevel": "surface",
    },
    "uswrf": {
        "shortName": "uswrf",
        "typeOfLevel": "surface",
    },
    "prate": {
        "shortName": "prate",
        "typeOfLevel": "surface",
    },
    "albdo": {
        "shortName": "al",
        "typeOfLevel": "surface",
    },
}

# Fallback filter keys using paramId
HRRR_PARAM_FALLBACK: Dict[str, dict] = {
    "prmsl": {"paramId": 260074, "typeOfLevel": "meanSea"},
    "spfh": {"paramId": 260242, "typeOfLevel": "heightAboveGround", "level": 2},
}


class HRRRProcessor(ForcingProcessor):
    """
    HRRR atmospheric forcing processor for SCHISM.

    Processes HRRR GRIB2 files and creates SCHISM-compatible sflux NetCDF files.
    HRRR is used as a secondary (higher-resolution) atmospheric source (air_2).

    Native Python implementation -- no subprocess calls to wgrib2, ncap2,
    ncrcat, ncks, ncatted, ncrename, or other shell tools.
    """

    # Variables from shell script list_var_oi in
    # stofs_3d_atl_create_surface_forcing_hrrr.sh line 156
    SHELL_SCRIPT_VARIABLES = [
        "uwind", "vwind", "prmsl", "stmp", "spfh", "rh",
        "dlwrf", "dswrf", "ulwrf", "uswrf", "prate", "albdo",
    ]

    DEFAULT_VARIABLES = [
        "uwind", "vwind", "prmsl", "stmp", "spfh",
        "dlwrf", "dswrf", "prate",
    ]

    # Minimum HRRR file size (100MB from shell script line 129)
    MIN_FILE_SIZE = 100_000_000

    # Minimum merged output size (1.8GB from shell script line 219)
    MIN_MERGED_SIZE = 1_800_000_000

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
            config: OFSConfig instance
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
            self.variables = list(self.DEFAULT_VARIABLES)

        self.cyc = config.cyc
        self.pdy = config.PDY

        # Domain bounds (configurable, not hardcoded)
        # Shell script defaults: LONMIN=-98.5, LONMAX=-49.5, LATMIN=5.5, LATMAX=50
        self.lon_min = getattr(config, "hrrr_lon_min", getattr(config, "lon_min", -98.5))
        self.lon_max = getattr(config, "hrrr_lon_max", getattr(config, "lon_max", -49.5))
        self.lat_min = getattr(config, "hrrr_lat_min", getattr(config, "lat_min", 5.5))
        self.lat_max = getattr(config, "hrrr_lat_max", getattr(config, "lat_max", 50.0))

        # Rerun output path
        self.comout_rerun = getattr(config, "COMOUTrerun", None)

    def process(self) -> ForcingResult:
        """
        Process HRRR forcing data.

        HRRR is optional/secondary -- failure returns success=True with warnings.

        Returns:
            ForcingResult with processed files
        """
        log.info("Processing %s forcing data", self.source_name)
        log.info("Input path: %s", self.input_path)
        log.info("Forecast hours: %d", self.forecast_hours)
        log.info(
            "Domain: lon[%.2f, %.2f], lat[%.2f, %.2f]",
            self.lon_min, self.lon_max, self.lat_min, self.lat_max,
        )

        # Check dependencies
        if not HAS_XARRAY or not HAS_CFGRIB:
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=[
                    "xarray/cfgrib not available for HRRR processing. "
                    "Install: pip install xarray cfgrib"
                ],
            )

        if not HAS_NETCDF4:
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=["netCDF4 not available for HRRR output"],
            )

        if not self.validate_input():
            log.warning("HRRR input path not found: %s", self.input_path)
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=["HRRR input path not found - using GFS only"],
            )

        self.create_output_dir()
        output_files: List[Path] = []

        try:
            # Step 1: Find HRRR files
            hrrr_files = self._find_hrrr_files()

            if not hrrr_files:
                log.warning("No HRRR files found - this is acceptable if GFS is primary")
                return ForcingResult(
                    success=True,
                    source=self.source_name,
                    warnings=["No HRRR input files found"],
                )

            # Step 2: Size-filter
            hrrr_files = self._filter_by_size(hrrr_files)
            log.info("Found %d valid HRRR files after size filter", len(hrrr_files))

            if not hrrr_files:
                return ForcingResult(
                    success=True,
                    source=self.source_name,
                    warnings=["All HRRR files failed size check"],
                )

            # Step 3: Extract data from all files
            extracted = self._extract_all_grib2(hrrr_files)

            if not extracted or not extracted.get("times"):
                return ForcingResult(
                    success=True,
                    source=self.source_name,
                    warnings=["Could not extract HRRR data"],
                )

            n_times = len(extracted["times"])
            log.info("Extracted %d time steps from HRRR files", n_times)

            # Step 4: Create merged sflux files (as air_2/rad_2/prc_2)
            sflux_files = self._create_sflux_files(extracted)
            output_files.extend(sflux_files)

            # Step 5: Archive to COMOUTrerun
            self._archive_outputs(sflux_files, extracted)

            return ForcingResult(
                success=True,
                source=self.source_name,
                output_files=output_files,
                metadata={
                    "forecast_hours": self.forecast_hours,
                    "priority": self.priority,
                    "num_files": len(hrrr_files),
                    "num_time_steps": n_times,
                },
            )

        except Exception as e:
            log.error("HRRR processing failed: %s", e)
            import traceback

            log.error(traceback.format_exc())
            # HRRR failure is non-fatal
            return ForcingResult(
                success=True,
                source=self.source_name,
                warnings=[f"HRRR processing failed: {e}"],
            )

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------

    def _find_hrrr_files(self) -> List[Path]:
        """
        Find HRRR GRIB2 files following the operational shell script logic.

        Shell script (stofs_3d_atl_create_surface_forcing_hrrr.sh):
          Yesterday t11-t23, f01 (13 files)
          Today t00-t11, f01 (12 files)
          Today t12z f01-f48 (48 files)
          Total target: 73 files

        Returns:
            List of existing HRRR file paths
        """
        hrrr_files: List[Path] = []

        base_date = datetime.strptime(self.pdy, "%Y%m%d")
        prev_date = base_date - timedelta(days=1)
        prev_str = prev_date.strftime("%Y%m%d")
        today_str = self.pdy

        # Resolve directories
        prev_dir = self._resolve_hrrr_dir(prev_str)
        today_dir = self._resolve_hrrr_dir(today_str)

        # Part 1: Yesterday t11-t23, f01 (13 files for nowcast coverage)
        if prev_dir:
            for hr in range(11, 24):
                f = prev_dir / f"hrrr.t{hr:02d}z.wrfsfcf01.grib2"
                if f.exists():
                    hrrr_files.append(f)

        # Part 2: Today t00-t11, f01 (12 files for nowcast)
        if today_dir:
            for hr in range(0, 12):
                f = today_dir / f"hrrr.t{hr:02d}z.wrfsfcf01.grib2"
                if f.exists():
                    hrrr_files.append(f)

        # Part 3: Today t{cyc}z f01-f48 (forecast)
        if today_dir:
            for fhr in range(1, min(self.forecast_hours + 1, 49)):
                f = today_dir / f"hrrr.t{self.cyc:02d}z.wrfsfcf{fhr:02d}.grib2"
                if f.exists():
                    hrrr_files.append(f)

        log.info(
            "Found %d HRRR files (target: ~73 for complete coverage)",
            len(hrrr_files),
        )
        return hrrr_files

    def _resolve_hrrr_dir(self, date_str: str) -> Optional[Path]:
        """
        Resolve HRRR directory for a given date.

        Checks:
          {input}/hrrr.{date}/conus/
          {input}/hrrr.{date}/
          {input}/

        Returns the first existing directory, or None.
        """
        candidates = [
            self.input_path / f"hrrr.{date_str}" / "conus",
            self.input_path / f"hrrr.{date_str}",
            self.input_path,
        ]
        for d in candidates:
            if d.exists() and d.is_dir():
                return d
        return None

    def _filter_by_size(self, files: List[Path]) -> List[Path]:
        """Filter HRRR files by minimum size (100 MB)."""
        valid: List[Path] = []
        for f in files:
            if not f.exists():
                continue
            sz = f.stat().st_size
            if sz >= self.MIN_FILE_SIZE:
                valid.append(f)
            else:
                log.warning(
                    "HRRR file too small (%d < %d): %s",
                    sz, self.MIN_FILE_SIZE, f.name,
                )
        return valid

    # ------------------------------------------------------------------
    # GRIB2 extraction with cfgrib/xarray
    # ------------------------------------------------------------------

    def _extract_all_grib2(self, hrrr_files: List[Path]) -> dict:
        """
        Read all HRRR GRIB2 files and extract variables using xarray/cfgrib.

        Returns:
            Dictionary with 'times', 'lons', 'lats', and variable arrays.
        """
        result: Dict = {
            "times": [],
            "lons": None,
            "lats": None,
        }
        for var in self.variables:
            result[var] = []

        for idx, hrrr_file in enumerate(hrrr_files):
            log.debug(
                "Processing HRRR (%d/%d): %s",
                idx + 1, len(hrrr_files), hrrr_file.name,
            )

            try:
                file_data = self._read_single_grib2(hrrr_file)
            except Exception as e:
                log.warning("Failed to read HRRR %s: %s", hrrr_file.name, e)
                continue

            if file_data is None:
                continue

            result["times"].append(file_data["valid_time"])

            if result["lons"] is None and file_data.get("lons") is not None:
                result["lons"] = file_data["lons"]
                result["lats"] = file_data["lats"]

            for var in self.variables:
                if var in file_data:
                    result[var].append(file_data[var])
                elif result["lons"] is not None:
                    shape = (len(result["lats"]), len(result["lons"]))
                    result[var].append(np.full(shape, np.nan, dtype=np.float32))

        # Remove None entries
        for var in self.variables:
            result[var] = [a for a in result[var] if a is not None]

        return result

    def _read_single_grib2(self, grib_file: Path) -> Optional[dict]:
        """
        Read a single HRRR GRIB2 file and extract requested variables.

        HRRR files use Lambert Conformal projection, so cfgrib will
        return 2-D latitude/longitude arrays. We subset to the bounding
        box using coordinate masks.
        """
        data: Dict = {}

        # Parse valid time from filename
        valid_time = self._parse_valid_time(grib_file)
        if valid_time is None:
            return None
        data["valid_time"] = valid_time

        for var in self.variables:
            fkeys = HRRR_GRIB2_FILTER_KEYS.get(var)
            if fkeys is None:
                continue

            arr, lons, lats = self._cfgrib_read_variable(grib_file, var, fkeys)
            if arr is not None:
                data[var] = arr
                if "lons" not in data or data.get("lons") is None:
                    data["lons"] = lons
                    data["lats"] = lats

        return data if len(data) > 1 else None

    def _cfgrib_read_variable(
        self,
        grib_file: Path,
        var_name: str,
        filter_keys: dict,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Read a single variable from an HRRR GRIB2 file using cfgrib.

        HRRR uses Lambert Conformal Conic projection, so the native grid
        has 2-D lat/lon arrays. We handle both regular lat-lon grids
        (if cfgrib decodes that way) and projected grids.

        For projected grids, we extract the rectangular sub-domain that
        contains the bounding box and return the 1-D coordinate arrays
        of the sub-domain (this is an approximation suitable for SCHISM
        sflux forcing which accepts rectilinear grids).

        Returns:
            Tuple of (data_2d, lons_1d, lats_1d) or (None, None, None)
        """
        try:
            ds = xr.open_dataset(
                grib_file,
                engine="cfgrib",
                backend_kwargs={
                    "filter_by_keys": filter_keys,
                    "indexpath": "",
                },
            )
        except Exception:
            fallback = HRRR_PARAM_FALLBACK.get(var_name)
            if fallback:
                try:
                    ds = xr.open_dataset(
                        grib_file,
                        engine="cfgrib",
                        backend_kwargs={
                            "filter_by_keys": fallback,
                            "indexpath": "",
                        },
                    )
                except Exception:
                    return None, None, None
            else:
                return None, None, None

        try:
            data_vars = list(ds.data_vars)
            if not data_vars:
                ds.close()
                return None, None, None

            da = ds[data_vars[0]].squeeze()

            # Determine coordinate type
            if "latitude" in ds.coords and "longitude" in ds.coords:
                lat_arr = ds["latitude"].values
                lon_arr = ds["longitude"].values
            elif "lat" in ds.coords and "lon" in ds.coords:
                lat_arr = ds["lat"].values
                lon_arr = ds["lon"].values
            elif "y" in ds.dims and "x" in ds.dims:
                # Projected grid -- lat/lon are 2-D
                if "latitude" in ds:
                    lat_arr = ds["latitude"].values
                    lon_arr = ds["longitude"].values
                else:
                    ds.close()
                    return None, None, None
            else:
                ds.close()
                return None, None, None

            arr = da.values

            # Convert 0-360 longitudes to -180..180
            if np.any(lon_arr > 180):
                lon_arr = np.where(lon_arr > 180, lon_arr - 360, lon_arr)

            # Handle 2-D coordinate arrays (Lambert Conformal)
            if lon_arr.ndim == 2 and lat_arr.ndim == 2:
                # Create mask for bounding box
                mask = (
                    (lon_arr >= self.lon_min)
                    & (lon_arr <= self.lon_max)
                    & (lat_arr >= self.lat_min)
                    & (lat_arr <= self.lat_max)
                )

                if not mask.any():
                    ds.close()
                    return None, None, None

                # Find bounding rectangle of the mask
                rows = np.any(mask, axis=1)
                cols = np.any(mask, axis=0)
                rmin, rmax = np.where(rows)[0][[0, -1]]
                cmin, cmax = np.where(cols)[0][[0, -1]]

                arr_sub = arr[rmin : rmax + 1, cmin : cmax + 1].astype(np.float32)

                # Build approximate 1-D coordinate arrays for the subset
                # Use the center column for latitudes and center row for longitudes
                mid_col = (cmin + cmax) // 2
                mid_row = (rmin + rmax) // 2
                lats_1d = lat_arr[rmin : rmax + 1, mid_col]
                lons_1d = lon_arr[mid_row, cmin : cmax + 1]

                ds.close()
                return arr_sub, lons_1d, lats_1d

            elif lon_arr.ndim == 1 and lat_arr.ndim == 1:
                # Regular lat-lon grid (unusual for HRRR but handle it)
                lon_mask = (lon_arr >= self.lon_min) & (lon_arr <= self.lon_max)
                lat_mask = (lat_arr >= self.lat_min) & (lat_arr <= self.lat_max)

                if not lon_mask.any() or not lat_mask.any():
                    ds.close()
                    return None, None, None

                lons_sub = lon_arr[lon_mask]
                lats_sub = lat_arr[lat_mask]

                if arr.ndim == 2:
                    arr_sub = arr[np.ix_(lat_mask, lon_mask)]
                else:
                    ds.close()
                    return None, None, None

                ds.close()
                return arr_sub.astype(np.float32), lons_sub, lats_sub

            else:
                ds.close()
                return None, None, None

        except Exception as e:
            log.debug("Error subsetting HRRR %s: %s", var_name, e)
            try:
                ds.close()
            except Exception:
                pass
            return None, None, None

    def _parse_valid_time(self, grib_file: Path) -> Optional[datetime]:
        """
        Determine valid time from an HRRR filename.

        Patterns:
          hrrr.t{HH}z.wrfsfcf{FF}.grib2
        where HH = cycle hour, FF = forecast hour.

        The date comes from the parent directory: hrrr.YYYYMMDD/conus/
        """
        try:
            fname = grib_file.name
            # Extract cycle hour
            cyc_str = fname.split(".t")[1].split("z")[0]
            cyc_hour = int(cyc_str)

            # Extract forecast hour
            fhr_str = fname.split("wrfsfcf")[1].split(".")[0]
            fhr = int(fhr_str)

            # Extract date from parent directory
            for parent in grib_file.parents:
                dirname = parent.name
                if dirname.startswith("hrrr.") and len(dirname) == 13:
                    date_str = dirname[5:]
                    base = datetime.strptime(date_str, "%Y%m%d")
                    return base + timedelta(hours=cyc_hour + fhr)

            # Fallback
            base = datetime.strptime(self.pdy, "%Y%m%d")
            return base + timedelta(hours=cyc_hour + fhr)

        except Exception as e:
            log.debug("Cannot parse valid time from HRRR %s: %s", grib_file.name, e)
            return None

    # ------------------------------------------------------------------
    # NetCDF output creation
    # ------------------------------------------------------------------

    def _create_sflux_files(self, data: dict) -> List[Path]:
        """
        Create SCHISM sflux files for HRRR (as air_2 secondary source).

        Mirrors the shell script which creates a merged file and then
        symlinks it as sflux_air_2.0001.nc, sflux_rad_2.0001.nc,
        sflux_prc_2.0001.nc.
        """
        output_files: List[Path] = []
        times = data["times"]
        lons = data["lons"]
        lats = data["lats"]

        if lons is None or lats is None or not times:
            return []

        # Reference time: previous day 00Z (same as GFS)
        base_date_dt = datetime.strptime(self.pdy, "%Y%m%d")
        prev_date = base_date_dt - timedelta(days=1)
        ref_time = datetime(prev_date.year, prev_date.month, prev_date.day, 0, 0, 0)
        base_date = [prev_date.year, prev_date.month, prev_date.day, 0]

        # Time values in days since ref_time
        time_values = np.array(
            [(t - ref_time).total_seconds() / 86400.0 for t in times],
            dtype=np.float32,
        )

        # Create merged file
        merged_file = self._create_merged_sflux(
            data, time_values, lons, lats, base_date
        )

        if merged_file:
            output_files.append(merged_file)

            # Create symlink-like copies for sflux_air_2, sflux_rad_2, sflux_prc_2
            for sflux_type in ["air", "rad", "prc"]:
                link_name = self.output_path / f"sflux_{sflux_type}_2.0001.nc"
                try:
                    if link_name.exists():
                        link_name.unlink()
                    shutil.copy2(str(merged_file), str(link_name))
                    output_files.append(link_name)
                except Exception as e:
                    log.warning("Cannot create %s: %s", link_name.name, e)

        return output_files

    def _create_merged_sflux(
        self,
        data: dict,
        time_values: np.ndarray,
        lons: np.ndarray,
        lats: np.ndarray,
        base_date: list,
    ) -> Optional[Path]:
        """
        Create a single merged HRRR sflux file with all time steps.

        Replicates the shell script's ncrcat + ncks + ncap2 pipeline:
          1. For each input: extract variables, drop x/y, set time
          2. ncrcat all into one merged file

        Output format matches the Fortran SELFE writer.
        """
        pdyhh_fcast_begin = getattr(self.config, "PDYHH_FCAST_BEGIN", self.pdy + f"{self.cyc:02d}")
        pdyhh_fcast_end = getattr(self.config, "PDYHH_FCAST_END", "")
        output_file = self.output_path / f"hrrr_date_{pdyhh_fcast_begin}_{pdyhh_fcast_end}.nc"

        try:
            nx = len(lons)
            ny = len(lats)
            nt = len(time_values)

            nc = Dataset(str(output_file), "w", format="NETCDF4_CLASSIC")

            nc.createDimension("nx_grid", nx)
            nc.createDimension("ny_grid", ny)
            nc.createDimension("time", None)  # UNLIMITED

            # Time variable
            time_var = nc.createVariable("time", "f4", ("time",))
            time_var.units = "days since {}-{:02d}-{:02d}".format(
                base_date[0], base_date[1], base_date[2]
            )
            time_var.base_date = np.array(base_date, dtype=np.int32)
            time_var.standard_name = "time"
            time_var.long_name = "Time"
            time_var._FillValue = np.float32(-9999.0)
            time_var[:] = time_values

            # Coordinates (2-D meshgrid)
            lon_var = nc.createVariable(
                "lon", "f4", ("ny_grid", "nx_grid"), fill_value=-9999.0
            )
            lon_var.units = "degrees_east"
            lon_var.standard_name = "longitude"
            lon_var.long_name = "Longitude"

            lat_var = nc.createVariable(
                "lat", "f4", ("ny_grid", "nx_grid"), fill_value=-9999.0
            )
            lat_var.units = "degrees_north"
            lat_var.standard_name = "latitude"
            lat_var.long_name = "Latitude"

            lon_2d, lat_2d = np.meshgrid(lons, lats)
            lon_var[:] = lon_2d
            lat_var[:] = lat_2d

            # Variable specs (matching Fortran SELFE writer attributes)
            var_specs = {
                "uwind": ("f4", "m/s", "eastward_wind", "Surface Eastward Air Velocity (10m AGL)"),
                "vwind": ("f4", "m/s", "northward_wind", "Surface Northward Air Velocity (10m AGL)"),
                "prmsl": ("f4", "Pa", "air_pressure_at_sea_level", "Pressure reduced to MSL"),
                "stmp": ("f4", "K", "air_temperature", "Surface Air Temperature (2m AGL)"),
                "spfh": ("f4", "1", "specific_humidity", "Surface Specific Humidity (2m AGL)"),
                "dlwrf": ("f4", "W/m^2", "surface_downwelling_longwave_flux_in_air", "Downward Long Wave Radiation Flux"),
                "dswrf": ("f4", "W/m^2", "surface_downwelling_shortwave_flux_in_air", "Downward Short Wave Radiation Flux"),
                "ulwrf": ("f4", "W/m^2", "surface_upwelling_longwave_flux_in_air", "Upward Long Wave Radiation Flux"),
                "uswrf": ("f4", "W/m^2", "surface_upwelling_shortwave_flux_in_air", "Upward Short Wave Radiation Flux"),
                "prate": ("f4", "kg/m^2/s", "precipitation_flux", "Surface Precipitation Rate"),
                "rh": ("f4", "%", "relative_humidity", "Relative Humidity (2m AGL)"),
                "albdo": ("f4", "%", "surface_albedo", "Surface Albedo"),
            }

            for varname, (dtype, units, std_name, long_name) in var_specs.items():
                if varname not in self.variables:
                    continue
                if varname not in data or not data[varname]:
                    continue

                var = nc.createVariable(
                    varname, dtype, ("time", "ny_grid", "nx_grid"),
                    fill_value=np.float32(-9999.0),
                )
                var.units = units
                var.standard_name = std_name
                var.long_name = long_name

                try:
                    stacked = np.stack(data[varname][:nt], axis=0)
                    var[:] = stacked.astype(np.float32)
                except Exception as e:
                    log.warning("Could not write HRRR %s: %s", varname, e)

            nc.type = "SCHISM sflux forcing"
            nc.title = "SCHISM sflux forcing from HRRR"
            nc.source = "HRRR 3km"
            nc.history = f"Created {datetime.now().isoformat()} by nos_ofs HRRRProcessor"
            nc.Conventions = "CF-1.6"
            nc.close()

            log.info("Created HRRR merged sflux: %s", output_file)
            return output_file

        except Exception as e:
            log.error("Failed to create HRRR merged sflux: %s", e)
            return None

    def _archive_outputs(self, sflux_files: List[Path], data: dict) -> None:
        """
        Archive HRRR output files to COMOUTrerun.

        Mirrors shell script cpreq commands:
          cpreq -pf $fn_link_src ${COMOUTrerun}/${fn_hrrr_rad_std}
          cpreq -pf $fn_link_src ${COMOUTrerun}/${fn_hrrr_prc_std}
          cpreq -pf $fn_link_src ${COMOUTrerun}/${fn_hrrr_air_std}
        """
        if not self.comout_rerun:
            return

        # Find the merged file
        merged = None
        for f in sflux_files:
            if "hrrr_date_" in f.name:
                merged = f
                break

        if merged is None or not merged.exists():
            return

        rerun_dir = Path(self.comout_rerun)
        rerun_dir.mkdir(parents=True, exist_ok=True)

        run_name = getattr(self.config, "RUN", "stofs_3d_atl")
        cycle = getattr(self.config, "cycle", f"t{self.cyc:02d}z")

        std_names = [
            f"{run_name}.{cycle}.hrrr.rad.nc",
            f"{run_name}.{cycle}.hrrr.prc.nc",
            f"{run_name}.{cycle}.hrrr.air.nc",
        ]

        for std_name in std_names:
            dst = rerun_dir / std_name
            try:
                shutil.copy2(str(merged), str(dst))
                log.info("Archived %s -> %s", merged.name, dst)
            except Exception as e:
                log.warning("Failed to archive HRRR %s: %s", std_name, e)
