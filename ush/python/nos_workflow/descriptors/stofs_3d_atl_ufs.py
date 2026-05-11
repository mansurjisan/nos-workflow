"""STOFS-3D-ATL-UFS descriptor.

SCHISM ocean coupled to CDEPS DATM via NUOPC under the UFS-Coastal
stack — the same runner as ``secofs_ufs``. The native operational
STOFS-3D-ATL workflow uses ``prep_nowcast`` / ``now_forecast`` stage
names; the UFS variant adopts the canonical ``prep`` / ``nowcast`` /
``forecast`` / ``post`` sequence directly so a single CLI verb works
across UFS-based OFS systems. Production resource counts (~4312 OCN
ranks + 120 ATM/MED) and v3.1.1 ``partition.prop`` plus other runtime
values live in ``parm/systems/stofs_3d_atl_ufs.yaml``; this descriptor
only carries the static identity bits the dispatcher needs.

The framework label is ``stofs_ufs`` (distinct from both ``comf`` and
the standalone ``stofs`` framework) so dispatch and resource-binding
logic can branch on the UFS-Coastal stack without colliding with
either of the existing frameworks.
"""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="stofs_3d_atl_ufs",
    framework="stofs_ufs",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},  # UFS variant uses canonical names directly
    yaml_path=Path("parm/systems/stofs_3d_atl_ufs.yaml"),
    runner_module="nos_workflow.runners.ufs_coastal",
    notes=(
        "STOFS-3D-ATL on UFS-Coastal: SCHISM + CDEPS DATM via NUOPC; "
        "~4312 OCN ranks + 120 ATM/MED; v3.1.1 partition.prop."
    ),
)


register(DESC)
