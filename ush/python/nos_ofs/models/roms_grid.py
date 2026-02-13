"""
ROMS Grid Handler

Handles ROMS structured curvilinear grid files (NetCDF format) and provides
node/element access for forcing interpolation and domain queries.

ROMS grids use a staggered Arakawa C-grid with:
- rho points: cell centers (primary scalar variables)
- u points: east-west cell edges (u velocity)
- v points: north-south cell edges (v velocity)
- psi points: cell corners (vorticity)
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from ..base_grid import BaseGrid, GridInfo
from ..config import OFSConfig

log = logging.getLogger(__name__)


class ROMSGrid(BaseGrid):
    """
    ROMS structured curvilinear grid handler.

    Reads and provides access to ROMS grid NetCDF files containing:
    - lon_rho, lat_rho: Geographic coordinates at rho points
    - mask_rho: Land/sea mask (1=water, 0=land)
    - h: Bathymetry depth (meters, positive downward)
    - angle: Grid rotation angle (radians)
    - pm, pn: Inverse grid spacing (1/dx, 1/dy)

    ROMS OFS systems using this handler:
    - CBOFS (Chesapeake Bay)
    - DBOFS (Delaware Bay)
    - TBOFS (Tampa Bay)
    - GOMOFS (Gulf of Maine)
    - CIOFS (Cook Inlet)
    - WCOFS (West Coast)
    """

    def __init__(self, config: OFSConfig):
        """
        Initialize ROMS grid handler.

        Args:
            config: OFS configuration
        """
        super().__init__(config)

        # Grid arrays (populated on load)
        self._lon_rho = None
        self._lat_rho = None
        self._mask_rho = None
        self._h = None
        self._angle = None
        self._pm = None
        self._pn = None

        # Grid dimensions
        self._n_eta = 0  # Number of rows (eta direction)
        self._n_xi = 0   # Number of columns (xi direction)

    def _get_grid_file(self) -> Path:
        """Get path to ROMS grid NetCDF file."""
        fix_dir = Path(getattr(self.config, 'FIXofs', '/tmp'))

        # Try common naming patterns from COMF conventions
        run_name = getattr(self.config, 'RUN', 'roms')
        patterns = [
            f"{run_name}_grid.nc",
            f"{run_name}.grid.nc",
            f"{run_name}_grd.nc",
            "grid.nc",
        ]

        # Check YAML config for explicit grid file name
        grid_file_cfg = None
        if hasattr(self.config, '_yaml_data'):
            grid_cfg = self.config._yaml_data.get('grid', {})
            files_cfg = grid_cfg.get('files', {})
            grid_file_cfg = files_cfg.get('grid')
        elif hasattr(self.config, 'system'):
            grid_cfg = getattr(self.config, 'system', None)
            if grid_cfg and hasattr(grid_cfg, '_raw'):
                files_cfg = grid_cfg._raw.get('grid', {}).get('files', {})
                grid_file_cfg = files_cfg.get('grid')

        if grid_file_cfg:
            patterns.insert(0, grid_file_cfg)

        for pattern in patterns:
            if pattern:
                grid_file = fix_dir / pattern
                if grid_file.exists():
                    return grid_file

        # Return default path even if not found
        return fix_dir / f"{run_name}_grid.nc"

    def load(self) -> None:
        """Load grid data from ROMS grid NetCDF file."""
        if self._loaded:
            return

        grid_file = self._grid_file
        if not grid_file.exists():
            raise FileNotFoundError(f"ROMS grid file not found: {grid_file}")

        self._read_grid_netcdf(grid_file)
        self._loaded = True

    def _read_grid_netcdf(self, filepath: Path) -> None:
        """
        Read ROMS grid from NetCDF file.

        ROMS grid files contain at minimum:
        - lon_rho(eta_rho, xi_rho): Longitude at rho points
        - lat_rho(eta_rho, xi_rho): Latitude at rho points
        - h(eta_rho, xi_rho): Bathymetry (positive depth)
        - mask_rho(eta_rho, xi_rho): Land/sea mask

        Optional:
        - angle(eta_rho, xi_rho): Grid angle
        - pm(eta_rho, xi_rho): Curvilinear coordinate metric in XI
        - pn(eta_rho, xi_rho): Curvilinear coordinate metric in ETA
        """
        try:
            import netCDF4 as nc
        except ImportError:
            log.warning("netCDF4 not available, attempting xarray")
            try:
                import xarray as xr
                self._read_grid_xarray(filepath)
                return
            except ImportError:
                raise ImportError(
                    "Either netCDF4 or xarray is required to read ROMS grid files"
                )

        with nc.Dataset(filepath, 'r') as ds:
            # Read primary coordinate arrays
            self._lon_rho = ds.variables['lon_rho'][:].data
            self._lat_rho = ds.variables['lat_rho'][:].data

            # Grid dimensions
            self._n_eta, self._n_xi = self._lon_rho.shape

            # Bathymetry
            if 'h' in ds.variables:
                self._h = ds.variables['h'][:].data
            else:
                self._h = np.zeros_like(self._lon_rho)

            # Land/sea mask
            if 'mask_rho' in ds.variables:
                self._mask_rho = ds.variables['mask_rho'][:].data
            else:
                self._mask_rho = np.ones_like(self._lon_rho)

            # Grid angle
            if 'angle' in ds.variables:
                self._angle = ds.variables['angle'][:].data
            else:
                self._angle = np.zeros_like(self._lon_rho)

            # Curvilinear metrics
            if 'pm' in ds.variables:
                self._pm = ds.variables['pm'][:].data
            if 'pn' in ds.variables:
                self._pn = ds.variables['pn'][:].data

        # Determine n_levels from config
        n_levels = getattr(self.config, 'n_levels', 20)
        if hasattr(self.config, '_yaml_data'):
            model_cfg = self.config._yaml_data.get('model', {})
            vert_cfg = model_cfg.get('vertical', {})
            n_levels = vert_cfg.get('n', n_levels)

        # Compute water-only depth statistics
        water_mask = self._mask_rho > 0
        if water_mask.any():
            depth_min = float(self._h[water_mask].min())
            depth_max = float(self._h[water_mask].max())
        else:
            depth_min = float(self._h.min())
            depth_max = float(self._h.max())

        # Create grid info
        self._info = GridInfo(
            n_nodes=int(self._n_eta * self._n_xi),
            n_elements=int((self._n_eta - 1) * (self._n_xi - 1)),
            n_levels=n_levels,
            lon_min=float(self._lon_rho.min()),
            lon_max=float(self._lon_rho.max()),
            lat_min=float(self._lat_rho.min()),
            lat_max=float(self._lat_rho.max()),
            depth_min=depth_min,
            depth_max=depth_max,
        )

        log.info(
            f"Loaded ROMS grid: {self._n_eta}x{self._n_xi} "
            f"({self._info.n_nodes} nodes), "
            f"depth range [{depth_min:.1f}, {depth_max:.1f}] m"
        )

    def _read_grid_xarray(self, filepath: Path) -> None:
        """Fallback grid reader using xarray."""
        import xarray as xr

        ds = xr.open_dataset(filepath)

        self._lon_rho = ds['lon_rho'].values
        self._lat_rho = ds['lat_rho'].values
        self._n_eta, self._n_xi = self._lon_rho.shape

        self._h = ds['h'].values if 'h' in ds else np.zeros_like(self._lon_rho)
        self._mask_rho = ds['mask_rho'].values if 'mask_rho' in ds else np.ones_like(self._lon_rho)
        self._angle = ds['angle'].values if 'angle' in ds else np.zeros_like(self._lon_rho)

        if 'pm' in ds:
            self._pm = ds['pm'].values
        if 'pn' in ds:
            self._pn = ds['pn'].values

        ds.close()

        n_levels = getattr(self.config, 'n_levels', 20)
        water_mask = self._mask_rho > 0
        depth_min = float(self._h[water_mask].min()) if water_mask.any() else float(self._h.min())
        depth_max = float(self._h[water_mask].max()) if water_mask.any() else float(self._h.max())

        self._info = GridInfo(
            n_nodes=int(self._n_eta * self._n_xi),
            n_elements=int((self._n_eta - 1) * (self._n_xi - 1)),
            n_levels=n_levels,
            lon_min=float(self._lon_rho.min()),
            lon_max=float(self._lon_rho.max()),
            lat_min=float(self._lat_rho.min()),
            lat_max=float(self._lat_rho.max()),
            depth_min=depth_min,
            depth_max=depth_max,
        )

    def get_nodes(self) -> np.ndarray:
        """
        Get node coordinates as flattened array.

        For ROMS, "nodes" are rho-point locations flattened to 1D.

        Returns:
            Array of shape (n_nodes, 3) with [lon, lat, depth]
        """
        if not self._loaded:
            self.load()

        nodes = np.zeros((self._n_eta * self._n_xi, 3))
        nodes[:, 0] = self._lon_rho.ravel()
        nodes[:, 1] = self._lat_rho.ravel()
        nodes[:, 2] = self._h.ravel()
        return nodes

    def get_elements(self) -> np.ndarray:
        """
        Get element connectivity for structured grid.

        ROMS uses a structured curvilinear grid, so each "element"
        is a quadrilateral cell defined by four rho points.

        Returns:
            Array of shape (n_elements, 4) with node indices
        """
        if not self._loaded:
            self.load()

        n_cells_eta = self._n_eta - 1
        n_cells_xi = self._n_xi - 1
        n_elements = n_cells_eta * n_cells_xi

        elements = np.zeros((n_elements, 4), dtype=int)
        idx = 0
        for j in range(n_cells_eta):
            for i in range(n_cells_xi):
                # Four corners of the cell (counterclockwise)
                n0 = j * self._n_xi + i
                n1 = j * self._n_xi + (i + 1)
                n2 = (j + 1) * self._n_xi + (i + 1)
                n3 = (j + 1) * self._n_xi + i
                elements[idx] = [n0, n1, n2, n3]
                idx += 1

        return elements

    def get_boundary_nodes(self, boundary_id: int = None) -> np.ndarray:
        """
        Get open boundary node indices.

        For ROMS structured grids, boundaries are defined by the
        grid edges. By convention:
        - boundary 0: South (j=0)
        - boundary 1: East (i=n_xi-1)
        - boundary 2: North (j=n_eta-1)
        - boundary 3: West (i=0)

        Args:
            boundary_id: Specific boundary (0-3), None for all

        Returns:
            Array of boundary node indices
        """
        if not self._loaded:
            self.load()

        boundaries = {
            0: np.arange(self._n_xi),  # South
            1: np.arange(self._n_xi - 1, self._n_eta * self._n_xi, self._n_xi),  # East
            2: np.arange(
                (self._n_eta - 1) * self._n_xi,
                self._n_eta * self._n_xi,
            ),  # North
            3: np.arange(0, self._n_eta * self._n_xi, self._n_xi),  # West
        }

        if boundary_id is not None:
            if boundary_id in boundaries:
                return boundaries[boundary_id]
            return np.array([], dtype=int)

        # Return all boundary nodes (unique)
        all_bnd = np.concatenate(list(boundaries.values()))
        return np.unique(all_bnd)

    # =========================================================================
    # ROMS-Specific Grid Methods
    # =========================================================================

    def get_grid_dimensions(self) -> Tuple[int, int]:
        """
        Get grid dimensions (eta, xi).

        Returns:
            Tuple of (n_eta, n_xi) dimensions
        """
        if not self._loaded:
            self.load()
        return (self._n_eta, self._n_xi)

    def get_lon_rho(self) -> np.ndarray:
        """Get 2D longitude array at rho points."""
        if not self._loaded:
            self.load()
        return self._lon_rho

    def get_lat_rho(self) -> np.ndarray:
        """Get 2D latitude array at rho points."""
        if not self._loaded:
            self.load()
        return self._lat_rho

    def get_bathymetry(self) -> np.ndarray:
        """Get 2D bathymetry array (positive depth in meters)."""
        if not self._loaded:
            self.load()
        return self._h

    def get_mask(self) -> np.ndarray:
        """Get 2D land/sea mask (1=water, 0=land)."""
        if not self._loaded:
            self.load()
        return self._mask_rho

    def get_angle(self) -> np.ndarray:
        """Get 2D grid angle array (radians)."""
        if not self._loaded:
            self.load()
        return self._angle

    def get_metrics(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Get grid metrics (pm, pn).

        pm = 1/dx (inverse spacing in xi direction)
        pn = 1/dy (inverse spacing in eta direction)

        Returns:
            Tuple of (pm, pn) arrays, either may be None
        """
        if not self._loaded:
            self.load()
        return (self._pm, self._pn)

    def compute_grid_spacing(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Compute approximate grid spacing in meters.

        Uses the Haversine formula to compute distances between
        adjacent rho points.

        Returns:
            Tuple of (dx, dy) arrays in meters
        """
        if not self._loaded:
            self.load()

        if self._pm is not None and self._pn is not None:
            dx = 1.0 / self._pm
            dy = 1.0 / self._pn
            return (dx, dy)

        # Compute from coordinates using Haversine
        R = 6371000.0  # Earth radius in meters
        lon_rad = np.deg2rad(self._lon_rho)
        lat_rad = np.deg2rad(self._lat_rho)

        # dx: spacing in xi direction
        dlon = np.diff(lon_rad, axis=1)
        dlat = np.diff(lat_rad, axis=1)
        lat_avg = (lat_rad[:, :-1] + lat_rad[:, 1:]) / 2.0
        a = np.sin(dlat / 2) ** 2 + np.cos(lat_avg) * np.cos(lat_avg + dlat) * np.sin(dlon / 2) ** 2
        dx = 2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

        # dy: spacing in eta direction
        dlon = np.diff(lon_rad, axis=0)
        dlat = np.diff(lat_rad, axis=0)
        lat_avg = (lat_rad[:-1, :] + lat_rad[1:, :]) / 2.0
        a = np.sin(dlat / 2) ** 2 + np.cos(lat_avg) * np.cos(lat_avg + dlat) * np.sin(dlon / 2) ** 2
        dy = 2 * R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

        return (dx, dy)

    def get_water_points_count(self) -> int:
        """Get number of water (non-masked) rho points."""
        if not self._loaded:
            self.load()
        return int(np.sum(self._mask_rho > 0))

    def __repr__(self) -> str:
        if self._info:
            return (
                f"ROMSGrid(eta={self._n_eta}, xi={self._n_xi}, "
                f"nodes={self._info.n_nodes})"
            )
        return f"ROMSGrid(file={self._grid_file})"
