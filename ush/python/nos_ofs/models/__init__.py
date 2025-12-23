"""
Model Implementations Package

This package provides model implementations for NOS OFS:
- SCHISM: STOFS-3D-ATL, STOFS-3D-PAC, SECOFS, CREOFS
- FVCOM: LEOFS, LOOFS, NGOFS2, etc.
- ROMS: CBOFS, DBOFS, TBOFS, GOMOFS, etc.

Usage:
    from nos_ofs.models import SCHISMModel, SCHISMConfig
    from nos_ofs import OFSRegistry

    # Create via registry (recommended)
    model = OFSRegistry.create_model("stofs_3d_atl")

    # Or directly
    config = SCHISMConfig.from_yaml("stofs_3d_atl.yaml")
    model = SCHISMModel(config)
"""

from .schism_model import SCHISMModel
from .schism_config import SCHISMConfig
from .workflow import WorkflowStage, WorkflowRunner
from .stage import StageRunner
from .legacy_runner import LegacyShellRunner
from .grid import GridProcessor
from .param import ParamGenerator
from .validation import ModelValidator

__all__ = [
    # SCHISM
    "SCHISMModel",
    "SCHISMConfig",
    # Workflow
    "WorkflowStage",
    "WorkflowRunner",
    "StageRunner",
    "LegacyShellRunner",
    # Grid utilities
    "GridProcessor",
    # Parameter generation
    "ParamGenerator",
    # Validation
    "ModelValidator",
]
