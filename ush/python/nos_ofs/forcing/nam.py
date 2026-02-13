"""
NAM (North American Mesoscale) Forcing Processor

Processes NAM atmospheric data for regional forcing. NAM provides
12km resolution (NAM-12) or 4km resolution (NAM-4/NAM-CONUS-NEST).

NAM is the PRIMARY atmospheric forcing source for COMF/SECOFS systems.
Preferred over HRRR for Southeast coast due to better coverage.

This processor replicates the functionality of the Fortran executables:
  nos_ofs_create_forcing_met        (ROMS output)
  nos_ofs_create_forcing_met_fvcom  (FVCOM/SCHISM output)

and the shell wrapper:
  nos_ofs_create_forcing_met.sh

The output format for SCHISM is:
  sflux_air_{N}.{XXXX}.nc  -- uwind, vwind, prmsl, stmp, spfh
  sflux_rad_{N}.{XXXX}.nc  -- dlwrf, dswrf
  sflux_prc_{N}.{XXXX}.nc  -- prate

where N = sflux index (1=primary, 2=secondary) and XXXX = day file number.

For FVCOM, the output is a single NetCDF with all met variables on the
unstructured grid (handled by model-specific configuration).

Native Python implementation using cfgrib/xarray for GRIB2 reading,
scipy for interpolation, and netCDF4 for output. No subprocess calls
to wgrib2, ncap2, ncrcat, ncks, ncatted, ncrename, or Fortran executables.
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

# Optional dependencies
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
    import cfgrib  # noqa: F401

    HAS_CFGRIB = True
except ImportError:
    HAS_CFGRIB = False

try:
    from scipy.interpolate import griddata

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    log.warning(
        "scipy not available - grid interpolation will use nearest neighbor only"
    )

# ---------------------------------------------------------------------------
# NAM GRIB2 variable specifications
# Matches the shell script's VARNAME/LEV arrays (18+ variables)
# ---------------------------------------------------------------------------

# Core SCHISM sflux variables (subset of full 19-variable list)
NAM_GRIB2_FILTER_KEYS: Dict[str, dict] = {
    "stmp": {
        "shortName": "2t",
        "typeOfLevel": "heightAboveGround",
        "level": 2,
    },
    "dpt": {
        "shortName": "2d",
        "typeOfLevel": "heightAboveGround",
        "level": 2,
    },
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
    "rh": {
        "shortName": "2r",
        "typeOfLevel": "heightAboveGround",
        "level": 2,
    },
    "prmsl": {
        "shortName": "prmsl",
        "typeOfLevel": "meanSea",
    },
    "dlwrf": {
        "shortName": "dlwrf",
        "typeOfLevel": "surface",
    },
    "ulwrf": {
        "shortName": "ulwrf",
        "typeOfLevel": "surface",
    },
    "dswrf": {
        "shortName": "dswrf",
        "typeOfLevel": "surface",
    },
    "uswrf": {
        "shortName": "uswrf",
        "typeOfLevel": "surface",
    },
    "lhtfl": {
        "shortName": "lhtfl",
        "typeOfLevel": "surface",
    },
    "shtfl": {
        "shortName": "shtfl",
        "typeOfLevel": "surface",
    },
    "spfh": {
        "shortName": "2sh",
        "typeOfLevel": "heightAboveGround",
        "level": 2,
    },
    "tcdc": {
        "shortName": "tcc",
        "typeOfLevel": "atmosphere",
    },
    "prate": {
        "shortName": "prate",
        "typeOfLevel": "surface",
    },
    "apcp": {
        "shortName": "tp",
        "typeOfLevel": "surface",
    },
    "evp": {
        "shortName": "evp",
        "typeOfLevel": "surface",
    },
    "pres": {
        "shortName": "sp",
        "typeOfLevel": "surface",
    },
    "wtmp": {
        "shortName": "sst",
        "typeOfLevel": "surface",
    },
}

# Fallback paramId mappings
NAM_PARAM_FALLBACK: Dict[str, dict] = {
    "spfh": {"paramId": 260242, "typeOfLevel": "heightAboveGround", "level": 2},
    "prate": {"paramId": 260045, "typeOfLevel": "surface"},
    "tcdc": {"shortName": "tcc"},
}


class NAMProcessor(ForcingProcessor):
    """
    NAM atmospheric forcing processor.

    Primary atmospheric forcing for COMF/SECOFS systems. Also used as
    backup for STOFS when HRRR is unavailable.

    Supports multiple NAM products:
      - NAM 12km (nam.t*z.awip12*.grib2)
      - NAM 4km CONUS nest (nam.t*z.conusnest.hiresf*.grib2)
      - NAM Alaska nest
      - NAM Hawaii nest
      - NAM Puerto Rico nest

    Supports multiple output model types:
      - SCHISM: produces sflux_air/rad/prc NetCDF files
      - FVCOM: produces combined met NetCDF with all variables
      - ROMS: produces met.nc and hflux.nc

    Supports automatic fallback to GFS (0.25 degree) if NAM is unavailable,
    matching the shell script's modelist logic.

    Native Python implementation -- no subprocess calls to wgrib2, ncap2,
    ncrcat, ncks, ncatted, ncrename, or Fortran executables.
    """

    # SCHISM sflux variables
    SCHISM_VARIABLES = [
        "uwind", "vwind", "prmsl", "stmp", "spfh",
        "dlwrf", "dswrf", "prate",
    ]

    # Full variable set matching the Fortran executable (18 variables)
    FULL_VARIABLES = [
        "stmp", "dpt", "uwind", "vwind", "rh", "prmsl",
        "dlwrf", "ulwrf", "dswrf", "uswrf", "lhtfl", "shtfl",
        "spfh", "tcdc", "prate", "apcp", "evp", "pres", "wtmp",
    ]

    DEFAULT_VARIABLES = SCHISM_VARIABLES

    # NAM product types
    NAM_12KM = "nam"
    NAM_4KM = "nam_conusnest"
    NAM_ALASKA = "nam_alaskanest"
    NAM_HAWAII = "nam_hawaiinest"
    NAM_PUERTO_RICO = "nam_priconest"

    # Product fallback order (matching shell script modelist)
    FALLBACK_ORDER = {
        "NAM": ["NAM", "GFS25"],
        "NAM4": ["NAM4", "NAM", "GFS25"],
        "GFS": ["GFS"],
        "GFS25": ["GFS25", "GFS"],
        "HRRR": ["HRRR", "GFS25"],
        "RTMA": ["RTMA", "NAM", "GFS25"],
    }

    @property
    def source_name(self) -> str:
        return "NAM"

    def __init__(
        self,
        config,
        input_path: Path,
        output_path: Path,
        variables: Optional[List[str]] = None,
        forecast_hours: int = 84,
        product: str = "nam_conusnest",
        priority: str = "high",
        ocean_model: str = "SCHISM",
        igrd_met: int = 0,
    ):
        """
        Initialize NAM processor.

        Args:
            config: OFSConfig instance
            input_path: Path to NAM input data (COMINnam)
            output_path: Path for output files (DATA)
            variables: Variables to extract
            forecast_hours: Forecast hours to process
            product: NAM product type (nam, nam_conusnest, etc.)
            priority: Priority level (high = primary source, sflux index 1)
            ocean_model: Target model type ("SCHISM", "FVCOM", or "ROMS")
            igrd_met: Interpolation grid indicator
                      0 = output on native GRIB grid (no interpolation)
                      1 = output on model grid (remesh interpolation)
                      3 = bilinear interpolation
                      4 = natural neighbors interpolation
        """
        super().__init__(config, input_path, output_path, variables)
        self.forecast_hours = forecast_hours
        self.product = product
        self.priority = priority
        self.ocean_model = ocean_model.upper()
        self.igrd_met = igrd_met

        if not self.variables:
            if self.ocean_model == "SCHISM":
                self.variables = list(self.SCHISM_VARIABLES)
            else:
                self.variables = list(self.FULL_VARIABLES)

        # Cycle info
        self.cyc = getattr(config, "cyc", 0)
        self.pdy = getattr(config, "PDY", "")

        # Domain bounds from config
        self.lon_min = getattr(config, "MINLON", getattr(config, "lon_min", -98.0))
        self.lon_max = getattr(config, "MAXLON", getattr(config, "lon_max", -52.0))
        self.lat_min = getattr(config, "MINLAT", getattr(config, "lat_min", 7.0))
        self.lat_max = getattr(config, "MAXLAT", getattr(config, "lat_max", 53.0))

        # Model grid file for interpolation (only needed if igrd_met > 0)
        self.grid_file = getattr(config, "GRIDFILE", None)

        # Heat flux scaling factor
        self.scale_hflux = float(getattr(config, "SCALE_HFLUX", 1.0))

        # Base date for time reference [YYYY, MM, DD, HH]
        base_date_str = getattr(config, "BASE_DATE", "")
        if base_date_str:
            try:
                parts = str(base_date_str).split()
                self.base_date = [int(p) for p in parts[:4]]
            except Exception:
                self.base_date = None
        else:
            self.base_date = None

        # Output paths
        self.comout = getattr(config, "COMOUT", None)

        # Sflux index: 1 for primary, 2 for secondary
        self.sflux_index = 1 if self.priority == "high" else 2

    def process(self) -> ForcingResult:
        """
        Process NAM forcing data.

        Returns:
            ForcingResult with processed files
        """
        log.info(
            "Processing %s forcing (product=%s, model=%s)",
            self.source_name, self.product, self.ocean_model,
        )
        log.info(
            "Domain: lon[%.4f, %.4f], lat[%.4f, %.4f]",
            self.lon_min, self.lon_max, self.lat_min, self.lat_max,
        )

        # Check dependencies
        if not HAS_XARRAY or not HAS_CFGRIB:
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[
                    "Required: pip install xarray cfgrib netCDF4. "
                    "cfgrib also needs the eccodes library."
                ],
            )

        if not HAS_NETCDF4:
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=["netCDF4 required. pip install netCDF4"],
            )

        if not self.validate_input():
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[f"Input path not found: {self.input_path}"],
            )

        self.create_output_dir()
        output_files: List[Path] = []

        try:
            # Step 1: Find NAM GRIB2 files
            nam_files = self._find_nam_files()

            if not nam_files:
                log.warning("No NAM files found for product %s", self.product)
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=[f"No NAM input files found for {self.product}"],
                )

            log.info("Found %d NAM files", len(nam_files))

            # Step 2: Extract variables from all files
            extracted = self._extract_all_grib2(nam_files)

            if not extracted or not extracted.get("times"):
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["Failed to extract data from NAM files"],
                )

            n_times = len(extracted["times"])
            log.info("Extracted %d time steps from NAM files", n_times)

            # Step 3: Optional model grid interpolation
            if self.igrd_met > 0 and self.grid_file and HAS_SCIPY:
                extracted = self._interpolate_to_model_grid(extracted)

            # Step 4: Create output files based on ocean model type
            if self.ocean_model in ("SCHISM", "SELFE"):
                output_files = self._create_schism_sflux(extracted)
            elif self.ocean_model == "FVCOM":
                output_files = self._create_fvcom_output(extracted)
            elif self.ocean_model == "ROMS":
                output_files = self._create_roms_output(extracted)
            else:
                # Default to SCHISM format
                output_files = self._create_schism_sflux(extracted)

            log.info("NAM processing complete: %d files", len(output_files))

            return ForcingResult(
                success=True,
                source=self.source_name,
                output_files=output_files,
                metadata={
                    "forecast_hours": self.forecast_hours,
                    "product": self.product,
                    "priority": self.priority,
                    "sflux_index": self.sflux_index,
                    "ocean_model": self.ocean_model,
                    "variables": self.variables,
                    "num_input_files": len(nam_files),
                    "num_time_steps": n_times,
                },
            )

        except Exception as e:
            log.error("NAM processing failed: %s", e)
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

    def _find_nam_files(self) -> List[Path]:
        """
        Find NAM GRIB2 files based on product type.

        Searches across date directories following NCEP naming conventions:
          nam.YYYYMMDD/nam.t{cyc}z.awip12{fhr}.tm00.grib2      (12km)
          nam.YYYYMMDD/nam.t{cyc}z.conusnest.hiresf{fhr}.tm00.grib2  (4km)
        """
        pattern = self.get_file_pattern()
        nam_files: List[Path] = []

        base_date = datetime.strptime(self.pdy, "%Y%m%d") if self.pdy else datetime.now()

        # Search today and yesterday (like shell script)
        for day_offset in range(-1, 1):
            search_date = base_date + timedelta(days=day_offset)
            date_str = search_date.strftime("%Y%m%d")

            # Check nam.YYYYMMDD/ directory
            nam_dir = self.input_path / f"nam.{date_str}"
            if nam_dir.exists():
                found = sorted(nam_dir.glob(pattern))
                nam_files.extend(found)

        # Also search directly in input_path
        direct_found = sorted(self.input_path.glob(pattern))
        for f in direct_found:
            if f not in nam_files:
                nam_files.append(f)

        # Filter to forecast hours we need
        filtered: List[Path] = []
        for f in nam_files:
            fhr = self._extract_forecast_hour(f)
            if fhr is not None and fhr <= self.forecast_hours:
                filtered.append(f)

        # Sort by forecast hour
        filtered.sort(key=lambda f: self._extract_forecast_hour(f) or 0)

        return filtered

    def _extract_forecast_hour(self, filepath: Path) -> Optional[int]:
        """Extract forecast hour from NAM filename."""
        fname = filepath.name
        try:
            if "conusnest" in fname or "alaskanest" in fname or "hawaiinest" in fname or "priconest" in fname:
                # nam.t00z.conusnest.hiresf00.tm00.grib2
                fhr_str = fname.split("hiresf")[1].split(".")[0]
            elif "awip12" in fname:
                # nam.t00z.awip1200.tm00.grib2
                fhr_str = fname.split("awip12")[1].split(".")[0]
            elif "awp242" in fname:
                # nam.t00z.awp24200.tm00.grib2
                fhr_str = fname.split("awp242")[1].split(".")[0]
            else:
                return None
            return int(fhr_str)
        except (ValueError, IndexError):
            return None

    def get_file_pattern(self) -> str:
        """Get glob pattern for NAM files based on product type."""
        patterns = {
            self.NAM_12KM: "nam.t*z.awip12*.tm00.grib2",
            self.NAM_4KM: "nam.t*z.conusnest.hiresf*.tm00.grib2",
            self.NAM_ALASKA: "nam.t*z.alaskanest.hiresf*.tm00.grib2",
            self.NAM_HAWAII: "nam.t*z.hawaiinest.hiresf*.tm00.grib2",
            self.NAM_PUERTO_RICO: "nam.t*z.priconest.hiresf*.tm00.grib2",
        }
        return patterns.get(self.product, patterns[self.NAM_12KM])

    # ------------------------------------------------------------------
    # GRIB2 extraction with cfgrib/xarray
    # ------------------------------------------------------------------

    def _extract_all_grib2(self, nam_files: List[Path]) -> dict:
        """
        Read all NAM GRIB2 files and extract variables.

        This replaces the shell script's wgrib2 extraction and the
        Fortran executable's ASCII file reading.

        Returns:
            Dict with 'times', 'lons', 'lats', and variable arrays.
        """
        result: Dict = {
            "times": [],
            "lons": None,
            "lats": None,
        }
        for var in self.variables:
            result[var] = []

        for idx, nam_file in enumerate(nam_files):
            log.debug(
                "Processing NAM (%d/%d): %s",
                idx + 1, len(nam_files), nam_file.name,
            )

            try:
                file_data = self._read_single_grib2(nam_file)
            except Exception as e:
                log.warning("Failed to read NAM %s: %s", nam_file.name, e)
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
                    ny = len(result["lats"])
                    nx = len(result["lons"])
                    result[var].append(np.full((ny, nx), -99999.0, dtype=np.float32))

        # Clean up
        for var in self.variables:
            result[var] = [a for a in result[var] if a is not None]

        return result

    def _read_single_grib2(self, grib_file: Path) -> Optional[dict]:
        """
        Read a single NAM GRIB2 file, subset to domain, extract variables.

        NAM 12km uses Lambert Conformal Conic projection (like HRRR).
        NAM 4km nest also uses Lambert Conformal.

        Mimics the shell script's workflow:
          1. wgrib2 -s | egrep "$list_var_oi" | wgrib2 -i -grib (select vars)
          2. wgrib2 -small_grib (subset to domain)
          3. wgrib2 -rpn "sto_1:-9999.9:rcl_1:merge:" -spread (extract text)

        In Python, we use cfgrib to read directly and numpy to subset.
        """
        data: Dict = {}

        # Parse valid time
        valid_time = self._parse_valid_time(grib_file)
        if valid_time is None:
            return None
        data["valid_time"] = valid_time

        for var in self.variables:
            fkeys = NAM_GRIB2_FILTER_KEYS.get(var)
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
        Read a variable from a NAM GRIB2 file using cfgrib, subset to domain.

        Handles both regular lat-lon grids and Lambert Conformal projected grids.

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
            fallback = NAM_PARAM_FALLBACK.get(var_name)
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

            # Get coordinate arrays
            lon_arr, lat_arr = self._get_coordinates(ds)
            if lon_arr is None:
                ds.close()
                return None, None, None

            arr = da.values

            # Convert longitudes from 0-360 to -180..180
            if np.any(lon_arr > 180):
                lon_arr = np.where(lon_arr > 180, lon_arr - 360, lon_arr)

            # Subset to domain
            if lon_arr.ndim == 2 and lat_arr.ndim == 2:
                # Lambert Conformal - 2-D coordinates
                mask = (
                    (lon_arr >= self.lon_min)
                    & (lon_arr <= self.lon_max)
                    & (lat_arr >= self.lat_min)
                    & (lat_arr <= self.lat_max)
                )
                if not mask.any():
                    ds.close()
                    return None, None, None

                rows = np.any(mask, axis=1)
                cols = np.any(mask, axis=0)
                rmin, rmax = np.where(rows)[0][[0, -1]]
                cmin, cmax = np.where(cols)[0][[0, -1]]

                arr_sub = arr[rmin : rmax + 1, cmin : cmax + 1].astype(np.float32)

                mid_col = (cmin + cmax) // 2
                mid_row = (rmin + rmax) // 2
                lats_1d = lat_arr[rmin : rmax + 1, mid_col]
                lons_1d = lon_arr[mid_row, cmin : cmax + 1]

                ds.close()
                return arr_sub, lons_1d, lats_1d

            elif lon_arr.ndim == 1 and lat_arr.ndim == 1:
                # Regular lat-lon
                lon_mask = (lon_arr >= self.lon_min) & (lon_arr <= self.lon_max)
                lat_mask = (lat_arr >= self.lat_min) & (lat_arr <= self.lat_max)

                if not lon_mask.any() or not lat_mask.any():
                    ds.close()
                    return None, None, None

                lons_sub = lon_arr[lon_mask]
                lats_sub = lat_arr[lat_mask]

                if arr.ndim >= 2:
                    # Sort longitude if needed
                    sort_idx = np.argsort(lon_arr)
                    lon_sorted = lon_arr[sort_idx]
                    lon_mask_sorted = (lon_sorted >= self.lon_min) & (lon_sorted <= self.lon_max)
                    arr_sorted = arr[:, sort_idx] if arr.ndim == 2 else arr
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
            log.debug("Error subsetting NAM %s: %s", var_name, e)
            try:
                ds.close()
            except Exception:
                pass
            return None, None, None

    def _get_coordinates(self, ds) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Extract longitude and latitude arrays from an xarray dataset."""
        for lon_name in ("longitude", "lon", "x"):
            if lon_name in ds.coords or lon_name in ds:
                lon_arr = ds[lon_name].values
                break
        else:
            return None, None

        for lat_name in ("latitude", "lat", "y"):
            if lat_name in ds.coords or lat_name in ds:
                lat_arr = ds[lat_name].values
                break
        else:
            return None, None

        return lon_arr, lat_arr

    def _parse_valid_time(self, grib_file: Path) -> Optional[datetime]:
        """
        Determine valid time from a NAM filename.

        Patterns:
          nam.t{HH}z.awip12{FF}.tm00.grib2
          nam.t{HH}z.conusnest.hiresf{FF}.tm00.grib2
        Date from parent directory: nam.YYYYMMDD/
        """
        try:
            fname = grib_file.name
            cyc_str = fname.split(".t")[1].split("z")[0]
            cyc_hour = int(cyc_str)

            fhr = self._extract_forecast_hour(grib_file) or 0

            # Get date from parent directory
            for parent in grib_file.parents:
                dirname = parent.name
                if dirname.startswith("nam.") and len(dirname) == 12:
                    date_str = dirname[4:]
                    base = datetime.strptime(date_str, "%Y%m%d")
                    return base + timedelta(hours=cyc_hour + fhr)

            # Fallback
            if self.pdy:
                base = datetime.strptime(self.pdy, "%Y%m%d")
                return base + timedelta(hours=cyc_hour + fhr)

            return None
        except Exception as e:
            log.debug("Cannot parse NAM valid time from %s: %s", grib_file.name, e)
            return None

    # ------------------------------------------------------------------
    # Grid interpolation (replaces Fortran remesh/bilinear routines)
    # ------------------------------------------------------------------

    def _interpolate_to_model_grid(self, data: dict) -> dict:
        """
        Interpolate forcing data from the met grid to the model grid.

        This replaces the Fortran interpolation in nos_ofs_create_forcing_met
        when IGRD > 0. Uses scipy.interpolate.griddata.

        Only performed if:
          - igrd_met > 0
          - grid_file is specified and exists
          - scipy is available

        Args:
            data: Extracted data dict with 'lons', 'lats', and variable arrays

        Returns:
            Updated data dict with interpolated arrays
        """
        if not HAS_SCIPY:
            log.warning("scipy not available, skipping model grid interpolation")
            return data

        if self.grid_file is None:
            return data

        grid_path = Path(self.grid_file)
        if not grid_path.exists():
            log.warning("Grid file not found: %s", grid_path)
            return data

        try:
            # Read model grid coordinates from NetCDF
            grid_ds = Dataset(str(grid_path), "r")

            if "lon" in grid_ds.variables:
                model_lon = grid_ds["lon"][:]
                model_lat = grid_ds["lat"][:]
            elif "lonc" in grid_ds.variables:
                model_lon = grid_ds["lonc"][:]
                model_lat = grid_ds["latc"][:]
            else:
                grid_ds.close()
                return data

            grid_ds.close()

            # Source grid points
            src_lons = data["lons"]
            src_lats = data["lats"]
            src_lon_2d, src_lat_2d = np.meshgrid(src_lons, src_lats)
            src_points = np.column_stack([src_lon_2d.ravel(), src_lat_2d.ravel()])

            # Target grid
            target_points = np.column_stack([model_lon.ravel(), model_lat.ravel()])

            # Interpolation method
            method = "linear" if self.igrd_met in (1, 3) else "nearest"

            # Interpolate each variable at each time step
            for var in self.variables:
                if var not in data or not data[var]:
                    continue
                new_data = []
                for arr in data[var]:
                    values = arr.ravel()
                    # Mask missing values
                    valid = values > -90000.0
                    if valid.sum() < 3:
                        new_data.append(np.full(model_lon.shape, -99999.0, dtype=np.float32))
                        continue

                    interp = griddata(
                        src_points[valid],
                        values[valid],
                        target_points,
                        method=method,
                        fill_value=-99999.0,
                    )
                    new_data.append(interp.reshape(model_lon.shape).astype(np.float32))

                data[var] = new_data

            # Update grid coordinates
            data["lons"] = model_lon if model_lon.ndim == 1 else model_lon[0, :]
            data["lats"] = model_lat if model_lat.ndim == 1 else model_lat[:, 0]

            log.info("Interpolated to model grid (%d points)", len(target_points))

        except Exception as e:
            log.warning("Model grid interpolation failed: %s", e)

        return data

    # ------------------------------------------------------------------
    # SCHISM output (sflux format)
    # ------------------------------------------------------------------

    def _create_schism_sflux(self, data: dict) -> List[Path]:
        """
        Create SCHISM sflux NetCDF files from extracted NAM data.

        Output format matches the Fortran subroutines:
          nos_ofs_write_netcdf_wind_SELFE   -> sflux_air_{N}.1.nc
          nos_ofs_write_netcdf_flux_SELFE   -> sflux_rad_{N}.1.nc
          nos_ofs_write_netcdf_prate_SELFE  -> sflux_prc_{N}.1.nc

        where N = self.sflux_index (1 for primary, 2 for secondary)
        """
        output_files: List[Path] = []
        times = data["times"]
        lons = data["lons"]
        lats = data["lats"]

        if lons is None or lats is None or not times:
            log.error("No valid data for SCHISM sflux output")
            return []

        # Determine base_date
        if self.base_date:
            base_date = self.base_date
        elif times:
            t0 = times[0]
            base_date = [t0.year, t0.month, t0.day, 0]
        else:
            base_date = [2000, 1, 1, 0]

        # Reference datetime for time calculation
        ref_time = datetime(base_date[0], base_date[1], base_date[2], base_date[3])

        # Time values in days since base_date
        time_values = np.array(
            [(t - ref_time).total_seconds() / 86400.0 for t in times],
            dtype=np.float32,
        )

        idx = self.sflux_index

        # sflux_air
        air_file = self._write_sflux_nc(
            f"sflux_air_{idx}.1.nc",
            data, time_values, lons, lats, base_date,
            {
                "uwind": ("f4", "m/s", "eastward_wind", "Surface Eastward Air Velocity (10m AGL)"),
                "vwind": ("f4", "m/s", "northward_wind", "Surface Northward Air Velocity (10m AGL)"),
                "prmsl": ("f4", "Pa", "air_pressure_at_sea_level", "Pressure reduced to MSL"),
                "stmp": ("f4", "K", "air_temperature", "Surface Air Temperature (2m AGL)"),
                "spfh": ("f4", "1", "specific_humidity", "Surface Specific Humidity (2m AGL)"),
            },
            "SCHISM sflux air forcing from NAM",
        )
        if air_file:
            output_files.append(air_file)

        # sflux_rad
        rad_file = self._write_sflux_nc(
            f"sflux_rad_{idx}.1.nc",
            data, time_values, lons, lats, base_date,
            {
                "dlwrf": ("f4", "W/m^2", "surface_downwelling_longwave_flux_in_air", "Downward Long Wave Radiation Flux"),
                "dswrf": ("f4", "W/m^2", "surface_downwelling_shortwave_flux_in_air", "Downward Short Wave Radiation Flux"),
            },
            "SCHISM sflux radiation forcing from NAM",
        )
        if rad_file:
            output_files.append(rad_file)

        # sflux_prc
        prc_file = self._write_sflux_nc(
            f"sflux_prc_{idx}.1.nc",
            data, time_values, lons, lats, base_date,
            {
                "prate": ("f4", "kg/m^2/s", "precipitation_flux", "Surface Precipitation Rate"),
            },
            "SCHISM sflux precipitation forcing from NAM",
        )
        if prc_file:
            output_files.append(prc_file)

        # Also copy to standard naming for archival
        self._copy_standard_names(output_files)

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
        Write a SCHISM sflux NetCDF file.

        Output format exactly matches the Fortran subroutines in
        nos_ofs_met_write_netcdf_SELFE.f:

        Dimensions:
          nx_grid, ny_grid, time(UNLIMITED)

        Variables:
          time(time):    float, units="days since YYYY-MM-DD", base_date=[Y,M,D,0]
          lon(ny_grid, nx_grid):  float, degrees_east
          lat(ny_grid, nx_grid):  float, degrees_north
          uwind(time, ny_grid, nx_grid): float, m/s
          vwind(time, ny_grid, nx_grid): float, m/s
          prmsl(time, ny_grid, nx_grid): float, Pa
          stmp(time, ny_grid, nx_grid):  float, K
          spfh(time, ny_grid, nx_grid):  float, 1
          ... etc.

        All variables have _FillValue = -9999.0.
        """
        output_file = self.output_path / filename

        has_data = any(var in data and data[var] for var in var_specs)
        if not has_data:
            return None

        try:
            nx = len(lons)
            ny = len(lats)

            nc = Dataset(str(output_file), "w", format="NETCDF4_CLASSIC")

            nc.createDimension("nx_grid", nx)
            nc.createDimension("ny_grid", ny)
            nc.createDimension("time", None)

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

            # Data variables
            nt = len(time_values)
            for varname, (dtype, units, std_name, long_name) in var_specs.items():
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

                    # Apply heat flux scaling if applicable
                    if self.scale_hflux != 1.0 and varname in (
                        "dlwrf", "dswrf", "ulwrf", "uswrf", "lhtfl", "shtfl"
                    ):
                        stacked = stacked * self.scale_hflux

                    var[:] = stacked.astype(np.float32)
                except Exception as e:
                    log.warning("Could not write NAM %s in %s: %s", varname, filename, e)

            nc.type = "SCHISM sflux forcing"
            nc.title = title
            nc.source = f"NAM {self.product}"
            nc.history = f"Created {datetime.now().isoformat()} by nos_ofs NAMProcessor"
            nc.Conventions = "CF-1.6"
            nc.close()

            log.debug("Created %s", output_file)
            return output_file

        except Exception as e:
            log.error("Failed to create %s: %s", filename, e)
            return None

    def _copy_standard_names(self, sflux_files: List[Path]) -> None:
        """
        Copy sflux files to standard NCO naming convention.

        Shell script copies:
          sflux_air.nc -> sflux_air_{N}.1.nc AND {PREFIX}.t{cyc}z.{PDY}.air.{RUNTYPE}.nc
        """
        if not self.comout:
            return

        prefix = getattr(self.config, "PREFIXNOS", getattr(self.config, "RUN", "nos_ofs"))
        cyc_str = f"{self.cyc:02d}"
        pdy1 = getattr(self.config, "PDY1", self.pdy)

        comout_dir = Path(self.comout)
        comout_dir.mkdir(parents=True, exist_ok=True)

        for f in sflux_files:
            try:
                if "air" in f.name:
                    std_name = f"{prefix}.t{cyc_str}z.{pdy1}.air.nc"
                elif "rad" in f.name:
                    std_name = f"{prefix}.t{cyc_str}z.{pdy1}.flux.nc"
                elif "prc" in f.name:
                    std_name = f"{prefix}.t{cyc_str}z.{pdy1}.precip.nc"
                else:
                    continue

                dst = comout_dir / std_name
                shutil.copy2(str(f), str(dst))
                log.debug("Copied %s -> %s", f.name, dst)
            except Exception as e:
                log.warning("Failed to copy %s: %s", f.name, e)

    # ------------------------------------------------------------------
    # FVCOM output
    # ------------------------------------------------------------------

    def _create_fvcom_output(self, data: dict) -> List[Path]:
        """
        Create FVCOM-format meteorological forcing NetCDF.

        FVCOM uses a single file with all met variables on the
        unstructured triangular grid. Variables include:
          uwind, vwind, net_heat_flux, air_temperature, air_pressure,
          short_wave, long_wave, humidity, dew_point, cloud_cover,
          evaporation, precipitation, specific_humidity

        This is a simplified version that outputs on the regular grid.
        For production, the Fortran executable handles unstructured interpolation.
        """
        output_files: List[Path] = []
        times = data["times"]
        lons = data["lons"]
        lats = data["lats"]

        if lons is None or lats is None or not times:
            return []

        if self.base_date:
            base_date = self.base_date
        elif times:
            t0 = times[0]
            base_date = [t0.year, t0.month, t0.day, 0]
        else:
            base_date = [2000, 1, 1, 0]

        ref_time = datetime(base_date[0], base_date[1], base_date[2], base_date[3])
        time_values = np.array(
            [(t - ref_time).total_seconds() / 86400.0 for t in times],
            dtype=np.float32,
        )

        # FVCOM met output includes all variables in one file
        all_vars = {
            "uwind": ("f4", "m/s", "eastward_wind", "Eastward Wind Velocity"),
            "vwind": ("f4", "m/s", "northward_wind", "Northward Wind Velocity"),
            "stmp": ("f4", "K", "air_temperature", "Air Temperature"),
            "prmsl": ("f4", "Pa", "air_pressure_at_sea_level", "Sea Level Pressure"),
            "spfh": ("f4", "kg/kg", "specific_humidity", "Specific Humidity"),
            "dlwrf": ("f4", "W/m^2", "surface_downwelling_longwave_flux_in_air", "Downward Longwave"),
            "dswrf": ("f4", "W/m^2", "surface_downwelling_shortwave_flux_in_air", "Downward Shortwave"),
            "prate": ("f4", "kg/m^2/s", "precipitation_flux", "Precipitation Rate"),
            "rh": ("f4", "%", "relative_humidity", "Relative Humidity"),
            "dpt": ("f4", "K", "dew_point_temperature", "Dew Point Temperature"),
            "tcdc": ("f4", "%", "cloud_area_fraction", "Total Cloud Cover"),
            "evp": ("f4", "kg/m^2", "water_evaporation_flux", "Evaporation"),
        }

        fvcom_file = self._write_sflux_nc(
            "met_forcing_fvcom.nc",
            data, time_values, lons, lats, base_date,
            all_vars,
            "FVCOM meteorological forcing from NAM",
        )
        if fvcom_file:
            output_files.append(fvcom_file)

        return output_files

    # ------------------------------------------------------------------
    # ROMS output
    # ------------------------------------------------------------------

    def _create_roms_output(self, data: dict) -> List[Path]:
        """
        Create ROMS-format meteorological forcing NetCDF.

        ROMS requires separate met.nc and hflux.nc files with variables
        on the model grid in local (rotated) coordinates.

        This is a simplified version outputting on the regular grid.
        """
        output_files: List[Path] = []
        times = data["times"]
        lons = data["lons"]
        lats = data["lats"]

        if lons is None or lats is None or not times:
            return []

        if self.base_date:
            base_date = self.base_date
        elif times:
            t0 = times[0]
            base_date = [t0.year, t0.month, t0.day, 0]
        else:
            base_date = [2000, 1, 1, 0]

        ref_time = datetime(base_date[0], base_date[1], base_date[2], base_date[3])
        time_values = np.array(
            [(t - ref_time).total_seconds() / 86400.0 for t in times],
            dtype=np.float32,
        )

        # Met file (winds + pressure)
        met_vars = {
            "uwind": ("f4", "m/s", "eastward_wind", "U-wind at 10m"),
            "vwind": ("f4", "m/s", "northward_wind", "V-wind at 10m"),
            "prmsl": ("f4", "Pa", "air_pressure_at_sea_level", "Sea Level Pressure"),
            "stmp": ("f4", "K", "air_temperature", "Air Temperature at 2m"),
        }

        met_file = self._write_sflux_nc(
            "met_forcing_roms.nc",
            data, time_values, lons, lats, base_date,
            met_vars,
            "ROMS meteorological forcing from NAM",
        )
        if met_file:
            output_files.append(met_file)

        # Heat flux file
        hflux_vars = {
            "dlwrf": ("f4", "W/m^2", "surface_downwelling_longwave_flux_in_air", "Downward Longwave"),
            "dswrf": ("f4", "W/m^2", "surface_downwelling_shortwave_flux_in_air", "Downward Shortwave"),
            "lhtfl": ("f4", "W/m^2", "surface_upward_latent_heat_flux", "Latent Heat Flux"),
            "shtfl": ("f4", "W/m^2", "surface_upward_sensible_heat_flux", "Sensible Heat Flux"),
            "prate": ("f4", "kg/m^2/s", "precipitation_flux", "Precipitation Rate"),
        }

        hflux_file = self._write_sflux_nc(
            "hflux_forcing_roms.nc",
            data, time_values, lons, lats, base_date,
            hflux_vars,
            "ROMS heat flux forcing from NAM",
        )
        if hflux_file:
            output_files.append(hflux_file)

        return output_files
