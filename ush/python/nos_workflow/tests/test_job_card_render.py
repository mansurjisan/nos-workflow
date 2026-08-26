"""WCOSS2 job-card and MPI-argv rendering baseline.

Two guarantees, both required before PBS syntax leaves the system YAMLs:

1. Rendering a card from (system YAML + machine profile) reproduces the
   hand-written ``pbs/*.pbs`` directives **exactly** -- so moving `select=`
   out of the YAML cannot silently change an allocation.
2. A frozen normalized snapshot of directives + launcher argv, so any later
   change is a visible diff rather than a discovery on WCOSS2.

Regenerate the snapshot deliberately:

    python3 ush/python/nos_workflow/tests/test_job_card_render.py --update
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "job_cards_wcoss2.json"

sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.platform import (  # noqa: E402
    JobSpec, KIND_MODEL, KIND_SERIAL, MachineProfile,
    render_directives, render_mpi_argv,
)
from nos_workflow.utils import yaml_to_env  # noqa: E402

# (card, system yaml, job name, kind, walltime, ompthreads, extra -l resources,
#  mem, real_logs). real_logs=True means the job redirects its own stdout/
# stderr in-script and PBS -o/-e must stay absent (see render.JobSpec.stdout).
CARDS = [
    ("pbs/jnos_prep_00.pbs", "secofs_ufs", "secofs_ufs_prep_00", KIND_SERIAL, "02:00:00", None, (), None, False),
    ("pbs/jnos_nowcast_00.pbs", "secofs_ufs", "secofs_ufs_nc_00", KIND_MODEL, "01:30:00", None, (), None, False),
    ("pbs/jnos_forecast_00.pbs", "secofs_ufs", "secofs_ufs_fc_00", KIND_MODEL, "05:30:00", None, (), None, False),
    ("pbs/jnos_post_00.pbs", "secofs_ufs", "secofs_ufs_post_00", KIND_SERIAL, "02:00:00", None, (), None, True),
    ("pbs/stofs_3d_atl_ufs/jnos_prep_00.pbs", "stofs_3d_atl_ufs", "stofs_3d_atl_ufs_prep_00", KIND_SERIAL, "02:00:00", None, (), None, False),
    ("pbs/stofs_3d_atl_ufs/jnos_nowcast_00.pbs", "stofs_3d_atl_ufs", "stofs_3d_atl_ufs_nc_00", KIND_MODEL, "01:30:00", 1, (), None, False),
    ("pbs/stofs_3d_atl_ufs/jnos_forecast_00.pbs", "stofs_3d_atl_ufs", "stofs_3d_atl_ufs_fc_00", KIND_MODEL, "05:30:00", 1, (), None, False),
    ("pbs/stofs_3d_atl_ufs/jnos_post_00.pbs", "stofs_3d_atl_ufs", "stofs_3d_atl_ufs_post_00", KIND_SERIAL, "02:00:00", None, (), None, True),
    ("pbs/stofs_3d_atl_ufs_standalone/jnos_prep_00.pbs", "stofs_3d_atl_ufs_standalone", "stofs_3d_atl_ufs_sa_prep_00", KIND_SERIAL, "05:00:00", None, (), None, False),
    ("pbs/stofs_3d_atl_ufs_standalone/jnos_nowcast_00.pbs", "stofs_3d_atl_ufs_standalone", "stofs_3d_atl_ufs_sa_nc_00", KIND_MODEL, "05:00:00", 1, (), None, False),
    ("pbs/stofs_3d_atl_ufs_standalone/jnos_forecast_00.pbs", "stofs_3d_atl_ufs_standalone", "stofs_3d_atl_ufs_sa_fc_00", KIND_MODEL, "05:00:00", 1, ("debug=true",), None, False),
]


def _nprocs(system: str) -> int:
    """Total MPI ranks for ``system``, straight from the resolved YAML."""
    saved = dict(os.environ)
    try:
        for var in ("PDY", "cyc"):
            os.environ.pop(var, None)
        os.environ["PDY"] = "20260724"
        os.environ["cyc"] = "00"
        exports = json.loads(
            yaml_to_env.export_env(
                REPO / "parm" / "systems" / f"{system}.yaml",
                framework="comf", output_format="json",
            )
        )
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return int(exports["NPROCS"])


def _spec(entry) -> JobSpec:
    _card, system, name, kind, walltime, omp, extras, mem, real_logs = entry
    stdio = None if real_logs else "/dev/null"
    return JobSpec(
        name=name,
        walltime=walltime,
        kind=kind,
        total_ranks=_nprocs(system) if kind == KIND_MODEL else 1,
        threads_per_rank=omp,
        mem_per_node=mem,
        extra_resources=extras,
        stdout=stdio,
        stderr=stdio,
    )


def _card_directives(card: str) -> list:
    path = REPO / card
    if not path.is_file():
        return []
    return [l.rstrip("\n") for l in path.read_text().splitlines() if l.startswith("#PBS")]


@pytest.fixture(scope="module")
def wcoss2():
    return MachineProfile.load("wcoss2", machines_dir=REPO / "parm" / "machines")


@pytest.mark.parametrize("entry", CARDS, ids=[c[0] for c in CARDS])
def test_rendered_card_matches_handwritten(entry, wcoss2):
    """The whole point of P1: a generated WCOSS2 card must be indistinguishable
    from the card that is running in pre-ops today."""
    card = entry[0]
    expected = _card_directives(card)
    if not expected:
        pytest.skip(f"{card} not present in this checkout")

    actual = render_directives(_spec(entry), wcoss2)
    assert actual == expected, (
        f"{card} rendering drifted:\n"
        f"  rendered:\n    " + "\n    ".join(actual) + "\n"
        f"  in file:\n    " + "\n    ".join(expected)
    )


def test_model_node_counts_are_derived_not_authored(wcoss2):
    """ceil(nprocs / ranks_per_node) must reproduce every hand-authored
    select= node count; that equality is what makes the move safe."""
    for entry in CARDS:
        card, system, _n, kind, *_ = entry
        if kind != KIND_MODEL:
            continue
        expected = _card_directives(card)
        if not expected:
            continue
        authored = int(re.search(r"select=(\d+)", " ".join(expected)).group(1))
        assert wcoss2.nodes(_nprocs(system)) == authored, (
            f"{card}: derived {wcoss2.nodes(_nprocs(system))} nodes, "
            f"card says {authored}"
        )


def _normalized() -> dict:
    profile = MachineProfile.load("wcoss2", machines_dir=REPO / "parm" / "machines")
    out = {}
    for entry in CARDS:
        card, _system, name, kind, *_ = entry
        spec = _spec(entry)
        record = {
            "directives": render_directives(spec, profile),
            "nodes": profile.nodes(spec.total_ranks) if kind == KIND_MODEL else 1,
            "total_ranks": spec.total_ranks,
        }
        if kind == KIND_MODEL:
            record["mpi_argv"] = render_mpi_argv(spec, profile, "MODEL.exe")
        out[card] = record
    return out


def test_normalized_render_matches_frozen_snapshot():
    if not FIXTURE.exists():
        pytest.fail(
            f"no frozen job-card snapshot. Create it with:\n"
            f"  python3 {Path(__file__).relative_to(REPO)} --update"
        )
    expected = json.loads(FIXTURE.read_text())
    actual = _normalized()

    drift = {k: (expected.get(k), actual.get(k))
             for k in sorted(set(expected) | set(actual))
             if expected.get(k) != actual.get(k)}
    assert not drift, f"rendered job cards drifted from the frozen baseline: {drift}"


def test_mpi_argv_has_no_empty_elements(wcoss2):
    """An empty argv element is the failure mode the ppn_flag: '' schema would
    have introduced; assert the list form never produces one."""
    argv = render_mpi_argv(
        JobSpec(name="x", walltime="01:00:00", total_ranks=2914), wcoss2, "MODEL.exe",
    )
    assert all(a != "" for a in argv), argv
    assert argv[:5] == ["mpiexec", "-n", "2914", "-ppn", "120"]


def _update() -> int:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(_normalized(), indent=2, sort_keys=True) + "\n")
    print(f"froze {FIXTURE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_update() if "--update" in sys.argv else 0)
