"""
NOS OFS Ensemble Forecasting Module

Provides probabilistic ocean forecasts by running multiple model instances
with perturbed inputs, initial conditions, and model parameters.

This module builds on top of the existing orchestration layer
(PrepOrchestrator, ModelRunOrchestrator) and supports all three model
types (SCHISM, FVCOM, ROMS) across both STOFS and COMF frameworks.

Architecture:
    EnsembleConfig    -- YAML-configurable ensemble settings
    EnsembleMember    -- Individual member state and directory management
    MemberManager     -- Creates N members with perturbed configs/inputs
    EnsembleRunner    -- Execution engine (sequential or parallel)
    EnsembleStatistics -- Post-run ensemble statistics (mean, spread, percentiles)
    EnsemblePlotter   -- Visualization helpers (spaghetti, spread maps, etc.)

Perturbation strategies:
    Initial conditions -- Gaussian noise, EOF modes, historical errors
    Atmospheric forcing -- Wind, pressure, precipitation perturbations
    Boundary conditions -- OBC temperature/salinity/SSH perturbation
    Model parameters   -- Bottom friction, wind drag, vertical mixing

Usage:
    from nos_ofs.config import OFSConfig
    from nos_ofs.ensemble import EnsembleConfig, EnsembleRunner

    base_config = OFSConfig.load("stofs_3d_atl")
    ens_config = EnsembleConfig.from_yaml("parm/ensemble/stofs_3d_atl_ensemble.yaml")

    runner = EnsembleRunner(base_config, ens_config)
    result = runner.run_all("forecast")

    # Access statistics
    print(result.statistics.mean("zeta"))
    print(result.statistics.spread("zeta"))
"""

from .config import (
    EnsembleConfig,
    ICPerturbationConfig,
    ForcingPerturbationConfig,
    ParamPerturbationConfig,
    StatisticsConfig,
    ExecutionConfig,
)
from .perturbation import (
    BasePerturbation,
    PerturbationResult,
    GaussianICPerturbation,
    EOFPerturbation,
    HistoricalPerturbation,
    WindPerturbation,
    PressurePerturbation,
    PrecipPerturbation,
    OBCPerturbation,
    BottomFrictionPerturbation,
    WindDragPerturbation,
    MixingPerturbation,
    GaussianRandomField,
)
from .member import (
    EnsembleMember,
    MemberManager,
)
from .runner import (
    EnsembleRunner,
    EnsembleResult,
)
from .statistics import (
    EnsembleStatistics,
    EnsembleStatsResult,
)

# Visualization is optional (requires matplotlib)
try:
    from .visualization import EnsemblePlotter
except ImportError:
    EnsemblePlotter = None

__all__ = [
    # Configuration
    "EnsembleConfig",
    "ICPerturbationConfig",
    "ForcingPerturbationConfig",
    "ParamPerturbationConfig",
    "StatisticsConfig",
    "ExecutionConfig",
    # Perturbations
    "BasePerturbation",
    "PerturbationResult",
    "GaussianICPerturbation",
    "EOFPerturbation",
    "HistoricalPerturbation",
    "WindPerturbation",
    "PressurePerturbation",
    "PrecipPerturbation",
    "OBCPerturbation",
    "BottomFrictionPerturbation",
    "WindDragPerturbation",
    "MixingPerturbation",
    "GaussianRandomField",
    # Member management
    "EnsembleMember",
    "MemberManager",
    # Execution
    "EnsembleRunner",
    "EnsembleResult",
    # Statistics
    "EnsembleStatistics",
    "EnsembleStatsResult",
    # Visualization (optional)
    "EnsemblePlotter",
]
