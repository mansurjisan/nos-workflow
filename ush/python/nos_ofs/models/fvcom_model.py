"""
FVCOM Model Implementation

Provides a unified interface for FVCOM-based OFS systems:
- LEOFS (Lake Erie)
- LOOFS (Lake Ontario)
- LMHOFS (Lake Michigan-Huron)
- LSOFS (Lake Superior)
- NGOFS2 (Northern Gulf of Mexico)
- SFBOFS (San Francisco Bay)
- SSCOFS (Salish Sea/Columbia River)

FVCOM uses an unstructured triangular grid with sigma-coordinate vertical
discretization. The COMF workflow stages are:
    prep -> nowcast -> forecast -> post

This implementation wraps the existing COMF shell scripts via the
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

from .fvcom_grid import FVCOMGrid
from .fvcom_config import FVCOMConfigGenerator

log = logging.getLogger(__name__)


class FVCOMModel(BaseModel):
    """
    FVCOM model implementation.

    Provides the unified BaseModel interface for all FVCOM-based OFS:
    - LEOFS (Lake Erie)
    - LOOFS (Lake Ontario)
    - LMHOFS (Lake Michigan-Huron)
    - LSOFS (Lake Superior)
    - NGOFS2 (Northern Gulf of Mexico)
    - SFBOFS (San Francisco Bay)
    - SSCOFS (Salish Sea/Columbia River)

    FVCOM-specific characteristics:
    - Unstructured triangular grid
    - Sigma vertical coordinates
    - GOTM or Mellor-Yamada vertical mixing
    - Casename-based file naming convention
    - Great Lakes systems: HRRR atmospheric forcing, no tides, no ocean BC
    - Gulf/coastal systems: GFS/NAM forcing, tidal and ocean BC
    """

    model_type = ModelType.FVCOM

    capabilities = ModelCapabilities(
        grid_type=GridType.UNSTRUCTURED,
        supports_nwm=True,
        supports_da=False,
        supports_nesting=True,    # FVCOM supports nesting
        vertical_coords="sigma",
        native_output_format="netcdf",
    )

    def __init__(self, config: OFSConfig):
        """
        Initialize FVCOM model.

        Args:
            config: OFS configuration
        """
        self.config = config
        self._config_generator = None

        # Initialize grid and forcing
        self.grid = self._init_grid()
        self.forcing_processors = self._init_forcing()

    def _init_grid(self) -> FVCOMGrid:
        """Initialize FVCOM grid handler."""
        return FVCOMGrid(self.config)

    def _init_forcing(self) -> Dict[str, BaseForcingProcessor]:
        """
        Initialize forcing processors for FVCOM.

        FVCOM COMF systems use Fortran executables for forcing generation,
        called via shell scripts. The forcing processors here wrap those
        scripts through the orchestration layer.

        For COMF systems, forcing is handled by:
        - nos_ofs_create_forcing_met.sh (atmospheric)
        - nos_ofs_create_forcing_obc.sh (ocean boundary, if applicable)
        - nos_ofs_create_forcing_river.sh (river: NWM/USGS)

        For Great Lakes FVCOM systems:
        - Primary atmospheric: HRRR (3km high-resolution)
        - GFS as fallback
        - No ocean boundary conditions (enclosed lakes)
        - No tidal forcing (no ocean tides)
        """
        processors = {}

        try:
            from ..forcing import (
                GFSProcessor,
                HRRRProcessor,
                NAMProcessor,
                NWMProcessor,
                RTOFSProcessor,
                TidalProcessor,
            )

            output_val = getattr(self.config, 'COMOUT', '') or ''
            output_path = Path(output_val) if output_val else Path("/tmp")

            # Get forcing config from YAML
            yaml_data = self._get_yaml_data()
            forcing_cfg = yaml_data.get('forcing', {})
            atmos_cfg = forcing_cfg.get('atmospheric', {})
            primary_met = atmos_cfg.get('primary', 'hrrr')

            # Atmospheric forcing
            if primary_met.lower() == 'hrrr':
                hrrr_input = getattr(self.config, 'COMINhrrr', '') or ''
                input_path = Path(hrrr_input) if hrrr_input else Path("/tmp")
                processors['hrrr'] = HRRRProcessor(
                    config=self.config,
                    input_path=input_path,
                    output_path=output_path,
                )
            elif primary_met.lower() == 'nam':
                nam_input = getattr(self.config, 'COMINnam', '') or ''
                input_path = Path(nam_input) if nam_input else Path("/tmp")
                processors['nam'] = NAMProcessor(
                    config=self.config,
                    input_path=input_path,
                    output_path=output_path,
                )

            # GFS as fallback
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

            # Ocean boundary (RTOFS) - only for non-lake systems
            ocean_cfg = forcing_cfg.get('ocean', {})
            if ocean_cfg.get('enabled', False):
                rtofs_input = getattr(self.config, 'COMINrtofs', '') or ''
                input_path = Path(rtofs_input) if rtofs_input else Path("/tmp")
                processors['rtofs'] = RTOFSProcessor(
                    config=self.config,
                    input_path=input_path,
                    output_path=output_path,
                )

            # Tidal forcing - only for non-lake systems
            tidal_cfg = forcing_cfg.get('tidal', {})
            if tidal_cfg.get('enabled', False):
                processors['tides'] = TidalProcessor(
                    config=self.config,
                    input_path=Path("/tmp"),
                    output_path=output_path,
                )

        except ImportError as e:
            log.warning(f"Could not import forcing processors: {e}")
            log.info("FVCOM forcing will be handled by COMF shell scripts")

        return processors

    def _get_yaml_data(self) -> Dict:
        """Extract YAML configuration data."""
        if hasattr(self.config, '_yaml_data'):
            return self.config._yaml_data
        if hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            return self.config.system._raw
        return {}

    def _get_config_generator(self) -> FVCOMConfigGenerator:
        """Get or create the FVCOM config generator."""
        if self._config_generator is None:
            self._config_generator = FVCOMConfigGenerator(self.config)
        return self._config_generator

    def generate_control_file(self, output_path: Path) -> Path:
        """
        Generate FVCOM run_control.nml control file.

        Args:
            output_path: Directory to write run_control.nml

        Returns:
            Path to generated run_control.nml
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
        Execute FVCOM model via mpiexec.

        For COMF systems, this delegates to nos_ofs_nowcast_forecast.sh.
        For direct execution, it runs the FVCOM executable via mpirun.

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
            nprocs = resources.get('nprocs', 240)
            env_nprocs = os.environ.get('TOTAL_TASKS', '')
            if env_nprocs:
                nprocs = int(env_nprocs)

        # Get executable name
        model_cfg = yaml_data.get('model', {})
        executable = model_cfg.get('executable', 'fvcom')

        # Check for COMF shell script execution mode
        ush_dir = os.environ.get('USHnos', os.environ.get('USHofs', ''))
        script_path = Path(ush_dir) / "nos_ofs_nowcast_forecast.sh" if ush_dir else None

        if script_path and script_path.exists():
            return self._run_via_shell(stage, script_path)
        else:
            return self._run_direct(stage, executable, nprocs)

    def _run_via_shell(self, stage: str, script: Path) -> ModelResult:
        """Execute FVCOM via COMF shell script."""
        log.info(f"Running FVCOM {stage} via COMF shell script: {script}")

        data_dir = os.environ.get('DATA', '/tmp')

        try:
            result = subprocess.run(
                f"{script} {stage}",
                shell=True,
                cwd=data_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=28800,
            )

            if result.returncode == 0:
                return ModelResult(
                    success=True,
                    stage=stage,
                    message=f"FVCOM {stage} completed successfully via COMF shell",
                )
            else:
                return ModelResult(
                    success=False,
                    stage=stage,
                    message=f"FVCOM {stage} failed with return code {result.returncode}",
                    errors=[result.stderr[:1000] if result.stderr else "Unknown error"],
                )

        except subprocess.TimeoutExpired:
            return ModelResult(
                success=False,
                stage=stage,
                message=f"FVCOM {stage} timed out after 8 hours",
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
        """Execute FVCOM directly via mpiexec."""
        ofs_name = getattr(self.config, 'RUN', 'fvcom')
        casename = self._get_yaml_data().get('system', {}).get('casename', ofs_name)

        log.info(
            f"Running FVCOM {stage} directly: "
            f"mpiexec -n {nprocs} {executable} --casename={casename}"
        )

        data_dir = os.environ.get('DATA', '/tmp')

        # Generate run_control.nml for this stage
        generator = self._get_config_generator()
        nml_path = generator.generate(
            output_path=Path(data_dir),
            stage=stage,
            pdy=getattr(self.config, 'PDY', None),
            cyc=getattr(self.config, 'cyc', 0),
        )

        # Find the executable
        exec_dir = os.environ.get('EXECnos', os.environ.get('EXECofs', ''))
        exec_path = Path(exec_dir) / executable if exec_dir else Path(executable)

        # FVCOM uses casename convention for input/output file discovery
        command = f"mpiexec -n {nprocs} {exec_path} --casename={casename}"

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
                output_dir = Path(data_dir) / "output"
                output_files = list(output_dir.glob(f"{casename}*.nc")) if output_dir.exists() else []

                return ModelResult(
                    success=True,
                    stage=stage,
                    message=f"FVCOM {stage} completed successfully",
                    output_files=output_files,
                )
            else:
                return ModelResult(
                    success=False,
                    stage=stage,
                    message=f"FVCOM {stage} failed with return code {result.returncode}",
                    errors=[result.stderr[:1000] if result.stderr else "Unknown error"],
                )

        except subprocess.TimeoutExpired:
            return ModelResult(
                success=False,
                stage=stage,
                message=f"FVCOM {stage} timed out",
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

        For COMF FVCOM systems, this delegates to the COMF prep handler
        which calls the shell scripts.
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

    def is_great_lakes(self) -> bool:
        """
        Check if this is a Great Lakes FVCOM system.

        Great Lakes systems (LEOFS, LOOFS, LMHOFS, LSOFS) do not
        have ocean boundary conditions or tidal forcing.

        Returns:
            True if this is a Great Lakes OFS
        """
        ofs_name = getattr(self.config, 'RUN', '').lower()
        great_lakes = {'leofs', 'loofs', 'lmhofs', 'lsofs'}
        return ofs_name in great_lakes

    def get_sigma_levels(self) -> Dict:
        """
        Get sigma-coordinate vertical grid parameters.

        Returns:
            Dictionary with sigma level parameters
        """
        yaml_data = self._get_yaml_data()
        model = yaml_data.get('model', {})
        vertical = model.get('vertical', {})

        return {
            'kb': vertical.get('kb', 21),
            'ksl': vertical.get('ksl', 1),
            'p_sigma': vertical.get('p_sigma', 1.0),
        }

    def get_output_files(self, stage: str) -> List[Path]:
        """
        Get list of expected output files for a stage.

        FVCOM output files follow the pattern:
        - {casename}_0001.nc (field output)
        - {casename}_restart_0001.nc (restart)
        - {casename}_station_timeseries.nc (stations)

        Args:
            stage: Workflow stage

        Returns:
            List of expected output file paths
        """
        comout = Path(getattr(self.config, 'COMOUT', '/tmp'))
        ofs_name = getattr(self.config, 'RUN', 'fvcom')

        expected = [
            comout / f"{ofs_name}_0001.nc",
            comout / f"{ofs_name}_restart_0001.nc",
            comout / f"{ofs_name}_station_timeseries.nc",
        ]

        return [f for f in expected if f.exists()]

    def __repr__(self) -> str:
        ofs_name = getattr(self.config, 'RUN', 'unknown')
        lakes_tag = " [Great Lakes]" if self.is_great_lakes() else ""
        return f"FVCOMModel(ofs={ofs_name}{lakes_tag})"
