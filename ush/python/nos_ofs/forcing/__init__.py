"""
Forcing Processors Package

This package provides forcing data processors for NOS OFS models:
- Atmospheric: GFS, HRRR, NAM
- Ocean: RTOFS, ADT
- River: NWM, St. Lawrence
- Tidal: TPXO9, FES2014
- Fortran Wrappers: LEGACY / DEPRECATED -- kept for backward compatibility

Each processor is **fully native Python** (xarray, netCDF4, numpy, scipy).
No subprocess calls to NCO tools (ncks, ncrcat, ncap2, ncatted, ncrename)
or Fortran executables (gen_3Dth_from_hycom, gen_nudge_from_hycom, tide_fac)
are required.

Usage:
    from nos_ofs.forcing import GFSProcessor, NWMProcessor, RTOFSProcessor

    # Create processors with config
    rtofs = RTOFSProcessor(config, input_path, output_path)
    result = rtofs.process()

    if result.success:
        print(f"Created files: {result.output_files}")
"""

import warnings as _warnings

from ..base import ForcingProcessor, ForcingResult
from .gfs import GFSProcessor
from .hrrr import HRRRProcessor
from .nam import NAMProcessor
from .rtofs import RTOFSProcessor, RTOFSProcessingConfig, RTOFSFileSet
from .adt import ADTProcessor
from .nwm import NWMProcessor
from .st_lawrence import StLawrenceProcessor
from .tidal import TidalProcessor, compute_nodal_corrections

# LEGACY Fortran wrappers -- imported lazily to avoid deprecation warnings
# on every ``import nos_ofs.forcing``.  Explicitly importing them still works.


def __getattr__(name):
    """Lazy-load deprecated Fortran wrapper symbols."""
    _fortran_names = {
        "FortranWrapper",
        "FortranResult",
        "FortranExecutableNotFoundError",
        "MetFileSearchWrapper",
        "MetForcingWrapper",
        "RiverForcingWrapper",
        "OBCForcingWrapper",
        "TidalForcingWrapper",
        "get_fortran_wrappers",
    }
    if name in _fortran_names:
        from . import fortran_wrapper as _fw
        return getattr(_fw, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
    "RTOFSFileSet",
    "ADTProcessor",
    # River
    "NWMProcessor",
    "StLawrenceProcessor",
    # Tidal
    "TidalProcessor",
    "compute_nodal_corrections",
    # LEGACY Fortran Wrappers (deprecated -- lazy loaded)
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
