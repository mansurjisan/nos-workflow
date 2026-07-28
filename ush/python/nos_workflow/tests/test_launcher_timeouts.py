"""The SECOFS launcher's stage timeouts vs the PBS jobs' walltimes.

The launcher polls for a STAGE_SUMMARY and gives up after a per-stage
timeout. It does not qdel, so a timeout shorter than the job's own
walltime cannot stop anything -- it can only mislabel a healthy cycle.

That is not hypothetical. POST_TIMEOUT was 1800 s, sized when post
produced stations only (~13 min). Enabling the full product suite took
post to 33:11 on the 20260728 coupled cycle, so the launcher reported

    FAIL[post]: TIMEOUT after 1802s (no STAGE_SUMMARY=PASS)
    ABORT cycle 20260728t00z: stage 'post' did not succeed

for a job that finished three minutes later with Exit_status = 0.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[4]
_LAUNCHER = _ROOT / "pbs" / "launch_secofs_ufs.sh"
_JOBS = {
    "PREP": _ROOT / "pbs" / "jnos_prep_00.pbs",
    "NOWCAST": _ROOT / "pbs" / "jnos_nowcast_00.pbs",
    "FORECAST": _ROOT / "pbs" / "jnos_forecast_00.pbs",
    "POST": _ROOT / "pbs" / "jnos_post_00.pbs",
}


def _launcher_timeout(stage: str) -> int:
    m = re.search(
        rf"^{stage}_TIMEOUT=\$\{{{stage}_TIMEOUT:-(\d+)\}}",
        _LAUNCHER.read_text(), re.M,
    )
    assert m, f"no {stage}_TIMEOUT default in {_LAUNCHER.name}"
    return int(m.group(1))


def _walltime_seconds(pbs: Path) -> int:
    m = re.search(r"^#PBS\s+-l\s+walltime=(\d+):(\d+):(\d+)",
                  pbs.read_text(), re.M)
    assert m, f"no walltime in {pbs.name}"
    h, mnt, s = (int(g) for g in m.groups())
    return h * 3600 + mnt * 60 + s


@pytest.mark.parametrize("stage", sorted(_JOBS))
def test_launcher_waits_at_least_as_long_as_the_job_may_run(stage):
    """A poll shorter than the walltime can only ever be wrong.

    The job cannot outlive its walltime, and the launcher does not kill
    it, so any shortfall is a false FAIL on a cycle that was fine.
    """
    pbs = _JOBS[stage]
    if not pbs.is_file():          # stage without a top-level PBS job
        pytest.skip(f"{pbs.name} not present")
    timeout = _launcher_timeout(stage)
    walltime = _walltime_seconds(pbs)
    assert timeout >= walltime, (
        f"{stage}_TIMEOUT={timeout}s is shorter than {pbs.name}'s "
        f"walltime={walltime}s: the launcher would report FAIL while the "
        f"job is still legitimately running"
    )


def test_post_timeout_covers_the_measured_full_suite_runtime():
    """33:11 measured with all eight products; keep real headroom over it."""
    assert _launcher_timeout("POST") >= 2 * 1991
