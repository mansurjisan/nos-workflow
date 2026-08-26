"""Machine profiles: how scientific task counts become an allocation.

A profile owns machine facts (cores per node, scheduler dialect, launcher
syntax). System YAMLs own science (nprocs, nscribes, walltime). Nothing in a
profile is scheduler syntax the caller has to assemble by hand -- see
``nos_workflow.platform.render``.

Deployment credentials (account, qos, partition) resolve through:

    explicit override  >  NOS_* environment  >  deployment overlay
                       >  machine default    >  fatal if required

They are deliberately ``null`` in committed profiles for sites where the valid
value depends on the user's project association.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[4]
MACHINES_DIR = _REPO / "parm" / "machines"

# Deployment credentials and their NOS_* environment overrides.
_CREDENTIALS = {
    "account": "NOS_ACCOUNT",
    "qos": "NOS_QOS",
    "partition": "NOS_PARTITION",
    "queue": "NOS_QUEUE",
}

# Which credentials a scheduler cannot submit without.
_REQUIRED_BY_SCHEDULER = {
    "pbs": ("account",),
    "slurm": ("account",),
}


class ProfileError(ValueError):
    """Malformed machine profile, or a required credential left unresolved."""


@dataclass(frozen=True)
class Allocation:
    cores_per_node: int
    ranks_per_node: int
    emit_ranks_per_node: bool = True
    exclusive: bool = True

    def nodes(self, total_ranks: int) -> int:
        if total_ranks < 1:
            raise ProfileError(f"total_ranks must be >= 1, got {total_ranks}")
        return math.ceil(total_ranks / self.ranks_per_node)


@dataclass(frozen=True)
class MpiSpec:
    launcher: str
    total_ranks_flag: str
    ranks_per_node_flag: Optional[str] = None
    fixed_args: tuple = ()


@dataclass(frozen=True)
class MachineProfile:
    machine: str
    scheduler_type: str
    allocation: Allocation
    mpi: MpiSpec
    account: Optional[str] = None
    qos: Optional[str] = None
    partition: Optional[str] = None
    queue: Optional[str] = None
    modulefile: Optional[str] = None
    versions: Optional[str] = None

    # ---- construction ---------------------------------------------------

    @classmethod
    def load(
        cls,
        machine: Optional[str] = None,
        *,
        overrides: Optional[Dict[str, Any]] = None,
        overlay: Optional[Dict[str, Any]] = None,
        machines_dir: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        validate: bool = True,
    ) -> "MachineProfile":
        """Load ``parm/machines/<machine>.yaml`` and resolve credentials.

        ``validate=False`` skips the required-credential check, for callers that
        only need allocation facts (node math, ranks per node) and are not about
        to submit anything.
        """
        import yaml

        env = os.environ if env is None else env
        machine = machine or env.get("NOS_MACHINE") or "wcoss2"
        base = Path(machines_dir) if machines_dir else MACHINES_DIR
        path = base / f"{machine}.yaml"
        if not path.is_file():
            available = sorted(p.stem for p in base.glob("*.yaml")) if base.is_dir() else []
            raise ProfileError(
                f"unknown machine {machine!r}: no {path}. Available: {available}"
            )

        with open(path) as fh:
            data = yaml.safe_load(fh) or {}

        return cls.from_dict(
            data, overrides=overrides, overlay=overlay, env=env, validate=validate,
        )

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        *,
        overrides: Optional[Dict[str, Any]] = None,
        overlay: Optional[Dict[str, Any]] = None,
        env: Optional[Dict[str, str]] = None,
        validate: bool = True,
    ) -> "MachineProfile":
        env = os.environ if env is None else env
        overrides = overrides or {}
        overlay = overlay or {}

        sched = data.get("scheduler") or {}
        sched_type = sched.get("type")
        if sched_type not in ("pbs", "slurm"):
            raise ProfileError(
                f"scheduler.type must be 'pbs' or 'slurm', got {sched_type!r}"
            )

        alloc_raw = data.get("allocation") or {}
        for key in ("cores_per_node", "ranks_per_node"):
            if not isinstance(alloc_raw.get(key), int) or alloc_raw[key] < 1:
                raise ProfileError(
                    f"allocation.{key} must be a positive integer, "
                    f"got {alloc_raw.get(key)!r}"
                )
        if alloc_raw["ranks_per_node"] > alloc_raw["cores_per_node"]:
            raise ProfileError(
                f"allocation.ranks_per_node ({alloc_raw['ranks_per_node']}) exceeds "
                f"cores_per_node ({alloc_raw['cores_per_node']})"
            )

        allocation = Allocation(
            cores_per_node=alloc_raw["cores_per_node"],
            ranks_per_node=alloc_raw["ranks_per_node"],
            emit_ranks_per_node=bool(alloc_raw.get("emit_ranks_per_node", True)),
            exclusive=bool(alloc_raw.get("exclusive", True)),
        )

        mpi_raw = data.get("mpi") or {}
        for key in ("launcher", "total_ranks_flag"):
            if not mpi_raw.get(key):
                raise ProfileError(f"mpi.{key} is required")
        fixed = mpi_raw.get("fixed_args") or []
        if isinstance(fixed, str):
            raise ProfileError(
                "mpi.fixed_args must be a list, not a string -- a shell string "
                "would have to be word-split or eval'd to become argv"
            )
        if any(a is None or str(a) == "" for a in fixed):
            raise ProfileError(
                "mpi.fixed_args contains an empty entry, which would become an "
                "empty argv element"
            )
        rpn_flag = mpi_raw.get("ranks_per_node_flag")
        if rpn_flag is not None and str(rpn_flag) == "":
            raise ProfileError(
                "mpi.ranks_per_node_flag must be a flag or null, never an empty "
                "string -- use allocation.emit_ranks_per_node to suppress it"
            )

        mpi = MpiSpec(
            launcher=str(mpi_raw["launcher"]),
            total_ranks_flag=str(mpi_raw["total_ranks_flag"]),
            ranks_per_node_flag=None if rpn_flag is None else str(rpn_flag),
            fixed_args=tuple(str(a) for a in fixed),
        )

        resolved = {}
        for name, env_var in _CREDENTIALS.items():
            resolved[name] = _first_set(
                overrides.get(name),
                env.get(env_var),
                overlay.get(name),
                sched.get(name),
            )

        profile = cls(
            machine=str(data.get("machine") or "unknown"),
            scheduler_type=sched_type,
            allocation=allocation,
            mpi=mpi,
            modulefile=data.get("modulefile"),
            versions=data.get("versions"),
            **resolved,
        )
        if validate:
            profile.validate()
        return profile

    # ---- use ------------------------------------------------------------

    def validate(self) -> None:
        """Fail before submission when a required credential is unresolved."""
        missing = [
            name
            for name in _REQUIRED_BY_SCHEDULER.get(self.scheduler_type, ())
            if not getattr(self, name)
        ]
        if missing:
            hints = ", ".join(f"{n} (set {_CREDENTIALS[n]})" for n in missing)
            raise ProfileError(
                f"machine {self.machine!r} ({self.scheduler_type}) requires "
                f"{hints}, or supply it via a deployment overlay"
            )

    def nodes(self, total_ranks: int) -> int:
        return self.allocation.nodes(total_ranks)

    def mpi_argv(
        self,
        total_ranks: int,
        executable: str,
        exe_args: Optional[List[str]] = None,
    ) -> List[str]:
        """Full launcher argv. A list, so callers never word-split or eval."""
        if total_ranks < 1:
            raise ProfileError(f"total_ranks must be >= 1, got {total_ranks}")

        argv = [self.mpi.launcher, self.mpi.total_ranks_flag, str(total_ranks)]
        if self.allocation.emit_ranks_per_node and self.mpi.ranks_per_node_flag:
            argv += [self.mpi.ranks_per_node_flag, str(self.allocation.ranks_per_node)]
        argv += list(self.mpi.fixed_args)
        argv.append(str(executable))
        argv += [str(a) for a in (exe_args or [])]
        return argv


def _first_set(*candidates):
    for c in candidates:
        if c is not None and c != "":
            return c
    return None


def available_machines(machines_dir: Optional[Path] = None) -> List[str]:
    base = Path(machines_dir) if machines_dir else MACHINES_DIR
    return sorted(p.stem for p in base.glob("*.yaml")) if base.is_dir() else []


__all__ = [
    "Allocation",
    "MachineProfile",
    "MpiSpec",
    "ProfileError",
    "available_machines",
]
