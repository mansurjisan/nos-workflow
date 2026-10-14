"""STOFS-2D-GLO ops mode: ADCIRC_SEGMENT / ADCIRC_STREAM comma lists run as the steps of one prep, nowcast, forecast or post job. MJ (10/14/26)"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from nos_workflow.errors import StageFailedError
from nos_workflow.registry import OFSDescriptor
from nos_workflow.stages import _adcirc, prep as prep_stage
from nos_workflow.machine import MachineProfile
from nos_workflow.runners.adcirc import hotstart, ops
from nos_workflow.tests.runners.test_adcirc_ops import RUN, FakeAdcirc, FakeAdcprep, _ctx, _ncst221, _rerun_forcing

DESC = OFSDescriptor(name="stofs_2d_glo", framework="adcirc", canonical_stages=("prep", "nowcast", "forecast", "post"),
                     stage_aliases={}, yaml_path=Path("parm/systems/stofs_2d_glo.yaml"), runner_module="", notes="test fixture")


class Steps:
    """A stand-in for the per-step function: records (segment, stream), fails on the step named in `fail`. MJ (10/14/26)"""

    def __init__(self, fail=""):
        self.calls, self.fail = [], fail

    def __call__(self, ctx):
        self.calls.append((ctx.segment, ctx.stream))
        if self.fail in ("%s_%s" % (ctx.stream, ctx.segment), ctx.segment, "*"):
            raise RuntimeError("boom")
        return ["mpiexec", "-n", "4"]


@pytest.fixture()
def run_stage(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)

    def go(stage, segment, stream="", step=None, mode="ops"):
        ctx = _ctx(tmp_path, ADCIRC_SEGMENT=segment, ADCIRC_STREAM=stream, ADCIRC_MODE=mode)
        monkeypatch.setattr(_adcirc, "load_context", lambda d: ctx)
        step = step or Steps()
        return step, _adcirc.run_model_stage(DESC, stage, step)
    go.log = lambda: [r.getMessage() for r in caplog.records]
    return go


def _summary(run_stage):
    return [m for m in run_stage.log() if m.startswith("STAGE_SUMMARY")][-1]


def test_nowcast_list_runs_spinup_once_then_every_stream(run_stage):
    step, rc = run_stage("nowcast", "spinup,ncst", "tide,surf")
    assert rc == 0 and step.calls == [("spinup", ""), ("ncst", "tide"), ("ncst", "surf")]
    assert re.search(r"STAGE_SUMMARY stage=nowcast ofs=stofs_2d_glo status=PASS runtime_s=\d+\.\d "
                     r"steps=spinup:\d+,tide_ncst:\d+,surf_ncst:\d+ launch=mpiexec -n 4$", _summary(run_stage))
    assert "--- step: surf_ncst ---" in run_stage.log()


def test_forecast_list_runs_every_stream_in_the_order_given(run_stage):
    step, _ = run_stage("forecast", "fcst", "surf, tide")
    assert step.calls == [("fcst", "surf"), ("fcst", "tide")]
    assert "steps=surf_fcst:" in _summary(run_stage) and ",tide_fcst:" in _summary(run_stage)


def test_prep_and_post_lists_do_not_iterate_over_streams(run_stage):
    step, _ = run_stage("prep", "adcprep,ncst,fcst", "tide,surf")
    assert step.calls == [("adcprep", ""), ("ncst", ""), ("fcst", "")]
    assert re.search(r"steps=adcprep:\d+,gfs_ncst:\d+,gfs_fcst:\d+", _summary(run_stage))
    step, _ = run_stage("post", "anomaly,bias,ncdiff,grib2,ncrcat", "tide,surf")
    assert [c[0] for c in step.calls] == ["anomaly", "bias", "ncdiff", "grib2", "ncrcat"] and {c[1] for c in step.calls} == {""}
    assert "steps=anomaly:" in _summary(run_stage) and ",ncrcat:" in _summary(run_stage)


def test_a_single_value_is_one_step_as_before(run_stage):
    step, _ = run_stage("nowcast", "ncst", "tide")
    assert step.calls == [("ncst", "tide")] and "steps=tide_ncst:" in _summary(run_stage)
    step, _ = run_stage("nowcast", "spinup")  # no stream needed; the spin-up is tide-only
    assert step.calls == [("spinup", "")]


def test_first_failure_stops_the_job_and_names_the_step(run_stage):
    step = Steps(fail="surf_fcst")
    with pytest.raises(StageFailedError, match=r"ADCIRC forecast failed: surf_fcst: boom"):
        run_stage("forecast", "fcst", "tide,surf,tide", step)
    assert step.calls == [("fcst", "tide"), ("fcst", "surf")]
    line = _summary(run_stage)
    assert re.search(r"status=FAIL runtime_s=\d+\.\d steps=tide_fcst:\d+ reason=surf_fcst: boom$", line)
    step = Steps(fail="tide_ncst")
    with pytest.raises(StageFailedError, match="tide_ncst: boom"):
        run_stage("nowcast", "spinup,ncst", "tide,surf", step)
    assert step.calls == [("spinup", ""), ("ncst", "tide")] and "steps=spinup:" in _summary(run_stage)


def test_retired_segments_are_rejected_anywhere_in_a_list_before_any_step(run_stage):
    for seg in ("fcst1", "fcst,fcst2", "fcst2,fcst"):
        step = Steps()
        with pytest.raises(StageFailedError, match=r"retired.*ADCIRC_SEGMENT=fcst"):
            run_stage("forecast", seg, "tide,surf", step)
        assert step.calls == []


@pytest.mark.parametrize("stage,seg,stream,msg", [
    ("nowcast", "spinup,bogus", "tide", "ADCIRC_SEGMENT must be one value or a comma list"),
    ("nowcast", "fcst", "tide", "ADCIRC_SEGMENT must be one value or a comma list"),
    ("forecast", "", "tide", "ADCIRC_SEGMENT must be one value or a comma list"),
    ("forecast", "fcst", "tide,sea", "ADCIRC_STREAM must be one value or a comma list"),
    ("nowcast", "spinup,ncst", "", "ADCIRC_STREAM must be one value or a comma list"),
    ("prep", "ncst,cold", "", "ADCIRC_SEGMENT must be one value or a comma list"),
    ("post", "ncdiff,grib3", "", "ADCIRC_SEGMENT must be one value or a comma list"),
])
def test_the_whole_list_is_checked_before_the_first_step(run_stage, stage, seg, stream, msg):
    step = Steps()
    with pytest.raises(StageFailedError, match=msg):
        run_stage(stage, seg, stream, step)
    assert step.calls == []
    assert "reason=%s" % msg in _summary(run_stage) or msg in _summary(run_stage)


def test_single_mode_runs_the_step_once_with_the_old_summary(run_stage):
    step, _ = run_stage("nowcast", "tide,surf", "tide,surf", mode="single")
    assert step.calls == [("tide,surf", "tide,surf")]
    assert re.search(r"status=PASS runtime_s=\d+\.\d launch=mpiexec -n 4$", _summary(run_stage))
    with pytest.raises(StageFailedError, match="ADCIRC nowcast failed: boom$"):
        run_stage("nowcast", "", "", Steps(fail="*"), mode="single")
    assert re.search(r"status=FAIL runtime_s=\d+\.\d reason=boom$", _summary(run_stage))


def test_the_summary_keeps_the_pass_gate_and_the_status_script_fields(run_stage):
    run_stage("nowcast", "ncst", "tide,surf")
    line = _summary(run_stage)
    assert re.search(r"STAGE_SUMMARY .*status=PASS", line)
    assert re.search(r"status=[A-Za-z]* runtime_s=[0-9.]*", line)  # what slurm/stofs_2d_glo/status_stofs_2d_glo.sh prints


def test_prep_stage_in_ops_mode_runs_the_segment_list(tmp_path, monkeypatch, caplog):
    from nos_workflow.runners.adcirc import ops

    caplog.set_level(logging.INFO)
    ctx = _ctx(tmp_path, ADCIRC_SEGMENT="adcprep,ncst,fcst")
    monkeypatch.setattr(_adcirc, "load_context", lambda d: ctx)
    monkeypatch.setenv("ADCIRC_MODE", "ops")
    calls = []
    monkeypatch.setattr(ops, "run_prep", lambda c: calls.append(c.segment) or 0)
    assert prep_stage.run(DESC, object()) == 0
    assert calls == ["adcprep", "ncst", "fcst"]
    line = [r.getMessage() for r in caplog.records if r.getMessage().startswith("STAGE_SUMMARY")][-1]
    assert re.search(r"stage=prep .*status=PASS runtime_s=\d+\.\d steps=adcprep:\d+,gfs_ncst:\d+,gfs_fcst:\d+$", line)
    monkeypatch.setattr(ops, "run_prep", lambda c: (_ for _ in ()).throw(RuntimeError("no GFS")))
    with pytest.raises(StageFailedError, match="adcprep: no GFS"):
        prep_stage.run(DESC, object())


def test_a_cold_cycle_runs_prep_nowcast_forecast_through_the_list_dispatch(tmp_path, monkeypatch, caplog):
    """The prep, nowcast and forecast jobs as the launchers submit them (cold start), real step functions, fake padcirc and adcprep. MJ (10/14/26)"""
    caplog.set_level(logging.INFO)
    prof = MachineProfile.load("wcoss2", validate=False)
    steps = {"prep": lambda c: ops.run_prep(c, FakeAdcprep()),
             "nowcast": lambda c: ops.run_nowcast(c, FakeAdcirc(), prof, FakeAdcprep()),
             "forecast": lambda c: ops.run_forecast(c, FakeAdcirc(), prof, FakeAdcprep())}

    def job(stage, segment, stream=""):
        ctx = _ctx(tmp_path, ADCIRC_SEGMENT=segment, ADCIRC_STREAM=stream)
        monkeypatch.setattr(_adcirc, "load_context", lambda d: ctx)
        caplog.clear()
        assert _adcirc.run_model_stage(DESC, stage, steps[stage]) == 0
        return ctx, [r.getMessage() for r in caplog.records if r.getMessage().startswith("STAGE_SUMMARY")][-1]

    ctx = _ctx(tmp_path)
    _rerun_forcing(ctx)  # staged ops forcing: the GFS steps skip, as on Hercules
    _ncst221(ctx, 7)
    ctx, line = job("prep", "adcprep,ncst,fcst")
    assert (ctx.comges / f"{RUN}_nod_equi").is_file() and "steps=adcprep:" in line and ",gfs_fcst:" in line
    ctx, line = job("nowcast", "spinup,ncst", "tide,surf")
    assert re.search(r"steps=spinup:\d+,tide_ncst:\d+,surf_ncst:\d+", line)
    for kind in ("hotstart", "restart"):
        assert hotstart.file_time(ctx.cycle_dir(ctx.cycle_time, kind)) == 604800
    ctx, line = job("forecast", "fcst", "tide,surf")
    assert re.search(r"status=PASS .*steps=tide_fcst:\d+,surf_fcst:\d+", line)
    for name in ("points.htp.nc", "points.cwl.nc", "points.cwl.noanomaly.nc", "fields.cwl.maxele.nc"):
        assert ctx.cycle_dir(ctx.cycle_time, name).is_file(), name
    # a forecast cannot run twice: the job stops at the first stream and names the step
    with pytest.raises(StageFailedError, match=r"tide_fcst: .*advanced past"):
        job("forecast", "fcst", "tide,surf")
    assert "status=FAIL" in [r.getMessage() for r in caplog.records if r.getMessage().startswith("STAGE_SUMMARY")][-1]
