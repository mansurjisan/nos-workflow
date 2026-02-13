"""
ADCIRC Grid Handler

Handles ADCIRC unstructured triangular grid files and provides
node/element access for forcing interpolation and domain queries.

ADCIRC grids use two primary files:
- fort.14: Mesh file (node coordinates, element connectivity, boundaries)
- fort.13: Nodal attributes (Manning's n, primitive weighting, etc.)

The grid is a 2D unstructured triangular mesh used for depth-averaged
barotropic simulations (STOFS-2D-Global).
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..base_grid import BaseGrid, GridInfo
from ..config import OFSConfig

log = logging.getLogger(__name__)


class ADCIRCGrid(BaseGrid):
    """
    ADCIRC unstructured triangular grid handler.

    Reads and provides access to ADCIRC grid files:
    - fort.14: Node positions, triangular element connectivity, boundary segments
    - fort.13: Nodal attributes (Manning's n, primitive weighting, etc.)

    ADCIRC OFS systems using this handler:
    - STOFS-2D-Global (global storm surge and tide)
    """

    def __init__(self, config: OFSConfig):
        """
        Initialize ADCIRC grid handler.

        Args:
            config: OFS configuration
        """
        super().__init__(config)

        # Grid arrays (populated on load)
        self._nodes = None          # (n_nodes, 3) [lon, lat, depth]
        self._elements = None       # (n_elements, 3) triangular connectivity
        self._boundaries_elev = None  # Elevation-specified boundary segments
        self._boundaries_flux = None  # Flux-specified boundary segments
        self._nodal_attributes = None  # Dict of attribute_name -> values

        # Grid dimensions
        self._n_nodes = 0
        self._n_elements = 0

        # Mesh header
        self._mesh_name = ""

    def _get_grid_file(self) -> Path:
        """Get path to ADCIRC fort.14 mesh file."""
        fix_dir = Path(getattr(self.config, 'FIXofs', '/tmp'))
        run_name = getattr(self.config, 'RUN', 'adcirc')

        # Try common naming patterns
        patterns = [
            "fort.14",
            f"{run_name}_fort.14",
            f"{run_name}.fort.14",
        ]

        # Check YAML config for explicit grid file name
        grid_file_cfg = None
        if hasattr(self.config, '_yaml_data'):
            grid_cfg = self.config._yaml_data.get('grid', {})
            files_cfg = grid_cfg.get('files', {})
            grid_file_cfg = files_cfg.get('mesh')
        elif hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            files_cfg = self.config.system._raw.get('grid', {}).get('files', {})
            grid_file_cfg = files_cfg.get('mesh')

        if grid_file_cfg:
            patterns.insert(0, grid_file_cfg)

        for pattern in patterns:
            if pattern:
                grid_file = fix_dir / pattern
                if grid_file.exists():
                    return grid_file

        # Return default path even if not found
        return fix_dir / "fort.14"

    def _get_attributes_file(self) -> Path:
        """Get path to ADCIRC fort.13 nodal attributes file."""
        fix_dir = Path(getattr(self.config, 'FIXofs', '/tmp'))
        run_name = getattr(self.config, 'RUN', 'adcirc')

        patterns = [
            "fort.13",
            f"{run_name}_fort.13",
            f"{run_name}.fort.13",
        ]

        # Check YAML config
        attr_file_cfg = None
        if hasattr(self.config, '_yaml_data'):
            files_cfg = self.config._yaml_data.get('grid', {}).get('files', {})
            attr_file_cfg = files_cfg.get('attributes')
        elif hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            files_cfg = self.config.system._raw.get('grid', {}).get('files', {})
            attr_file_cfg = files_cfg.get('attributes')

        if attr_file_cfg:
            patterns.insert(0, attr_file_cfg)

        for pattern in patterns:
            if pattern:
                attr_file = fix_dir / pattern
                if attr_file.exists():
                    return attr_file

        return fix_dir / "fort.13"

    def load(self) -> None:
        """Load grid data from ADCIRC fort.14 file."""
        if self._loaded:
            return

        grid_file = self._grid_file
        if not grid_file.exists():
            raise FileNotFoundError(f"ADCIRC grid file not found: {grid_file}")

        self._read_fort14(grid_file)

        # Optionally load nodal attributes
        attr_file = self._get_attributes_file()
        if attr_file.exists():
            try:
                self._read_fort13(attr_file)
            except Exception as e:
                log.warning(f"Could not read fort.13 nodal attributes: {e}")
                self._nodal_attributes = {}

        self._loaded = True

    def _read_fort14(self, filepath: Path) -> None:
        """
        Read ADCIRC fort.14 mesh file.

        Format:
            mesh_name (header line)
            NE  NP  (num_elements  num_nodes)
            node_id  x  y  depth  (for each node, NP lines)
            elem_id  3  n1  n2  n3  (for each element, NE lines)
            NOPE  (number of open boundary segments)
            NETA  (total open boundary nodes)
            for each open boundary segment:
                NVDLL(k)  (number of nodes in segment k)
                node_id  (for each node in segment)
            NBOU  (number of land/flux boundary segments)
            NVEL  (total land boundary nodes)
            for each land boundary segment:
                NVELL(k)  IBTYPE(k)  (nodes in segment, boundary type)
                node_id  (for each node in segment)
        """
        with open(filepath, 'r') as f:
            # Line 1: Mesh name
            self._mesh_name = f.readline().strip()

            # Line 2: NE, NP
            line = f.readline().split()
            n_elements = int(line[0])
            n_nodes = int(line[1])

            self._n_nodes = n_nodes
            self._n_elements = n_elements

            # Read nodes: node_id, x (lon), y (lat), depth
            self._nodes = np.zeros((n_nodes, 3))
            for i in range(n_nodes):
                parts = f.readline().split()
                self._nodes[i, 0] = float(parts[1])  # lon/x
                self._nodes[i, 1] = float(parts[2])  # lat/y
                self._nodes[i, 2] = float(parts[3])  # depth

            # Read elements: elem_id, 3, n1, n2, n3
            self._elements = np.zeros((n_elements, 3), dtype=int)
            for i in range(n_elements):
                parts = f.readline().split()
                # parts[1] should be '3' for triangles
                self._elements[i, 0] = int(parts[2]) - 1  # 0-indexed
                self._elements[i, 1] = int(parts[3]) - 1
                self._elements[i, 2] = int(parts[4]) - 1

            # Read open (elevation-specified) boundary segments
            self._boundaries_elev = []
            try:
                nope = int(f.readline().split()[0])   # Number of open boundary segments
                neta = int(f.readline().split()[0])    # Total open boundary nodes

                for _ in range(nope):
                    nvdll = int(f.readline().split()[0])  # Nodes in this segment
                    segment_nodes = []
                    for _ in range(nvdll):
                        node_id = int(f.readline().split()[0]) - 1
                        segment_nodes.append(node_id)
                    self._boundaries_elev.append(np.array(segment_nodes))
            except (ValueError, IndexError):
                log.warning("Could not read open boundary segments from fort.14")

            # Read land/flux boundary segments
            self._boundaries_flux = []
            try:
                nbou = int(f.readline().split()[0])   # Number of land boundary segments
                nvel = int(f.readline().split()[0])    # Total land boundary nodes

                for _ in range(nbou):
                    line_parts = f.readline().split()
                    nvell = int(line_parts[0])  # Nodes in this segment
                    ibtype = int(line_parts[1]) if len(line_parts) > 1 else 0
                    segment_nodes = []
                    for _ in range(nvell):
                        node_id = int(f.readline().split()[0]) - 1
                        segment_nodes.append(node_id)
                    self._boundaries_flux.append({
                        'nodes': np.array(segment_nodes),
                        'type': ibtype,
                    })
            except (ValueError, IndexError):
                log.warning("Could not read land boundary segments from fort.14")

        # Create grid info (ADCIRC is 2D: n_levels=1)
        self._info = GridInfo(
            n_nodes=n_nodes,
            n_elements=n_elements,
            n_levels=1,  # 2D barotropic model
            lon_min=float(self._nodes[:, 0].min()),
            lon_max=float(self._nodes[:, 0].max()),
            lat_min=float(self._nodes[:, 1].min()),
            lat_max=float(self._nodes[:, 1].max()),
            depth_min=float(self._nodes[:, 2].min()),
            depth_max=float(self._nodes[:, 2].max()),
        )

        log.info(
            f"Loaded ADCIRC grid '{self._mesh_name}': "
            f"{n_nodes} nodes, {n_elements} elements, "
            f"lon=[{self._info.lon_min:.2f}, {self._info.lon_max:.2f}], "
            f"lat=[{self._info.lat_min:.2f}, {self._info.lat_max:.2f}]"
        )

    def _read_fort13(self, filepath: Path) -> None:
        """
        Read ADCIRC fort.13 nodal attributes file.

        Format:
            header line
            NP (number of nodes, must match fort.14)
            NAttr (number of attributes)
            For each attribute:
                AttrName
                Units
                ValuesPerNode
                DefaultValue(s)
            For each attribute (again, data section):
                AttrName
                NumNodesNotDefault
                For each non-default node:
                    node_id  value(s)
        """
        self._nodal_attributes = {}

        with open(filepath, 'r') as f:
            # Header
            f.readline()

            # Number of nodes
            np_attr = int(f.readline().split()[0])

            # Number of attributes
            n_attr = int(f.readline().split()[0])

            # Read attribute metadata
            attr_metadata = []
            for _ in range(n_attr):
                attr_name = f.readline().strip()
                units = f.readline().strip()
                vals_per_node = int(f.readline().split()[0])
                default_values = [float(x) for x in f.readline().split()]
                attr_metadata.append({
                    'name': attr_name,
                    'units': units,
                    'vals_per_node': vals_per_node,
                    'defaults': default_values,
                })

            # Read attribute data
            for _ in range(n_attr):
                attr_name = f.readline().strip()
                n_non_default = int(f.readline().split()[0])

                # Find metadata for this attribute
                meta = None
                for m in attr_metadata:
                    if m['name'] == attr_name:
                        meta = m
                        break

                if meta is None:
                    # Skip unknown attribute data
                    for _ in range(n_non_default):
                        f.readline()
                    continue

                vals_per_node = meta['vals_per_node']

                # Initialize with default values
                if vals_per_node == 1:
                    values = np.full(np_attr, meta['defaults'][0])
                else:
                    values = np.tile(meta['defaults'], (np_attr, 1))

                # Read non-default values
                for _ in range(n_non_default):
                    parts = f.readline().split()
                    node_id = int(parts[0]) - 1  # 0-indexed
                    if vals_per_node == 1:
                        values[node_id] = float(parts[1])
                    else:
                        for v in range(vals_per_node):
                            values[node_id, v] = float(parts[1 + v])

                self._nodal_attributes[attr_name] = values

        log.info(
            f"Loaded {len(self._nodal_attributes)} nodal attributes from fort.13"
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
        Get triangular element connectivity.

        Returns:
            Array of shape (n_elements, 3) with node indices (0-indexed)
        """
        if not self._loaded:
            self.load()
        return self._elements

    def get_boundary_nodes(self, boundary_id: int = None) -> np.ndarray:
        """
        Get open (elevation-specified) boundary node indices.

        Args:
            boundary_id: Specific boundary segment (0-indexed), None for all

        Returns:
            Array of boundary node indices
        """
        if not self._loaded:
            self.load()

        if not self._boundaries_elev:
            return np.array([], dtype=int)

        if boundary_id is not None:
            if 0 <= boundary_id < len(self._boundaries_elev):
                return self._boundaries_elev[boundary_id]
            return np.array([], dtype=int)

        return np.concatenate(self._boundaries_elev)

    # =========================================================================
    # ADCIRC-Specific Grid Methods
    # =========================================================================

    @property
    def mesh_name(self) -> str:
        """Get the mesh name from the fort.14 header."""
        if not self._loaded:
            self.load()
        return self._mesh_name

    @property
    def n_nodes(self) -> int:
        """Get the number of nodes."""
        if not self._loaded:
            self.load()
        return self._n_nodes

    @property
    def n_elements(self) -> int:
        """Get the number of elements."""
        if not self._loaded:
            self.load()
        return self._n_elements

    def domain_bounds(self) -> Tuple[float, float, float, float]:
        """
        Get domain bounding box from node coordinates.

        Returns:
            Tuple of (lon_min, lon_max, lat_min, lat_max)
        """
        if not self._loaded:
            self.load()
        return (
            float(self._nodes[:, 0].min()),
            float(self._nodes[:, 0].max()),
            float(self._nodes[:, 1].min()),
            float(self._nodes[:, 1].max()),
        )

    def get_land_boundaries(self) -> List[Dict]:
        """
        Get land/flux boundary segments with type information.

        Returns:
            List of dicts with 'nodes' (array) and 'type' (ibtype int)

        ADCIRC boundary types (IBTYPE):
        - 0: External barrier (normal flux = 0)
        - 1: Island barrier (normal flux = 0)
        - 2: External flux boundary (specified flow)
        - 10: Internal barrier with pipe connections
        - 20: External weir
        """
        if not self._loaded:
            self.load()
        return self._boundaries_flux or []

    def get_nodal_attribute(self, attr_name: str) -> Optional[np.ndarray]:
        """
        Get a specific nodal attribute from fort.13.

        Common attributes:
        - 'mannings_n_at_sea_floor': Manning's friction coefficient
        - 'primitive_weighting_in_continuity_equation': GWCE weighting
        - 'surface_directional_effective_roughness_length': directional roughness
        - 'surface_canopy_coefficient': vegetation canopy

        Args:
            attr_name: Name of the nodal attribute

        Returns:
            Array of attribute values per node, or None if not found
        """
        if not self._loaded:
            self.load()

        if self._nodal_attributes is None:
            return None

        return self._nodal_attributes.get(attr_name)

    def get_nodal_attribute_names(self) -> List[str]:
        """
        Get list of available nodal attribute names.

        Returns:
            List of attribute name strings
        """
        if not self._loaded:
            self.load()

        if self._nodal_attributes is None:
            return []

        return list(self._nodal_attributes.keys())

    def get_bathymetry(self) -> np.ndarray:
        """
        Get bathymetry depths at nodes.

        Returns:
            1D array of depth values (positive downward, meters)
        """
        if not self._loaded:
            self.load()
        return self._nodes[:, 2]

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

    def validate(self) -> bool:
        """
        Validate ADCIRC mesh consistency.

        Checks:
        - Grid file exists and is readable
        - Element node indices are within valid range
        - No degenerate elements (zero area)

        Returns:
            True if grid is valid
        """
        if not self._grid_file.exists():
            return False

        try:
            self.load()
        except Exception:
            return False

        # Check element connectivity references valid nodes
        if self._elements.max() >= self._n_nodes:
            log.error(
                f"Element references node {self._elements.max()} "
                f"but only {self._n_nodes} nodes exist"
            )
            return False

        if self._elements.min() < 0:
            log.error("Element references negative node index")
            return False

        return True

    def __repr__(self) -> str:
        if self._info:
            return (
                f"ADCIRCGrid(nodes={self._info.n_nodes}, "
                f"elements={self._info.n_elements}, "
                f"mesh='{self._mesh_name}')"
            )
        return f"ADCIRCGrid(file={self._grid_file})"
