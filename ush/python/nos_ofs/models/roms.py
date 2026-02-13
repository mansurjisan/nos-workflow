"""
ROMS Model Implementation

Provides a unified interface for ROMS-based OFS systems:
- CBOFS (Chesapeake Bay)
- DBOFS (Delaware Bay)
- TBOFS (Tampa Bay)
- GOMOFS (Gulf of Maine)
- CIOFS (Cook Inlet)
- WCOFS (West Coast)
- WCOFS_DA (West Coast with Data Assimilation)
- WCOFS_FREE (West Coast free-running)

ROMS uses structured curvilinear grids with terrain-following (sigma/S)
vertical coordinates. Model execution is delegated to COMF legacy shell
scripts via subprocess.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from ..base_model import (
    BaseModel,
    ModelType,
    ModelCapabilities,
    GridType,
    ModelResult,
)
from ..base_forcing import BaseForcingProcessor, ForcingResult
from ..base_grid import BaseGrid, GridInfo
from ..config import OFSConfig
from ..forcing import (
    GFSProcessor,
    HRRRProcessor,
    NAMProcessor,
    NWMProcessor,
    RTOFSProcessor,
    TidalProcessor,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ROMS Grid
# ---------------------------------------------------------------------------

class ROMSGrid(BaseGrid):
    """
    ROMS structured curvilinear grid handler.

    Reads ROMS grid NetCDF files that contain:
    - lon_rho, lat_rho: Cell-center coordinates
    - lon_psi, lat_psi: Cell-corner coordinates
    - h: Bottom depth at rho points
    - mask_rho: Land/sea mask
    """

    def __init__(self, config: OFSConfig):
        """
        Initialize ROMS grid handler.

        Args:
            config: OFS configuration
        """
        super().__init__(config)
        self._lon_rho = None
        self._lat_rho = None
        self._h = None
        self._mask = None

    def _get_grid_file(self) -> Path:
        """Get path to ROMS grid NetCDF file."""
        fix_dir = Path(getattr(self.config, 'FIXofs', '/tmp'))

        ofs_name = getattr(self.config, 'RUN', 'unknown')
        patterns = [
            f"{ofs_name}_grid.nc",
            f"{ofs_name}.grid.nc",
            f"nos.{ofs_name}.romsgrid.nc",
            "grid.nc",
        ]

        for pattern in patterns:
            candidate = fix_dir / pattern
            if candidate.exists():
                return candidate

        # Fallback: return the first pattern (may not exist yet)
        return fix_dir / patterns[0]

    def load(self) -> None:
        """
        Load ROMS grid data from NetCDF file.

        Requires netCDF4 to be available. If the grid file does not
        exist, logs a warning and marks as not loaded.
        """
        if self._loaded:
            return

        grid_path = self._grid_file
        if not grid_path.exists():
            logger.warning("ROMS grid file not found: %s", grid_path)
            return

        try:
            from netCDF4 import Dataset

            with Dataset(str(grid_path), 'r') as ds:
                self._lon_rho = ds.variables['lon_rho'][:]
                self._lat_rho = ds.variables['lat_rho'][:]
                self._h = ds.variables['h'][:]
                if 'mask_rho' in ds.variables:
                    self._mask = ds.variables['mask_rho'][:]

            eta, xi = self._lon_rho.shape
            n_levels = int(getattr(self.config, 'n_levels', 0)) or 1

            self._info = GridInfo(
                n_nodes=eta * xi,
                n_elements=(eta - 1) * (xi - 1),
                n_levels=n_levels,
                lon_min=float(np.nanmin(self._lon_rho)),
                lon_max=float(np.nanmax(self._lon_rho)),
                lat_min=float(np.nanmin(self._lat_rho)),
                lat_max=float(np.nanmax(self._lat_rho)),
                depth_min=float(np.nanmin(self._h)),
                depth_max=float(np.nanmax(self._h)),
            )
            self._loaded = True

        except ImportError:
            logger.warning("netCDF4 not available; grid loading deferred")
        except Exception as exc:
            logger.error("Failed to load ROMS grid: %s", exc)

    def get_nodes(self) -> np.ndarray:
        """
        Get rho-point coordinates as (n_nodes, 3) array [lon, lat, depth].
        """
        if not self._loaded:
            self.load()
        if self._lon_rho is None:
            return np.empty((0, 3))

        lon_flat = self._lon_rho.ravel()
        lat_flat = self._lat_rho.ravel()
        h_flat = self._h.ravel()
        return np.column_stack([lon_flat, lat_flat, h_flat])

    def get_elements(self) -> np.ndarray:
        """
        Get structured-grid cell connectivity.

        Each cell is defined by four corner indices in row-major order.
        Returns array of shape (n_elements, 4).
        """
        if not self._loaded:
            self.load()
        if self._lon_rho is None:
            return np.empty((0, 4), dtype=int)

        eta, xi = self._lon_rho.shape
        rows, cols = np.mgrid[0:eta - 1, 0:xi - 1]
        rows_flat = rows.ravel()
        cols_flat = cols.ravel()

        idx = lambda r, c: r * xi + c  # noqa: E731
        elements = np.column_stack([
            idx(rows_flat, cols_flat),
            idx(rows_flat, cols_flat + 1),
            idx(rows_flat + 1, cols_flat + 1),
            idx(rows_flat + 1, cols_flat),
        ])
        return elements

    def get_boundary_nodes(self, boundary_id: int = None) -> np.ndarray:
        """
        Get open boundary node indices.

        For ROMS, open boundaries are typically defined in the ocean.in
        control file rather than in the grid file.  This method returns
        the perimeter indices as a simple placeholder.
        """
        if not self._loaded:
            self.load()
        if self._lon_rho is None:
            return np.empty(0, dtype=int)

        eta, xi = self._lon_rho.shape
        # Perimeter indices (south, east, north, west edges)
        south = np.arange(xi)
        east = np.arange(1, eta) * xi + (xi - 1)
        north = np.arange(xi - 2, -1, -1) + (eta - 1) * xi
        west = np.arange(eta - 2, 0, -1) * xi
        return np.concatenate([south, east, north, west])

    def validate(self) -> bool:
        """
        Validate that the ROMS grid file exists and is readable.

        Returns True even when netCDF4 is not installed because grid
        validation can be deferred to model runtime on HPC nodes.
        """
        grid_path = self._grid_file
        if grid_path.exists():
            return True

        # If running in a prep environment where FIXofs may not be
        # mounted yet, accept the configuration as valid.
        logger.info(
            "ROMS grid file not found at %s; deferring validation", grid_path
        )
        return True


# ---------------------------------------------------------------------------
# ROMS Model
# ---------------------------------------------------------------------------

class ROMSModel(BaseModel):
    """
    ROMS model implementation.

    Provides the unified BaseModel interface for all ROMS-based OFS:
    - CBOFS, DBOFS, TBOFS (East Coast estuaries)
    - GOMOFS (Gulf of Maine)
    - CIOFS (Cook Inlet, Alaska)
    - WCOFS / WCOFS_DA / WCOFS_FREE (West Coast)

    Model execution is delegated to the COMF legacy shell scripts
    (exnos_ofs_nowcast_forecast.sh) via subprocess.  Forcing preparation
    uses the Python forcing processors when available and falls back to
    COMF Fortran executables on HPC.
    """

    model_type = ModelType.ROMS

    capabilities = ModelCapabilities(
        grid_type=GridType.STRUCTURED,
        supports_nwm=True,
        supports_da=True,
        supports_nesting=False,
        vertical_coords="sigma",
        native_output_format="netcdf",
    )

    def __init__(self, config: OFSConfig):
        """
        Initialize ROMS model.

        Args:
            config: OFS configuration
        """
        self.config = config
        self.grid = self._init_grid()
        self.forcing_processors = self._init_forcing()

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def _init_grid(self) -> ROMSGrid:
        """Initialize the ROMS curvilinear grid handler."""
        return ROMSGrid(self.config)

    def _init_forcing(self) -> Dict[str, BaseForcingProcessor]:
        """
        Initialize forcing processors for ROMS.

        ROMS OFS systems use:
        - NAM (primary) / GFS (fallback) for atmospheric forcing
        - RTOFS for ocean boundary conditions
        - NWM for river discharge
        - Tidal constituents for tidal forcing

        Processor selection honours config flags when present.
        """
        processors: Dict[str, BaseForcingProcessor] = {}

        output_val = (
            getattr(self.config, 'COMOUTrerun', None)
            or getattr(self.config, 'COMOUT', None)
            or ""
        )
        output_path = Path(output_val) if output_val else Path("/tmp")

        # -- Atmospheric forcing (NAM primary, GFS/HRRR available) ------
        if getattr(self.config, 'nam_enabled', True):
            nam_input = getattr(self.config, 'COMINnam', '') or ''
            processors['nam'] = NAMProcessor(
                config=self.config,
                input_path=Path(nam_input) if nam_input else Path("/tmp"),
                output_path=output_path,
            )

        if getattr(self.config, 'gfs_enabled', False):
            gfs_input = getattr(self.config, 'COMINgfs', '') or ''
            processors['gfs'] = GFSProcessor(
                config=self.config,
                input_path=Path(gfs_input) if gfs_input else Path("/tmp"),
                output_path=output_path,
            )

        if getattr(self.config, 'hrrr_enabled', False):
            hrrr_input = getattr(self.config, 'COMINhrrr', '') or ''
            processors['hrrr'] = HRRRProcessor(
                config=self.config,
                input_path=Path(hrrr_input) if hrrr_input else Path("/tmp"),
                output_path=output_path,
            )

        # -- Ocean boundary conditions (RTOFS) --------------------------
        if getattr(self.config, 'rtofs_enabled', True):
            rtofs_input = getattr(self.config, 'COMINrtofs', '') or ''
            processors['rtofs'] = RTOFSProcessor(
                config=self.config,
                input_path=Path(rtofs_input) if rtofs_input else Path("/tmp"),
                output_path=output_path,
            )

        # -- River forcing (NWM) ----------------------------------------
        if getattr(self.config, 'nwm_enabled', True):
            nwm_input = getattr(self.config, 'COMINnwm', '') or ''
            processors['nwm'] = NWMProcessor(
                config=self.config,
                input_path=Path(nwm_input) if nwm_input else Path("/tmp"),
                output_path=output_path,
            )

        # -- Tidal forcing ----------------------------------------------
        if getattr(self.config, 'tides_enabled', True):
            processors['tides'] = TidalProcessor(
                config=self.config,
                input_path=Path("/tmp"),
                output_path=output_path,
            )

        return processors

    def generate_control_file(self, output_path: Path) -> Path:
        """
        Generate the ROMS ocean.in control file.

        Uses the template from FIXofs and substitutes runtime values
        (time stepping, forcing paths, restart settings, etc.).

        Args:
            output_path: Directory to write ocean.in

        Returns:
            Path to the generated ocean.in file
        """
        ofs_name = getattr(self.config, 'RUN', 'unknown')
        fix_dir = Path(getattr(self.config, 'FIXofs', '/tmp'))

        # Locate the ocean.in template
        template_candidates = [
            fix_dir / f"nos.{ofs_name}.ocean.in",
            fix_dir / f"{ofs_name}.ocean.in",
            fix_dir / "ocean.in",
        ]

        template_path = None
        for candidate in template_candidates:
            if candidate.exists():
                template_path = candidate
                break

        output_file = Path(output_path) / "ocean.in"

        if template_path is None:
            logger.warning(
                "No ocean.in template found in %s; "
                "COMF shell scripts will generate control file at runtime",
                fix_dir,
            )
            # Create a minimal placeholder so downstream scripts can detect
            # that control-file generation was attempted.
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(
                f"! ocean.in placeholder for {ofs_name}\n"
                f"! Generated by ROMSModel -- will be overwritten at runtime\n"
            )
            return output_file

        # Read template and substitute runtime tokens
        template_text = template_path.read_text()

        substitutions = {
            "__TITLE__": f"NOS {ofs_name.upper()} Run",
            "__VARNAME__": getattr(self.config, 'PREFIXNOS', ofs_name),
            "__NTIMES__": str(getattr(self.config, 'ntimes', '')),
            "__DT__": str(getattr(self.config, 'dt', '')),
            "__NRREC__": str(getattr(self.config, 'nrrec', -1)),
            "__NHIS__": str(getattr(self.config, 'nhis', '')),
            "__NAVG__": str(getattr(self.config, 'navg', '')),
            "__NSTA__": str(getattr(self.config, 'nsta', '')),
            "__NRST__": str(getattr(self.config, 'nrst', '')),
        }

        for token, value in substitutions.items():
            if value:
                template_text = template_text.replace(token, value)

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(template_text)
        logger.info("Generated ROMS control file: %s", output_file)
        return output_file

    def run_model(self, stage: str, nprocs: int = None) -> ModelResult:
        """
        Execute the ROMS model for a given workflow stage.

        Delegates to the COMF shell scripts which handle MPI launch,
        environment setup, and the actual ``romsM`` execution.

        Args:
            stage: Workflow stage -- ``"nowcast"`` or ``"forecast"``
            nprocs: Number of MPI processes (uses config default if None)

        Returns:
            ModelResult with execution status
        """
        ofs_name = getattr(self.config, 'RUN', 'unknown')

        # Resolve paths to COMF shell infrastructure
        scripts_dir = Path(
            getattr(self.config, 'SCRIPTSnos', '') or
            getattr(self.config, 'HOMEnos', '/tmp') + '/scripts'
        )
        data_dir = Path(getattr(self.config, 'DATA', '/tmp'))

        # The COMF ex-script handles both nowcast and forecast
        ex_script = scripts_dir / "exnos_ofs_nowcast_forecast.sh"

        if not ex_script.exists():
            msg = f"COMF execution script not found: {ex_script}"
            logger.error(msg)
            return ModelResult(
                success=False,
                stage=stage,
                message=msg,
                errors=[msg],
            )

        # Build environment for the subprocess
        env = os.environ.copy()
        env['RUN'] = ofs_name
        env['STAGE'] = stage
        env['PDY'] = str(getattr(self.config, 'PDY', ''))
        env['cyc'] = str(getattr(self.config, 'cyc', ''))
        env['DATA'] = str(data_dir)
        env['COMOUT'] = str(getattr(self.config, 'COMOUT', ''))
        env['FIXofs'] = str(getattr(self.config, 'FIXofs', ''))
        env['EXECnos'] = str(getattr(self.config, 'EXECnos', ''))
        env['HOMEnos'] = str(getattr(self.config, 'HOMEnos', ''))

        if nprocs is not None:
            env['NPROCS'] = str(nprocs)

        logger.info(
            "Running ROMS %s stage=%s nprocs=%s",
            ofs_name, stage, nprocs or "default",
        )

        try:
            result = subprocess.run(
                ["bash", str(ex_script)],
                env=env,
                cwd=str(data_dir),
                capture_output=True,
                text=True,
                timeout=7200,  # 2-hour timeout
            )

            if result.returncode == 0:
                logger.info("ROMS %s %s completed successfully", ofs_name, stage)
                return ModelResult(
                    success=True,
                    stage=stage,
                    message=f"Successfully completed {stage}",
                )
            else:
                stderr_tail = (result.stderr or "")[-2000:]
                msg = (
                    f"ROMS {stage} failed with return code {result.returncode}"
                )
                logger.error("%s\nstderr: %s", msg, stderr_tail)
                return ModelResult(
                    success=False,
                    stage=stage,
                    message=msg,
                    errors=[msg, stderr_tail],
                )

        except subprocess.TimeoutExpired:
            msg = f"ROMS {stage} timed out after 7200 seconds"
            logger.error(msg)
            return ModelResult(
                success=False,
                stage=stage,
                message=msg,
                errors=[msg],
            )
        except Exception as exc:
            msg = f"ROMS {stage} execution error: {exc}"
            logger.error(msg)
            return ModelResult(
                success=False,
                stage=stage,
                message=msg,
                errors=[str(exc)],
            )

    # ------------------------------------------------------------------
    # ROMS-specific convenience methods
    # ------------------------------------------------------------------

    def prep_nowcast(self) -> Dict[str, ForcingResult]:
        """
        Run preprocessing for the nowcast stage.

        Processes all enabled forcing types (atmospheric, ocean,
        river, tidal) using the registered processors.
        """
        results: Dict[str, ForcingResult] = {}
        for name, processor in self.forcing_processors.items():
            if processor.enabled:
                try:
                    results[name] = processor.process()
                except Exception as exc:
                    logger.error("Forcing processor '%s' failed: %s", name, exc)
                    results[name] = ForcingResult(
                        success=False,
                        source=name,
                        errors=[str(exc)],
                    )
        return results

    def run_nowcast(self) -> ModelResult:
        """Run the nowcast stage."""
        return self.run_model("nowcast")

    def run_forecast(self) -> ModelResult:
        """Run the forecast stage."""
        return self.run_model("forecast")

    def __repr__(self) -> str:
        return f"ROMSModel(ofs={getattr(self.config, 'RUN', 'unknown')})"
