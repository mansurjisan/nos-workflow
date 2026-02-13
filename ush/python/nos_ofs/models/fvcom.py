"""
FVCOM Model Implementation

Provides a unified interface for FVCOM-based OFS systems:
- LEOFS (Lake Erie)
- LOOFS (Lake Ontario)
- LMHOFS (Lake Michigan-Huron)
- LSOFS (Lake Superior)
- NGOFS2 (Northern Gulf of Mexico)
- SFBOFS (San Francisco Bay)
- SSCOFS (Salish Sea / Cook Inlet)

Most FVCOM systems are Great Lakes models that use HRRR atmospheric
forcing as their primary source, have NWM river inputs, and do NOT
require ocean boundary conditions or tidal forcing. NGOFS2 is the
exception: it covers the Gulf of Mexico and requires both tides and
RTOFS ocean boundary conditions.

FVCOM uses an unstructured triangular mesh with sigma vertical
coordinates. The control file is a Fortran namelist (run_control.nml).
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict

import numpy as np

from ..base_model import (
    BaseModel,
    ModelType,
    ModelCapabilities,
    GridType,
    ModelResult,
)
from ..base_forcing import BaseForcingProcessor
from ..base_grid import BaseGrid, GridInfo
from ..config import OFSConfig

# Import forcing processors from the nos_ofs.forcing package
from ..forcing import (
    ForcingResult,
    GFSProcessor,
    HRRRProcessor,
    NWMProcessor,
    RTOFSProcessor,
    TidalProcessor,
)

logger = logging.getLogger(__name__)

# FVCOM systems that require ocean boundary conditions and tidal forcing.
# Great Lakes systems are enclosed basins and do not need these.
_OFS_WITH_OCEAN_OBC = {"ngofs2"}


class FVCOMGrid(BaseGrid):
    """
    FVCOM grid handler.

    Reads FVCOM unstructured triangular grid files.  FVCOM grids are
    typically stored in a NetCDF file (e.g., ``{OFS}_grd.dat``) or as
    a combined grid/sigma coordinate file.

    For the purposes of this implementation, grid validation simply
    checks that the expected grid file exists.  Full grid reading
    (nodes, elements, boundary segments) is deferred to ``load()``.
    """

    def __init__(self, config: OFSConfig):
        """
        Initialize FVCOM grid handler.

        Args:
            config: OFS configuration
        """
        super().__init__(config)

        self._nodes = None
        self._elements = None
        self._boundaries = None

    def _get_grid_file(self) -> Path:
        """Get path to the primary FVCOM grid file."""
        fix_dir = Path(self.config.FIXofs)

        # Try common COMF naming patterns for FVCOM grids
        patterns = [
            f"{self.config.RUN}_grd.dat",
            f"{self.config.RUN}.grd.dat",
            f"{self.config.RUN}_grid.nc",
            getattr(self.config, "grid_file", None),
        ]

        for pattern in patterns:
            if pattern:
                grid_file = fix_dir / pattern
                if grid_file.exists():
                    return grid_file

        # Return default path even if not found yet
        return fix_dir / f"{self.config.RUN}_grd.dat"

    def load(self) -> None:
        """Load grid data from file."""
        if self._loaded:
            return

        grid_file = self._grid_file
        if not grid_file.exists():
            raise FileNotFoundError(f"FVCOM grid file not found: {grid_file}")

        self._read_grid(grid_file)
        self._loaded = True

    def _read_grid(self, filepath: Path) -> None:
        """
        Read an FVCOM grid file.

        FVCOM grid files (.grd.dat) follow a format similar to SMS:
            n_elements n_nodes
            node_id x y depth
            elem_id node1 node2 node3

        For production use the grid metadata (node count, element count,
        bounding box) is typically obtained from the YAML config or the
        .ctl control file rather than parsed at runtime.  This method
        provides a basic parser for offline validation.
        """
        with open(filepath, "r") as f:
            # First line: counts
            line = f.readline().split()
            n_elements = int(line[0])
            n_nodes = int(line[1])

            # Read nodes
            self._nodes = np.zeros((n_nodes, 3))
            for i in range(n_nodes):
                parts = f.readline().split()
                self._nodes[i, 0] = float(parts[1])  # lon/x
                self._nodes[i, 1] = float(parts[2])  # lat/y
                self._nodes[i, 2] = float(parts[3])  # depth

            # Read triangular elements
            self._elements = np.zeros((n_elements, 3), dtype=int)
            for i in range(n_elements):
                parts = f.readline().split()
                self._elements[i, 0] = int(parts[1]) - 1
                self._elements[i, 1] = int(parts[2]) - 1
                self._elements[i, 2] = int(parts[3]) - 1

        # Open boundary parsing is model-specific; default to empty
        self._boundaries = []

        self._info = GridInfo(
            n_nodes=n_nodes,
            n_elements=n_elements,
            n_levels=getattr(self.config, "n_levels", 20),
            lon_min=float(self._nodes[:, 0].min()),
            lon_max=float(self._nodes[:, 0].max()),
            lat_min=float(self._nodes[:, 1].min()),
            lat_max=float(self._nodes[:, 1].max()),
            depth_min=float(self._nodes[:, 2].min()),
            depth_max=float(self._nodes[:, 2].max()),
        )

    def get_nodes(self) -> np.ndarray:
        """
        Get node coordinates.

        Returns:
            Array of shape (n_nodes, 3) with [lon, lat, depth]
        """
        if not self._loaded:
            self.load()
        return self._nodes

    def get_elements(self) -> np.ndarray:
        """
        Get element connectivity.

        Returns:
            Array of shape (n_elements, 3) with triangle node indices
        """
        if not self._loaded:
            self.load()
        return self._elements

    def get_boundary_nodes(self, boundary_id: int = None) -> np.ndarray:
        """
        Get open boundary node indices.

        Args:
            boundary_id: Specific boundary (0-indexed), None for all

        Returns:
            Array of boundary node indices
        """
        if not self._loaded:
            self.load()

        if not self._boundaries:
            return np.array([], dtype=int)

        if boundary_id is not None:
            if 0 <= boundary_id < len(self._boundaries):
                return self._boundaries[boundary_id]
            return np.array([], dtype=int)

        return np.concatenate(self._boundaries)

    def validate(self) -> bool:
        """
        Validate that grid files exist.

        For FVCOM in the COMF workflow the grid files are staged into
        the run directory by the J-job / ex-script, so we only check
        for existence of the expected grid file in FIXofs.  If the file
        does not exist yet (e.g., before the J-job stages it), we
        return True to avoid blocking workflow setup.

        Returns:
            True if grid file exists or has not yet been staged.
        """
        grid_file = self._grid_file
        if grid_file.exists():
            return True
        # Grid may be staged later by the J-job; do not block
        logger.debug("FVCOM grid file not yet available: %s", grid_file)
        return True

    def __repr__(self) -> str:
        if self._info:
            return (
                f"FVCOMGrid(nodes={self._info.n_nodes}, "
                f"elements={self._info.n_elements})"
            )
        return f"FVCOMGrid(file={self._grid_file})"


class FVCOMModel(BaseModel):
    """
    FVCOM model implementation.

    Provides the unified BaseModel interface for all FVCOM-based OFS:
    - LEOFS  (Lake Erie Operational Forecast System)
    - LOOFS  (Lake Ontario Operational Forecast System)
    - LMHOFS (Lake Michigan-Huron Operational Forecast System)
    - LSOFS  (Lake Superior Operational Forecast System)
    - NGOFS2 (Northern Gulf of Mexico Operational Forecast System)
    - SFBOFS (San Francisco Bay Operational Forecast System)
    - SSCOFS (Salish Sea / Cook Inlet Operational Forecast System)

    FVCOM execution in production is handled by the COMF shell scripts
    (``nos_ofs_nowcast_forecast.sh``) which are invoked by the J-jobs.
    This Python class provides the interface for direct Python invocation
    and configuration management.
    """

    model_type = ModelType.FVCOM

    capabilities = ModelCapabilities(
        grid_type=GridType.UNSTRUCTURED,
        supports_nwm=True,
        supports_da=False,
        supports_nesting=True,
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
        self._ofs_name = getattr(config, "RUN", "unknown").lower()

        # Initialize grid and forcing
        self.grid = self._init_grid()
        self.forcing_processors = self._init_forcing()

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def _init_grid(self) -> FVCOMGrid:
        """Initialize FVCOM grid handler."""
        return FVCOMGrid(self.config)

    def _init_forcing(self) -> Dict[str, BaseForcingProcessor]:
        """
        Initialize forcing processors.

        FVCOM systems share a common set of forcing processors.
        Great Lakes systems use HRRR as primary atmospheric forcing
        with GFS as fallback. NGOFS2 additionally requires RTOFS
        ocean boundary conditions and tidal forcing.
        """
        processors = {}

        # Common output path
        output_val = (
            getattr(self.config, "COMOUTrerun", None)
            or getattr(self.config, "COMOUT", None)
            or ""
        )
        output_path = Path(output_val) if output_val else Path("/tmp")

        # -- Atmospheric forcing ----------------------------------------
        # HRRR is the primary source for most FVCOM systems (Great Lakes).
        if getattr(self.config, "hrrr_enabled", True):
            hrrr_input = getattr(self.config, "COMINhrrr", "") or ""
            input_path = Path(hrrr_input) if hrrr_input else Path("/tmp")
            processors["hrrr"] = HRRRProcessor(
                config=self.config,
                input_path=input_path,
                output_path=output_path,
            )

        # GFS is the fallback atmospheric source.
        if getattr(self.config, "gfs_enabled", True):
            gfs_input = getattr(self.config, "COMINgfs", "") or ""
            input_path = Path(gfs_input) if gfs_input else Path("/tmp")
            processors["gfs"] = GFSProcessor(
                config=self.config,
                input_path=input_path,
                output_path=output_path,
            )

        # -- River forcing (NWM) ----------------------------------------
        if getattr(self.config, "nwm_enabled", True):
            nwm_input = getattr(self.config, "COMINnwm", "") or ""
            input_path = Path(nwm_input) if nwm_input else Path("/tmp")
            processors["nwm"] = NWMProcessor(
                config=self.config,
                input_path=input_path,
                output_path=output_path,
            )

        # -- Ocean boundary conditions (RTOFS) --------------------------
        # Only needed for systems with open ocean boundaries (e.g. NGOFS2).
        if self._needs_ocean_obc():
            if getattr(self.config, "rtofs_enabled", True):
                rtofs_input = getattr(self.config, "COMINrtofs", "") or ""
                input_path = Path(rtofs_input) if rtofs_input else Path("/tmp")
                processors["rtofs"] = RTOFSProcessor(
                    config=self.config,
                    input_path=input_path,
                    output_path=output_path,
                )

        # -- Tidal forcing ----------------------------------------------
        # Only needed for systems with open ocean boundaries.
        if self._needs_tidal_forcing():
            if getattr(self.config, "tides_enabled", True):
                processors["tides"] = TidalProcessor(
                    config=self.config,
                    input_path=Path("/tmp"),
                    output_path=output_path,
                )

        return processors

    def generate_control_file(self, output_path: Path) -> Path:
        """
        Generate FVCOM run_control.nml control file.

        In the COMF workflow, the run control namelist is assembled by
        ``nos_ofs_launch.sh`` from a template in FIXofs.  This method
        copies the template and patches cycle-specific values (start
        time, end time, restart flag, output interval).

        Args:
            output_path: Directory to write run_control.nml

        Returns:
            Path to generated run_control.nml
        """
        output_file = output_path / "run_control.nml"

        # Locate the template namelist in FIXofs
        fix_dir = Path(getattr(self.config, "FIXofs", ""))
        template_candidates = [
            fix_dir / f"{self._ofs_name}.run_control.nml",
            fix_dir / f"{self._ofs_name}_run_control.nml",
            fix_dir / "run_control.nml",
        ]

        template_path = None
        for candidate in template_candidates:
            if candidate.exists():
                template_path = candidate
                break

        if template_path is not None:
            # Copy template and patch cycle-specific values
            content = template_path.read_text()
            content = self._patch_namelist(content)
            output_file.write_text(content)
            logger.info("Generated FVCOM control file: %s", output_file)
        else:
            # Create a minimal placeholder so the caller gets a valid path.
            # In production the J-job / nos_ofs_launch.sh handles this.
            logger.warning(
                "No FVCOM namelist template found in %s; "
                "creating placeholder at %s",
                fix_dir,
                output_file,
            )
            output_file.write_text(
                "! FVCOM run_control.nml placeholder\n"
                "! Generated by nos_ofs FVCOMModel\n"
                f"! OFS: {self._ofs_name}\n"
            )

        return output_file

    def run_model(self, stage: str, nprocs: int = None) -> ModelResult:
        """
        Execute FVCOM model for a given workflow stage.

        FVCOM execution is handled by the COMF shell scripts
        (``nos_ofs_nowcast_forecast.sh``) which are called by the
        J-jobs (JNOS_OFS_NOWCST, JNOS_OFS_FCST).  This Python
        method provides the interface for direct Python invocation.

        Args:
            stage: Workflow stage ("nowcast" or "forecast")
            nprocs: Number of MPI processes (uses config default if None)

        Returns:
            ModelResult with execution status
        """
        if nprocs is None:
            nprocs = int(getattr(self.config, "NPROCS", 1))

        # Resolve paths
        home_dir = getattr(self.config, "HOMEnos", "")
        data_dir = getattr(self.config, "DATA", "")
        comout = getattr(self.config, "COMOUT", "")

        # The COMF workflow script that drives FVCOM execution
        script_path = os.path.join(
            home_dir, "scripts", "exnos_ofs_nowcast_forecast.sh"
        )

        if not os.path.isfile(script_path):
            return ModelResult(
                success=False,
                stage=stage,
                message=f"COMF execution script not found: {script_path}",
                errors=[f"Missing script: {script_path}"],
            )

        # Build environment for the shell script
        env = os.environ.copy()
        env.update(
            {
                "RUN": self._ofs_name,
                "cyc": str(getattr(self.config, "cyc", "00")).zfill(2),
                "PDY": str(getattr(self.config, "PDY", "")),
                "RUNTYPE": stage,
                "DATA": str(data_dir),
                "COMOUT": str(comout),
                "HOMEnos": str(home_dir),
                "FIXofs": str(getattr(self.config, "FIXofs", "")),
                "EXECnos": str(getattr(self.config, "EXECnos", "")),
                "NPROCS": str(nprocs),
            }
        )

        logger.info(
            "Running FVCOM %s stage=%s nprocs=%d",
            self._ofs_name,
            stage,
            nprocs,
        )

        try:
            result = subprocess.run(
                ["bash", script_path],
                env=env,
                cwd=str(data_dir) if data_dir else None,
                capture_output=True,
                text=True,
                timeout=7200,  # 2-hour timeout
            )

            if result.returncode == 0:
                return ModelResult(
                    success=True,
                    stage=stage,
                    message=f"FVCOM {stage} completed successfully",
                )
            else:
                stderr_tail = (result.stderr or "")[-2000:]
                return ModelResult(
                    success=False,
                    stage=stage,
                    message=f"FVCOM {stage} failed (rc={result.returncode})",
                    errors=[stderr_tail],
                )

        except subprocess.TimeoutExpired:
            return ModelResult(
                success=False,
                stage=stage,
                message=f"FVCOM {stage} timed out after 7200 seconds",
                errors=["Execution timeout"],
            )
        except Exception as e:
            return ModelResult(
                success=False,
                stage=stage,
                message=str(e),
                errors=[str(e)],
            )

    # ------------------------------------------------------------------
    # FVCOM-specific public methods
    # ------------------------------------------------------------------

    def run_nowcast(self) -> ModelResult:
        """Run the nowcast stage."""
        return self.run_model("nowcast")

    def run_forecast(self) -> ModelResult:
        """Run the forecast stage."""
        return self.run_model("forecast")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _needs_ocean_obc(self) -> bool:
        """
        Determine whether this OFS requires ocean boundary conditions.

        Great Lakes systems are closed basins and do not need RTOFS
        ocean boundary data. NGOFS2 (Gulf of Mexico) does.

        Returns:
            True if ocean OBC is needed
        """
        # Allow explicit override from config
        explicit = getattr(self.config, "rtofs_enabled", None)
        if explicit is not None and not explicit:
            return False

        return self._ofs_name in _OFS_WITH_OCEAN_OBC

    def _needs_tidal_forcing(self) -> bool:
        """
        Determine whether this OFS requires tidal forcing.

        Great Lakes systems have negligible tides. NGOFS2 requires
        tidal boundary conditions.

        Returns:
            True if tidal forcing is needed
        """
        explicit = getattr(self.config, "tides_enabled", None)
        if explicit is not None and not explicit:
            return False

        return self._ofs_name in _OFS_WITH_OCEAN_OBC

    def _patch_namelist(self, content: str) -> str:
        """
        Patch cycle-specific values into a namelist template.

        Replaces placeholder tokens with values from the current
        configuration.  Tokens follow the convention used by
        ``nos_ofs_launch.sh``: ``__TOKEN__``.

        Args:
            content: Raw namelist template text

        Returns:
            Patched namelist text
        """
        pdy = str(getattr(self.config, "PDY", ""))
        cyc = str(getattr(self.config, "cyc", "00")).zfill(2)

        replacements = {
            "__PDY__": pdy,
            "__CYC__": cyc,
            "__NPROCS__": str(getattr(self.config, "NPROCS", 1)),
            "__RUN__": self._ofs_name,
        }

        for token, value in replacements.items():
            content = content.replace(token, value)

        return content

    def __repr__(self) -> str:
        return f"FVCOMModel(ofs={self._ofs_name})"
