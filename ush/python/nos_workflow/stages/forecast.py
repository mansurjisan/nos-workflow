"""Forecast stage entry point (stub).

Real implementation lands with the runner module port — see task #35
on the unified-workflow roadmap.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..registry import OFSDescriptor

if TYPE_CHECKING:
    from ..env import NCOEnv  # noqa: F401


def run(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    raise NotImplementedError(
        f"{__name__.rsplit('.', 1)[1]} stage not yet ported — see task #35 punch list"
    )


__all__ = ["run"]
