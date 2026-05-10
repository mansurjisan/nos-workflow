"""STOFS-2D-GLO descriptor (stub — ADCIRC pending).

Global STOFS-2D is ADCIRC-based; its prep / forcing / post differ enough
from the SCHISM stack that we keep ``framework="adcirc"`` as its own
branch in the dispatcher. Runner wiring lands with task #34.
"""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="stofs_2d_glo",
    framework="adcirc",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},
    extra_stages=(),
    yaml_path=Path("parm/systems/stofs_2d_glo.yaml"),
    runner_module="",  # runner module not yet wired
    notes="STOFS-2D-GLO ADCIRC support pending; runner + ex-script port tracked as task #34.",
)


register(DESC)
