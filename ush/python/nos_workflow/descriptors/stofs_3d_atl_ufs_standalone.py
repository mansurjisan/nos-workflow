"""STOFS-3D-ATL standalone (pschism) descriptor.

Same stages and runner as the UFS-coupled ``stofs_3d_atl_ufs``; the only difference
is ``execution.mode=standalone`` in the YAML, which makes the resolver select
``pschism_WCOSS2`` + ``nws=2`` + 6 I/O scribes instead of ``fv3_coastalS.exe`` +
CDEPS DATM. The prep and the four-step stage contract are unchanged.
"""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="stofs_3d_atl_ufs_standalone",
    framework="stofs_ufs",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},
    yaml_path=Path("parm/systems/stofs_3d_atl_ufs_standalone.yaml"),
    runner_module="nos_workflow.runners.ufs_coastal",
    notes=(
        "STOFS-3D-ATL standalone pschism (execution.mode=standalone): nws=2 sflux "
        "forcing, 6 I/O scribes, 4320 ranks / 36 nodes, no NUOPC/CDEPS mediator. "
        "Reuses the UFS-coupled prep/stages; only the execution engine differs."
    ),
)


register(DESC)
