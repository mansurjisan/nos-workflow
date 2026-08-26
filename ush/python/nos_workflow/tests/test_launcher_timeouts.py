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

import fnmatch
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


# ---------------------------------------------------------------------------
# secofs_ufs_ww3 (DATM+SCHISM+WW3): same invariant, per-directory PBS layout
# ---------------------------------------------------------------------------

_WW3_LAUNCHER = _ROOT / "pbs" / "secofs_ufs_ww3" / "launch_secofs_ufs_ww3.sh"
_WW3_JOBS = {
    "PREP": _ROOT / "pbs" / "secofs_ufs_ww3" / "jnos_prep_00.pbs",
    "NOWCAST": _ROOT / "pbs" / "secofs_ufs_ww3" / "jnos_nowcast_00.pbs",
    "FORECAST": _ROOT / "pbs" / "secofs_ufs_ww3" / "jnos_forecast_00.pbs",
    "POST": _ROOT / "pbs" / "secofs_ufs_ww3" / "jnos_post_00.pbs",
}


def _ww3_launcher_timeout(stage: str) -> int:
    m = re.search(
        rf"^{stage}_TIMEOUT=\$\{{{stage}_TIMEOUT:-(\d+)\}}",
        _WW3_LAUNCHER.read_text(), re.M,
    )
    assert m, f"no {stage}_TIMEOUT default in {_WW3_LAUNCHER.name}"
    return int(m.group(1))


@pytest.mark.parametrize("stage", sorted(_WW3_JOBS))
def test_ww3_launcher_waits_at_least_as_long_as_the_job_may_run(stage):
    """Same invariant as the secofs_ufs launcher: a poll shorter than the
    walltime can only ever be wrong, since the launcher never qdels."""
    pbs = _WW3_JOBS[stage]
    if not pbs.is_file():
        pytest.skip(f"{pbs.name} not present")
    timeout = _ww3_launcher_timeout(stage)
    walltime = _walltime_seconds(pbs)
    assert timeout >= walltime, (
        f"{stage}_TIMEOUT={timeout}s is shorter than {pbs.name}'s "
        f"walltime={walltime}s: the launcher would report FAIL while the "
        f"job is still legitimately running"
    )


def test_ww3_pbs_scripts_sized_for_5520_ranks():
    """nowcast/forecast select= lines are resized to 46 nodes @ 120 ppn
    (5520 ranks = datm 120 + schism 2794 + wav 2606), matching
    ufs_coastal.total_tasks in parm/systems/secofs_ufs_ww3.yaml."""
    for stage in ("NOWCAST", "FORECAST"):
        pbs = _WW3_JOBS[stage]
        if not pbs.is_file():
            pytest.skip(f"{pbs.name} not present")
        text = pbs.read_text()
        assert "select=46:ncpus=128:mpiprocs=120:ompthreads=1" in text
        assert re.search(r"TOTAL_TASKS:-5520\}", text)


def test_ww3_pbs_scripts_point_at_wave_executable():
    """nowcast/forecast export UFS_EXEC_NAME=fv3_coastalSW.exe explicitly
    -- the YAML's model.executable is NOT auto-propagated to the runner
    for the UFS (non-standalone) path, so without this export the runner
    would silently fall back to the non-wave fv3_coastalS.exe default."""
    for stage in ("NOWCAST", "FORECAST"):
        pbs = _WW3_JOBS[stage]
        if not pbs.is_file():
            pytest.skip(f"{pbs.name} not present")
        text = pbs.read_text()
        assert re.search(r"UFS_EXEC_NAME:-fv3_coastalSW\.exe\}", text)


def test_ww3_nowcast_timeout_covers_one_blind_retry_plus_headroom():
    """NOWCAST_TIMEOUT must clear 2x walltime (one attempt + one ParMETIS
    blind retry) with real queue/polling headroom on top -- not exactly
    2x with zero slack, which false-FAILs a healthy cycle whose retry
    submission is merely slow to schedule."""
    walltime = _walltime_seconds(_WW3_JOBS["NOWCAST"])
    timeout = _ww3_launcher_timeout("NOWCAST")
    assert timeout >= 2 * walltime + 1800, (
        f"NOWCAST_TIMEOUT={timeout}s leaves no real headroom over "
        f"2x walltime ({2 * walltime}s)"
    )


def test_ww3_forecast_timeout_has_real_headroom_over_walltime():
    """FORECAST_TIMEOUT's comment has always claimed '+ 10 min' (now
    '+ 30 min') over the PBS walltime -- pin that the constant actually
    carries it rather than silently drifting back to walltime exactly."""
    walltime = _walltime_seconds(_WW3_JOBS["FORECAST"])
    timeout = _ww3_launcher_timeout("FORECAST")
    assert timeout >= walltime + 1800, (
        f"FORECAST_TIMEOUT={timeout}s leaves no real headroom over "
        f"walltime ({walltime}s)"
    )


def test_ww3_pbs_scripts_keep_parmetis_retry():
    """nowcast/forecast keep the ParMETIS blind-retry block (same
    signature-driven guard as secofs_ufs's own PBS cards)."""
    for stage in ("NOWCAST", "FORECAST"):
        pbs = _WW3_JOBS[stage]
        if not pbs.is_file():
            pytest.skip(f"{pbs.name} not present")
        text = pbs.read_text()
        assert "PARMETIS_RETRY" in text
        assert "partition_hgrid" in text


class TestWarmLauncherTimeout:
    """The warm-start launcher obeys the same timeout rule as its sibling.

    launch_secofs_ufs_ww3_warm.sh polls for a STAGE_SUMMARY and gives up
    after RUN_WAIT_MIN. Like the operational launcher it does not qdel, so
    a value below the PBS job's own walltime cannot stop anything -- it can
    only mislabel a healthy cycle, which is the failure this module exists
    to prevent.
    """

    _WARM = _ROOT / "pbs" / "secofs_ufs_ww3" / "launch_secofs_ufs_ww3_warm.sh"
    _NOWCAST = _ROOT / "pbs" / "secofs_ufs_ww3" / "jnos_nowcast_00.pbs"

    def _walltime_minutes(self) -> int:
        m = re.search(r"walltime=(\d+):(\d+):(\d+)", self._NOWCAST.read_text())
        assert m, "no walltime= in jnos_nowcast_00.pbs"
        return int(m.group(1)) * 60 + int(m.group(2))

    def _run_wait_minutes(self) -> int:
        m = re.search(r"RUN_WAIT_MIN=\$\{RUN_WAIT_MIN:-(\d+)\}", self._WARM.read_text())
        assert m, "no RUN_WAIT_MIN default in launch_secofs_ufs_ww3_warm.sh"
        return int(m.group(1))

    def test_warm_launcher_exists_and_is_executable(self) -> None:
        assert self._WARM.is_file()
        assert self._WARM.stat().st_mode & 0o111, "warm launcher must be executable (cron runs it)"

    def test_run_wait_covers_nowcast_walltime(self) -> None:
        wall = self._walltime_minutes()
        wait = self._run_wait_minutes()
        assert wait >= wall, (
            f"RUN_WAIT_MIN={wait} min is below the nowcast walltime of {wall} min; "
            "a healthy slow cycle would be reported as TIMEOUT"
        )

    def test_scratch_comout_is_not_the_operational_one(self) -> None:
        """The experiment must never write into the operational COMOUT."""
        txt = self._WARM.read_text()
        assert "warmtest" in txt
        assert "COMOUT=$SCRATCH" in txt


class TestWarmLauncherStagesInputsOnly:
    """The warm launcher stages prep's inputs, not the run's outputs.

    The nowcast reads its inputs from $COMOUT, so the scratch tree has to be
    seeded from the operational one -- but only with what prep produced. A
    plain `rsync -a` also copied the SCHISM restarts the run writes rather
    than reads, this cycle's own wave restart archive, and every post
    product: 86 GB against roughly 20 GB of real inputs, growing daily as
    post writes more.

    Both directions are pinned here. Asserting only that certain excludes
    exist would let a new one that swallows the hotstart pass, and asserting
    only that the hotstart survives would let an exclude quietly disappear.
    """

    _WARM = _ROOT / "pbs" / "secofs_ufs_ww3" / "launch_secofs_ufs_ww3_warm.sh"

    # Every post product enabled in parm/systems/secofs_ufs.yaml, plus the
    # run's own restarts. Keep in step with that file's `post.products`.
    _REQUIRED_EXCLUDES = (
        "*.rst.*.nc",              # SCHISM restarts the run writes, ~18 GB each
        "*restart_outputs",        # SCHISM run output directory
        "*wave_restart",           # this cycle's own wave restart, ~7 GB
        "*stations*.nc",           # stations_nc, stations_mllw
        "*station.profile*.nc",    # profiles
        "*outputs.post.json",      # post manifest
        "*.fields.*.nc",           # fields_nc
        "*.field2d.*.nc",          # slab2d
        "*.adcirc.*",              # adcirc
        "*.gpkg",                  # geopkg, 54 files
        "*maxele*",                # maxele
    )

    # Representative prep-produced inputs the nowcast stages. If any exclude
    # glob matches one of these, staging fails.
    _MUST_KEEP = (
        "secofs_ufs_ww3.t12z.20260825.init.nowcast.nc",
        "secofs_ufs_ww3.t12z.20260825.init.nowcast.nc.provenance.json",
        "secofs_ufs_ww3.t12z.nest.ww3",
        "secofs_ufs_ww3.t12z.ufs.configure",
        "secofs_ufs_ww3.t12z.20260825.bctides.in.nowcast",
        "secofs_ufs_ww3.t12z.20260825.bctides.in.forecast",
        "secofs_ufs_ww3.t12z.20260825.river.th.tar",
        "secofs_ufs_ww3.t12z.20260825.obc.nowcast.tar",
        "secofs_ufs_ww3.t12z.20260825.nwm.source.sink.now.tar",
        "secofs_ufs_ww3.t12z.20260825.inputs.nowcast.json",
        "secofs_ufs_ww3.t12z.datm.streams",
        "secofs_ufs_ww3.t12z.datm_in",
        "secofs_ufs_ww3.t12z.model_configure",
        "secofs_ufs_ww3.t12z.ww3_bound.inp",
        "secofs_ufs_ww3.t12z.forecast_outputs",   # prep-produced; near restart_outputs
        "secofs_ufs_ww3.source_sink.in",
        "base_date.t12z",
        "time_hotstart.t12z",
        "time_nowcastend.t12z",
    )

    def _configured_excludes(self) -> list:
        return re.findall(r"--exclude='([^']+)'", self._WARM.read_text())

    def test_every_required_output_pattern_is_excluded(self) -> None:
        configured = set(self._configured_excludes())
        missing = [p for p in self._REQUIRED_EXCLUDES if p not in configured]
        assert not missing, f"staging no longer excludes: {missing}"

    def test_no_exclude_matches_a_prep_produced_input(self) -> None:
        """The real contract: whatever the globs are, they must not eat an input.

        A pattern such as `*.nc`, `*nowcast*.nc` or `*init.nowcast.nc` would
        pass a list-of-strings check while dropping the hotstart and failing
        the run at staging.
        """
        configured = self._configured_excludes()
        for name in self._MUST_KEEP:
            hit = [g for g in configured if fnmatch.fnmatch(name, g)]
            assert not hit, f"exclude {hit} would drop required input {name}"
