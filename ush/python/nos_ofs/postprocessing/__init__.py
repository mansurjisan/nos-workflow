"""
NOS OFS Post-Processing Package

Provides post-processing implementations for all model types:
- SCHISM: STOFS-3D (two-phase) and COMF SCHISM (single-phase)
- ROMS: CBOFS, DBOFS, TBOFS, GOMOFS, CIOFS, WCOFS
- FVCOM: LEOFS, LOOFS, LMHOFS, LSOFS, NGOFS2, SFBOFS, SSCOFS

Post-processing stages:
    1. extract_fields() - Extract 2D/3D fields from raw model output
    2. extract_stations() - Extract station timeseries
    3. create_standard_netcdf() - Convert to CO-OPS standard NetCDF with CF conventions
    4. create_grib2() - Create GRIB2 output for AWIPS dissemination
    5. create_awips() - Create AWIPS/SHEF format outputs
    6. archive_outputs() - Copy final products to COMOUT

Usage:
    from nos_ofs.postprocessing import (
        SCHISMPostProcessor,
        ROMSPostProcessor,
        FVCOMPostProcessor,
        PostResult,
    )

    # Create processor based on model type
    processor = SCHISMPostProcessor(config)
    result = processor.run_all()
"""

from .base import BasePostProcessor, PostResult
from .schism import SCHISMPostProcessor
from .roms import ROMSPostProcessor
from .fvcom import FVCOMPostProcessor

__all__ = [
    # Base classes
    "BasePostProcessor",
    "PostResult",
    # Model-specific processors
    "SCHISMPostProcessor",
    "ROMSPostProcessor",
    "FVCOMPostProcessor",
]
