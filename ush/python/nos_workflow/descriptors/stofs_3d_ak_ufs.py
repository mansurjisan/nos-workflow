"""STOFS-3D-AK-UFS descriptor."""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="stofs_3d_ak_ufs",
    framework="stofs_ufs",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},
    yaml_path=Path("parm/systems/stofs_3d_ak_ufs.yaml"),
    runner_module="nos_workflow.runners.ufs_coastal",
    notes=(
        "STOFS-3D-Alaska on the coupled DATM+SCHISM path; dateline domain "
        "(lon 156.7-203.1, 0-360). 2393 OCN + 120 ATM/MED = 2513 ranks / "
        "21 nodes; partition.prop staged for 2393 compute ranks under a "
        "NO_PARMETIS build. dt=45s. No river forcing (mesh has no sources)."
    ),
)


register(DESC)
