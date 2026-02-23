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

# Lazy imports to avoid dual-import conflict when running submodules
# as scripts via `python -m nos_ofs.ensemble.param_generator`.
# Eager import of param_generator in __init__.py causes a segfault
# on WCOSS2 Python 3.12 because runpy finds the module already in
# sys.modules before it can execute it as __main__.


def __getattr__(name):
    if name in ("EnsembleConfig", "GEFSEnsembleConfig", "ParamGenerator", "ADCIRC_PARAMS"):
        from .param_generator import EnsembleConfig, GEFSEnsembleConfig, ParamGenerator, ADCIRC_PARAMS
        return {"EnsembleConfig": EnsembleConfig,
                "GEFSEnsembleConfig": GEFSEnsembleConfig,
                "ParamGenerator": ParamGenerator,
                "ADCIRC_PARAMS": ADCIRC_PARAMS}[name]
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
    "ADCIRC_PARAMS",
    "EnsembleConfig",
    "GEFSEnsembleConfig",
    "ParamGenerator",
    "EnsemblePost",
]
