"""
Model Implementations Package

This package provides model implementations for NOS OFS:
- SCHISM: STOFS-3D-ATL, STOFS-3D-PAC, SECOFS, CREOFS
- FVCOM: LEOFS, LOOFS, LMHOFS, LSOFS, NGOFS2, SFBOFS, SSCOFS
- ROMS: CBOFS, DBOFS, TBOFS, GOMOFS, CIOFS, WCOFS
- ADCIRC: STOFS-2D-GLO (Global Surge and Tide)

Usage:
    from nos_ofs.models import SCHISMModel, ROMSModel, FVCOMModel, ADCIRCModel
    from nos_ofs import OFSRegistry

    # Create via registry (recommended)
    model = OFSRegistry.create_model("stofs_3d_atl")  # Returns SCHISMModel
    model = OFSRegistry.create_model("cbofs")          # Returns ROMSModel
    model = OFSRegistry.create_model("leofs")          # Returns FVCOMModel
    model = OFSRegistry.create_model("stofs_2d_glo")   # Returns ADCIRCModel

    # Or directly
    from nos_ofs.models import StofsConfig
    config = StofsConfig.from_yaml("stofs_3d_atl.yaml")
    model = SCHISMModel(config)
"""

# SCHISM model components
from .schism_model import SCHISMModel
from .schism_config import StofsConfig
from .workflow import SchismModel as SchismWorkflowModel
from .stage import Stage
from .legacy_runner import LegacyScriptRunner
from .grid import SCHISMGrid
from .param import ParamNmlGenerator
from .validation import InputValidator, OutputValidator

# ROMS model components
from .roms_model import ROMSModel
from .roms_grid import ROMSGrid
from .roms_config import ROMSConfigGenerator

# FVCOM model components
from .fvcom_model import FVCOMModel
from .fvcom_grid import FVCOMGrid
from .fvcom_config import FVCOMConfigGenerator

# ADCIRC model components
from .adcirc_model import ADCIRCModel
from .adcirc_grid import ADCIRCGrid
from .adcirc_config import ADCIRCConfigGenerator

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
    "SCHISMGrid",
    "GridProcessor",
    # ROMS
    "ROMSModel",
    "ROMSGrid",
    "ROMSConfigGenerator",
    # FVCOM
    "FVCOMModel",
    "FVCOMGrid",
    "FVCOMConfigGenerator",
    # ADCIRC
    "ADCIRCModel",
    "ADCIRCGrid",
    "ADCIRCConfigGenerator",
    # Workflow
    "SchismWorkflowModel",
    "Stage",
    "LegacyScriptRunner",
    "LegacyShellRunner",
    # Parameter generation
    "ParamNmlGenerator",
    "ParamGenerator",
    # Validation
    "InputValidator",
    "OutputValidator",
]
