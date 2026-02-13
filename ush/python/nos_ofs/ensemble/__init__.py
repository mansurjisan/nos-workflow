"""
NOS-OFS Ensemble Forecasting Module

Provides parameter perturbation ensemble capability for uncertainty
quantification. Supports Latin Hypercube Sampling of model physics
parameters (bottom friction, mixing coefficients, roughness).

Usage:
    from nos_ofs.ensemble import EnsembleConfig, ParamGenerator, EnsemblePost

    config = EnsembleConfig.from_yaml("secofs.yaml")
    generator = ParamGenerator(config)
    members = generator.generate()
"""

from .param_generator import EnsembleConfig, ParamGenerator
from .ensemble_post import EnsemblePost

__all__ = [
    "EnsembleConfig",
    "ParamGenerator",
    "EnsemblePost",
]
