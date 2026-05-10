"""SECOFS-UFS descriptor.

SCHISM ocean coupled to CDEPS DATM via NUOPC. Production resource
counts (2794 OCN + 120 ATM/MED) and other runtime values live in
``parm/systems/secofs_ufs.yaml``; this descriptor only carries the
static identity bits the dispatcher needs.
"""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="secofs_ufs",
    framework="comf",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},  # SECOFS-UFS uses canonical names directly
    yaml_path=Path("parm/systems/secofs_ufs.yaml"),
    runner_module="nos_workflow.runners.ufs_coastal",
    notes="SCHISM + CDEPS DATM via NUOPC; 2794 OCN ranks + 120 ATM/MED.",
)


register(DESC)
