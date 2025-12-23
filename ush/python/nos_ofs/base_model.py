"""
Base Model Abstract Class

Defines the interface that all hydrodynamic model implementations must follow.
This enables unified workflow execution across SCHISM, FVCOM, and ROMS models.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

from .base_forcing import BaseForcingProcessor, ForcingResult


class ModelType(Enum):
    """Supported hydrodynamic model types."""
    SCHISM = "schism"
    FVCOM = "fvcom"
    ROMS = "roms"


class GridType(Enum):
    """Grid structure types."""
    STRUCTURED = "structured"        # ROMS (curvilinear)
    UNSTRUCTURED = "unstructured"    # SCHISM, FVCOM (triangular/hybrid)


@dataclass
class ModelCapabilities:
    """
    Defines what capabilities each model implementation supports.

    Attributes:
        grid_type: Type of computational grid
        supports_nwm: Whether NWM river forcing is supported
        supports_da: Whether data assimilation is supported
        supports_nesting: Whether nested model configurations are supported
        vertical_coords: Type of vertical coordinate system
        native_output_format: Output file format (netCDF, binary, etc.)
    """
    grid_type: GridType
    supports_nwm: bool = False
    supports_da: bool = False
    supports_nesting: bool = False
    vertical_coords: str = "sigma"  # "sigma", "z-sigma", "generalized"
    native_output_format: str = "netcdf"


@dataclass
class ModelResult:
    """Result of a model operation."""
    success: bool
    stage: str
    message: str = ""
    output_files: List[Path] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseModel(ABC):
    """
    Abstract base class for all hydrodynamic models.

    All model implementations (SCHISM, FVCOM, ROMS) must inherit from this
    class and implement the required abstract methods.

    Attributes:
        config: OFS configuration object
        grid: Model grid handler
        forcing_processors: Dictionary of forcing processors by type
    """

    # Class attributes to be defined by subclasses
    model_type: ModelType
    capabilities: ModelCapabilities

    def __init__(self, config: 'OFSConfig'):
        """
        Initialize the model.

        Args:
            config: OFS configuration object
        """
        self.config = config
        self.grid = self._init_grid()
        self.forcing_processors = self._init_forcing()

    @abstractmethod
    def _init_grid(self) -> 'BaseGrid':
        """
        Initialize the model-specific grid handler.

        Returns:
            Grid handler instance for this model type
        """
        pass

    @abstractmethod
    def _init_forcing(self) -> Dict[str, BaseForcingProcessor]:
        """
        Initialize forcing processors for this model.

        Returns:
            Dictionary mapping forcing type names to processor instances
        """
        pass

    @abstractmethod
    def generate_control_file(self, output_path: Path) -> Path:
        """
        Generate the model control file.

        For SCHISM: param.nml
        For FVCOM: run_control.nml
        For ROMS: ROMS.in

        Args:
            output_path: Directory to write control file

        Returns:
            Path to generated control file
        """
        pass

    @abstractmethod
    def run_model(self, stage: str, nprocs: int = None) -> ModelResult:
        """
        Execute the model for a given stage.

        Args:
            stage: Workflow stage (nowcast, forecast, etc.)
            nprocs: Number of MPI processes (uses config default if None)

        Returns:
            ModelResult with execution status
        """
        pass

    # Common methods with default implementations

    def prep_nowcast(self) -> Dict[str, ForcingResult]:
        """
        Run preprocessing for nowcast stage.

        Processes all enabled forcing types (atmospheric, ocean, river, tidal).

        Returns:
            Dictionary mapping forcing type to processing result
        """
        results = {}
        for name, processor in self.forcing_processors.items():
            if processor.enabled:
                results[name] = processor.process()
        return results

    def prep_forecast(self) -> Dict[str, ForcingResult]:
        """
        Run preprocessing for forecast stage.

        Default implementation calls prep_nowcast. Override if forecast
        requires different processing.

        Returns:
            Dictionary mapping forcing type to processing result
        """
        return self.prep_nowcast()

    def run_nowcast(self) -> ModelResult:
        """Run the nowcast stage."""
        return self.run_model("nowcast")

    def run_forecast(self) -> ModelResult:
        """Run the forecast stage."""
        return self.run_model("forecast")

    def validate_inputs(self) -> bool:
        """
        Validate that all required input files exist.

        Returns:
            True if all inputs are valid
        """
        # Check grid files
        if not self.grid.validate():
            return False

        # Check forcing inputs
        for name, processor in self.forcing_processors.items():
            if processor.enabled and not processor.validate_inputs():
                return False

        return True

    def get_output_files(self, stage: str) -> List[Path]:
        """
        Get list of expected output files for a stage.

        Args:
            stage: Workflow stage

        Returns:
            List of expected output file paths
        """
        output_dir = Path(self.config.COMOUT) / stage
        return list(output_dir.glob("*.nc"))

    @property
    def ofs_name(self) -> str:
        """Return the OFS system name (e.g., 'stofs_3d_atl', 'cbofs')."""
        return self.config.RUN

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(ofs={self.ofs_name}, type={self.model_type.value})"
