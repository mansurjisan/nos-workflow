"""
ROMS Model Implementation

Provides a unified interface for ROMS-based OFS systems:
- CBOFS (Chesapeake Bay)
- DBOFS (Delaware Bay)
- TBOFS (Tampa Bay)
- GOMOFS (Gulf of Maine)
- CIOFS (Cook Inlet)
- WCOFS (West Coast)

ROMS uses a structured curvilinear grid with S-coordinate vertical
discretization. The COMF workflow stages are:
    prep -> nowcast -> forecast -> post

This implementation wraps the existing COMF shell scripts
(nos_ofs_nowcast_forecast.sh, nos_ofs_create_forcing_*.sh) via the
orchestration layer while providing a Python-native interface.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List

from ..base_model import (
    BaseModel,
    ModelType,
    ModelCapabilities,
    GridType,
    ModelResult,
)
from ..base_forcing import BaseForcingProcessor, ForcingResult
from ..config import OFSConfig

from .roms_grid import ROMSGrid
from .roms_config import ROMSConfigGenerator

log = logging.getLogger(__name__)


class ROMSModel(BaseModel):
    """
    ROMS model implementation.

    Provides the unified BaseModel interface for all ROMS-based OFS:
    - CBOFS (Chesapeake Bay)
    - DBOFS (Delaware Bay)
    - TBOFS (Tampa Bay)
    - GOMOFS (Gulf of Maine)
    - CIOFS (Cook Inlet)
    - WCOFS (West Coast)

    ROMS-specific characteristics:
    - Structured curvilinear (Arakawa C) grid
    - S-coordinate vertical discretization
    - COARE or bulk flux atmospheric forcing
    - Separate nowcast/forecast model runs with restart file handoff
    """

    model_type = ModelType.ROMS

    capabilities = ModelCapabilities(
        grid_type=GridType.STRUCTURED,
        supports_nwm=True,
        supports_da=True,        # WCOFS_DA uses data assimilation
        supports_nesting=True,   # ROMS supports nesting
        vertical_coords="s-coordinate",
        native_output_format="netcdf",
    )

    def __init__(self, config: OFSConfig):
        """
        Initialize ROMS model.

        Args:
            config: OFS configuration
        """
        self.config = config
        self._config_generator = None

        # Initialize grid and forcing
        self.grid = self._init_grid()
        self.forcing_processors = self._init_forcing()

    def _init_grid(self) -> ROMSGrid:
        """Initialize ROMS grid handler."""
        return ROMSGrid(self.config)

    def _init_forcing(self) -> Dict[str, BaseForcingProcessor]:
        """
        Initialize forcing processors for ROMS.

        ROMS COMF systems use Fortran executables for forcing generation,
        called via shell scripts. The forcing processors here wrap those
        shell scripts through the orchestration layer.

        For COMF systems, forcing is handled by:
        - nos_ofs_create_forcing_met.sh (atmospheric: NAM/GFS)
        - nos_ofs_create_forcing_obc.sh (ocean boundary: RTOFS)
        - nos_ofs_create_forcing_river.sh (river: NWM/USGS)
        """
        processors = {}

        # ROMS COMF systems use shell-script-based forcing processors.
        # The actual forcing generation is handled by the COMFPrepHandler
        # in the orchestration layer. Here we create lightweight processor
        # stubs that record configuration but delegate execution.

        try:
            from ..forcing import (
                NAMProcessor,
                GFSProcessor,
                NWMProcessor,
                RTOFSProcessor,
                TidalProcessor,
            )

            output_val = getattr(self.config, 'COMOUT', '') or ''
            output_path = Path(output_val) if output_val else Path("/tmp")

            # Atmospheric forcing (NAM primary for most ROMS, GFS fallback)
            yaml_data = self._get_yaml_data()
            forcing_cfg = yaml_data.get('forcing', {})
            atmos_cfg = forcing_cfg.get('atmospheric', {})
            primary_met = atmos_cfg.get('primary', 'nam')

            if primary_met.lower() == 'nam':
                nam_input = getattr(self.config, 'COMINnam', '') or ''
                input_path = Path(nam_input) if nam_input else Path("/tmp")
                processors['nam'] = NAMProcessor(
                    config=self.config,
                    input_path=input_path,
                    output_path=output_path,
                )

            # GFS as fallback or primary
            gfs_input = getattr(self.config, 'COMINgfs', '') or ''
            input_path = Path(gfs_input) if gfs_input else Path("/tmp")
            processors['gfs'] = GFSProcessor(
                config=self.config,
                input_path=input_path,
                output_path=output_path,
            )

            # River forcing (NWM)
            river_cfg = forcing_cfg.get('river', {})
            if river_cfg.get('enabled', True):
                nwm_input = getattr(self.config, 'COMINnwm', '') or ''
                input_path = Path(nwm_input) if nwm_input else Path("/tmp")
                processors['nwm'] = NWMProcessor(
                    config=self.config,
                    input_path=input_path,
                    output_path=output_path,
                )

            # Ocean boundary (RTOFS)
            ocean_cfg = forcing_cfg.get('ocean', {})
            if ocean_cfg.get('enabled', True):
                rtofs_input = getattr(self.config, 'COMINrtofs', '') or ''
                input_path = Path(rtofs_input) if rtofs_input else Path("/tmp")
                processors['rtofs'] = RTOFSProcessor(
                    config=self.config,
                    input_path=input_path,
                    output_path=output_path,
                )

            # Tidal forcing
            tidal_cfg = forcing_cfg.get('tidal', {})
            if tidal_cfg.get('enabled', True):
                processors['tides'] = TidalProcessor(
                    config=self.config,
                    input_path=Path("/tmp"),
                    output_path=output_path,
                )

        except ImportError as e:
            log.warning(f"Could not import forcing processors: {e}")
            log.info("ROMS forcing will be handled by COMF shell scripts")

        return processors

    def _get_yaml_data(self) -> Dict:
        """Extract YAML configuration data."""
        if hasattr(self.config, '_yaml_data'):
            return self.config._yaml_data
        if hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            return self.config.system._raw
        return {}

    def _get_config_generator(self) -> ROMSConfigGenerator:
        """Get or create the ROMS config generator."""
        if self._config_generator is None:
            self._config_generator = ROMSConfigGenerator(self.config)
        return self._config_generator

    def generate_control_file(self, output_path: Path) -> Path:
        """
        Generate ROMS ocean.in control file.

        Args:
            output_path: Directory to write ocean.in

        Returns:
            Path to generated ocean.in
        """
        generator = self._get_config_generator()
        return generator.generate(
            output_path=output_path,
            stage="nowcast",
            pdy=getattr(self.config, 'PDY', None),
            cyc=getattr(self.config, 'cyc', 0),
        )

    def run_model(self, stage: str, nprocs: int = None) -> ModelResult:
        """
        Execute ROMS model via mpiexec.

        For COMF systems, this delegates to nos_ofs_nowcast_forecast.sh.
        For direct execution, it runs the ROMS executable via mpirun.

        Args:
            stage: Workflow stage ("nowcast" or "forecast")
            nprocs: Number of MPI processes (uses config default if None)

        Returns:
            ModelResult with execution status
        """
        yaml_data = self._get_yaml_data()

        # Determine number of processors
        if nprocs is None:
            resources = yaml_data.get('resources', {})
            nprocs = resources.get('nprocs', 120)
            # Also check environment
            env_nprocs = os.environ.get('TOTAL_TASKS', '')
            if env_nprocs:
                nprocs = int(env_nprocs)

        # Get executable name
        model_cfg = yaml_data.get('model', {})
        executable = model_cfg.get('executable', 'romsM')

        # Check for COMF shell script execution mode
        ush_dir = os.environ.get('USHnos', os.environ.get('USHofs', ''))
        script_path = Path(ush_dir) / "nos_ofs_nowcast_forecast.sh" if ush_dir else None

        if script_path and script_path.exists():
            return self._run_via_shell(stage, script_path)
        else:
            return self._run_direct(stage, executable, nprocs)

    def _run_via_shell(self, stage: str, script: Path) -> ModelResult:
        """Execute ROMS via COMF shell script."""
        log.info(f"Running ROMS {stage} via COMF shell script: {script}")

        data_dir = os.environ.get('DATA', '/tmp')

        try:
            result = subprocess.run(
                f"{script} {stage}",
                shell=True,
                cwd=data_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=28800,  # 8 hours
            )

            if result.returncode == 0:
                return ModelResult(
                    success=True,
                    stage=stage,
                    message=f"ROMS {stage} completed successfully via COMF shell",
                )
            else:
                return ModelResult(
                    success=False,
                    stage=stage,
                    message=f"ROMS {stage} failed with return code {result.returncode}",
                    errors=[result.stderr[:1000] if result.stderr else "Unknown error"],
                )

        except subprocess.TimeoutExpired:
            return ModelResult(
                success=False,
                stage=stage,
                message=f"ROMS {stage} timed out after 8 hours",
                errors=["Model execution timed out"],
            )
        except Exception as e:
            return ModelResult(
                success=False,
                stage=stage,
                message=str(e),
                errors=[str(e)],
            )

    def _run_direct(self, stage: str, executable: str, nprocs: int) -> ModelResult:
        """Execute ROMS directly via mpiexec."""
        log.info(f"Running ROMS {stage} directly: mpiexec -n {nprocs} {executable}")

        data_dir = os.environ.get('DATA', '/tmp')
        ofs_name = getattr(self.config, 'RUN', 'roms')

        # Generate ocean.in for this stage
        generator = self._get_config_generator()
        ocean_in = generator.generate(
            output_path=Path(data_dir),
            stage=stage,
            pdy=getattr(self.config, 'PDY', None),
            cyc=getattr(self.config, 'cyc', 0),
        )

        # Find the executable
        exec_dir = os.environ.get('EXECnos', os.environ.get('EXECofs', ''))
        exec_path = Path(exec_dir) / executable if exec_dir else Path(executable)

        command = f"mpiexec -n {nprocs} {exec_path} {ocean_in}"

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=data_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=28800,
            )

            if result.returncode == 0:
                # Collect output files
                output_dir = Path(data_dir)
                output_files = list(output_dir.glob(f"{ofs_name}*.nc"))

                return ModelResult(
                    success=True,
                    stage=stage,
                    message=f"ROMS {stage} completed successfully",
                    output_files=output_files,
                )
            else:
                return ModelResult(
                    success=False,
                    stage=stage,
                    message=f"ROMS {stage} failed with return code {result.returncode}",
                    errors=[result.stderr[:1000] if result.stderr else "Unknown error"],
                )

        except subprocess.TimeoutExpired:
            return ModelResult(
                success=False,
                stage=stage,
                message=f"ROMS {stage} timed out",
                errors=["Model execution timed out"],
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

        For COMF ROMS systems, this delegates to the COMF prep handler
        which calls the shell scripts. When forcing processors are
        available, they are used directly.
        """
        results = {}
        for name, processor in self.forcing_processors.items():
            if hasattr(processor, 'enabled') and processor.enabled:
                try:
                    results[name] = processor.process()
                except Exception as e:
                    results[name] = ForcingResult(
                        success=False,
                        source=name,
                        errors=[str(e)],
                    )
        return results

    def run_nowcast(self) -> ModelResult:
        """Run the nowcast stage."""
        return self.run_model("nowcast")

    def run_forecast(self) -> ModelResult:
        """Run the forecast stage."""
        return self.run_model("forecast")

    def get_s_coordinate_params(self) -> Dict:
        """
        Get S-coordinate vertical grid parameters.

        Returns:
            Dictionary with S-coordinate parameters
        """
        yaml_data = self._get_yaml_data()
        model = yaml_data.get('model', {})
        vertical = model.get('vertical', {})
        physics = model.get('physics', {})

        return {
            'N': vertical.get('n', 20),
            'Vtransform': vertical.get('vtransform', physics.get('vtransform', 2)),
            'Vstretching': vertical.get('vstretching', physics.get('vstretching', 4)),
            'theta_s': vertical.get('theta_s', physics.get('theta_s', 5.0)),
            'theta_b': vertical.get('theta_b', physics.get('theta_b', 0.4)),
            'Tcline': vertical.get('tcline', physics.get('tcline', 10.0)),
            'hc': vertical.get('hc', physics.get('hc', 10.0)),
        }

    def get_output_files(self, stage: str) -> List[Path]:
        """
        Get list of expected output files for a stage.

        ROMS output files follow the pattern:
        - {prefix}.his.{stage}.nc (history)
        - {prefix}.avg.{stage}.nc (averages)
        - {prefix}.rst.{stage}.nc (restart)
        - {prefix}.sta.{stage}.nc (stations)

        Args:
            stage: Workflow stage

        Returns:
            List of expected output file paths
        """
        comout = Path(getattr(self.config, 'COMOUT', '/tmp'))
        ofs_name = getattr(self.config, 'RUN', 'roms')

        expected = [
            comout / f"{ofs_name}.his.{stage}.nc",
            comout / f"{ofs_name}.avg.{stage}.nc",
            comout / f"{ofs_name}.rst.{stage}.nc",
            comout / f"{ofs_name}.sta.{stage}.nc",
        ]

        return [f for f in expected if f.exists()]

    def __repr__(self) -> str:
        return f"ROMSModel(ofs={getattr(self.config, 'RUN', 'unknown')})"
