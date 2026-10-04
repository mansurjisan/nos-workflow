"""STOFS-3D-ATL previous-cycle files in the ops v3.1 layout.

Covers the staout_1 join written to $COMOUT (time shift, boundary duplicate, missing half), the
nowcast param.nml archived to $COMOUT/rerun, the ATL prep env (COMOUT_PREV, COMOUTrerun) and its
ATL-only gating.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from nos_workflow.registry import OFSDescriptor
from nos_workflow.runners.schism_ufs.archive import run_python as archive_run
from nos_workflow.runners.schism_ufs.context import SchismRunContext
from nos_workflow.stages import prep as prep_stage
from nos_workflow.tools import build_staout_1 as bs

from .test_stage_dispatch import (
    _install_stub_nco_bridge,
    _secofs_ufs_desc,
    _stofs_3d_atl_ufs_desc,
)

RUN = "stofs_3d_atl_ufs"
# Rows as SCHISM writes them: e24.16 time, then (1x,e14.6) values.
NOW = [
    "  0.3000000000000000E+03   0.373644E+00  -0.208740E-02",
    "  0.6000000000000000E+03   0.380000E+00  -0.100000E-01",
    "  0.9000000000000000E+03   0.390000E+00   0.500000E-02",
]
FC = [
    "  0.3000000000000000E+03   0.400000E+00   0.100000E-01",
    "  0.6000000000000000E+03   0.410000E+00   0.200000E-01",
]


def _write(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n")
    return path


def _cycle_dir(tmp_path, pdy="20260928", now=NOW, fc=FC, markers=True, run=RUN):
    comout = tmp_path / ("%s.%s" % (run, pdy))
    if now is not None:
        _write(comout / ("%s.t12z.restart_outputs" % run) / "staout_1", now)
    if fc is not None:
        _write(comout / ("%s.t12z.forecast_outputs" % run) / "staout_1", fc)
    if markers:
        cyc = datetime.strptime(pdy + "12", "%Y%m%d%H")
        (comout / "time_hotstart.t12z").write_text((cyc - timedelta(days=1)).strftime("%Y%m%d%H") + "\n")
        (comout / "time_nowcastend.t12z").write_text(cyc.strftime("%Y%m%d%H") + "\n")
    return comout


class TestJoinStaout1:
    def test_forecast_time_is_shifted_by_the_nowcast_length_in_ops_format(self, tmp_path):
        text, dropped = bs.join_staout_1(
            _write(tmp_path / "n", NOW), _write(tmp_path / "f", FC), 86400.0)
        lines = text.splitlines()
        assert dropped == 0 and len(lines) == 5
        assert lines[:3] == NOW
        assert lines[3] == "  0.8670000000000000E+05   0.400000E+00   0.100000E-01"
        assert lines[4] == "  0.8700000000000000E+05   0.410000E+00   0.200000E-01"

    def test_numeric_content_is_nowcast_then_shifted_forecast(self, tmp_path):
        text, _ = bs.join_staout_1(_write(tmp_path / "n", NOW), _write(tmp_path / "f", FC), 900.0)
        out = tmp_path / "j"
        out.write_text(text)
        got = np.loadtxt(str(out))
        want = np.vstack([np.loadtxt(str(tmp_path / "n")), np.loadtxt(str(tmp_path / "f"))])
        want[3:, 0] += 900.0
        np.testing.assert_allclose(got, want, rtol=0, atol=0)
        assert np.all(np.diff(got[:, 0]) > 0)

    def test_boundary_row_shared_by_both_runs_is_dropped_once(self, tmp_path):
        fc = ["  0.0000000000000000E+00   0.390000E+00   0.500000E-02"] + FC
        text, dropped = bs.join_staout_1(_write(tmp_path / "n", NOW), _write(tmp_path / "f", fc), 900.0)
        assert dropped == 1
        times = [float(r.split()[0]) for r in text.splitlines()]
        assert times == [300.0, 600.0, 900.0, 1200.0, 1500.0]
        assert text.splitlines()[2] == NOW[2]

    def test_time_format_follows_the_input_width_and_decimals(self, tmp_path):
        now = ["   0.300000E+03   0.1E+00", "   0.600000E+03   0.2E+00"]
        fc = ["   0.300000E+03   0.3E+00"]
        text, _ = bs.join_staout_1(_write(tmp_path / "n", now), _write(tmp_path / "f", fc), 86400.0)
        assert text.splitlines()[2] == "   0.867000E+05   0.3E+00"

    @pytest.mark.parametrize("value,decimals,want", [
        (300.0, 16, "0.3000000000000000E+03"),
        (86700.0, 6, "0.867000E+05"),
        (999999.5, 3, "0.100E+07"),
        (0.0, 4, "0.0000E+00"),
        (-12.5, 4, "-0.1250E+02"),
    ])
    def test_fortran_e_format(self, value, decimals, want):
        assert bs._fortran_e(value, decimals) == want

    def test_column_count_mismatch_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="column count"):
            bs.join_staout_1(_write(tmp_path / "n", NOW),
                             _write(tmp_path / "f", ["  0.3000000000000000E+03   0.4E+00"]), 900.0)

    def test_empty_input_is_rejected(self, tmp_path):
        (tmp_path / "n").write_text("")
        with pytest.raises(ValueError, match="empty"):
            bs.join_staout_1(tmp_path / "n", _write(tmp_path / "f", FC), 900.0)


class TestBuildStaout1:
    def test_joined_series_lands_at_the_comout_root_as_ops_writes_it(self, tmp_path):
        comout = _cycle_dir(tmp_path)
        out = bs.build_staout_1(comout, RUN, 12)
        assert out == comout / "staout_1"
        # shift = time_nowcastend - time_hotstart = 86400 s from the markers
        assert np.loadtxt(str(out))[:, 0].tolist() == [300.0, 600.0, 900.0, 86700.0, 87000.0]
        assert not (comout / "rerun").exists()

    def test_time_origin_is_the_nowcast_start_so_next_cycle_rule_lines_up(self, tmp_path):
        """Next cycle (PDY+1) takes model start = its nowcast start - 24 h = this cycle's nowcast start."""
        comout = _cycle_dir(tmp_path)
        times = np.loadtxt(str(bs.build_staout_1(comout, RUN, 12)))[:, 0]
        next_cycle = datetime(2026, 9, 29, 12)
        model_start = next_cycle - timedelta(hours=24 + 24)
        assert model_start == datetime(2026, 9, 27, 12)
        assert model_start + timedelta(seconds=float(times[2])) == datetime(2026, 9, 27, 12, 15)
        assert model_start + timedelta(seconds=float(times[3])) == datetime(2026, 9, 28, 12, 5)

    def test_avg_bias_file_seeds_a_backfill_under_rerun(self, tmp_path):
        seed = tmp_path / "seed_bias"
        seed.write_text("-0.045\n")
        comout = _cycle_dir(tmp_path)
        bs.build_staout_1(comout, RUN, 12, avg_bias_file=str(seed))
        assert (comout / "rerun" / (RUN + ".t12z.avg_bias")).read_text() == "-0.045\n"

    def test_avg_bias_file_already_in_place_is_accepted(self, tmp_path):
        comout = _cycle_dir(tmp_path)
        placed = comout / "rerun" / (RUN + ".t12z.avg_bias")
        placed.parent.mkdir()
        placed.write_text("0.1\n")
        assert bs.build_staout_1(comout, RUN, 12, avg_bias_file=str(placed))
        assert placed.read_text() == "0.1\n"

    @pytest.mark.parametrize("half", ["now", "fc"])
    def test_missing_half_writes_nothing(self, tmp_path, caplog, half):
        comout = _cycle_dir(tmp_path, now=None if half == "now" else NOW,
                            fc=None if half == "fc" else FC)
        with caplog.at_level("WARNING"):
            assert bs.build_staout_1(comout, RUN, 12) is None
        assert not (comout / "staout_1").exists()
        assert "nothing written" in caplog.text

    def test_unjoinable_inputs_write_nothing(self, tmp_path):
        comout = _cycle_dir(tmp_path, fc=["  0.3000000000000000E+03   0.4E+00"])
        assert bs.build_staout_1(comout, RUN, 12) is None
        assert not (comout / "staout_1").exists()

    def test_a_stale_staout_1_is_left_alone_when_the_rebuild_is_skipped(self, tmp_path):
        comout = _cycle_dir(tmp_path)
        bs.build_staout_1(comout, RUN, 12)
        before = (comout / "staout_1").read_text()
        (comout / ("%s.t12z.forecast_outputs" % RUN) / "staout_1").unlink()
        assert bs.build_staout_1(comout, RUN, 12) is None
        assert (comout / "staout_1").read_text() == before

    def test_without_markers_the_window_comes_from_the_cycle_and_nowcast_hours(self, tmp_path):
        comout = _cycle_dir(tmp_path, markers=False)
        out = bs.build_staout_1(comout, RUN, 12, nowcast_hours=24)
        assert np.loadtxt(str(out))[3, 0] == 86700.0

    def test_without_markers_or_pdy_nothing_is_written(self, tmp_path):
        comout = _cycle_dir(tmp_path, markers=False)
        odd = comout.rename(tmp_path / "unnamed")
        assert bs.build_staout_1(odd, RUN, 12) is None

    def test_nowcast_longer_than_default_follows_the_markers(self, tmp_path):
        comout = _cycle_dir(tmp_path)
        (comout / "time_hotstart.t12z").write_text("2026092612\n")
        out = bs.build_staout_1(comout, RUN, 12, nowcast_hours=24)
        assert np.loadtxt(str(out))[3, 0] == 172800.0 + 300.0

    def test_rebuild_overwrites_without_leaving_temp_files(self, tmp_path):
        comout = _cycle_dir(tmp_path)
        bs.build_staout_1(comout, RUN, 12)
        bs.build_staout_1(comout, RUN, 12)
        assert not list(comout.glob("*.tmp"))

    def test_cli_backfills_and_reports_skip(self, tmp_path):
        comout = _cycle_dir(tmp_path)
        assert bs.main(["--comout", str(comout), "--run", RUN, "--cyc", "12", "--nowcast-hours", "24"]) == 0
        assert (comout / "staout_1").is_file()
        empty = tmp_path / "empty.20260929"
        empty.mkdir()
        assert bs.main(["--comout", str(empty), "--run", RUN, "--cyc", "12"]) == 1


def _ak_desc() -> OFSDescriptor:
    return OFSDescriptor(
        name="stofs_3d_ak_ufs", framework="stofs_ufs",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        yaml_path=Path("parm/systems/stofs_3d_ak_ufs.yaml"),
    )


class TestPrepExportsOpsDirs:
    @pytest.fixture
    def cycle_env(self, tmp_path, monkeypatch):
        """PDY 20260928 prep with the previous cycle's COMOUT present."""
        root = tmp_path / "com"
        prev = root / (RUN + ".20260927")
        prev.mkdir(parents=True)
        monkeypatch.setenv("PDY", "20260928")
        monkeypatch.setenv("RUN", RUN)
        monkeypatch.setenv("COMOUT", str(root / (RUN + ".20260928")))
        for var in ("COMOUT_PREV", "COMOUTrerun", "COMINrerun"):
            monkeypatch.setenv(var, "")
        return {"root": root, "prev": prev}

    def _prep(self, desc):
        seen = []

        def fake_run_prep(phase="nowcast", skip_legacy=True):
            import os
            seen.append(tuple(os.environ.get(v, "") for v in ("COMOUT_PREV", "COMOUTrerun", "COMINrerun")))
            return True

        with patch.dict(sys.modules, _install_stub_nco_bridge(fake_run_prep)):
            assert prep_stage.run(desc, object()) == 0
        return seen

    def test_atl_gets_ops_comout_prev_and_comout_rerun_for_both_phases(self, cycle_env):
        want = (str(cycle_env["prev"]), str(cycle_env["root"] / (RUN + ".20260928") / "rerun"), "")
        assert self._prep(_stofs_3d_atl_ufs_desc()) == [want, want]

    def test_comin_rerun_is_never_set_by_the_stage(self, cycle_env):
        assert all(s[2] == "" for s in self._prep(_stofs_3d_atl_ufs_desc()))

    def test_missing_previous_comout_is_still_exported_and_warned(self, cycle_env, caplog):
        cycle_env["prev"].rmdir()
        with caplog.at_level("WARNING"):
            seen = self._prep(_stofs_3d_atl_ufs_desc())
        assert seen[0][0] == str(cycle_env["prev"])
        assert "not found" in caplog.text

    def test_explicit_values_are_kept(self, cycle_env, monkeypatch, tmp_path):
        monkeypatch.setenv("COMOUT_PREV", str(tmp_path / "p"))
        monkeypatch.setenv("COMOUTrerun", str(tmp_path / "r"))
        monkeypatch.setenv("COMINrerun", str(tmp_path / "flat"))
        assert self._prep(_stofs_3d_atl_ufs_desc())[0] == (
            str(tmp_path / "p"), str(tmp_path / "r"), str(tmp_path / "flat"))

    def test_pdy_crossing_a_month_boundary(self, cycle_env, monkeypatch):
        monkeypatch.setenv("PDY", "20260901")
        monkeypatch.setenv("COMOUT", str(cycle_env["root"] / (RUN + ".20260901")))
        assert self._prep(_stofs_3d_atl_ufs_desc())[0][0] == str(cycle_env["root"] / (RUN + ".20260831"))

    def test_missing_pdy_does_not_fail_prep(self, cycle_env, monkeypatch):
        monkeypatch.delenv("PDY")
        assert self._prep(_stofs_3d_atl_ufs_desc()) == [("", "", "")] * 2

    @pytest.mark.parametrize("desc_factory", [_secofs_ufs_desc, _ak_desc])
    def test_other_systems_are_untouched(self, cycle_env, desc_factory, monkeypatch):
        desc = desc_factory()
        monkeypatch.setenv("RUN", desc.name)
        (cycle_env["root"] / (desc.name + ".20260927")).mkdir(parents=True)
        assert self._prep(desc) == [("", "", "")] * 2

    def test_gate_names(self):
        assert bs.is_atl_run("stofs_3d_atl_ufs") and bs.is_atl_run("STOFS_3D_ATL")
        for other in ("secofs_ufs", "stofs_3d_ak_ufs", "stofs_3d_pac_ufs", "stofs_2d_glo", "", None):
            assert not bs.is_atl_run(other)


class TestArchiveHooks:
    def _ctx(self, tmp_path, run, phase, with_param=True):
        comout = _cycle_dir(tmp_path, now=NOW, fc=None, run=run)
        out = tmp_path / "data" / "outputs"
        _write(out / "staout_1", FC)
        if with_param:
            (tmp_path / "data" / "param.nml").write_text("&opt\n start_day = 27\n/\n")
        return SchismRunContext(comout=comout, data=tmp_path / "data", phase=phase, run=run,
                                cycle="t12z", pdy="20260928", cyc="12", len_nowcast="24")

    def test_atl_forecast_archive_writes_the_joined_staout_1_to_comout(self, tmp_path):
        ctx = self._ctx(tmp_path, RUN, "forecast")
        assert archive_run(ctx, "forecast") == 0
        assert np.loadtxt(str(ctx.comout / "staout_1"))[:, 0].tolist() == [
            300.0, 600.0, 900.0, 86700.0, 87000.0]
        assert not (ctx.comout / "rerun").exists()

    def test_atl_nowcast_archive_puts_the_run_param_nml_in_rerun_like_ops(self, tmp_path):
        ctx = self._ctx(tmp_path, RUN, "nowcast")
        assert archive_run(ctx, "nowcast") == 0
        assert (ctx.comout / "rerun" / (RUN + ".t12z.param.nml")).read_text() == "&opt\n start_day = 27\n/\n"
        assert not (ctx.comout / "staout_1").exists()

    def test_atl_nowcast_archive_without_param_nml_still_succeeds(self, tmp_path, caplog):
        ctx = self._ctx(tmp_path, RUN, "nowcast", with_param=False)
        with caplog.at_level("WARNING"):
            assert archive_run(ctx, "nowcast") == 0
        assert not (ctx.comout / "rerun").exists()
        assert "param.nml" in caplog.text

    @pytest.mark.parametrize("run", ["secofs_ufs", "stofs_3d_ak_ufs"])
    @pytest.mark.parametrize("phase", ["nowcast", "forecast"])
    def test_other_systems_archive_is_unchanged(self, tmp_path, run, phase):
        ctx = self._ctx(tmp_path, run, phase)
        assert archive_run(ctx, phase) == 0
        assert not (ctx.comout / "rerun").exists() and not (ctx.comout / "staout_1").exists()
        sub = "restart_outputs" if phase == "nowcast" else "forecast_outputs"
        assert (ctx.comout / ("%s.t12z.%s" % (run, sub)) / "staout_1").is_file()

    def test_a_failing_build_never_fails_the_archive(self, tmp_path):
        ctx = self._ctx(tmp_path, RUN, "forecast")
        with patch.object(bs, "build_staout_1", side_effect=RuntimeError("boom")):
            assert archive_run(ctx, "forecast") == 0
        assert (ctx.comout / ("%s.t12z.forecast_outputs" % RUN) / "staout_1").is_file()
