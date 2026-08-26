"""Render scheduler directives from a JobSpec + MachineProfile.

The WCOSS2 output is required to reproduce the hand-written ``pbs/*.pbs``
headers exactly; ``tests/test_job_card_render.py`` freezes that and diffs it
against the real cards.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .profile import MachineProfile, ProfileError

# Model jobs take whole nodes; serial jobs (prep/post) take a slice of one.
KIND_MODEL = "model"
KIND_SERIAL = "serial"


@dataclass(frozen=True)
class JobSpec:
    """Everything that varies per job rather than per machine."""

    name: str
    walltime: str
    kind: str = KIND_MODEL
    total_ranks: int = 1
    cpus: int = 8                       # serial jobs only
    threads_per_rank: Optional[int] = None   # PBS ompthreads=
    mem_per_node: Optional[str] = None       # e.g. "500GB"; per-system, not per-machine
    # None suppresses the -o/-e (PBS) directive entirely, for jobs that
    # redirect their own logs in-script to capture a SIGKILLed job's PBS
    # epilogue (walltime/OOM), which an in-script trap can never see.
    stdout: Optional[str] = "/dev/null"
    stderr: Optional[str] = "/dev/null"
    extra_resources: Tuple[str, ...] = ()    # e.g. ("debug=true",)

    def __post_init__(self):
        if self.kind not in (KIND_MODEL, KIND_SERIAL):
            raise ProfileError(f"unknown job kind {self.kind!r}")
        if not self.walltime:
            raise ProfileError("walltime is required")


def render_directives(spec: JobSpec, profile: MachineProfile) -> List[str]:
    if profile.scheduler_type == "pbs":
        return _render_pbs(spec, profile)
    if profile.scheduler_type == "slurm":
        return _render_slurm(spec, profile)
    raise ProfileError(f"no renderer for scheduler {profile.scheduler_type!r}")


def _render_pbs(spec: JobSpec, profile: MachineProfile) -> List[str]:
    # Two spaces after #PBS: matches the existing hand-written cards.
    p = "#PBS  "
    lines = [
        f"{p}-N {spec.name}",
        f"{p}-A {profile.account}",
        f"{p}-q {profile.queue}",
    ]
    if spec.stdout is not None:
        lines.append(f"{p}-o {spec.stdout}")
    if spec.stderr is not None:
        lines.append(f"{p}-e {spec.stderr}")

    alloc = profile.allocation
    if spec.kind == KIND_MODEL:
        chunk = (
            f"select={profile.nodes(spec.total_ranks)}"
            f":ncpus={alloc.cores_per_node}"
        )
        if alloc.emit_ranks_per_node:
            chunk += f":mpiprocs={alloc.ranks_per_node}"
        # Both follow mpiprocs= in the existing cards; no card carries both, so
        # this order is a convention rather than something reproduced from one.
        if spec.threads_per_rank is not None:
            chunk += f":ompthreads={spec.threads_per_rank}"
        if spec.mem_per_node:
            chunk += f":mem={spec.mem_per_node}"
        place = "vscatter:excl" if alloc.exclusive else "vscatter"
        lines.append(f"{p}-l place={place},{chunk}")
    else:
        lines.append(f"{p}-l select=1:ncpus={spec.cpus}:mpiprocs={spec.cpus}")
        lines.append(f"{p}-l place=vscatter")

    lines.append(f"{p}-l walltime={spec.walltime}")
    lines += [f"{p}-l {r}" for r in spec.extra_resources]
    return lines


def _render_slurm(spec: JobSpec, profile: MachineProfile) -> List[str]:
    p = "#SBATCH "
    lines = [
        f"{p}--job-name={spec.name}",
        f"{p}--account={profile.account}",
    ]
    if profile.partition:
        lines.append(f"{p}--partition={profile.partition}")
    if profile.qos:
        lines.append(f"{p}--qos={profile.qos}")
    lines += [
        f"{p}--output={spec.stdout}",
        f"{p}--error={spec.stderr}",
    ]

    alloc = profile.allocation
    if spec.kind == KIND_MODEL:
        lines.append(f"{p}--nodes={profile.nodes(spec.total_ranks)}")
        lines.append(f"{p}--ntasks={spec.total_ranks}")
        # Suppressed on machines where --ntasks-per-node is known to break
        # large-domain runs; the node count above already used ranks_per_node.
        if alloc.emit_ranks_per_node:
            lines.append(f"{p}--ntasks-per-node={alloc.ranks_per_node}")
        if alloc.exclusive:
            lines.append(f"{p}--exclusive")
    else:
        lines.append(f"{p}--nodes=1")
        lines.append(f"{p}--ntasks={spec.cpus}")

    if spec.threads_per_rank is not None:
        lines.append(f"{p}--cpus-per-task={spec.threads_per_rank}")
    if spec.mem_per_node:
        lines.append(f"{p}--mem={spec.mem_per_node}")

    lines.append(f"{p}--time={spec.walltime}")
    return lines


def render_mpi_argv(spec: JobSpec, profile: MachineProfile, executable: str,
                    exe_args: Optional[List[str]] = None) -> List[str]:
    return profile.mpi_argv(spec.total_ranks, executable, exe_args)


__all__ = [
    "JobSpec",
    "KIND_MODEL",
    "KIND_SERIAL",
    "render_directives",
    "render_mpi_argv",
]
