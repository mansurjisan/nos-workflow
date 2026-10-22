"""CBOFS descriptor — Chesapeake Bay OFS (ROMS, standalone)."""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="cbofs",
    framework="comf_standalone",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},
    yaml_path=Path("parm/systems/cbofs.yaml"),
    runner_module="nos_workflow.runners.comf_standalone",
    notes="ROMS standalone (Chesapeake Bay); model execution shells out to "
          "the legacy COMF scripts (WCOSS2-gated).",
)


register(DESC)
