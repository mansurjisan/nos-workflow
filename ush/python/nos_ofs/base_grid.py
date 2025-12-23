"""
Base Grid Abstract Class

Handles model grid operations for different grid types:
- Structured grids (ROMS)
- Unstructured grids (SCHISM, FVCOM)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional
import numpy as np


@dataclass
class GridInfo:
    """Basic grid information."""
    n_nodes: int
    n_elements: int
    n_levels: int
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float
    depth_min: float
    depth_max: float


class BaseGrid(ABC):
    """
    Abstract base class for model grid handling.

    Handles grid file reading, node/element access, and coordinate
    transformations for different model types.
    """

    def __init__(self, config: 'OFSConfig'):
        """
        Initialize grid handler.

        Args:
            config: OFS configuration object
        """
        self.config = config
        self._grid_file = self._get_grid_file()
        self._loaded = False
        self._info: Optional[GridInfo] = None

    @abstractmethod
    def _get_grid_file(self) -> Path:
        """
        Get path to primary grid file.

        For SCHISM: hgrid.gr3
        For FVCOM: *.grd.dat
        For ROMS: grid netCDF file

        Returns:
            Path to grid file
        """
        pass

    @abstractmethod
    def load(self) -> None:
        """Load grid data from file(s)."""
        pass

    @abstractmethod
    def get_nodes(self) -> np.ndarray:
        """
        Get node coordinates.

        Returns:
            Array of shape (n_nodes, 3) with [lon, lat, depth]
        """
        pass

    @abstractmethod
    def get_elements(self) -> np.ndarray:
        """
        Get element connectivity.

        Returns:
            Array of shape (n_elements, max_nodes_per_element)
        """
        pass

    @abstractmethod
    def get_boundary_nodes(self, boundary_id: int = None) -> np.ndarray:
        """
        Get open boundary node indices.

        Args:
            boundary_id: Specific boundary ID (None for all boundaries)

        Returns:
            Array of boundary node indices
        """
        pass

    def validate(self) -> bool:
        """
        Validate that grid files exist and are readable.

        Returns:
            True if grid is valid
        """
        if not self._grid_file.exists():
            return False

        try:
            self.load()
            return True
        except Exception:
            return False

    def get_info(self) -> GridInfo:
        """
        Get basic grid information.

        Returns:
            GridInfo dataclass with grid statistics
        """
        if not self._loaded:
            self.load()
        return self._info

    def get_bounding_box(self) -> Tuple[float, float, float, float]:
        """
        Get grid bounding box.

        Returns:
            Tuple of (lon_min, lon_max, lat_min, lat_max)
        """
        info = self.get_info()
        return (info.lon_min, info.lon_max, info.lat_min, info.lat_max)

    def find_nearest_node(self, lon: float, lat: float) -> int:
        """
        Find nearest grid node to a point.

        Args:
            lon: Longitude
            lat: Latitude

        Returns:
            Node index
        """
        nodes = self.get_nodes()
        dist = np.sqrt((nodes[:, 0] - lon) ** 2 + (nodes[:, 1] - lat) ** 2)
        return int(np.argmin(dist))

    @property
    def grid_file(self) -> Path:
        """Path to primary grid file."""
        return self._grid_file

    def __repr__(self) -> str:
        if self._info:
            return f"{self.__class__.__name__}(nodes={self._info.n_nodes}, elements={self._info.n_elements})"
        return f"{self.__class__.__name__}(file={self._grid_file})"
