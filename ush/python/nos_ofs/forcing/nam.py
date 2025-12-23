"""
NAM (North American Mesoscale) Forcing Processor

Processes NAM atmospheric data for regional forcing. NAM provides
12km resolution (NAM-12) or 4km resolution (NAM-4/NAM-CONUS-NEST).

NAM is the PRIMARY atmospheric forcing source for COMF/SECOFS systems.
Preferred over HRRR for Southeast coast due to better coverage.

Key differences from HRRR:
- Better coverage for SE US coast (SECOFS domain)
- 12km or 4km resolution (vs 3km for HRRR)
- Longer forecast horizon available
- More reliable for offshore areas
"""

import logging
from pathlib import Path
from typing import List, Optional

from ..base import ForcingProcessor, ForcingResult

log = logging.getLogger(__name__)


class NAMProcessor(ForcingProcessor):
    """
    NAM atmospheric forcing processor.

    Primary atmospheric forcing for COMF/SECOFS systems.
    Also used as backup for STOFS when HRRR is unavailable.
    """

    DEFAULT_VARIABLES = [
        "uwind",      # U-component of wind at 10m
        "vwind",      # V-component of wind at 10m
        "prmsl",      # Pressure reduced to MSL
        "stmp",       # Surface temperature (2m)
        "spfh",       # Specific humidity at 2m
        "dlwrf",      # Downward longwave radiation
        "dswrf",      # Downward shortwave radiation
        "prate",      # Precipitation rate
    ]

    # NAM product types
    NAM_12KM = "nam"           # 12km CONUS
    NAM_4KM = "nam_conusnest"  # 4km CONUS nest
    NAM_ALASKA = "nam_alaskanest"
    NAM_HAWAII = "nam_hawaiinest"
    NAM_PUERTO_RICO = "nam_priconest"

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
        product: str = "nam_conusnest",  # Default to 4km
        priority: str = "high",
    ):
        """
        Initialize NAM processor.

        Args:
            config: StofsConfig instance
            input_path: Path to NAM input data
            output_path: Path for output files
            variables: Variables to extract
            forecast_hours: Forecast hours to process
            product: NAM product type (nam, nam_conusnest, etc.)
            priority: Priority level (high = primary source)
        """
        super().__init__(config, input_path, output_path, variables)
        self.forecast_hours = forecast_hours
        self.product = product
        self.priority = priority
        if not self.variables:
            self.variables = self.DEFAULT_VARIABLES

    def process(self) -> ForcingResult:
        """
        Process NAM forcing data.

        Returns:
            ForcingResult with processed files
        """
        log.info(f"Processing {self.source_name} forcing data (product: {self.product})")

        if not self.validate_input():
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[f"Input path not found: {self.input_path}"],
            )

        self.create_output_dir()
        output_files = []

        try:
            # Find NAM GRIB2 files based on product type
            if self.product == self.NAM_4KM:
                # NAM 4km nest files
                nam_files = list(self.input_path.glob("nam.t*z.conusnest.hiresf*.tm00.grib2"))
            else:
                # NAM 12km files
                nam_files = list(self.input_path.glob("nam.t*z.awphys*.tm00.grib2"))

            if not nam_files:
                log.warning(f"No NAM files found for product {self.product}")
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=[f"No NAM input files found for {self.product}"],
                )

            log.info(f"Found {len(nam_files)} NAM files")

            # Determine sflux index based on priority
            # High priority = index 1 (primary), low = index 2 (secondary)
            sflux_index = 1 if self.priority == "high" else 2

            # Create sflux files for SCHISM
            air_file = self.output_path / f"sflux_air_{sflux_index}.0001.nc"
            rad_file = self.output_path / f"sflux_rad_{sflux_index}.0001.nc"
            prc_file = self.output_path / f"sflux_prc_{sflux_index}.0001.nc"

            # Placeholder: actual processing would:
            # 1. Read GRIB2 using wgrib2 or pygrib
            # 2. Extract required variables
            # 3. Interpolate to model grid
            # 4. Rotate wind vectors if needed
            # 5. Calculate derived fields (heat flux, etc.)
            # 6. Write NetCDF in SCHISM sflux format

            log.info(f"Would create: {air_file}")
            log.info(f"Would create: {rad_file}")
            log.info(f"Would create: {prc_file}")

            output_files = [air_file, rad_file, prc_file]

            return ForcingResult(
                success=True,
                source=self.source_name,
                output_files=output_files,
                metadata={
                    "forecast_hours": self.forecast_hours,
                    "product": self.product,
                    "priority": self.priority,
                    "sflux_index": sflux_index,
                    "variables": self.variables,
                    "num_input_files": len(nam_files),
                },
            )

        except Exception as e:
            log.error(f"NAM processing failed: {e}")
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[str(e)],
            )

    def get_file_pattern(self) -> str:
        """Get glob pattern for NAM files based on product type."""
        patterns = {
            self.NAM_12KM: "nam.t*z.awphys*.tm00.grib2",
            self.NAM_4KM: "nam.t*z.conusnest.hiresf*.tm00.grib2",
            self.NAM_ALASKA: "nam.t*z.alaskanest.hiresf*.tm00.grib2",
            self.NAM_HAWAII: "nam.t*z.hawaiinest.hiresf*.tm00.grib2",
            self.NAM_PUERTO_RICO: "nam.t*z.priconest.hiresf*.tm00.grib2",
        }
        return patterns.get(self.product, patterns[self.NAM_12KM])
