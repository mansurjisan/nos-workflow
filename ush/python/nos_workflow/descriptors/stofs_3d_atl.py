"""STOFS-3D-ATL descriptor."""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="stofs_3d_atl",
    framework="stofs",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={
        "prep_nowcast": "prep",
        "now_forecast": "nowcast",
    },
    extra_stages=("post_1", "post_2", "temp_salt_restart"),
    yaml_path=Path("parm/systems/stofs_3d_atl.yaml"),
    runner_module="",
    notes="STOFS-3D-ATL pending integration.",
)


register(DESC)
