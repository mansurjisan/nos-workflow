"""
NOS-OFS Ensemble Forecasting Module

Provides ensemble capability for uncertainty quantification using:
  - GEFS atmospheric forcing ensemble (method: gefs)
  - LHS physics parameter perturbation (method: parameter_perturbation)
  - Atmospheric source switching (method: atmospheric)

Usage:
    from nos_ofs.ensemble import EnsembleConfig, ParamGenerator, EnsemblePost

    config = EnsembleConfig.from_yaml("secofs.yaml")
    generator = ParamGenerator(config)
    members = generator.generate()
"""

from .param_generator import (
    EnsembleConfig,
    GEFSEnsembleConfig,
    ParamGenerator,
)
from .ensemble_post import EnsemblePost
from .plot_ensemble_stations import plot_station_timeseries
from .plot_ensemble_spatial import plot_spatial_stats

__all__ = [
    "EnsembleConfig",
    "GEFSEnsembleConfig",
    "ParamGenerator",
    "EnsemblePost",
    "plot_station_timeseries",
    "plot_spatial_stats",
]
