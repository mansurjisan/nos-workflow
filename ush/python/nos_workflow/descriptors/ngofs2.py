"""NGOFS2 descriptor — Northern Gulf of Mexico OFS (FVCOM, standalone)."""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="ngofs2",
    framework="comf_standalone",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},
    yaml_path=Path("parm/systems/ngofs2.yaml"),
    runner_module="nos_workflow.runners.comf_standalone",
    notes="FVCOM standalone (Northern Gulf of Mexico); model execution shells "
          "out to the legacy COMF scripts (WCOSS2-gated).",
)


register(DESC)
