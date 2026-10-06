"""STOFS-3D-ATL bad-day checks on the nos-workflow side: mirror.out verdict, post stop,
restart search anchored on COMOUT. SECOFS and the other systems must not change."""
import os
from pathlib import Path

import pytest

from nos_workflow.errors import StageFailedError
from nos_workflow.runners.schism_ufs import archive, execute
from nos_workflow.runners.schism_ufs.mirror_status import STATUS_NAME, check_mirror_out
from nos_workflow.stages import post, prep

from .runners.test_standalone_mode import _make_ctx

STANDALONE_OK = "TIME STEP=          576;  TIME=         86400.0\n\nRun completed successfully at 2026\n"
COUPLED_END = " hot start written\nTIME STEP=          576;  TIME=         86400.000000\n"
PARAM = "&CORE\n  rnday = 1.0\n  dt = 150.\n/\n"


def _mirror(tmp_path, text):
    p = tmp_path / "mirror.out"
    p.write_text(text)
    return p


class TestMirrorCheck:
    def test_standalone_completion_line(self, tmp_path):
        assert check_mirror_out(_mirror(tmp_path, STANDALONE_OK), None, coupled=False)[0]

    def test_standalone_missing_line_is_incomplete(self, tmp_path):
        ok, why = check_mirror_out(_mirror(tmp_path, COUPLED_END), None, coupled=False)
        assert not ok and "Run completed successfully" in why

    def test_missing_or_empty_file(self, tmp_path):
        assert not check_mirror_out(tmp_path / "nope", None, coupled=False)[0]
        assert not check_mirror_out(_mirror(tmp_path, ""), None, coupled=True)[0]

    def test_coupled_full_step_count(self, tmp_path):
        nml = tmp_path / "param.nml"
        nml.write_text(PARAM)
        assert check_mirror_out(_mirror(tmp_path, COUPLED_END), nml, coupled=True)[0]

    def test_coupled_truncated_run(self, tmp_path):
        nml = tmp_path / "param.nml"
        nml.write_text(PARAM)
        m = _mirror(tmp_path, "TIME STEP=          300;  TIME= 45000.0\n")
        ok, why = check_mirror_out(m, nml, coupled=True)
        assert not ok and "expected 576" in why

    def test_coupled_without_param_nml_is_not_trusted(self, tmp_path):
        assert not check_mirror_out(_mirror(tmp_path, COUPLED_END), tmp_path / "x", coupled=True)[0]

    def test_coupled_fortran_style_rnday(self, tmp_path):
        nml = tmp_path / "param.nml"
        nml.write_text("  rnday = 5.5d0\n  dt = 150.\n")
        m = _mirror(tmp_path, "TIME STEP=         3168;  TIME= 1.0\n")
        assert check_mirror_out(m, nml, coupled=True)[0]


class TestArchiveVerdict:
    def _run(self, tmp_path, monkeypatch, text, prefixnos="stofs_3d_atl_ufs", coupled=False):
        monkeypatch.setenv("USE_DATM", "true" if coupled else "false")
        ctx = _make_ctx(tmp_path, prefixnos=prefixnos)
        (ctx.data / "outputs").mkdir()
        (ctx.data / "outputs" / "mirror.out").write_text(text)
        (ctx.data / "param.nml").write_text(PARAM)
        archive.run_python(ctx, "nowcast")
        return ctx.comout / f"{ctx.run}.{ctx.cycle}.restart_outputs" / STATUS_NAME

    def test_ok_verdict(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, STANDALONE_OK).read_text().startswith("OK")

    def test_incomplete_verdict(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, COUPLED_END).read_text().startswith("INCOMPLETE")

    def test_coupled_verdict_uses_step_count(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, COUPLED_END, coupled=True).read_text().startswith("OK")

    def test_secofs_writes_no_verdict(self, tmp_path, monkeypatch):
        assert not self._run(tmp_path, monkeypatch, STANDALONE_OK, prefixnos="secofs_ufs").exists()


class _Desc:
    name = "stofs_3d_atl_ufs"


def _archived(comout, run, text, status):
    for sub in ("restart_outputs", "forecast_outputs"):
        d = comout / f"{run}.t12z.{sub}"
        d.mkdir(parents=True)
        if text is not None:
            (d / "mirror.out").write_text(text)
        if status is not None:
            (d / STATUS_NAME).write_text(status)


class TestPostStops:
    def test_passes_when_both_phases_ok(self, tmp_path):
        _archived(tmp_path, "stofs_3d_atl_ufs", "x", "OK done\n")
        post._require_complete_model_runs(_Desc, tmp_path, "stofs_3d_atl_ufs", "t12z")

    def test_stops_on_incomplete(self, tmp_path):
        _archived(tmp_path, "stofs_3d_atl_ufs", "x", "INCOMPLETE no line\n")
        with pytest.raises(StageFailedError, match="incomplete"):
            post._require_complete_model_runs(_Desc, tmp_path, "stofs_3d_atl_ufs", "t12z")

    def test_stops_on_missing_mirror(self, tmp_path):
        _archived(tmp_path, "stofs_3d_atl_ufs", None, "OK\n")
        with pytest.raises(StageFailedError, match="mirror.out"):
            post._require_complete_model_runs(_Desc, tmp_path, "stofs_3d_atl_ufs", "t12z")

    def test_old_archive_without_verdict_is_judged_from_mirror_out(self, tmp_path, monkeypatch):
        # cycles archived before mirror.status existed MJ (10/05/26)
        monkeypatch.setenv("USE_DATM", "false")
        _archived(tmp_path, "stofs_3d_atl_ufs", STANDALONE_OK, None)
        post._require_complete_model_runs(_Desc, tmp_path, "stofs_3d_atl_ufs", "t12z")

    def test_old_archive_with_incomplete_mirror_out_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("USE_DATM", "false")
        _archived(tmp_path, "stofs_3d_atl_ufs", COUPLED_END, None)
        with pytest.raises(StageFailedError, match="Run completed successfully"):
            post._require_complete_model_runs(_Desc, tmp_path, "stofs_3d_atl_ufs", "t12z")

    def _coupled_old(self, tmp_path, monkeypatch, forecast_last):
        monkeypatch.setenv("USE_DATM", "true")
        monkeypatch.setenv("LEN_FORECAST", "96")
        _archived(tmp_path, "stofs_3d_atl_ufs", COUPLED_END, None)
        (tmp_path / "stofs_3d_atl_ufs.t12z.forecast_outputs" / "mirror.out").write_text(
            f"TIME STEP={forecast_last:>12};  TIME= 1.0\n")
        (tmp_path / "rerun").mkdir()
        (tmp_path / "rerun" / "stofs_3d_atl_ufs.t12z.param.nml").write_text(PARAM)  # no data/param.nml MJ (10/05/26)

    def test_old_coupled_archive_uses_step_count(self, tmp_path, monkeypatch):
        self._coupled_old(tmp_path, monkeypatch, 2304)  # 4 days at dt 150 MJ (10/05/26)
        post._require_complete_model_runs(_Desc, tmp_path, "stofs_3d_atl_ufs", "t12z")

    def test_old_coupled_forecast_stopping_at_nowcast_length_fails(self, tmp_path, monkeypatch):
        self._coupled_old(tmp_path, monkeypatch, 576)
        with pytest.raises(StageFailedError, match="expected 2304"):
            post._require_complete_model_runs(_Desc, tmp_path, "stofs_3d_atl_ufs", "t12z")

    def test_other_systems_untouched(self, tmp_path):
        post._require_complete_model_runs(_Desc, tmp_path, "secofs_ufs", "t12z")


class TestModelStageLogsOnly:
    def test_missing_completion_is_warning_not_failure(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("USE_DATM", "false")
        ctx = _make_ctx(tmp_path)
        (ctx.data / "outputs").mkdir()
        (ctx.data / "outputs" / "mirror.out").write_text(COUPLED_END)
        (ctx.data / "param.nml").write_text(PARAM)
        for n in ("_validate_configs", "_validate_wave_ufs_configure", "_validate_atl_inputs",
                  "_maybe_regenerate_mesh", "_run_mpi_shell", "_archive_restart",
                  "_archive_wave_restarts"):
            monkeypatch.setattr(execute, n, lambda *a, **k: 0)
        monkeypatch.setattr(execute.combine_hotstart, "combine_hotstart_files", lambda *a: 0)
        monkeypatch.setattr(execute.normalize_fields, "normalize_field_outputs", lambda *a: 0)
        with caplog.at_level("WARNING"):
            assert execute.run_python(ctx, "nowcast") == 0
        assert "mirror.out check" in caplog.text

    def test_nonzero_mpi_rc_still_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("USE_DATM", "false")
        ctx = _make_ctx(tmp_path)
        for n in ("_validate_configs", "_validate_wave_ufs_configure", "_validate_atl_inputs",
                  "_maybe_regenerate_mesh"):
            monkeypatch.setattr(execute, n, lambda *a, **k: 0)
        monkeypatch.setattr(execute, "_run_mpi_shell", lambda *a: 7)
        assert execute.run_python(ctx, "nowcast") == 7


class TestRestartSearchFollowsComout:
    def _env(self, monkeypatch, tmp_path, **extra):
        for k in ("COMIN", "RESTART_DIR", "COMOUT"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("COMROOT", str(tmp_path / "com"))
        monkeypatch.setenv("NET", "nos")
        monkeypatch.setenv("RUN", "stofs_3d_atl_ufs")
        monkeypatch.setenv("PDY", "20261001")
        for k, v in extra.items():
            monkeypatch.setenv(k, v)

    def test_comout_override_moves_comin(self, tmp_path, monkeypatch):
        alt = tmp_path / "alt" / "stofs_3d_atl_ufs.20261001"
        shared = tmp_path / "com" / "nos" / "stofs_3d_atl_ufs.20261001"
        self._env(monkeypatch, tmp_path, COMOUT=str(alt), COMIN=str(shared))
        prep._export_prev_cycle_dirs(_Desc)
        assert os.environ["COMIN"] == str(alt)

    def test_unset_comin_follows_comout(self, tmp_path, monkeypatch):
        alt = tmp_path / "alt" / "stofs_3d_atl_ufs.20261001"
        self._env(monkeypatch, tmp_path, COMOUT=str(alt))
        prep._export_prev_cycle_dirs(_Desc)
        assert os.environ["COMIN"] == str(alt)

    def test_explicit_comin_is_kept(self, tmp_path, monkeypatch):
        alt = tmp_path / "alt" / "stofs_3d_atl_ufs.20261001"
        other = tmp_path / "seed" / "stofs_3d_atl_ufs.20261001"
        self._env(monkeypatch, tmp_path, COMOUT=str(alt), COMIN=str(other))
        prep._export_prev_cycle_dirs(_Desc)
        assert os.environ["COMIN"] == str(other)

    def test_restart_dir_wins(self, tmp_path, monkeypatch):
        alt = tmp_path / "alt" / "stofs_3d_atl_ufs.20261001"
        self._env(monkeypatch, tmp_path, COMOUT=str(alt), RESTART_DIR=str(tmp_path / "r"))
        prep._export_prev_cycle_dirs(_Desc)
        assert "COMIN" not in os.environ

    def test_default_layout_unchanged(self, tmp_path, monkeypatch):
        d = tmp_path / "com" / "nos" / "stofs_3d_atl_ufs.20261001"
        self._env(monkeypatch, tmp_path, COMOUT=str(d), COMIN=str(d))
        prep._export_prev_cycle_dirs(_Desc)
        assert os.environ["COMIN"] == str(d)

    def test_secofs_untouched(self, tmp_path, monkeypatch):
        class D:
            name = "secofs_ufs"
        self._env(monkeypatch, tmp_path, COMOUT=str(tmp_path / "alt" / "x"), RUN="secofs_ufs")
        prep._export_prev_cycle_dirs(D)
        assert "COMIN" not in os.environ


class TestPbsCardsSeparateComroot:
    PBS = Path(__file__).resolve().parents[4] / "pbs"

    def _roots(self, variant):
        out = {}
        for card in sorted((self.PBS / variant).glob("jnos_*_00.pbs")):
            line = [ln for ln in card.read_text().splitlines() if ln.startswith("export COMROOT=")]
            assert len(line) == 1, card
            out[card.name] = line[0]
        return out

    def test_standalone_has_own_default_and_override(self):
        roots = self._roots("stofs_3d_atl_ufs_standalone")
        assert len(roots) == 4
        for line in roots.values():
            assert line == "export COMROOT=${COMROOT_SA:-/lfs/h1/nos/ptmp/$LOGNAME/com_atl_sa}"

    def test_coupled_default_unchanged_with_override(self):
        roots = self._roots("stofs_3d_atl_ufs")
        assert len(roots) == 4
        for line in roots.values():
            assert line == "export COMROOT=${COMROOT_UFS:-/lfs/h1/nos/ptmp/$LOGNAME/com}"

    def test_launchers_forward_the_overrides(self):
        sa = (self.PBS / "stofs_3d_atl_ufs_standalone" / "launch_stofs_standalone.sh").read_text()
        ufs = (self.PBS / "stofs_3d_atl_ufs" / "launch_stofs_3d_atl_ufs.sh").read_text()
        assert "COMROOT_SA; do" in sa and "COMROOT_UFS; do" in ufs


def test_atl_prep_cards_pin_coldstart_no_after_run_ver():
    # The shared run.ver exports COLDSTART=YES; the ATL prep gate refuses it, so every ATL
    # prep card must reset it after sourcing run.ver. MJ (10/05/26)
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    cards = sorted(root.glob("pbs/stofs_3d_atl_ufs*/jnos_prep_00.pbs")) + sorted(root.glob("slurm/stofs_3d_atl_ufs*/jnos_prep_00.sh"))
    assert len(cards) == 4
    for card in cards:
        lines = card.read_text().splitlines()
        src = next(i for i, l in enumerate(lines) if l.startswith(". ${PACKAGEROOT}/nos-workflow/versions/run"))
        pin = next(i for i, l in enumerate(lines) if l.strip() == "export COLDSTART=NO")
        assert pin > src, card


class TestFieldsWorkerGate:
    class _R:
        def __init__(self, status):
            self.name, self.status, self.detail = "fields_nc", status, "worker failed"

    def test_atl_failed_fields_fails_post(self):
        with pytest.raises(StageFailedError):
            post._require_fields_worker(_Desc, "stofs_3d_atl_ufs", [self._R("failed")])

    def test_atl_ok_fields_passes(self):
        post._require_fields_worker(_Desc, "stofs_3d_atl_ufs", [self._R("ok")])

    def test_secofs_failed_fields_only_warns(self):
        post._require_fields_worker(_Desc, "secofs_ufs", [self._R("failed")])
