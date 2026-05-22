"""DBOFS descriptor — Delaware Bay OFS (ROMS, standalone)."""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="dbofs",
    framework="comf_standalone",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},
    yaml_path=Path("parm/systems/dbofs.yaml"),
    runner_module="nos_workflow.runners.comf_standalone",
    notes="ROMS standalone (Delaware Bay); model execution shells out to "
          "the legacy COMF scripts (WCOSS2-gated).",
)


register(DESC)
