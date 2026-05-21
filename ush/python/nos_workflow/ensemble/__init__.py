"""
NOS-OFS Ensemble Forecasting Module

Provides ensemble capability for uncertainty quantification using:
  - GEFS atmospheric forcing ensemble (method: gefs)
  - LHS physics parameter perturbation (method: parameter_perturbation)
  - Atmospheric source switching (method: atmospheric)

Usage:
    from nos_workflow.ensemble import EnsembleConfig, ParamGenerator, EnsemblePost

    config = EnsembleConfig.from_yaml("secofs.yaml")
    generator = ParamGenerator(config)
    members = generator.generate()
"""

# Lazy imports to avoid dual-import conflict when running submodules
# as scripts via `python -m nos_workflow.ensemble.param_generator`.
# Eager import of param_generator in __init__.py causes a segfault
# on WCOSS2 Python 3.12 because runpy finds the module already in
# sys.modules before it can execute it as __main__.


def __getattr__(name):
    if name in ("EnsembleConfig", "GEFSEnsembleConfig", "ParamGenerator"):
        from .param_generator import EnsembleConfig, GEFSEnsembleConfig, ParamGenerator
        return {"EnsembleConfig": EnsembleConfig,
                "GEFSEnsembleConfig": GEFSEnsembleConfig,
                "ParamGenerator": ParamGenerator}[name]
    if name == "EnsemblePost":
        from .ensemble_post import EnsemblePost
        return EnsemblePost
    if name == "plot_station_timeseries":
        from .plot_ensemble_stations import plot_station_timeseries
        return plot_station_timeseries
    if name == "plot_spatial_stats":
        from .plot_ensemble_spatial import plot_spatial_stats
        return plot_spatial_stats
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "EnsembleConfig",
    "GEFSEnsembleConfig",
    "ParamGenerator",
    "EnsemblePost",
]
