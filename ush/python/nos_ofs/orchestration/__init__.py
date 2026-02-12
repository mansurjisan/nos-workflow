"""
NOS OFS Orchestration Module

Provides Python orchestration layer for NOS OFS workflows, mirroring
the shell-based orchestration in ush/nos_ofs_prep_run.sh and
ush/nos_ofs_model_run.sh.

This is "Phase B" — native Python implementations that dispatch to
existing shell scripts via subprocess, providing a migration path
from shell to Python workflow management.

Usage:
    from nos_ofs.orchestration import PrepOrchestrator, ModelRunOrchestrator
    from nos_ofs.config import OFSConfig

    # Load configuration
    config = OFSConfig.load("stofs_3d_atl")

    # Run prep workflow
    prep = PrepOrchestrator(config)
    prep_result = prep.run_all()

    if prep_result.success:
        # Run nowcast
        runner = ModelRunOrchestrator(config)
        nowcast_result = runner.run_all("nowcast")

        if nowcast_result.success:
            # Run forecast
            forecast_result = runner.run_all("forecast")
"""

from .prep import PrepOrchestrator, PrepResult
from .model_run import ModelRunOrchestrator, ModelRunResult
from .handlers import StepResult

__all__ = [
    # Orchestrators
    "PrepOrchestrator",
    "ModelRunOrchestrator",
    # Result classes
    "PrepResult",
    "ModelRunResult",
    "StepResult",
]
