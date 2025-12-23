"""
NOS OFS Unified Python Package

This package provides a unified API for NOAA's Operational Ocean Forecast Systems,
supporting both IT-STOFS (STOFS-3D) and nosofs/COMF frameworks.

Directory Structure (NCO Standard):
    nos_ofs/
    ├── ecf/                    # ECFLOW scripts
    ├── jobs/                   # J-jobs (job control)
    ├── scripts/                # Ex-scripts (execution)
    ├── ush/                    # Utility scripts
    │   ├── python/nos_ofs/     # This package
    │   └── stofs_3d_atl/       # STOFS shell utilities
    ├── parm/                   # Configuration files (YAML)
    ├── fix/                    # Static input files
    ├── exec/                   # Compiled executables
    └── sorc/                   # Source code

Usage:
    from nos_ofs import OFSConfig, OFSRegistry
    from nos_ofs.forcing import GFSProcessor, RTOFSProcessor, NWMProcessor

    # Load configuration
    config = OFSConfig.from_yaml("stofs_3d_atl.yaml")

    # Create model instance
    model = OFSRegistry.create_model("stofs_3d_atl")
"""

__version__ = "1.0.0"

# Core components
from .base import ForcingProcessor, ForcingResult
from .base_model import BaseModel
from .registry import OFSRegistry

# Configuration
from .config import OFSConfig

# Aliases for backward compatibility
StofsConfig = OFSConfig
ComfConfig = OFSConfig

# Convenience imports - forcing processors
try:
    from .forcing import (
        GFSProcessor,
        HRRRProcessor,
        NAMProcessor,
        RTOFSProcessor,
        ADTProcessor,
        NWMProcessor,
        StLawrenceProcessor,
        TidalProcessor,
    )
except ImportError:
    # Some processors may not be available
    pass

__all__ = [
    # Version
    "__version__",
    # Base classes
    "ForcingProcessor",
    "ForcingResult",
    "BaseModel",
    "OFSRegistry",
    # Configuration
    "OFSConfig",
    "StofsConfig",
    "ComfConfig",
    # Forcing processors
    "GFSProcessor",
    "HRRRProcessor",
    "NAMProcessor",
    "RTOFSProcessor",
    "ADTProcessor",
    "NWMProcessor",
    "StLawrenceProcessor",
    "TidalProcessor",
]
