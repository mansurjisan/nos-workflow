"""
GFS (Global Forecast System) Forcing Processor

Processes GFS atmospheric data for SCHISM ocean model forcing including:
- Wind (u, v components at 10m)
- Sea level pressure (PRMSL)
- Air temperature (TMP at 2m)
- Specific humidity (SPFH at 2m)
- Relative humidity (RH at 2m)
- Downward shortwave radiation (DSWRF)
- Downward longwave radiation (DLWRF)
- Upward shortwave radiation (USWRF)
- Upward longwave radiation (ULWRF)
- Surface albedo (ALBDO)
- Precipitation rate (PRATE)

Output: SCHISM sflux NetCDF files
- sflux_air_1.XXXX.nc - wind, temperature, humidity, pressure
- sflux_rad_1.XXXX.nc - shortwave, longwave radiation
- sflux_prc_1.XXXX.nc - precipitation

Native Python implementation using cfgrib/xarray for GRIB2 reading
and netCDF4 for output generation. No subprocess calls to wgrib2,
ncap2, ncrcat, ncks, ncatted, ncrename, or any other shell tools.
"""

import logging
import os
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
    log.warning("netCDF4 not available - GFS processing will be limited")

# Optional dependency: cfgrib via xarray
try:
    import xarray as xr

    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False
    log.warning("xarray not available - GFS GRIB2 reading will be limited")

try:
    import cfgrib  # noqa: F401 - needed as xarray backend

    HAS_CFGRIB = True
except ImportError:
    HAS_CFGRIB = False
    log.warning(
        "cfgrib not available - install with: pip install cfgrib. "
        "Also requires eccodes library."
    )


# ---------------------------------------------------------------------------
# GRIB2 variable filter key specifications for cfgrib
# Each entry maps an internal variable name to the cfgrib filter_by_keys
# dict used to open the dataset and the shortName in the resulting dataset.
# ---------------------------------------------------------------------------
GRIB2_FILTER_KEYS: Dict[str, dict] = {
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
        "shortName": "prmsl",
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

# Fallback: mapping of internal name -> GRIB2 parameterName regex for cases
# where shortName lookup fails (GFS sometimes encodes SPFH as paramId).
GRIB2_PARAM_FALLBACK: Dict[str, dict] = {
    "spfh": {"paramId": 260242, "typeOfLevel": "heightAboveGround", "level": 2},
    "prate": {"paramId": 260045, "typeOfLevel": "surface"},
}


class GFSProcessor(ForcingProcessor):
    """
    GFS atmospheric forcing processor for SCHISM.

    Processes GFS GRIB2 files and creates SCHISM-compatible sflux NetCDF files.
    Uses cfgrib (via xarray) for GRIB2 reading and netCDF4 for output.
    No external tool dependencies (wgrib2, ncap2, ncrcat, etc.).
    """

    # Variables extracted from shell script list_var_oi in
    # stofs_3d_atl_create_surface_forcing_gfs.sh line 249
    SHELL_SCRIPT_VARIABLES = [
        "uwind",
        "vwind",
        "prmsl",
        "stmp",
        "spfh",
        "rh",
        "dlwrf",
        "dswrf",
        "ulwrf",
        "uswrf",
        "prate",
        "albdo",
    ]

    DEFAULT_VARIABLES = [
        "uwind",
        "vwind",
        "prmsl",
        "stmp",
        "spfh",
        "dlwrf",
        "dswrf",
        "prate",
    ]

    # GFS grid resolution options
    GFS_0P25 = "0p25"  # 0.25 degree
    GFS_0P50 = "0p50"  # 0.50 degree

    # Minimum file size to consider a GFS file valid (500MB from shell script)
    MIN_FILE_SIZE = 500_000_000

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
            config: OFSConfig instance with at minimum: cyc, PDY, lon_min,
                    lon_max, lat_min, lat_max attributes.
            input_path: Path to GFS GRIB2 files (COMINgfs)
            output_path: Path for sflux output files (DATA/sflux)
            variables: List of variables to process (default: DEFAULT_VARIABLES)
            forecast_hours: Number of forecast hours to process
            resolution: GFS resolution ("0p25" or "0p50")
        """
        super().__init__(config, input_path, output_path, variables)
        self.forecast_hours = forecast_hours
        self.resolution = resolution
        if not self.variables:
            self.variables = list(self.DEFAULT_VARIABLES)

        # Get cycle info from config
        self.cyc = config.cyc
        self.pdy = config.PDY

        # Domain bounds from config (configurable, not hardcoded)
        self.lon_min = getattr(config, "lon_min", -98.5035)
        self.lon_max = getattr(config, "lon_max", -52.4867)
        self.lat_min = getattr(config, "lat_min", 7.347)
        self.lat_max = getattr(config, "lat_max", 52.5904)

        # Rerun output path (for archiving standard-named copies)
        self.comout_rerun = getattr(config, "COMOUTrerun", None)

        # Previous COMOUT for backup fallback
        self.comout_prev = getattr(config, "COMOUT_PREV", None)

        # Minimum time steps required
        self.n_list_target = int(getattr(config, "N_list_target", 97))

    def process(self) -> ForcingResult:
        """
        Process GFS forcing data and create SCHISM sflux files.

        Returns:
            ForcingResult with processed files
        """
        log.info("Processing %s forcing data", self.source_name)
        log.info("Input path: %s", self.input_path)
        log.info("Output path: %s", self.output_path)
        log.info("Forecast hours: %d", self.forecast_hours)
        log.info(
            "Domain: lon[%.4f, %.4f], lat[%.4f, %.4f]",
            self.lon_min,
            self.lon_max,
            self.lat_min,
            self.lat_max,
        )

        # Validate dependencies
        if not HAS_XARRAY or not HAS_CFGRIB:
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[
                    "Required dependencies not available. "
                    "Install with: pip install xarray cfgrib netCDF4"
                ],
            )

        if not HAS_NETCDF4:
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=["netCDF4 required for sflux output. pip install netCDF4"],
            )

        if not self.validate_input():
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[f"Input path not found: {self.input_path}"],
            )

        self.create_output_dir()
        output_files: List[Path] = []
        warnings: List[str] = []

        try:
            # Step 1: Build file lists (primary + backup), mimicking shell script
            gfs_files = self._find_gfs_files()

            if not gfs_files:
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["No GFS input files found"],
                )

            log.info("Found %d GFS files to process", len(gfs_files))

            # Step 2: Read and extract all variables from all GRIB2 files
            extracted = self._extract_all_grib2(gfs_files)

            if not extracted or not extracted.get("times"):
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["Failed to extract data from GFS files"],
                )

            n_times = len(extracted["times"])
            log.info("Extracted %d time steps from GFS files", n_times)

            # Step 3: Create merged sflux NetCDF and day-split files
            sflux_files = self._create_sflux_files(extracted)
            output_files.extend(sflux_files)

            # Step 4: Create sflux_inputs.txt
            inputs_file = self._create_sflux_inputs()
            if inputs_file:
                output_files.append(inputs_file)

            # Step 5: Archive to COMOUTrerun if configured
            self._archive_outputs(sflux_files)

            log.info(
                "GFS processing complete: %d files created", len(output_files)
            )

            return ForcingResult(
                success=True,
                source=self.source_name,
                output_files=output_files,
                warnings=warnings,
                metadata={
                    "forecast_hours": self.forecast_hours,
                    "variables": self.variables,
                    "num_input_files": len(gfs_files),
                    "num_time_steps": n_times,
                    "resolution": self.resolution,
                },
            )

        except Exception as e:
            log.error("GFS processing failed: %s", e)
            import traceback

            log.error(traceback.format_exc())
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[str(e)],
            )

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------

    def _find_gfs_files(self) -> List[Path]:
        """
        Find GFS GRIB2 files following the operational shell script logic.

        The shell script builds two file lists:
          LIST_fn_all_1 (primary): yest_t06z + yest_t12z + yest_t18z +
                                   today_t00z + today_t06z + today_t12z(f001..f099)
          LIST_fn_all_2 (backup):  yest_t06z(f006) + yest_t12z(f001..f099)

        Each file is size-checked (>= 500 MB).
        If primary has fewer than N_list_target files, it merges with backup.
        """
        primary = self._build_primary_file_list()
        backup = self._build_backup_file_list()

        # Size-filter both lists
        primary = self._filter_by_size(primary)
        backup = self._filter_by_size(backup)

        log.info(
            "Primary list: %d files, Backup list: %d files",
            len(primary),
            len(backup),
        )

        # Merge logic from shell script lines 216-243
        if len(primary) > 1:
            final = list(primary)
            if (
                len(primary) < self.n_list_target
                and len(backup) > len(primary)
            ):
                n_diff = len(backup) - len(primary)
                final.extend(backup[len(primary) : len(primary) + n_diff])
                log.info(
                    "Merged %d backup files into primary (total: %d)",
                    min(n_diff, len(backup)),
                    len(final),
                )
        elif len(backup) > 1:
            log.info("Using backup list (%d files)", len(backup))
            final = list(backup)
        else:
            final = list(primary)

        return final

    def _build_primary_file_list(self) -> List[Path]:
        """
        Build primary GFS file list from multiple cycles.

        Mirrors shell script lines 101-127:
          yest t06z f006
          yest t12z f001..f006
          yest t18z f001..f006
          today t00z f001..f006
          today t06z f001..f006
          today t12z f001..f099
        """
        base_date = datetime.strptime(self.pdy, "%Y%m%d")
        prev_date = base_date - timedelta(days=1)
        prev_str = prev_date.strftime("%Y%m%d")
        today_str = base_date.strftime("%Y%m%d")

        files: List[Path] = []

        # yest t06z f006
        files.extend(
            self._resolve_gfs_files(prev_str, "06", [6])
        )

        # yest t12z f001..f006
        files.extend(
            self._resolve_gfs_files(prev_str, "12", list(range(1, 7)))
        )

        # yest t18z f001..f006
        files.extend(
            self._resolve_gfs_files(prev_str, "18", list(range(1, 7)))
        )

        # today t00z f001..f006
        files.extend(
            self._resolve_gfs_files(today_str, "00", list(range(1, 7)))
        )

        # today t06z f001..f006
        files.extend(
            self._resolve_gfs_files(today_str, "06", list(range(1, 7)))
        )

        # today t12z f001..f099
        files.extend(
            self._resolve_gfs_files(today_str, "12", list(range(1, 100)))
        )

        return files

    def _build_backup_file_list(self) -> List[Path]:
        """
        Build backup GFS file list from yesterday t06z/t12z.

        Mirrors shell script lines 131-144:
          yest t06z f006
          yest t12z f001..f009
          yest t12z f01X..f08X  (10-89)
          yest t12z f090..f099
        """
        base_date = datetime.strptime(self.pdy, "%Y%m%d")
        prev_date = base_date - timedelta(days=1)
        prev_str = prev_date.strftime("%Y%m%d")

        files: List[Path] = []

        # yest t06z f006
        files.extend(self._resolve_gfs_files(prev_str, "06", [6]))

        # yest t12z f001..f099
        files.extend(
            self._resolve_gfs_files(prev_str, "12", list(range(1, 100)))
        )

        return files

    def _resolve_gfs_files(
        self, date_str: str, cyc_str: str, forecast_hours: List[int]
    ) -> List[Path]:
        """
        Resolve GFS file paths for a given date/cycle/forecast-hour list.

        Checks directory structures:
          {input}/gfs.{date}/{cyc}/atmos/gfs.t{cyc}z.pgrb2.{res}.f{fhr:03d}
          {input}/gfs.{date}/{cyc}/gfs.t{cyc}z.pgrb2.{res}.f{fhr:03d}
        """
        found: List[Path] = []

        # Try atmos subdir first, then direct
        candidate_dirs = [
            self.input_path / f"gfs.{date_str}" / cyc_str / "atmos",
            self.input_path / f"gfs.{date_str}" / cyc_str,
        ]

        gfs_dir = None
        for d in candidate_dirs:
            if d.exists():
                gfs_dir = d
                break

        if gfs_dir is None:
            return found

        for fhr in forecast_hours:
            fname = f"gfs.t{cyc_str}z.pgrb2.{self.resolution}.f{fhr:03d}"
            fpath = gfs_dir / fname
            if fpath.exists():
                found.append(fpath)

        return found

    def _filter_by_size(
        self, files: List[Path], min_size: int = 0
    ) -> List[Path]:
        """
        Filter files by minimum size (default: self.MIN_FILE_SIZE).

        Mirrors shell script lines 167-198.
        """
        if min_size <= 0:
            min_size = self.MIN_FILE_SIZE

        valid: List[Path] = []
        for f in files:
            if not f.exists():
                log.debug("GFS file does not exist: %s", f)
                continue
            sz = f.stat().st_size
            if sz >= min_size:
                valid.append(f)
            else:
                log.warning(
                    "GFS file too small (%d < %d): %s", sz, min_size, f.name
                )
        return valid

    # ------------------------------------------------------------------
    # GRIB2 extraction with cfgrib/xarray
    # ------------------------------------------------------------------

    def _extract_all_grib2(self, gfs_files: List[Path]) -> dict:
        """
        Read all GFS GRIB2 files and extract required variables.

        Uses xarray with cfgrib engine. For each file, opens the dataset
        with appropriate filter_by_keys, subsets to the domain, and
        collects 2-D arrays.

        Returns:
            Dictionary with keys:
                'times': list of datetime
                'lons': 1-D or 2-D lon array
                'lats': 1-D or 2-D lat array
                '<varname>': list of 2-D numpy arrays (one per time step)
        """
        result: Dict = {
            "times": [],
            "lons": None,
            "lats": None,
        }
        for var in self.variables:
            result[var] = []

        for idx, gfs_file in enumerate(gfs_files):
            log.debug("Processing (%d/%d): %s", idx + 1, len(gfs_files), gfs_file.name)

            try:
                file_data = self._read_single_grib2(gfs_file)
            except Exception as e:
                log.warning("Failed to read %s: %s", gfs_file.name, e)
                continue

            if file_data is None:
                continue

            # Record valid time
            result["times"].append(file_data["valid_time"])

            # Set grid coordinates from first successfully read file
            if result["lons"] is None and file_data.get("lons") is not None:
                result["lons"] = file_data["lons"]
                result["lats"] = file_data["lats"]

            # Collect variable data
            for var in self.variables:
                if var in file_data:
                    result[var].append(file_data[var])
                else:
                    # Append NaN placeholder to keep alignment
                    if result["lons"] is not None:
                        shape = (len(result["lats"]), len(result["lons"]))
                        result[var].append(
                            np.full(shape, np.nan, dtype=np.float32)
                        )
                    else:
                        result[var].append(None)

        # Clean up None placeholders
        for var in self.variables:
            result[var] = [a for a in result[var] if a is not None]

        return result

    def _read_single_grib2(self, grib_file: Path) -> Optional[dict]:
        """
        Read a single GFS GRIB2 file and extract all requested variables.

        Uses xarray with cfgrib engine, subsetting to the domain bounding box.

        Returns:
            Dict with 'valid_time', 'lons', 'lats', and variable arrays,
            or None if the file cannot be read.
        """
        data: Dict = {}

        # Determine valid time from the filename (f{fhr:03d})
        # and from the directory structure (gfs.{date}/{cyc}/...)
        valid_time = self._parse_valid_time(grib_file)
        if valid_time is None:
            log.warning("Cannot determine valid time for %s", grib_file.name)
            return None

        data["valid_time"] = valid_time

        for var in self.variables:
            fkeys = GRIB2_FILTER_KEYS.get(var)
            if fkeys is None:
                continue

            arr, lons_1d, lats_1d = self._cfgrib_read_variable(
                grib_file, var, fkeys
            )

            if arr is not None:
                data[var] = arr
                if "lons" not in data or data.get("lons") is None:
                    data["lons"] = lons_1d
                    data["lats"] = lats_1d

        return data if len(data) > 1 else None  # >1 because valid_time always present

    def _cfgrib_read_variable(
        self,
        grib_file: Path,
        var_name: str,
        filter_keys: dict,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Read a single variable from a GRIB2 file using cfgrib, subset to domain.

        Args:
            grib_file: Path to GRIB2 file
            var_name: Internal variable name
            filter_keys: cfgrib filter_by_keys dictionary

        Returns:
            Tuple of (data_2d, lons_1d, lats_1d) or (None, None, None)
        """
        try:
            ds = xr.open_dataset(
                grib_file,
                engine="cfgrib",
                backend_kwargs={
                    "filter_by_keys": filter_keys,
                    "indexpath": "",  # don't write .idx files
                },
            )
        except Exception:
            # Try fallback paramId if available
            fallback = GRIB2_PARAM_FALLBACK.get(var_name)
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
            # Identify the data variable (first non-coordinate variable)
            data_vars = list(ds.data_vars)
            if not data_vars:
                ds.close()
                return None, None, None

            da = ds[data_vars[0]]

            # Get coordinate names (cfgrib uses 'latitude'/'longitude')
            lon_name = None
            lat_name = None
            for name in ds.coords:
                if name in ("longitude", "lon", "x"):
                    lon_name = name
                elif name in ("latitude", "lat", "y"):
                    lat_name = name

            if lon_name is None or lat_name is None:
                ds.close()
                return None, None, None

            lons = ds[lon_name].values
            lats = ds[lat_name].values

            # Convert longitudes from 0-360 to -180..180 if needed
            if np.any(lons > 180):
                lons = np.where(lons > 180, lons - 360, lons)
                # Re-sort if needed
                sort_idx = np.argsort(lons)
                lons = lons[sort_idx]
                # Re-index data along longitude dimension
                da = da.isel({lon_name: sort_idx})

            # Subset to domain bounding box
            lon_mask = (lons >= self.lon_min) & (lons <= self.lon_max)
            lat_mask = (lats >= self.lat_min) & (lats <= self.lat_max)

            lons_sub = lons[lon_mask]
            lats_sub = lats[lat_mask]

            # Extract 2-D subset
            if da.ndim == 2:
                arr = da.values
            elif da.ndim == 1:
                arr = da.values
            else:
                # Squeeze extra dimensions (step, valid_time, etc.)
                arr = da.squeeze().values

            if arr.ndim == 2:
                arr_sub = arr[np.ix_(lat_mask, lon_mask)]
            elif arr.ndim == 1:
                # Shouldn't happen for gridded data, but handle gracefully
                ds.close()
                return None, None, None
            else:
                ds.close()
                return None, None, None

            ds.close()
            return arr_sub.astype(np.float32), lons_sub, lats_sub

        except Exception as e:
            log.debug("Error subsetting %s from %s: %s", var_name, grib_file.name, e)
            try:
                ds.close()
            except Exception:
                pass
            return None, None, None

    def _parse_valid_time(self, grib_file: Path) -> Optional[datetime]:
        """
        Determine the valid time of a GFS GRIB2 file from its path.

        Expected path patterns:
          .../gfs.YYYYMMDD/HH/atmos/gfs.tHHz.pgrb2.0p25.fFFF
          .../gfs.YYYYMMDD/HH/gfs.tHHz.pgrb2.0p25.fFFF

        Returns:
            datetime of the valid time, or None if parsing fails
        """
        try:
            fname = grib_file.name
            # Extract cycle hour from filename: gfs.t{HH}z.pgrb2...
            cyc_str = fname.split(".t")[1].split("z")[0]
            cyc_hour = int(cyc_str)

            # Extract forecast hour: ...f{FFF}
            fhr_str = fname.split(".f")[-1]
            fhr = int(fhr_str)

            # Extract date from parent directory: gfs.YYYYMMDD
            # Walk up to find the gfs.YYYYMMDD directory
            for parent in grib_file.parents:
                dirname = parent.name
                if dirname.startswith("gfs.") and len(dirname) == 12:
                    date_str = dirname[4:]
                    base = datetime.strptime(date_str, "%Y%m%d")
                    return base + timedelta(hours=cyc_hour + fhr)

            # Fallback: use self.pdy + cyc from filename
            base = datetime.strptime(self.pdy, "%Y%m%d")
            return base + timedelta(hours=cyc_hour + fhr)

        except Exception as e:
            log.debug("Cannot parse valid time from %s: %s", grib_file, e)
            return None

    # ------------------------------------------------------------------
    # NetCDF output creation
    # ------------------------------------------------------------------

    def _create_sflux_files(self, data: dict) -> List[Path]:
        """
        Create SCHISM sflux NetCDF files from extracted data.

        This creates a single merged file per type (matching the operational
        shell script's ncrcat behavior), then also creates the day-split
        files used by SCHISM runtime.

        Returns:
            List of created output file paths
        """
        output_files: List[Path] = []
        times = data["times"]
        lons = data["lons"]
        lats = data["lats"]

        if lons is None or lats is None:
            log.error("Grid coordinates not available")
            return []

        # Base date: start of nowcast (typically 24h before forecast start)
        # Shell script uses: iyr-imon-iday from yyyymmdd_prev
        base_date = datetime.strptime(self.pdy, "%Y%m%d")
        prev_date = base_date - timedelta(days=1)

        # Compute time values as hours-since-00Z-of-prev_date
        # The shell script: ihr=12, then hr_cnt_since_hr00 = ihr + cnt
        # where cnt starts at 0. So time = (12 + cnt) in hours / 24 = days
        # We compute directly from valid_time - prev_date_00Z
        ref_time = datetime(prev_date.year, prev_date.month, prev_date.day, 0, 0, 0)

        # Create base_date as [year, month, day, 0]
        base_date_arr = [prev_date.year, prev_date.month, prev_date.day, 0]

        # Time values in days since ref_time
        time_values = np.array(
            [(t - ref_time).total_seconds() / 86400.0 for t in times],
            dtype=np.float32,
        )

        # Adjust first and last time per shell script QC logic
        # Shell: ncap2 -s "time(0)=float(0.499999);time(-1)=float(${time_end_step})"
        n_dim_cr_max = 121
        n_dim_cr_min = 110
        time_end_step = 10.0

        if len(times) >= n_dim_cr_max:
            time_values[0] = 0.499999
            time_values[-1] = time_end_step
        elif len(times) >= n_dim_cr_min:
            time_values[0] = 0.499999
            time_values[-1] = time_end_step

        # Create merged sflux file (all times concatenated)
        merged_file = self._create_merged_sflux(
            data, time_values, lons, lats, base_date_arr
        )
        if merged_file:
            output_files.append(merged_file)

            # The shell script copies the same merged file as air, rad, prc:
            # sflux_air_1.0001.nc, sflux_rad_1.0001.nc, sflux_prc_1.0001.nc
            # These are all the same file in the STOFS workflow.
            for sflux_type in ["air", "rad", "prc"]:
                link_name = self.output_path / f"sflux_{sflux_type}_1.0001.nc"
                if link_name != merged_file:
                    try:
                        if link_name.exists():
                            link_name.unlink()
                        # Copy rather than symlink for portability
                        import shutil

                        shutil.copy2(str(merged_file), str(link_name))
                        output_files.append(link_name)
                    except Exception as e:
                        log.warning("Cannot create %s: %s", link_name.name, e)

        # Also create proper day-split files for SCHISM
        day_files = self._create_day_split_sflux(
            data, times, lons, lats, ref_time, base_date_arr
        )
        output_files.extend(day_files)

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
        Create a single merged sflux file with all time steps.

        This replicates the shell script's ncrcat + ncap2 pipeline:
          1. For each input file, extract variables, rename, set time
          2. ncrcat all into one merged file
          3. Adjust first/last time values

        The merged file contains ALL variables (air + rad + prc).
        """
        output_file = self.output_path / "gfs_merge_v1.nc"

        try:
            nx = len(lons)
            ny = len(lats)
            nt = len(time_values)

            nc = Dataset(str(output_file), "w", format="NETCDF4_CLASSIC")

            # Dimensions
            nc.createDimension("nx_grid", nx)
            nc.createDimension("ny_grid", ny)
            nc.createDimension("time", None)  # UNLIMITED

            # Time
            time_var = nc.createVariable("time", "f4", ("time",))
            time_var.units = "days since {}-{:02d}-{:02d}".format(
                base_date[0], base_date[1], base_date[2]
            )
            time_var.base_date = np.array(base_date, dtype=np.int32)
            time_var.standard_name = "time"
            time_var.long_name = "Time"
            time_var._FillValue = np.float32(-9999.0)
            time_var[:] = time_values

            # Coordinates
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

            # All forcing variables in one file (matching shell script behavior)
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
                    varname,
                    dtype,
                    ("time", "ny_grid", "nx_grid"),
                    fill_value=np.float32(-9999.0),
                )
                var.units = units
                var.standard_name = std_name
                var.long_name = long_name

                try:
                    stacked = np.stack(data[varname][: nt], axis=0)
                    var[:] = stacked.astype(np.float32)
                except Exception as e:
                    log.warning("Could not write %s: %s", varname, e)

            # Global attributes
            nc.type = "SCHISM sflux forcing"
            nc.title = "SCHISM sflux forcing from GFS"
            nc.source = f"GFS {self.resolution}"
            nc.history = f"Created {datetime.now().isoformat()} by nos_ofs GFSProcessor"
            nc.Conventions = "CF-1.6"

            nc.close()
            log.info("Created merged sflux file: %s", output_file)
            return output_file

        except Exception as e:
            log.error("Failed to create merged sflux: %s", e)
            return None

    def _create_day_split_sflux(
        self,
        data: dict,
        times: list,
        lons: np.ndarray,
        lats: np.ndarray,
        ref_time: datetime,
        base_date: list,
    ) -> List[Path]:
        """
        Create day-split sflux files (one file per day) for SCHISM runtime.

        SCHISM expects files named:
          sflux_air_1.XXXX.nc
          sflux_rad_1.XXXX.nc
          sflux_prc_1.XXXX.nc
        where XXXX is day number (0001, 0002, ...).
        """
        output_files: List[Path] = []

        # Group time indices by day number relative to ref_time
        day_groups: Dict[int, List[int]] = {}
        for i, t in enumerate(times):
            day_num = (t - ref_time).days + 1
            if day_num < 1:
                day_num = 1
            day_groups.setdefault(day_num, []).append(i)

        log.info("Creating day-split sflux files for %d days", len(day_groups))

        for day_num, indices in sorted(day_groups.items()):
            file_num = f"{day_num:04d}"
            day_times = [times[i] for i in indices]
            day_time_vals = np.array(
                [(t - ref_time).total_seconds() / 86400.0 for t in day_times],
                dtype=np.float32,
            )

            # Collect variable data for this day
            day_data: Dict[str, list] = {}
            for var in self.variables:
                if var in data and data[var]:
                    day_data[var] = [
                        data[var][i]
                        for i in indices
                        if i < len(data[var])
                    ]

            if not day_times:
                continue

            # Air file
            af = self._write_sflux_nc(
                f"sflux_air_1.{file_num}.nc",
                day_data,
                day_time_vals,
                lons,
                lats,
                base_date,
                {
                    "uwind": ("f4", "m/s", "eastward_wind", "Surface Eastward Air Velocity (10m AGL)"),
                    "vwind": ("f4", "m/s", "northward_wind", "Surface Northward Air Velocity (10m AGL)"),
                    "prmsl": ("f4", "Pa", "air_pressure_at_sea_level", "Pressure reduced to MSL"),
                    "stmp": ("f4", "K", "air_temperature", "Surface Air Temperature (2m AGL)"),
                    "spfh": ("f4", "1", "specific_humidity", "Surface Specific Humidity (2m AGL)"),
                },
                "SCHISM sflux air forcing from GFS",
            )
            if af:
                output_files.append(af)

            # Rad file
            rf = self._write_sflux_nc(
                f"sflux_rad_1.{file_num}.nc",
                day_data,
                day_time_vals,
                lons,
                lats,
                base_date,
                {
                    "dlwrf": ("f4", "W/m^2", "surface_downwelling_longwave_flux_in_air", "Downward Long Wave Radiation Flux"),
                    "dswrf": ("f4", "W/m^2", "surface_downwelling_shortwave_flux_in_air", "Downward Short Wave Radiation Flux"),
                },
                "SCHISM sflux radiation forcing from GFS",
            )
            if rf:
                output_files.append(rf)

            # Prc file
            pf = self._write_sflux_nc(
                f"sflux_prc_1.{file_num}.nc",
                day_data,
                day_time_vals,
                lons,
                lats,
                base_date,
                {
                    "prate": ("f4", "kg/m^2/s", "precipitation_flux", "Surface Precipitation Rate"),
                },
                "SCHISM sflux precipitation forcing from GFS",
            )
            if pf:
                output_files.append(pf)

        return output_files

    def _write_sflux_nc(
        self,
        filename: str,
        data: dict,
        time_values: np.ndarray,
        lons: np.ndarray,
        lats: np.ndarray,
        base_date: list,
        var_specs: dict,
        title: str,
    ) -> Optional[Path]:
        """
        Write a single SCHISM sflux NetCDF file.

        The output format matches the Fortran subroutines:
          nos_ofs_write_netcdf_wind_SELFE
          nos_ofs_write_netcdf_flux_SELFE
          nos_ofs_write_netcdf_prate_SELFE

        Dimensions: nx_grid, ny_grid, time(UNLIMITED)
        Coords: lon(ny_grid, nx_grid), lat(ny_grid, nx_grid)
        Time: days since base_date, with base_date attribute
        Variables: 3-D (time, ny_grid, nx_grid), fill_value=-9999.0

        Args:
            filename: Output filename (e.g., "sflux_air_1.0001.nc")
            data: Dict of variable arrays
            time_values: Time in days since base_date
            lons: 1-D longitude array
            lats: 1-D latitude array
            base_date: [year, month, day, 0]
            var_specs: Dict of varname -> (dtype, units, std_name, long_name)
            title: NetCDF title attribute

        Returns:
            Path to created file, or None on failure
        """
        output_file = self.output_path / filename

        # Check that at least one variable has data
        has_data = any(
            var in data and data[var]
            for var in var_specs
        )
        if not has_data:
            return None

        try:
            nx = len(lons)
            ny = len(lats)

            nc = Dataset(str(output_file), "w", format="NETCDF4_CLASSIC")

            nc.createDimension("nx_grid", nx)
            nc.createDimension("ny_grid", ny)
            nc.createDimension("time", None)

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

            # Coordinates
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

            # Data variables
            for varname, (dtype, units, std_name, long_name) in var_specs.items():
                if varname not in data or not data[varname]:
                    continue
                var = nc.createVariable(
                    varname,
                    dtype,
                    ("time", "ny_grid", "nx_grid"),
                    fill_value=np.float32(-9999.0),
                )
                var.units = units
                var.standard_name = std_name
                var.long_name = long_name
                try:
                    stacked = np.stack(data[varname], axis=0)
                    var[:] = stacked.astype(np.float32)
                except Exception as e:
                    log.warning("Could not write %s in %s: %s", varname, filename, e)

            nc.type = "SCHISM sflux forcing"
            nc.title = title
            nc.source = f"GFS {self.resolution}"
            nc.history = f"Created {datetime.now().isoformat()} by nos_ofs GFSProcessor"
            nc.Conventions = "CF-1.6"
            nc.close()

            log.debug("Created %s", output_file)
            return output_file

        except Exception as e:
            log.error("Failed to create %s: %s", filename, e)
            return None

    def _create_sflux_inputs(self) -> Optional[Path]:
        """
        Create sflux_inputs.txt namelist file for SCHISM.

        This controls how SCHISM blends air_1 (GFS) and air_2 (HRRR).
        """
        output_file = self.output_path / "sflux_inputs.txt"

        try:
            with open(output_file, "w") as f:
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

            log.info("Created %s", output_file)
            return output_file

        except Exception as e:
            log.error("Failed to create sflux_inputs.txt: %s", e)
            return None

    def _archive_outputs(self, sflux_files: List[Path]) -> None:
        """
        Archive output files to COMOUTrerun (if configured).

        Mirrors the shell script's cpreq commands that copy the merged
        file as gfs.{air,rad,prc}.nc to COMOUTrerun.
        """
        if not self.comout_rerun:
            return

        import shutil

        rerun_dir = Path(self.comout_rerun)
        rerun_dir.mkdir(parents=True, exist_ok=True)

        run_name = getattr(self.config, "RUN", "stofs_3d_atl")
        cycle = getattr(self.config, "cycle", f"t{self.cyc:02d}z")

        std_names = [
            f"{run_name}.{cycle}.gfs.rad.nc",
            f"{run_name}.{cycle}.gfs.prc.nc",
            f"{run_name}.{cycle}.gfs.air.nc",
        ]

        # Find the merged file to copy
        merged = self.output_path / "gfs_merge_v1.nc"
        if not merged.exists():
            return

        for std_name in std_names:
            dst = rerun_dir / std_name
            try:
                shutil.copy2(str(merged), str(dst))
                log.info("Archived %s -> %s", merged.name, dst)
            except Exception as e:
                log.warning("Failed to archive %s: %s", std_name, e)
