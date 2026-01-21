"""
Forcing Processors Package

This package provides forcing data processors for NOS OFS models:
- Atmospheric: GFS, HRRR, NAM
- Ocean: RTOFS, ADT
- River: NWM, St. Lawrence
- Tidal: TPXO9, FES2014
- Fortran Wrappers: Production executable wrappers

Each processor follows the ForcingProcessor interface and can be
used with any SCHISM-based OFS (STOFS-3D-ATL, SECOFS, etc.).

Usage:
    from nos_ofs.forcing import GFSProcessor, NWMProcessor, RTOFSProcessor

    # Create processors with config
    gfs = GFSProcessor(config, input_path, output_path)
    result = gfs.process()

    if result.success:
        print(f"Created files: {result.output_files}")

    # Or use Fortran wrappers for production compatibility
    from nos_ofs.forcing import get_fortran_wrappers

    wrappers = get_fortran_wrappers(model_type="SCHISM", exec_dir="/path/to/exec")
    result = wrappers["met_search"].search(time_start, time_end, ...)
"""

from ..base import ForcingProcessor, ForcingResult
from .gfs import GFSProcessor
from .hrrr import HRRRProcessor
from .nam import NAMProcessor
from .rtofs import RTOFSProcessor, RTOFSProcessingConfig
from .adt import ADTProcessor
from .nwm import NWMProcessor
from .st_lawrence import StLawrenceProcessor
from .tidal import TidalProcessor
from .fortran_wrapper import (
    FortranWrapper,
    FortranResult,
    FortranExecutableNotFoundError,
    MetFileSearchWrapper,
    MetForcingWrapper,
    RiverForcingWrapper,
    OBCForcingWrapper,
    TidalForcingWrapper,
    get_fortran_wrappers,
)

# Aliases for compatibility
BaseForcingProcessor = ForcingProcessor

__all__ = [
    # Base classes
    "BaseForcingProcessor",
    "ForcingProcessor",
    "ForcingResult",
    # Atmospheric
    "GFSProcessor",
    "HRRRProcessor",
    "NAMProcessor",
    # Ocean
    "RTOFSProcessor",
    "RTOFSProcessingConfig",
    "ADTProcessor",
    # River
    "NWMProcessor",
    "StLawrenceProcessor",
    # Tidal
    "TidalProcessor",
    # Fortran Wrappers
    "FortranWrapper",
    "FortranResult",
    "FortranExecutableNotFoundError",
    "MetFileSearchWrapper",
    "MetForcingWrapper",
    "RiverForcingWrapper",
    "OBCForcingWrapper",
    "TidalForcingWrapper",
    "get_fortran_wrappers",
]
