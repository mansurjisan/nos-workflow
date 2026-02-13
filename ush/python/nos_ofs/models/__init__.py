"""
Model Implementations Package

This package provides model implementations for NOS OFS:
- SCHISM: STOFS-3D-ATL, STOFS-3D-PAC, SECOFS, CREOFS
- FVCOM: LEOFS, LOOFS, LMHOFS, LSOFS, NGOFS2, SFBOFS, SSCOFS
- ROMS: CBOFS, DBOFS, TBOFS, GOMOFS, etc.

Usage:
    from nos_ofs.models import SCHISMModel, FVCOMModel, ROMSModel, StofsConfig
    from nos_ofs import OFSRegistry

    # Create via registry (recommended)
    model = OFSRegistry.create_model("stofs_3d_atl")
    model = OFSRegistry.create_model("leofs")
    model = OFSRegistry.create_model("cbofs")

    # Or directly
    config = StofsConfig.from_yaml("stofs_3d_atl.yaml")
    model = SCHISMModel(config)
"""

from .schism_model import SCHISMModel
from .schism_config import StofsConfig
from .fvcom import FVCOMModel, FVCOMGrid
from .roms import ROMSModel, ROMSGrid
from .workflow import SchismModel as SchismWorkflowModel
from .stage import Stage
from .legacy_runner import LegacyScriptRunner
from .grid import SCHISMGrid
from .param import ParamNmlGenerator
from .validation import InputValidator, OutputValidator

# Aliases for backward compatibility
SCHISMConfig = StofsConfig
LegacyShellRunner = LegacyScriptRunner
GridProcessor = SCHISMGrid
ParamGenerator = ParamNmlGenerator

__all__ = [
    # SCHISM
    "SCHISMModel",
    "StofsConfig",
    "SCHISMConfig",
    # FVCOM
    "FVCOMModel",
    "FVCOMGrid",
    # ROMS
    "ROMSModel",
    "ROMSGrid",
    # Workflow
    "SchismWorkflowModel",
    "Stage",
    "LegacyScriptRunner",
    "LegacyShellRunner",
    # Grid utilities
    "SCHISMGrid",
    "GridProcessor",
    # Parameter generation
    "ParamNmlGenerator",
    "ParamGenerator",
    # Validation
    "InputValidator",
    "OutputValidator",
]
