"""
Base Forcing Processor Abstract Class

Defines the interface for all forcing data processors (atmospheric, ocean,
river, tidal). Model-specific implementations handle data format differences.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class ForcingResult:
    """
    Result of a forcing processing operation.

    Attributes:
        success: Whether processing completed successfully
        source: Name of the data source (e.g., "GFS", "RTOFS", "NWM")
        output_files: List of generated output files
        errors: List of error messages if failed
        warnings: List of warning messages
        metadata: Additional processing metadata
    """
    success: bool
    source: str
    output_files: List[Path] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Allow using result in boolean context."""
        return self.success


class BaseForcingProcessor(ABC):
    """
    Abstract base class for forcing data processors.

    Each forcing type (atmospheric, ocean, river, tidal) has a processor
    that handles data discovery, validation, processing, and output generation.

    Attributes:
        config: OFS configuration object
        grid: Model grid handler
        enabled: Whether this forcing type is enabled
        source_name: Name of the data source
    """

    # To be set by subclasses
    source_name: str = "Unknown"
    forcing_type: str = "unknown"  # "atmospheric", "ocean", "river", "tidal"

    def __init__(
        self,
        config: 'OFSConfig',
        grid: 'BaseGrid' = None,
        input_path: Path = None,
        output_path: Path = None,
        enabled: bool = True,
    ):
        """
        Initialize the forcing processor.

        Args:
            config: OFS configuration object
            grid: Model grid handler (optional, some processors don't need it)
            input_path: Override input data path
            output_path: Override output path
            enabled: Whether this processor is enabled
        """
        self.config = config
        self.grid = grid
        self.input_path = input_path or self._default_input_path()
        self.output_path = output_path or self._default_output_path()
        self.enabled = enabled

    def _default_input_path(self) -> Path:
        """Return default input path based on config."""
        return Path(getattr(self.config, f"COMIN{self.source_name.lower()}", "/tmp"))

    def _default_output_path(self) -> Path:
        """Return default output path based on config."""
        return Path(self.config.COMOUTrerun)

    @abstractmethod
    def process(self) -> ForcingResult:
        """
        Process forcing data and generate output files.

        This is the main entry point for forcing processing.

        Returns:
            ForcingResult with status and output files
        """
        pass

    @abstractmethod
    def find_input_files(self) -> List[Path]:
        """
        Find and validate input data files.

        Returns:
            List of input file paths
        """
        pass

    def validate_inputs(self) -> bool:
        """
        Validate that required input files exist.

        Returns:
            True if inputs are valid
        """
        files = self.find_input_files()
        return len(files) > 0

    def get_time_range(self) -> tuple:
        """
        Get the time range for forcing data.

        Returns:
            Tuple of (start_datetime, end_datetime)
        """
        pdy = self.config.PDY
        cyc = self.config.cyc

        start = datetime.strptime(f"{pdy}{cyc:02d}", "%Y%m%d%H")

        # Default: 6-hour hindcast + 5.25 day forecast
        from datetime import timedelta
        end = start + timedelta(days=5.5)

        return start, end

    def get_output_filename(self, base_name: str, extension: str = "nc") -> str:
        """
        Generate standardized output filename.

        Format: {RUN}.{cycle}.{base_name}.{extension}
        Example: stofs_3d_atl.t12z.gfs.air.nc

        Args:
            base_name: Base name for the file
            extension: File extension (default: nc)

        Returns:
            Formatted filename string
        """
        return f"{self.config.RUN}.{self.config.cycle}.{base_name}.{extension}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source={self.source_name}, enabled={self.enabled})"


class AtmosphericProcessor(BaseForcingProcessor):
    """Base class for atmospheric forcing processors (GFS, HRRR, NAM)."""
    forcing_type = "atmospheric"


class OceanProcessor(BaseForcingProcessor):
    """Base class for ocean boundary condition processors (RTOFS, NCOM)."""
    forcing_type = "ocean"


class RiverProcessor(BaseForcingProcessor):
    """Base class for river forcing processors (NWM, USGS)."""
    forcing_type = "river"


class TidalProcessor(BaseForcingProcessor):
    """Base class for tidal forcing processors."""
    forcing_type = "tidal"
