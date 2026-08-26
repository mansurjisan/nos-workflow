"""Submit-side CLI: ``python3 -m nos_workflow.platform <card|mpi> ...``.

The one caller ``render_directives``/``render_mpi_argv`` were missing: shell
job cards print a scheduler header with ``card``, and ``ush/nos_run.sh``
resolves its MPI launch line with ``mpi`` instead of a hardcoded ``mpiexec``
string, so both track ``parm/machines/$NOS_MACHINE.yaml`` instead of drifting
from it.

Machine resolution (matches ``profile.py`` `MachineProfile.load`):
    --machine flag  >  $NOS_MACHINE  >  "wcoss2"
"""
from __future__ import annotations

import argparse
import sys

from . import jobs
from .profile import MachineProfile, ProfileError
from .render import JobSpec, render_directives, render_mpi_argv


def _card(args: argparse.Namespace) -> int:
    try:
        # About to print a submittable header, so credentials ARE validated
        # (default validate=True) -- a null account on Hercules must fail
        # loudly here, not at qsub/sbatch time.
        profile = MachineProfile.load(args.machine)
        spec = jobs.build_job_spec(args.system, args.stage)
    except (KeyError, ProfileError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for line in render_directives(spec, profile):
        print(line)
    return 0


def _mpi(args: argparse.Namespace) -> int:
    try:
        # Only allocation/launcher facts are needed, not submission
        # credentials -- this runs inside an already-submitted job.
        profile = MachineProfile.load(args.machine, validate=False)
        spec = JobSpec(name="mpi", walltime="00:00:01", total_ranks=args.ranks)
        # executable="" so the argv can be trimmed to the bare launcher line;
        # render_mpi_argv always appends str(executable), even when empty.
        argv = render_mpi_argv(spec, profile, "")[:-1]
    except ProfileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(" ".join(argv))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m nos_workflow.platform",
        description="Machine-aware scheduler headers and MPI launch lines.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    card = sub.add_parser("card", help="print a scheduler header for one system/stage")
    card.add_argument("--system", required=True, help="system yaml name, e.g. secofs_ufs")
    card.add_argument("--stage", required=True, choices=["prep", "nowcast", "forecast", "post"])
    card.add_argument("--machine", default=None, help="default: $NOS_MACHINE or wcoss2")
    card.set_defaults(func=_card)

    mpi = sub.add_parser("mpi", help="print the MPI launch argv for N ranks")
    mpi.add_argument("--ranks", required=True, type=int)
    mpi.add_argument("--machine", default=None, help="default: $NOS_MACHINE or wcoss2")
    mpi.set_defaults(func=_mpi)

    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
