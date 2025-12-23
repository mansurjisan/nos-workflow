"""
SCHISM Model Implementation

Provides a unified interface for SCHISM-based OFS systems:
- STOFS-3D-Atlantic
- STOFS-3D-Pacific
- SECOFS
- CREOFS

This implementation uses the forcing processors and workflow code
directly from within the nos_ofs package.
"""

from pathlib import Path
from typing import Dict

from ..base_model import (
    BaseModel,
    ModelType,
    ModelCapabilities,
    GridType,
    ModelResult,
)
from ..base_forcing import BaseForcingProcessor
from ..config import OFSConfig

from .grid import SCHISMGrid
from .schism_config import StofsConfig

# Import forcing processors from local package (not external schism_workflow)
from .forcing import (
    ForcingResult,
    GFSProcessor,
    HRRRProcessor,
    NWMProcessor,
    RTOFSProcessor,
    TidalProcessor,
)

# Import workflow components
from .workflow import SchismModel as SchismWorkflowModel
from .model.param import ParamNmlGenerator


class SCHISMModel(BaseModel):
    """
    SCHISM model implementation.

    Provides the unified BaseModel interface for all SCHISM-based OFS:
    - STOFS-3D-Atlantic
    - STOFS-3D-Pacific
    - SECOFS
    - CREOFS

    Uses the forcing processors and workflow code directly from within
    the nos_ofs package.
    """

    model_type = ModelType.SCHISM

    capabilities = ModelCapabilities(
        grid_type=GridType.UNSTRUCTURED,
        supports_nwm=True,
        supports_da=False,
        supports_nesting=False,
        vertical_coords="generalized",
        native_output_format="netcdf",
    )

    def __init__(self, config: OFSConfig):
        """
        Initialize SCHISM model.

        Args:
            config: OFS configuration
        """
        self.config = config
        self._workflow_model = None
        self._stofs_config = None

        # Initialize grid and forcing
        self.grid = self._init_grid()
        self.forcing_processors = self._init_forcing()

    def _init_grid(self) -> SCHISMGrid:
        """Initialize SCHISM grid handler."""
        return SCHISMGrid(self.config)

    def _init_forcing(self) -> Dict[str, BaseForcingProcessor]:
        """
        Initialize forcing processors.

        Uses the forcing processors directly from nos_ofs.models.schism.forcing.
        """
        processors = {}
        stofs_config = self._get_stofs_config()

        # Get input/output paths
        output_val = getattr(self.config, 'COMOUTrerun', None) or getattr(self.config, 'COMOUT', None) or ""
        output_path = Path(output_val) if output_val else Path("/tmp")

        # Initialize processors based on config
        if getattr(self.config, 'gfs_enabled', True):
            gfs_input = getattr(self.config, 'COMINgfs', '') or ''
            input_path = Path(gfs_input) if gfs_input else Path("/tmp")
            processors['gfs'] = GFSProcessor(
                config=stofs_config,
                input_path=input_path,
                output_path=output_path,
            )

        if getattr(self.config, 'hrrr_enabled', False):
            hrrr_input = getattr(self.config, 'COMINhrrr', '') or ''
            input_path = Path(hrrr_input) if hrrr_input else Path("/tmp")
            processors['hrrr'] = HRRRProcessor(
                config=stofs_config,
                input_path=input_path,
                output_path=output_path,
            )

        if getattr(self.config, 'nwm_enabled', True):
            nwm_input = getattr(self.config, 'COMINnwm', '') or ''
            input_path = Path(nwm_input) if nwm_input else Path("/tmp")
            processors['nwm'] = NWMProcessor(
                config=stofs_config,
                input_path=input_path,
                output_path=output_path,
            )

        if getattr(self.config, 'rtofs_enabled', True):
            rtofs_input = getattr(self.config, 'COMINrtofs', '') or ''
            input_path = Path(rtofs_input) if rtofs_input else Path("/tmp")
            processors['rtofs'] = RTOFSProcessor(
                config=stofs_config,
                input_path=input_path,
                output_path=output_path,
            )

        if getattr(self.config, 'tides_enabled', True):
            processors['tides'] = TidalProcessor(
                config=stofs_config,
                input_path=Path("/tmp"),
                output_path=output_path,
            )

        return processors

    def _get_stofs_config(self) -> StofsConfig:
        """
        Get or create a StofsConfig object.

        Adapts OFSConfig to work with SCHISM workflow code.
        """
        if self._stofs_config is None:
            # Create a StofsConfig-compatible object
            class ConfigAdapter:
                """Adapter to make OFSConfig work with SCHISM workflow."""
                pass

            adapter = ConfigAdapter()

            # Copy all attributes from OFSConfig
            for attr in dir(self.config):
                if not attr.startswith('_'):
                    try:
                        setattr(adapter, attr, getattr(self.config, attr))
                    except (AttributeError, TypeError):
                        pass

            # Add legacy attribute name mappings (OFSConfig -> StofsConfig)
            legacy_mappings = {
                'FIXstofs3d': 'FIXofs',
                'EXECstofs3d': 'EXECofs',
                'HOMEstofs': 'HOMEnos',
            }
            for legacy_name, new_name in legacy_mappings.items():
                if not hasattr(adapter, legacy_name):
                    setattr(adapter, legacy_name, getattr(self.config, new_name, ''))

            # Add any missing expected attributes
            if not hasattr(adapter, 'cycle'):
                adapter.cycle = getattr(self.config, 'cycle', None)

            self._stofs_config = adapter

        return self._stofs_config

    def _get_workflow_model(self) -> SchismWorkflowModel:
        """Get or create the SchismWorkflowModel instance."""
        if self._workflow_model is None:
            self._workflow_model = SchismWorkflowModel(self._get_stofs_config())
        return self._workflow_model

    def generate_control_file(self, output_path: Path) -> Path:
        """
        Generate SCHISM param.nml control file.

        Args:
            output_path: Directory to write param.nml

        Returns:
            Path to generated param.nml
        """
        generator = ParamNmlGenerator(self._get_stofs_config())
        return generator.generate_for_cycle(
            output_path=output_path / "param.nml",
            pdy=self.config.PDY,
            cyc=self.config.cyc,
        )

    def run_model(self, stage: str, nprocs: int = None) -> ModelResult:
        """
        Execute SCHISM model.

        Args:
            stage: Workflow stage (nowcast, forecast, etc.)
            nprocs: Number of MPI processes

        Returns:
            ModelResult with execution status
        """
        workflow = self._get_workflow_model()

        try:
            workflow.run_stage(stage)
            return ModelResult(
                success=True,
                stage=stage,
                message=f"Successfully completed {stage}",
            )
        except Exception as e:
            return ModelResult(
                success=False,
                stage=stage,
                message=str(e),
                errors=[str(e)],
            )

    def prep_nowcast(self) -> Dict[str, ForcingResult]:
        """
        Run preprocessing for nowcast.

        Uses the workflow model to run preprocessing.
        """
        workflow = self._get_workflow_model()

        try:
            workflow.run_stage("prep_nowcast")
            return {"all": ForcingResult(success=True, source="workflow")}
        except Exception as e:
            return {"all": ForcingResult(
                success=False,
                source="workflow",
                errors=[str(e)],
            )}

    def run_nowcast(self) -> ModelResult:
        """Run the nowcast stage."""
        return self.run_model("now_forecast")

    def run_forecast(self) -> ModelResult:
        """Run the forecast stage."""
        return self.run_model("now_forecast")

    def __repr__(self) -> str:
        return f"SCHISMModel(ofs={getattr(self.config, 'RUN', 'unknown')})"
