"""No-op restart preparation; actual staging happens in stage_model_files."""
from __future__ import annotations

import logging

from .context import SchismRunContext

logger = logging.getLogger(__name__)


def run_python(ctx: SchismRunContext, phase: str) -> int:
    """No-op restart preparation. Returns 0 always."""
    logger.info(
        "prepare_restart: no-op (phase=%s, data=%s)",
        phase, ctx.data,
    )
    return 0


__all__ = ["run_python"]
