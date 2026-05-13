"""STOFS-2D-GLO descriptor."""
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
    runner_module="",
    notes="STOFS-2D-GLO ADCIRC support pending.",
)


register(DESC)
