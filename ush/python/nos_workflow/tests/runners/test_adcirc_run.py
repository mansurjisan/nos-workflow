"""STOFS-2D-GLO launch lines, crash detection, hotstart handoff and archive. MJ (10/05/26)"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.machine import MachineProfile  # noqa: E402
from nos_workflow.runners.adcirc import execute, hotstart as hs, run  # noqa: E402
from nos_workflow.runners.adcirc.settings import AdcircSettings, CycleContext  # noqa: E402
from nos_workflow.tests.runners.test_adcirc_prep import (  # noqa: E402
    CYCLE, FakeAdcprep, YAML, _ctx, _restart, fake_acquire, mesh)  # noqa: F401

RPN = {"wcoss2": 128}


def _profile(name):
    return MachineProfile.load(name, validate=False)


def _s(**env):
    return AdcircSettings.from_yaml(YAML, env)


def test_wcoss2_launch_line_matches_june():
    argv = execute.padcirc_argv(_s(), _profile("wcoss2"), "padcirc", RPN)
    assert argv == ["mpiexec", "-n", "4064", "-ppn", "128", "--cpu-bind", "core", "padcirc"]


def test_hercules_launch_line():
    argv = execute.padcirc_argv(_s(), _profile("hercules"), "padcirc", RPN)
    assert argv == ["srun", "-n", "4064", "--label", "--cpu-bind=cores", "padcirc"]


def test_writers_add_ranks_and_w_flag():
    argv = execute.padcirc_argv(_s(NUM_WRITERS="32"), _profile("wcoss2"), "padcirc", RPN)
    assert argv == ["mpiexec", "-n", "4096", "-ppn", "128", "--cpu-bind", "core",
                    "padcirc", "-W", "32"]
    h = execute.padcirc_argv(_s(NUM_WRITERS="32"), _profile("hercules"), "padcirc", RPN)
    assert h[-3:] == ["padcirc", "-W", "32"] and h[2] == "4096"


def _staged(tmp_path, hot=False, **extra):
    ctx, env = _ctx(tmp_path, **extra)
    prep_mod = __import__("nos_workflow.runners.adcirc.prep", fromlist=["x"])
    return ctx, prep_mod


def _prepped(tmp_path, monkeypatch, mesh_fx=None):
    ctx, env = _ctx(tmp_path)
    from nos_workflow.runners.adcirc import prep

    prep.run_prep(ctx, FakeAdcprep(), fake_acquire)
    return ctx


def test_nowcast_runs_and_archives(tmp_path, mesh):
    ctx = _prepped(tmp_path, None)
    seen = {}

    def launcher(argv, cwd):
        seen["argv"], seen["cwd"] = list(argv), cwd
        (cwd / "adcirc.out").write_text("running\n")
        cold = datetime.fromisoformat(hs.read_timing(cwd)["coldstart_time"])
        _restart(cwd / "fort.68.nc", (CYCLE - cold).total_seconds())
        (cwd / "fort.63.nc").write_text("x")
        return 0

    argv = run.run_nowcast(ctx, launcher, _profile("wcoss2"))
    assert argv[:2] == ["mpiexec", "-n"] and seen["cwd"] == ctx.run_dir("nowcast")
    nc = ctx.run_dir("nowcast")
    done = json.loads((nc / "stofs_2d_glo.t12z.nowcast.done.json").read_text())
    assert "fort.63.nc" in done["outputs"] and "fort.68.nc" in done["outputs"]
    assert not list(nc.glob("PE[0-9]*"))


def test_nowcast_without_restart_fails(tmp_path, mesh):
    ctx = _prepped(tmp_path, None)
    with pytest.raises(RuntimeError, match="valid fort.67/68.nc"):
        run.run_nowcast(ctx, lambda a, c: 0, _profile("wcoss2"))


@pytest.mark.parametrize("text", ["ADCIRC stopping", "MPI Terminating job"])
def test_crash_text_fails_even_with_rc_zero(tmp_path, mesh, text):
    ctx = _prepped(tmp_path, None)

    def launcher(argv, cwd):
        (cwd / "adcirc.err").write_text(f"foo\n{text}\n")
        return 0

    with pytest.raises(RuntimeError, match="crashed"):
        run.run_nowcast(ctx, launcher, _profile("wcoss2"))


def test_nonzero_rc_fails(tmp_path, mesh):
    ctx = _prepped(tmp_path, None)
    with pytest.raises(RuntimeError, match="return code 9"):
        run.run_nowcast(ctx, lambda a, c: 9, _profile("wcoss2"))


def test_missing_pe_dirs_fail_before_launch(tmp_path, mesh):
    ctx = _prepped(tmp_path, None)
    for pe in ctx.run_dir("nowcast").glob("PE[0-9]*"):
        import shutil
        shutil.rmtree(pe)
    called = []
    with pytest.raises(Exception, match="PE directories"):
        run.run_nowcast(ctx, lambda a, c: called.append(1) or 0, _profile("wcoss2"))
    assert called == []


def test_forecast_takes_nowcast_restart(tmp_path, mesh):
    ctx = _prepped(tmp_path, None)
    nc = ctx.run_dir("nowcast")
    cold = datetime.fromisoformat(hs.read_timing(nc)["coldstart_time"])
    _restart(nc / "fort.67.nc", (CYCLE - cold).total_seconds() - 10800)
    _restart(nc / "fort.68.nc", (CYCLE - cold).total_seconds())
    fc = ctx.run_dir("forecast")

    def launcher(argv, cwd):
        assert (cwd / "fort.67.nc").is_file() and not (cwd / "fort.67.nc").is_symlink()
        return 0

    run.run_forecast(ctx, launcher, _profile("wcoss2"))
    t = hs.read_timing(fc)
    assert t["hotstart_file"].endswith("fort.68.nc")
    assert datetime.fromisoformat(t["end_time"]) == CYCLE + timedelta(hours=180)
    assert (fc / "stofs_2d_glo.t12z.forecast.done.json").is_file()


def test_forecast_without_nowcast_restart_fails(tmp_path, mesh):
    ctx = _prepped(tmp_path, None)
    with pytest.raises(RuntimeError, match="forecast cannot run"):
        run.run_forecast(ctx, lambda a, c: 0, _profile("wcoss2"))
