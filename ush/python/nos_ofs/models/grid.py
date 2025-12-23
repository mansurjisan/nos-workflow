"""
SCHISM Grid Handler

Handles SCHISM grid files (hgrid.gr3, vgrid.in) and provides
node/element access for forcing interpolation.
"""

from pathlib import Path
from typing import List, Optional
import numpy as np

from ..base_grid import BaseGrid, GridInfo
from ..config import OFSConfig


class SCHISMGrid(BaseGrid):
    """
    SCHISM grid handler.

    Reads and provides access to SCHISM unstructured grid files:
    - hgrid.gr3: Horizontal grid (nodes, elements, boundaries)
    - vgrid.in: Vertical grid (sigma/z-levels)
    """

    def __init__(self, config: OFSConfig):
        """
        Initialize SCHISM grid handler.

        Args:
            config: OFS configuration
        """
        super().__init__(config)

        self._nodes = None
        self._elements = None
        self._boundaries = None
        self._vgrid = None

    def _get_grid_file(self) -> Path:
        """Get path to hgrid.gr3 file."""
        fix_dir = Path(self.config.FIXofs)

        # Try common naming patterns
        patterns = [
            f"{self.config.RUN}_hgrid.gr3",
            f"{self.config.RUN}.hgrid.gr3",
            "hgrid.gr3",
            self.config.grid_file,
        ]

        for pattern in patterns:
            if pattern:
                grid_file = fix_dir / pattern
                if grid_file.exists():
                    return grid_file

        # Return default path even if not found
        return fix_dir / f"{self.config.RUN}_hgrid.gr3"

    def load(self) -> None:
        """Load grid data from hgrid.gr3 file."""
        if self._loaded:
            return

        grid_file = self._grid_file
        if not grid_file.exists():
            raise FileNotFoundError(f"Grid file not found: {grid_file}")

        self._read_hgrid(grid_file)
        self._loaded = True

    def _read_hgrid(self, filepath: Path) -> None:
        """
        Read SCHISM hgrid.gr3 format.

        Format:
            header
            n_elements n_nodes
            node_id x y depth (for each node)
            elem_id n_nodes node1 node2 node3 [node4] (for each element)
            n_open_boundaries
            ...
        """
        with open(filepath, 'r') as f:
            # Skip header
            f.readline()

            # Read counts
            line = f.readline().split()
            n_elements = int(line[0])
            n_nodes = int(line[1])

            # Read nodes
            self._nodes = np.zeros((n_nodes, 3))
            for i in range(n_nodes):
                parts = f.readline().split()
                # node_id, x, y, depth
                self._nodes[i, 0] = float(parts[1])  # lon/x
                self._nodes[i, 1] = float(parts[2])  # lat/y
                self._nodes[i, 2] = float(parts[3])  # depth

            # Read elements (support triangles and quads)
            self._elements = []
            for i in range(n_elements):
                parts = f.readline().split()
                n_elem_nodes = int(parts[1])
                nodes = [int(parts[j]) - 1 for j in range(2, 2 + n_elem_nodes)]
                self._elements.append(nodes)

            # Read open boundaries
            try:
                n_open = int(f.readline().split()[0])
                total_open_nodes = int(f.readline().split()[0])

                self._boundaries = []
                for _ in range(n_open):
                    n_bnd_nodes = int(f.readline().split()[0])
                    bnd_nodes = []
                    for _ in range(n_bnd_nodes):
                        bnd_nodes.append(int(f.readline().split()[0]) - 1)
                    self._boundaries.append(np.array(bnd_nodes))
            except (ValueError, IndexError):
                self._boundaries = []

        # Create grid info
        self._info = GridInfo(
            n_nodes=n_nodes,
            n_elements=n_elements,
            n_levels=self.config.n_levels,
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
            List of element node indices (variable length per element)
        """
        if not self._loaded:
            self.load()
        # Pad to max size for numpy array
        max_nodes = max(len(e) for e in self._elements)
        elements = np.full((len(self._elements), max_nodes), -1, dtype=int)
        for i, elem in enumerate(self._elements):
            elements[i, :len(elem)] = elem
        return elements

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

        # Return all boundary nodes
        return np.concatenate(self._boundaries)

    def get_vgrid_file(self) -> Path:
        """Get path to vgrid.in file."""
        fix_dir = Path(self.config.FIXofs)

        patterns = [
            f"{self.config.RUN}_vgrid.in",
            f"{self.config.RUN}.vgrid.in",
            "vgrid.in",
            self.config.vgrid_file,
        ]

        for pattern in patterns:
            if pattern:
                vgrid_file = fix_dir / pattern
                if vgrid_file.exists():
                    return vgrid_file

        return fix_dir / f"{self.config.RUN}_vgrid.in"

    def __repr__(self) -> str:
        if self._info:
            return f"SCHISMGrid(nodes={self._info.n_nodes}, elements={self._info.n_elements})"
        return f"SCHISMGrid(file={self._grid_file})"
