"""Per-(system, stage) JobSpec construction, shared by the submit CLI and the
WCOSS2 job-card parity tests (``tests/test_job_card_render.py``).

System science (nprocs, walltime, thread/mem sizing) already lives in
``parm/systems/<name>.yaml`` via ``resources:`` / ``standalone:``; this module
only carries the handful of fields a YAML resolve cannot hand back as a
scalar -- the job-name suffix, PBS/Slurm job ``kind``, and stage-specific
extras -- and derives ``total_ranks`` from the resolved YAML at call time so
it can never drift from ``resources.nprocs``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from .render import JobSpec, KIND_MODEL, KIND_SERIAL

REPO = Path(__file__).resolve().parents[4]

# Fixed so nprocs_for() is reproducible regardless of the caller's ambient
# PDY/cyc -- NPROCS is a per-system scalar and does not vary by cycle date.
_NPROCS_PDY = "20260724"
_NPROCS_CYC = "00"


@dataclass(frozen=True)
class StageSpec:
    card: str                                # pbs/<...>.pbs path, repo-relative
    job_name: str
    kind: str
    walltime: str
    threads_per_rank: Optional[int] = None
    mem_per_node: Optional[str] = None
    extra_resources: Tuple[str, ...] = ()
    # True suppresses PBS -o/-e: the job redirects its own stdout/stderr
    # in-script so a SIGKILLed job's PBS epilogue (walltime/OOM) still lands
    # somewhere, which an in-script trap can never see. See render.JobSpec.
    real_logs: bool = False


# One entry per (system, stage) this submit path currently supports.
CATALOG: Dict[Tuple[str, str], StageSpec] = {
    ("secofs_ufs", "prep"): StageSpec(
        "pbs/jnos_prep_00.pbs", "secofs_ufs_prep_00", KIND_SERIAL, "02:00:00"),
    ("secofs_ufs", "nowcast"): StageSpec(
        "pbs/jnos_nowcast_00.pbs", "secofs_ufs_nc_00", KIND_MODEL, "01:30:00"),
    ("secofs_ufs", "forecast"): StageSpec(
        "pbs/jnos_forecast_00.pbs", "secofs_ufs_fc_00", KIND_MODEL, "05:30:00"),
    ("secofs_ufs", "post"): StageSpec(
        "pbs/jnos_post_00.pbs", "secofs_ufs_post_00", KIND_SERIAL, "02:00:00",
        real_logs=True),

    ("stofs_3d_atl_ufs", "prep"): StageSpec(
        "pbs/stofs_3d_atl_ufs/jnos_prep_00.pbs", "stofs_3d_atl_ufs_prep_00",
        KIND_SERIAL, "02:00:00"),
    ("stofs_3d_atl_ufs", "nowcast"): StageSpec(
        "pbs/stofs_3d_atl_ufs/jnos_nowcast_00.pbs", "stofs_3d_atl_ufs_nc_00",
        KIND_MODEL, "01:30:00", threads_per_rank=1),
    ("stofs_3d_atl_ufs", "forecast"): StageSpec(
        "pbs/stofs_3d_atl_ufs/jnos_forecast_00.pbs", "stofs_3d_atl_ufs_fc_00",
        KIND_MODEL, "05:30:00", threads_per_rank=1),
    ("stofs_3d_atl_ufs", "post"): StageSpec(
        "pbs/stofs_3d_atl_ufs/jnos_post_00.pbs", "stofs_3d_atl_ufs_post_00",
        KIND_SERIAL, "02:00:00", real_logs=True),

    ("stofs_3d_atl_ufs_standalone", "prep"): StageSpec(
        "pbs/stofs_3d_atl_ufs_standalone/jnos_prep_00.pbs",
        "stofs_3d_atl_ufs_sa_prep_00", KIND_SERIAL, "05:00:00"),
    ("stofs_3d_atl_ufs_standalone", "nowcast"): StageSpec(
        "pbs/stofs_3d_atl_ufs_standalone/jnos_nowcast_00.pbs",
        "stofs_3d_atl_ufs_sa_nc_00", KIND_MODEL, "05:00:00", threads_per_rank=1),
    ("stofs_3d_atl_ufs_standalone", "forecast"): StageSpec(
        "pbs/stofs_3d_atl_ufs_standalone/jnos_forecast_00.pbs",
        "stofs_3d_atl_ufs_sa_fc_00", KIND_MODEL, "05:00:00", threads_per_rank=1,
        extra_resources=("debug=true",)),
}


def nprocs_for(system: str, repo_root: Optional[Path] = None) -> int:
    """Total MPI ranks for ``system``, straight from the resolved YAML."""
    from nos_workflow.utils import yaml_to_env

    root = Path(repo_root) if repo_root else REPO
    saved = dict(os.environ)
    try:
        for var in ("PDY", "cyc"):
            os.environ.pop(var, None)
        os.environ["PDY"] = _NPROCS_PDY
        os.environ["cyc"] = _NPROCS_CYC
        exports = json.loads(
            yaml_to_env.export_env(
                root / "parm" / "systems" / f"{system}.yaml",
                framework="comf", output_format="json",
            )
        )
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return int(exports["NPROCS"])


def build_job_spec(system: str, stage: str, repo_root: Optional[Path] = None) -> JobSpec:
    """The ``JobSpec`` for one (system, stage), ranks resolved from its YAML."""
    key = (system, stage)
    if key not in CATALOG:
        raise KeyError(
            f"no job spec for system={system!r} stage={stage!r}; known "
            f"combinations: {sorted(CATALOG.keys())}"
        )
    ss = CATALOG[key]
    total_ranks = nprocs_for(system, repo_root) if ss.kind == KIND_MODEL else 1
    stdio = None if ss.real_logs else "/dev/null"
    return JobSpec(
        name=ss.job_name,
        walltime=ss.walltime,
        kind=ss.kind,
        total_ranks=total_ranks,
        threads_per_rank=ss.threads_per_rank,
        mem_per_node=ss.mem_per_node,
        extra_resources=ss.extra_resources,
        stdout=stdio,
        stderr=stdio,
    )


__all__ = ["CATALOG", "StageSpec", "build_job_spec", "nprocs_for"]
