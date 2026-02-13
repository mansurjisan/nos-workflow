"""
FVCOM Grid Handler

Handles FVCOM unstructured triangular grid files and provides
node/element access for forcing interpolation.

FVCOM grids use three primary files:
- *_grd.dat: Node coordinates and element connectivity
- *_dep.dat: Bathymetry depths at nodes
- *_obc.dat: Open boundary node definitions

The grid is an unstructured triangular mesh with sigma-coordinate
vertical discretization.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from ..base_grid import BaseGrid, GridInfo
from ..config import OFSConfig

log = logging.getLogger(__name__)


class FVCOMGrid(BaseGrid):
    """
    FVCOM unstructured triangular grid handler.

    Reads and provides access to FVCOM grid files:
    - *_grd.dat: Node positions and triangular element connectivity
    - *_dep.dat: Node depth values
    - *_obc.dat: Open boundary node lists

    FVCOM OFS systems using this handler:
    - LEOFS (Lake Erie)
    - LOOFS (Lake Ontario)
    - LMHOFS (Lake Michigan-Huron)
    - LSOFS (Lake Superior)
    - NGOFS2 (Northern Gulf of Mexico)
    - SFBOFS (San Francisco Bay)
    - SSCOFS (Salish Sea/Columbia River)
    """

    def __init__(self, config: OFSConfig):
        """
        Initialize FVCOM grid handler.

        Args:
            config: OFS configuration
        """
        super().__init__(config)

        # Grid arrays (populated on load)
        self._nodes = None          # (n_nodes, 3) [lon, lat, depth]
        self._elements = None       # (n_elements, 3) triangular connectivity
        self._boundaries = None     # List of boundary node arrays
        self._node_depths = None    # Separate depth array from dep.dat

        # Grid dimensions
        self._n_nodes = 0
        self._n_elements = 0

    def _get_grid_file(self) -> Path:
        """Get path to FVCOM grid file (*_grd.dat)."""
        fix_dir = Path(getattr(self.config, 'FIXofs', '/tmp'))
        run_name = getattr(self.config, 'RUN', 'fvcom')

        # Try common naming patterns from COMF conventions
        patterns = [
            f"{run_name}_grd.dat",
            f"{run_name}.grd.dat",
            f"{run_name}_grid.dat",
        ]

        # Check YAML config for explicit grid file name
        grid_file_cfg = None
        if hasattr(self.config, '_yaml_data'):
            grid_cfg = self.config._yaml_data.get('grid', {})
            files_cfg = grid_cfg.get('files', {})
            grid_file_cfg = files_cfg.get('horizontal')
        elif hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            files_cfg = self.config.system._raw.get('grid', {}).get('files', {})
            grid_file_cfg = files_cfg.get('horizontal')

        if grid_file_cfg:
            patterns.insert(0, grid_file_cfg)

        for pattern in patterns:
            if pattern:
                grid_file = fix_dir / pattern
                if grid_file.exists():
                    return grid_file

        # Return default path even if not found
        return fix_dir / f"{run_name}_grd.dat"

    def _get_depth_file(self) -> Path:
        """Get path to FVCOM depth file (*_dep.dat)."""
        fix_dir = Path(getattr(self.config, 'FIXofs', '/tmp'))
        run_name = getattr(self.config, 'RUN', 'fvcom')

        patterns = [
            f"{run_name}_dep.dat",
            f"{run_name}.dep.dat",
        ]

        # Check YAML config
        depth_file_cfg = None
        if hasattr(self.config, '_yaml_data'):
            files_cfg = self.config._yaml_data.get('grid', {}).get('files', {})
            depth_file_cfg = files_cfg.get('depth')
        elif hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            files_cfg = self.config.system._raw.get('grid', {}).get('files', {})
            depth_file_cfg = files_cfg.get('depth')

        if depth_file_cfg:
            patterns.insert(0, depth_file_cfg)

        for pattern in patterns:
            if pattern:
                depth_file = fix_dir / pattern
                if depth_file.exists():
                    return depth_file

        return fix_dir / f"{run_name}_dep.dat"

    def _get_obc_file(self) -> Path:
        """Get path to FVCOM open boundary file (*_obc.dat)."""
        fix_dir = Path(getattr(self.config, 'FIXofs', '/tmp'))
        run_name = getattr(self.config, 'RUN', 'fvcom')

        patterns = [
            f"{run_name}_obc.dat",
            f"{run_name}.obc.dat",
        ]

        # Check YAML config
        obc_file_cfg = None
        if hasattr(self.config, '_yaml_data'):
            files_cfg = self.config._yaml_data.get('grid', {}).get('files', {})
            obc_file_cfg = files_cfg.get('obc')
        elif hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            files_cfg = self.config.system._raw.get('grid', {}).get('files', {})
            obc_file_cfg = files_cfg.get('obc')

        if obc_file_cfg:
            patterns.insert(0, obc_file_cfg)

        for pattern in patterns:
            if pattern:
                obc_file = fix_dir / pattern
                if obc_file.exists():
                    return obc_file

        return fix_dir / f"{run_name}_obc.dat"

    def load(self) -> None:
        """Load grid data from FVCOM grid files."""
        if self._loaded:
            return

        grid_file = self._grid_file
        if not grid_file.exists():
            raise FileNotFoundError(f"FVCOM grid file not found: {grid_file}")

        self._read_grd_dat(grid_file)

        # Read depths from separate file if available
        depth_file = self._get_depth_file()
        if depth_file.exists():
            self._read_dep_dat(depth_file)

        # Read open boundary nodes
        obc_file = self._get_obc_file()
        if obc_file.exists():
            self._read_obc_dat(obc_file)
        else:
            self._boundaries = []

        self._loaded = True

    def _read_grd_dat(self, filepath: Path) -> None:
        """
        Read FVCOM grid file (*_grd.dat).

        Format:
            Node Number = n_nodes
            Cell Number = n_elements
            node_id  x  y  depth
            ...
            elem_id  n1  n2  n3
            ...

        Some FVCOM grid files use a simpler format:
            n_nodes  n_elements
            node_id  x  y  h
            ...
            elem_id  n1  n2  n3
            ...
        """
        with open(filepath, 'r') as f:
            lines = f.readlines()

        # Determine format by examining first lines
        idx = 0
        n_nodes = 0
        n_elements = 0

        # Skip comment lines
        while idx < len(lines) and lines[idx].strip().startswith('!'):
            idx += 1

        # Check for header format
        first_line = lines[idx].strip()
        if first_line.startswith('Node'):
            # Format: "Node Number = XXXX"
            n_nodes = int(first_line.split('=')[1].strip())
            idx += 1
            n_elements = int(lines[idx].split('=')[1].strip())
            idx += 1
        else:
            # Simple format: "n_nodes n_elements" or "n_elements n_nodes"
            parts = first_line.split()
            if len(parts) >= 2:
                n_elements = int(parts[0])
                n_nodes = int(parts[1])
            idx += 1

        self._n_nodes = n_nodes
        self._n_elements = n_elements

        # Read nodes
        self._nodes = np.zeros((n_nodes, 3))
        for i in range(n_nodes):
            parts = lines[idx].split()
            if len(parts) >= 4:
                # node_id, x, y, depth
                self._nodes[i, 0] = float(parts[1])  # lon/x
                self._nodes[i, 1] = float(parts[2])  # lat/y
                self._nodes[i, 2] = float(parts[3])  # depth
            elif len(parts) >= 3:
                self._nodes[i, 0] = float(parts[0])
                self._nodes[i, 1] = float(parts[1])
                self._nodes[i, 2] = float(parts[2]) if len(parts) > 2 else 0.0
            idx += 1

        # Read elements (triangular connectivity)
        self._elements = np.zeros((n_elements, 3), dtype=int)
        for i in range(n_elements):
            if idx < len(lines):
                parts = lines[idx].split()
                if len(parts) >= 4:
                    # elem_id, n1, n2, n3
                    self._elements[i, 0] = int(parts[1]) - 1
                    self._elements[i, 1] = int(parts[2]) - 1
                    self._elements[i, 2] = int(parts[3]) - 1
                elif len(parts) >= 3:
                    self._elements[i, 0] = int(parts[0]) - 1
                    self._elements[i, 1] = int(parts[1]) - 1
                    self._elements[i, 2] = int(parts[2]) - 1
                idx += 1

        # Get n_levels from config
        n_levels = 21  # FVCOM default sigma levels
        if hasattr(self.config, '_yaml_data'):
            model_cfg = self.config._yaml_data.get('model', {})
            vert_cfg = model_cfg.get('vertical', {})
            n_levels = vert_cfg.get('kb', n_levels)
        grid_cfg_levels = None
        if hasattr(self.config, '_yaml_data'):
            grid_cfg_levels = self.config._yaml_data.get('grid', {}).get('n_levels')
        if grid_cfg_levels:
            n_levels = grid_cfg_levels

        # Create grid info
        self._info = GridInfo(
            n_nodes=n_nodes,
            n_elements=n_elements,
            n_levels=n_levels,
            lon_min=float(self._nodes[:, 0].min()),
            lon_max=float(self._nodes[:, 0].max()),
            lat_min=float(self._nodes[:, 1].min()),
            lat_max=float(self._nodes[:, 1].max()),
            depth_min=float(self._nodes[:, 2].min()),
            depth_max=float(self._nodes[:, 2].max()),
        )

        log.info(
            f"Loaded FVCOM grid: {n_nodes} nodes, {n_elements} elements, "
            f"lon=[{self._info.lon_min:.2f}, {self._info.lon_max:.2f}], "
            f"lat=[{self._info.lat_min:.2f}, {self._info.lat_max:.2f}]"
        )

    def _read_dep_dat(self, filepath: Path) -> None:
        """
        Read FVCOM depth file (*_dep.dat).

        Format:
            Node Number = n_nodes
            node_id  depth
            ...

        Or simple format:
            n_nodes
            depth1
            depth2
            ...
        """
        with open(filepath, 'r') as f:
            lines = f.readlines()

        idx = 0
        # Skip comments
        while idx < len(lines) and lines[idx].strip().startswith('!'):
            idx += 1

        first_line = lines[idx].strip()
        if first_line.startswith('Node'):
            n_nodes = int(first_line.split('=')[1].strip())
            idx += 1
        else:
            parts = first_line.split()
            n_nodes = int(parts[0])
            idx += 1

        self._node_depths = np.zeros(n_nodes)
        for i in range(n_nodes):
            if idx < len(lines):
                parts = lines[idx].split()
                if len(parts) >= 2:
                    self._node_depths[i] = float(parts[1])
                else:
                    self._node_depths[i] = float(parts[0])
                idx += 1

        # Update node depths if we loaded them separately
        if self._nodes is not None and len(self._node_depths) == len(self._nodes):
            self._nodes[:, 2] = self._node_depths

            # Update grid info with new depth range
            if self._info:
                self._info = GridInfo(
                    n_nodes=self._info.n_nodes,
                    n_elements=self._info.n_elements,
                    n_levels=self._info.n_levels,
                    lon_min=self._info.lon_min,
                    lon_max=self._info.lon_max,
                    lat_min=self._info.lat_min,
                    lat_max=self._info.lat_max,
                    depth_min=float(self._node_depths.min()),
                    depth_max=float(self._node_depths.max()),
                )

    def _read_obc_dat(self, filepath: Path) -> None:
        """
        Read FVCOM open boundary file (*_obc.dat).

        Format varies by FVCOM version:

        Format 1 (with header):
            OBC Node Number = n_obc
            obc_index  node_id  obc_type
            ...

        Format 2 (simple list):
            n_obc
            node_id
            node_id
            ...
        """
        self._boundaries = []

        with open(filepath, 'r') as f:
            lines = f.readlines()

        idx = 0
        # Skip comments
        while idx < len(lines) and lines[idx].strip().startswith('!'):
            idx += 1

        if not lines[idx:]:
            return

        first_line = lines[idx].strip()
        if 'OBC' in first_line.upper() or 'Node' in first_line:
            n_obc = int(first_line.split('=')[1].strip())
            idx += 1
        else:
            parts = first_line.split()
            n_obc = int(parts[0])
            idx += 1

        obc_nodes = []
        for i in range(n_obc):
            if idx < len(lines):
                parts = lines[idx].split()
                if len(parts) >= 2:
                    # Format: obc_index node_id [type]
                    node_id = int(parts[1]) - 1  # Convert to 0-indexed
                else:
                    node_id = int(parts[0]) - 1
                obc_nodes.append(node_id)
                idx += 1

        if obc_nodes:
            self._boundaries = [np.array(obc_nodes)]

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
        Get triangular element connectivity.

        Returns:
            Array of shape (n_elements, 3) with node indices
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

    # =========================================================================
    # FVCOM-Specific Grid Methods
    # =========================================================================

    def get_element_centers(self) -> np.ndarray:
        """
        Compute element center coordinates.

        Returns:
            Array of shape (n_elements, 3) with [lon, lat, depth] at centers
        """
        if not self._loaded:
            self.load()

        centers = np.zeros((self._n_elements, 3))
        for i in range(self._n_elements):
            n0, n1, n2 = self._elements[i]
            centers[i] = (self._nodes[n0] + self._nodes[n1] + self._nodes[n2]) / 3.0

        return centers

    def get_element_areas(self) -> np.ndarray:
        """
        Compute triangular element areas using the cross product method.

        Returns:
            Array of element areas (in coordinate units squared)
        """
        if not self._loaded:
            self.load()

        areas = np.zeros(self._n_elements)
        for i in range(self._n_elements):
            n0, n1, n2 = self._elements[i]
            x0, y0 = self._nodes[n0, 0], self._nodes[n0, 1]
            x1, y1 = self._nodes[n1, 0], self._nodes[n1, 1]
            x2, y2 = self._nodes[n2, 0], self._nodes[n2, 1]
            areas[i] = abs(
                (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            ) / 2.0

        return areas

    def get_node_depths(self) -> np.ndarray:
        """Get depth values at nodes."""
        if not self._loaded:
            self.load()
        return self._nodes[:, 2]

    def get_grid_dimensions(self) -> Tuple[int, int]:
        """
        Get grid dimensions (n_nodes, n_elements).

        Returns:
            Tuple of (n_nodes, n_elements)
        """
        if not self._loaded:
            self.load()
        return (self._n_nodes, self._n_elements)

    def has_open_boundary(self) -> bool:
        """Check if the grid has open boundary nodes defined."""
        if not self._loaded:
            self.load()
        return bool(self._boundaries)

    def __repr__(self) -> str:
        if self._info:
            return (
                f"FVCOMGrid(nodes={self._info.n_nodes}, "
                f"elements={self._info.n_elements})"
            )
        return f"FVCOMGrid(file={self._grid_file})"
