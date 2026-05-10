"""STOFS-3D-ATL descriptor (stub — pending integration).

Operational STOFS-3D Atlantic uses a continuous nowcast+forecast model
run, so its native stage names are ``prep_nowcast`` / ``now_forecast``;
we map those to our canonical ``prep`` / ``nowcast`` so a single CLI
verb works across frameworks. Two-phase post and the temp/salt restart
job stay as ``extra_stages`` rather than getting flattened into the
canonical sequence.

Concrete runner wiring lands with task #33 on the unified-workflow
roadmap.
"""
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
    runner_module="",  # runner module not yet wired
    notes="STOFS-3D-ATL pending integration; runner + ex-script port tracked as task #33.",
)


register(DESC)
