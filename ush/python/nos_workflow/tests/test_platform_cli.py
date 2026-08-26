"""``python3 -m nos_workflow.platform`` -- the submit-side CLI end to end.

Runs the module as a real subprocess (not an in-process import) so this
proves what ``ush/nos_run.sh`` and generated job cards actually invoke.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
USH_PYTHON = REPO / "ush" / "python"


def _run(args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "nos_workflow.platform", *args],
        capture_output=True, text=True, cwd=str(USH_PYTHON), env=env,
    )


def test_wcoss2_mpi_launch_is_unchanged_from_todays_command(monkeypatch):
    """The exact string ``ush/nos_run.sh`` hardcodes today -- proves the
    profile-driven CLI is a drop-in replacement, not a behavior change."""
    monkeypatch.delenv("NOS_MACHINE", raising=False)
    proc = _run(["mpi", "--ranks", "2914"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "mpiexec -n 2914 -ppn 120 --cpu-bind core\n"


def test_wcoss2_mpi_launch_explicit_machine(monkeypatch):
    monkeypatch.setenv("NOS_MACHINE", "wcoss2")
    proc = _run(["mpi", "--ranks", "2914"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "mpiexec -n 2914 -ppn 120 --cpu-bind core\n"


def test_hercules_mpi_launch_order(monkeypatch):
    """The proven working ufs-coastal launch line on Hercules: srun -n <N>
    --label, no --export=ALL, no ranks-per-node flag (srun gets total ranks
    only -- ranks-per-node is an SBATCH-header-only fact there). Already
    pinned by test_machine_profile.py's test_mpi_argv_uses_bare_ranks_flag."""
    monkeypatch.setenv("NOS_MACHINE", "hercules")
    proc = _run(["mpi", "--ranks", "2914"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "srun -n 2914 --label\n"


def test_machine_flag_beats_nos_machine_env(monkeypatch):
    monkeypatch.setenv("NOS_MACHINE", "hercules")
    proc = _run(["mpi", "--ranks", "2914", "--machine", "wcoss2"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "mpiexec -n 2914 -ppn 120 --cpu-bind core\n"


def test_card_matches_render_directives_directly():
    """The CLI is a thin wrapper: card output must equal calling
    render_directives/build_job_spec in-process for the same (system, stage)."""
    sys.path.insert(0, str(USH_PYTHON))
    from nos_workflow.platform import MachineProfile, render_directives
    from nos_workflow.platform import jobs

    profile = MachineProfile.load("wcoss2", machines_dir=REPO / "parm" / "machines")
    expected = render_directives(jobs.build_job_spec("secofs_ufs", "prep", REPO), profile)

    proc = _run(["card", "--system", "secofs_ufs", "--stage", "prep"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == expected


def test_card_on_hercules_requires_account(monkeypatch):
    """account: null in hercules.yaml must fail the CLI, not print a card
    with account=None baked in."""
    monkeypatch.delenv("NOS_ACCOUNT", raising=False)
    proc = _run(["card", "--system", "secofs_ufs", "--stage", "nowcast",
                 "--machine", "hercules"])
    assert proc.returncode != 0
    assert "requires account" in proc.stderr
