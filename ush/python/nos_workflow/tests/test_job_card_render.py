"""WCOSS2 job-card and MPI-argv rendering baseline.

Two guarantees, both required before PBS syntax leaves the system YAMLs:

1. Rendering a card from (system YAML + machine profile) reproduces the
   hand-written ``pbs/*.pbs`` directives **exactly** -- so moving `select=`
   out of the YAML cannot silently change an allocation.
2. A frozen normalized snapshot of directives + launcher argv, so any later
   change is a visible diff rather than a discovery on WCOSS2.

The (system, stage) -> JobSpec mapping lives in ``nos_workflow.platform.jobs``
so the submit CLI (``python3 -m nos_workflow.platform card ...``) renders the
exact same cards this test freezes, rather than a second hand-copy of them.

Regenerate the snapshot deliberately:

    python3 ush/python/nos_workflow/tests/test_job_card_render.py --update
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "job_cards_wcoss2.json"

sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.platform import (  # noqa: E402
    JobSpec, KIND_MODEL, MachineProfile, render_directives, render_mpi_argv,
)
from nos_workflow.platform import jobs  # noqa: E402

CATALOG_KEYS = sorted(jobs.CATALOG.keys())


def _card_directives(card: str) -> list:
    path = REPO / card
    if not path.is_file():
        return []
    return [l.rstrip("\n") for l in path.read_text().splitlines() if l.startswith("#PBS")]


@pytest.fixture()
def wcoss2():
    # Function-scoped (not module-scoped): a module-scoped fixture would be
    # built before the per-function autouse clean_env fixture ever runs
    # (pytest instantiates higher-scoped fixtures first), so a NOS_ACCOUNT/
    # NOS_QOS/NOS_MACHINE already exported in the caller's shell would leak
    # into every parametrized case here instead of being stripped.
    return MachineProfile.load("wcoss2", machines_dir=REPO / "parm" / "machines")


@pytest.mark.parametrize("key", CATALOG_KEYS, ids=[f"{s}/{g}" for s, g in CATALOG_KEYS])
def test_rendered_card_matches_handwritten(key, wcoss2):
    """The whole point of P1: a generated WCOSS2 card must be indistinguishable
    from the card that is running in pre-ops today."""
    system, stage = key
    card = jobs.CATALOG[key].card
    expected = _card_directives(card)
    if not expected:
        pytest.skip(f"{card} not present in this checkout")

    actual = render_directives(jobs.build_job_spec(system, stage, REPO), wcoss2)
    assert actual == expected, (
        f"{card} rendering drifted:\n"
        f"  rendered:\n    " + "\n    ".join(actual) + "\n"
        f"  in file:\n    " + "\n    ".join(expected)
    )


def test_model_node_counts_are_derived_not_authored(wcoss2):
    """ceil(nprocs / ranks_per_node) must reproduce every hand-authored
    select= node count; that equality is what makes the move safe."""
    for system, stage in CATALOG_KEYS:
        ss = jobs.CATALOG[(system, stage)]
        if ss.kind != KIND_MODEL:
            continue
        expected = _card_directives(ss.card)
        if not expected:
            continue
        authored = int(re.search(r"select=(\d+)", " ".join(expected)).group(1))
        derived = wcoss2.nodes(jobs.nprocs_for(system, REPO))
        assert derived == authored, (
            f"{ss.card}: derived {derived} nodes, card says {authored}"
        )


def _normalized() -> dict:
    profile = MachineProfile.load("wcoss2", machines_dir=REPO / "parm" / "machines")
    out = {}
    for system, stage in CATALOG_KEYS:
        ss = jobs.CATALOG[(system, stage)]
        spec = jobs.build_job_spec(system, stage, REPO)
        record = {
            "directives": render_directives(spec, profile),
            "nodes": profile.nodes(spec.total_ranks) if ss.kind == KIND_MODEL else 1,
            "total_ranks": spec.total_ranks,
        }
        if ss.kind == KIND_MODEL:
            record["mpi_argv"] = render_mpi_argv(spec, profile, "MODEL.exe")
        out[ss.card] = record
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
