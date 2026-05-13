"""SECOFS-UFS descriptor."""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="secofs_ufs",
    framework="comf",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},
    yaml_path=Path("parm/systems/secofs_ufs.yaml"),
    runner_module="nos_workflow.runners.ufs_coastal",
    notes="SCHISM + CDEPS DATM via NUOPC; 2794 OCN ranks + 120 ATM/MED.",
)


register(DESC)
