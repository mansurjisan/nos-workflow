"""SECOFS-UFS-WW3 descriptor (DATM+SCHISM+WW3 coupled)."""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="secofs_ufs_ww3",
    framework="comf",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},
    yaml_path=Path("parm/systems/secofs_ufs_ww3.yaml"),
    runner_module="nos_workflow.runners.ufs_coastal",
    notes=(
        "SCHISM + CDEPS DATM + WW3 via NUOPC/CMEPS (4-component); "
        "2794 OCN + 120 ATM/MED + 2606 WAV = 5520 ranks. SCHISM cycles via "
        "its own hotstart (ihot=1); WW3 and the mediator instead cycle via "
        "CMEPS restarts (ufs.cpld.{ww3,cpl}.r.*.nc + rpointer.cpl)."
    ),
)


register(DESC)
