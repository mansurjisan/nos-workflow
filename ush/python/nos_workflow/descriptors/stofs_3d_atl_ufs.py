"""STOFS-3D-ATL-UFS descriptor."""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="stofs_3d_atl_ufs",
    framework="stofs_ufs",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},
    yaml_path=Path("parm/systems/stofs_3d_atl_ufs.yaml"),
    runner_module="nos_workflow.runners.ufs_coastal",
    notes=(
        "STOFS-3D-ATL on UFS-Coastal: SCHISM + CDEPS DATM via NUOPC; "
        "~4312 OCN ranks + 120 ATM/MED; v3.1.1 partition.prop."
    ),
)


register(DESC)
