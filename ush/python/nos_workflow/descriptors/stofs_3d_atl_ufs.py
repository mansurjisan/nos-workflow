"""STOFS-3D-ATL-UFS descriptor — greenfield UFS-Coastal port of STOFS-3D Atlantic.

The legacy STOFS-3D-ATL (descriptor in ``stofs_3d_atl.py``) runs standalone
SCHISM with sflux atmospheric forcing and three post-processing extras
(``post_1`` / ``post_2`` / ``temp_salt_restart``). This descriptor names the
UFS-compliant variant of the same OFS: SCHISM coupled to CDEPS DATM via the
NUOPC mediator, packaged in ``fv3_coastalS.exe`` — the same coupling stack
that SECOFS-UFS already runs on this branch.

We pick ``framework="comf"`` because once UFS-coupled, dispatch in
``stages/{prep,nowcast,forecast,post}.py`` is identical to SECOFS-UFS. There
is no functional reason to fork a third framework branch for this port, and
the legacy ``framework="stofs"`` value stays reserved for the standalone
descriptor (and its ``NotImplementedError`` stubs in stage modules).

Resource counts (OCN + ATM/MED PETs, total tasks, walltime, NetCDF chunking)
are runtime values that live in ``parm/systems/stofs_3d_atl_ufs.yaml``; only
the static identity bits the dispatcher needs are encoded here.

Scoping doc: ``docs/STOFS_3D_ATL_UFS_PORT_PLAN.md``. Tracked as issue #219
task #33.
"""
from __future__ import annotations

from pathlib import Path

from ..registry import OFSDescriptor, register


DESC = OFSDescriptor(
    name="stofs_3d_atl_ufs",
    framework="comf",
    canonical_stages=("prep", "nowcast", "forecast", "post"),
    stage_aliases={},  # canonical-only; comf dispatch needs no aliasing
    yaml_path=Path("parm/systems/stofs_3d_atl_ufs.yaml"),
    runner_module="nos_workflow.runners.ufs_coastal",
    notes=(
        "STOFS-3D-ATL on the UFS-Coastal coupling stack "
        "(fv3_coastalS.exe = DATM + SCHISM via NUOPC); greenfield port "
        "tracked as task #33 per docs/STOFS_3D_ATL_UFS_PORT_PLAN.md. "
        "Many YAML fields are scaffolding placeholders pending commits 2-6 "
        "(atm forcing, ESMF mesh, NWM rivers, OBC, parity test)."
    ),
)


register(DESC)
