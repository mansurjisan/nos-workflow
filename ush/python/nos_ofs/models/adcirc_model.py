"""
ADCIRC Model Implementation

Provides a unified interface for ADCIRC-based OFS systems:
- STOFS-2D-Global (Global Surge and Tide Operational Forecast System)

ADCIRC is a 2D barotropic, depth-averaged model that solves the shallow
water equations on unstructured triangular meshes. It is used for storm
surge and tidal prediction on global and regional scales.

The STOFS-2D-Global workflow has a multi-stage structure:
    cold_spinup -> tide_nowcast -> tide_forecast1 -> tide_forecast2
                -> surf_nowcast -> surf_forecast1 -> surf_forecast2
    GFS forcing prep: gfs_ncst -> gfs_fcst1 -> gfs_fcst2
    Post: post_ncrcat -> post_ncdiff -> post_bias_correction
          -> post_anomaly -> post_grib2 -> gempak

This implementation wraps the ADCIRC executables (adcprep, padcirc) and
provides a Python-native interface for configuration generation,
forcing preparation, and model execution.
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

from .adcirc_grid import ADCIRCGrid
from .adcirc_config import ADCIRCConfigGenerator

log = logging.getLogger(__name__)


class ADCIRCModel(BaseModel):
    """
    ADCIRC model implementation.

    Provides the unified BaseModel interface for ADCIRC-based OFS:
    - STOFS-2D-Global (global storm surge and tide)

    ADCIRC-specific characteristics:
    - 2D barotropic (depth-averaged) shallow water equations
    - Unstructured triangular mesh (fort.14)
    - Nodal attributes for spatially varying friction (fort.13)
    - Template-based control file (fort.15)
    - OWI NetCDF format for atmospheric forcing (fort.221/222/225.nc)
    - Tidal potential and boundary forcing with 8 constituents
    - adcprep for mesh partitioning, padcirc for parallel execution
    - Bias correction using CO-OPS tide gauge observations
    """

    model_type = ModelType.ADCIRC

    capabilities = ModelCapabilities(
        grid_type=GridType.UNSTRUCTURED,
        supports_nwm=False,          # 2D global domain, no river forcing
        supports_da=False,
        supports_nesting=False,
        vertical_coords="2d_barotropic",  # Depth-averaged, no vertical
        native_output_format="netcdf",
    )

    def __init__(self, config: OFSConfig):
        """
        Initialize ADCIRC model.

        Args:
            config: OFS configuration
        """
        self.config = config
        self._config_generator = None

        # Initialize grid and forcing
        self.grid = self._init_grid()
        self.forcing_processors = self._init_forcing()

    def _init_grid(self) -> ADCIRCGrid:
        """Initialize ADCIRC grid handler."""
        return ADCIRCGrid(self.config)

    def _init_forcing(self) -> Dict[str, BaseForcingProcessor]:
        """
        Initialize forcing processors for ADCIRC.

        ADCIRC STOFS-2D-Global uses:
        - GFS atmospheric forcing (wind and pressure) in OWI format
        - Tidal forcing (computed by tide_fac executable)
        - No river forcing (global 2D domain)
        - No ocean boundary conditions (global domain, no open boundary)
        """
        processors = {}

        try:
            from ..forcing import GFSProcessor, TidalProcessor

            output_val = getattr(self.config, 'COMOUT', '') or ''
            output_path = Path(output_val) if output_val else Path("/tmp")

            # Get forcing config from YAML
            yaml_data = self._get_yaml_data()
            forcing_cfg = yaml_data.get('forcing', {})

            # Atmospheric forcing (GFS only for global domain)
            atmos_cfg = forcing_cfg.get('atmospheric', {})
            if atmos_cfg.get('primary', 'gfs').lower() == 'gfs':
                gfs_input = getattr(self.config, 'COMINgfs', '') or ''
                input_path = Path(gfs_input) if gfs_input else Path("/tmp")
                processors['gfs'] = GFSProcessor(
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
            log.info("ADCIRC forcing will be handled by STOFS shell scripts")

        return processors

    def _get_yaml_data(self) -> Dict:
        """Extract YAML configuration data."""
        if hasattr(self.config, '_yaml_data'):
            return self.config._yaml_data
        if hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            return self.config.system._raw
        return {}

    def _get_config_generator(self) -> ADCIRCConfigGenerator:
        """Get or create the ADCIRC config generator."""
        if self._config_generator is None:
            self._config_generator = ADCIRCConfigGenerator(self.config)
        return self._config_generator

    def generate_control_file(self, output_path: Path) -> Path:
        """
        Generate ADCIRC fort.15 control file.

        Args:
            output_path: Directory to write fort.15

        Returns:
            Path to generated fort.15
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
        Execute ADCIRC model via adcprep + padcirc.

        The ADCIRC execution sequence is:
        1. adcprep --np N --partmesh  (partition the mesh)
        2. adcprep --np N --prepall   (prepare all input files)
        3. mpiexec -n N padcirc       (run the parallel solver)

        For hotstart runs (ihot=67/68), adcprep --prep15 is used instead
        of --prepall to avoid re-partitioning.

        Args:
            stage: Workflow stage (e.g., "tide_nowcast", "surf_forecast1")
            nprocs: Number of MPI processes (uses config default if None)

        Returns:
            ModelResult with execution status
        """
        yaml_data = self._get_yaml_data()

        # Determine number of processors
        if nprocs is None:
            resources = yaml_data.get('resources', {})
            nprocs = resources.get('nprocs', 2400)
            env_nprocs = os.environ.get('TOTAL_TASKS', '')
            if env_nprocs:
                nprocs = int(env_nprocs)

        # Determine if this is a hotstart run
        stage_params = self._get_config_generator().get_stage_params(stage)
        is_hotstart = stage_params.get('ihot', 0) > 0

        # Check for STOFS shell script execution mode
        ush_dir = os.environ.get('USHstofs2d', os.environ.get('USHnos', ''))
        script_name = f"stofs_2d_glo_{stage}.sh"
        script_path = Path(ush_dir) / script_name if ush_dir else None

        if script_path and script_path.exists():
            return self._run_via_shell(stage, script_path)
        else:
            return self._run_direct(stage, nprocs, is_hotstart)

    def _run_via_shell(self, stage: str, script: Path) -> ModelResult:
        """Execute ADCIRC via STOFS shell script."""
        log.info(f"Running ADCIRC {stage} via STOFS shell script: {script}")

        data_dir = os.environ.get('DATA', '/tmp')

        try:
            result = subprocess.run(
                str(script),
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
                    message=f"ADCIRC {stage} completed successfully via STOFS shell",
                )
            else:
                return ModelResult(
                    success=False,
                    stage=stage,
                    message=f"ADCIRC {stage} failed with return code {result.returncode}",
                    errors=[result.stderr[:1000] if result.stderr else "Unknown error"],
                )

        except subprocess.TimeoutExpired:
            return ModelResult(
                success=False,
                stage=stage,
                message=f"ADCIRC {stage} timed out after 8 hours",
                errors=["Model execution timed out"],
            )
        except Exception as e:
            return ModelResult(
                success=False,
                stage=stage,
                message=str(e),
                errors=[str(e)],
            )

    def _run_direct(self, stage: str, nprocs: int, is_hotstart: bool) -> ModelResult:
        """
        Execute ADCIRC directly via adcprep + padcirc.

        Args:
            stage: Workflow stage
            nprocs: Number of MPI processes
            is_hotstart: Whether this is a hotstart (restart) run
        """
        data_dir = os.environ.get('DATA', '/tmp')
        exec_dir = os.environ.get('EXECstofs2d', os.environ.get('EXECnos', ''))

        adcprep = Path(exec_dir) / "adcprep" if exec_dir else Path("adcprep")
        padcirc = Path(exec_dir) / "padcirc" if exec_dir else Path("padcirc")

        log.info(
            f"Running ADCIRC {stage} directly: "
            f"nprocs={nprocs}, hotstart={is_hotstart}"
        )

        # Generate fort.15 for this stage
        generator = self._get_config_generator()
        fort15_path = generator.generate(
            output_path=Path(data_dir),
            stage=stage,
            pdy=getattr(self.config, 'PDY', None),
            cyc=getattr(self.config, 'cyc', 0),
        )

        try:
            # Step 1: Mesh partitioning (only for cold start or first run)
            if not is_hotstart:
                log.info(f"Running adcprep --partmesh with {nprocs} processors")
                result = subprocess.run(
                    f"{adcprep} --np {nprocs} --partmesh",
                    shell=True,
                    cwd=data_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3600,
                )
                if result.returncode != 0:
                    return ModelResult(
                        success=False,
                        stage=stage,
                        message=f"adcprep --partmesh failed (rc={result.returncode})",
                        errors=[result.stderr[:1000] if result.stderr else "partmesh failed"],
                    )

                # Step 2: Prepare all input files
                log.info("Running adcprep --prepall")
                result = subprocess.run(
                    f"{adcprep} --np {nprocs} --prepall",
                    shell=True,
                    cwd=data_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3600,
                )
                if result.returncode != 0:
                    return ModelResult(
                        success=False,
                        stage=stage,
                        message=f"adcprep --prepall failed (rc={result.returncode})",
                        errors=[result.stderr[:1000] if result.stderr else "prepall failed"],
                    )
            else:
                # For hotstart runs, only re-prepare fort.15
                log.info("Running adcprep --prep15 (hotstart mode)")
                result = subprocess.run(
                    f"{adcprep} --np {nprocs} --prep15",
                    shell=True,
                    cwd=data_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3600,
                )
                if result.returncode != 0:
                    return ModelResult(
                        success=False,
                        stage=stage,
                        message=f"adcprep --prep15 failed (rc={result.returncode})",
                        errors=[result.stderr[:1000] if result.stderr else "prep15 failed"],
                    )

            # Step 3: Run padcirc
            log.info(f"Running padcirc with {nprocs} MPI processes")
            command = f"mpiexec -n {nprocs} {padcirc}"
            result = subprocess.run(
                command,
                shell=True,
                cwd=data_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=28800,  # 8 hours
            )

            if result.returncode == 0:
                # Collect output files
                output_dir = Path(data_dir)
                output_files = []
                for pattern in ["fort.61.nc", "fort.63.nc", "maxele.63.nc",
                                "fort.67.nc", "fort.68.nc"]:
                    found = list(output_dir.glob(pattern))
                    output_files.extend(found)

                return ModelResult(
                    success=True,
                    stage=stage,
                    message=f"ADCIRC {stage} completed successfully",
                    output_files=output_files,
                )
            else:
                return ModelResult(
                    success=False,
                    stage=stage,
                    message=f"padcirc failed with return code {result.returncode}",
                    errors=[result.stderr[:1000] if result.stderr else "Unknown error"],
                )

        except subprocess.TimeoutExpired as e:
            return ModelResult(
                success=False,
                stage=stage,
                message=f"ADCIRC {stage} timed out",
                errors=[f"Execution timed out: {e}"],
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

        For ADCIRC STOFS-2D-Global, this prepares:
        - GFS atmospheric forcing in OWI format (fort.221/222/225.nc)
        - Tidal nodal factors via tide_fac executable
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
        """Run the nowcast stage (tidal + surface)."""
        return self.run_model("surf_nowcast")

    def run_forecast(self) -> ModelResult:
        """Run the forecast stage (tidal + surface, phase 1)."""
        return self.run_model("surf_forecast1")

    def run_tide_fac(self, output_path: Path = None) -> ModelResult:
        """
        Run the tide_fac executable to compute tidal nodal factors.

        tide_fac computes nodal factor and equilibrium argument corrections
        for the specified tidal constituents and simulation reference time.

        Args:
            output_path: Directory for tide_fac output (defaults to DATA)

        Returns:
            ModelResult with execution status
        """
        data_dir = output_path or Path(os.environ.get('DATA', '/tmp'))
        exec_dir = os.environ.get('EXECstofs2d', os.environ.get('EXECnos', ''))

        tide_fac_exec = Path(exec_dir) / "stofs_2d_glo_tide_fac" if exec_dir else None
        if tide_fac_exec is None or not tide_fac_exec.exists():
            tide_fac_exec = Path(exec_dir) / "tide_fac" if exec_dir else Path("tide_fac")

        log.info(f"Running tide_fac: {tide_fac_exec}")

        try:
            result = subprocess.run(
                str(tide_fac_exec),
                shell=True,
                cwd=str(data_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,
            )

            if result.returncode == 0:
                return ModelResult(
                    success=True,
                    stage="tide_fac",
                    message="tide_fac completed successfully",
                )
            else:
                return ModelResult(
                    success=False,
                    stage="tide_fac",
                    message=f"tide_fac failed (rc={result.returncode})",
                    errors=[result.stderr[:500] if result.stderr else "Unknown error"],
                )
        except Exception as e:
            return ModelResult(
                success=False,
                stage="tide_fac",
                message=str(e),
                errors=[str(e)],
            )

    def get_output_files(self, stage: str) -> List[Path]:
        """
        Get list of expected output files for a stage.

        ADCIRC output files:
        - fort.61.nc: Station timeseries (water levels)
        - fort.63.nc: Global field output (water surface elevation)
        - maxele.63.nc: Maximum elevation envelope
        - fort.67.nc / fort.68.nc: Hotstart files

        Args:
            stage: Workflow stage

        Returns:
            List of expected output file paths
        """
        comout = Path(getattr(self.config, 'COMOUT', '/tmp'))
        ofs_name = getattr(self.config, 'RUN', 'stofs_2d_glo')

        expected = [
            comout / f"{ofs_name}.{stage}.fort.61.nc",
            comout / f"{ofs_name}.{stage}.fort.63.nc",
            comout / f"{ofs_name}.{stage}.maxele.63.nc",
        ]

        return [f for f in expected if f.exists()]

    def get_workflow_stages(self) -> List[str]:
        """
        Get the ordered list of STOFS-2D-Global workflow stages.

        Returns:
            List of stage names in execution order
        """
        return [
            "cold_adcprep",
            "cold_spinup",
            "tide_nowcast",
            "gfs_ncst",
            "surf_nowcast",
            "tide_forecast1",
            "gfs_fcst1",
            "surf_forecast1",
            "tide_forecast2",
            "gfs_fcst2",
            "surf_forecast2",
            "post_ncrcat",
            "post_ncdiff",
            "post_bias_correction",
            "post_anomaly",
            "post_grib2",
        ]

    def __repr__(self) -> str:
        return f"ADCIRCModel(ofs={getattr(self.config, 'RUN', 'unknown')})"
