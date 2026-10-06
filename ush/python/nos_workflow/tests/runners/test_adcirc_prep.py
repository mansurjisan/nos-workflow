"""STOFS-2D-GLO prep path: yaml exports, mesh staging, adcprep cache, hotstart, prep stage. MJ (10/05/26)"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.machine import MachineProfile, jobs, render_directives  # noqa: E402
from nos_workflow.machine.render import JobSpec  # noqa: E402
from nos_workflow.runners.adcirc import decomp, hotstart as hs, prep  # noqa: E402
from nos_workflow.runners.adcirc.settings import (  # noqa: E402
    AdcircConfigError, AdcircSettings, CycleContext)
from nos_workflow.utils import yaml_to_env  # noqa: E402

YAML = REPO / "parm" / "systems" / "stofs_2d_glo.yaml"
NC = 4
CYCLE = datetime(2026, 10, 4, 12)


def _env(tmp_path, **extra):
    fix = tmp_path / "fix"
    fix.mkdir(exist_ok=True)
    (fix / "stofs_2d_glo_grid").write_text("grid\n")
    (fix / "stofs_2d_glo_attr").write_text("attr\n")
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for n in ("adcprep", "padcirc"):
        (bindir / n).write_text("#!/bin/sh\n")
        (bindir / n).chmod(0o755)
    env = {
        "PDY": "20261004", "cyc": "12", "RUN": "stofs_2d_glo",
        "COMOUT": str(tmp_path / "com" / "stofs_2d_glo.20261004"),
        "COMOUTroot": str(tmp_path / "com"), "COMGES": str(tmp_path / "com" / "stofs_2d_glo"),
        "FIXofs": str(fix), "ADCIRC_EXEC_DIR": str(bindir), "NCPU": str(NC),
        "COMINgfs": str(tmp_path / "gfs"),
    }
    env.update(extra)
    return env


def _ctx(tmp_path, **extra):
    env = _env(tmp_path, **extra)
    return CycleContext.from_env(AdcircSettings.from_yaml(YAML, env), env), env


class FakeAdcprep:
    def __init__(self, ncpu=NC):
        self.calls, self.ncpu = [], ncpu

    def __call__(self, cmd, cwd):
        self.calls.append(list(cmd[1:]))
        flag = cmd[1]
        if flag == "--partmesh":
            (cwd / "partmesh.txt").write_text("part\n")
        elif flag == "--prepall":
            for i in range(self.ncpu):
                pe = cwd / f"PE{i:04d}"
                pe.mkdir(exist_ok=True)
                for n in ("fort.14", "fort.18", "fort.13", "fort.15"):
                    (pe / n).write_text(n)
        elif flag == "--prep15":
            assert len(list(cwd.glob("PE[0-9]*"))) == self.ncpu
            for pe in cwd.glob("PE[0-9]*"):
                (pe / "fort.15").write_text("new")
        return 0


def fake_tides(constituents, start, run_days, nodal_reference="midrun"):
    from nos_utils.forcing.adcirc_tides import AdcircConstituent

    return [AdcircConstituent(name=c, frequency=1e-4, etrf=0.69, tpk=0.1, nodal_factor=1.0,
                              equilibrium_arg_deg=0.0) for c in constituents]


def fake_acquire(ctx, phase, start, end, run_dir, names=("fort.221.nc", "fort.222.nc", "fort.225.nc")):
    for n in names + ("fort.22",):
        (run_dir / n).write_text(phase)
    return SimpleNamespace(files={n: run_dir / n for n in names})


def fake_acquire_no_ice(ctx, phase, start, end, run_dir):
    return fake_acquire(ctx, phase, start, end, run_dir, names=("fort.221.nc", "fort.222.nc"))


@pytest.fixture
def mesh(monkeypatch):
    from nos_workflow.runners.adcirc import mesh as mesh_mod

    info = mesh_mod.MeshInfo(5, 3, -10.0, 5.0, 0, 0)
    monkeypatch.setattr(prep, "read_mesh_info", lambda *a, **k: info)
    monkeypatch.setattr(prep, "compute_tides", lambda ctx, c, e: {
        t.name.upper(): t for t in fake_tides(ctx.settings.tide_constituents, c, 1)})


# ---- yaml and resolver ------------------------------------------------------

def test_yaml_exports_through_resolver(monkeypatch):
    monkeypatch.setenv("PDY", "20261004")
    monkeypatch.setenv("cyc", "12")
    monkeypatch.setenv("NOS_MACHINE", "wcoss2")
    out = json.loads(yaml_to_env.export_env(YAML, framework="adcirc", output_format="json"))
    assert out["OFS"] == "stofs_2d_glo" and out["RUN"] == "stofs_2d_glo"
    assert out["NCPU"] == 4064 and out["NUM_WRITERS"] == 0
    assert out["NPROCS"] == 4064 and out["PPN"] == "128" and out["NNODES"] == "32"
    assert out["time_hotstart"] == "2026100406"
    assert out["OCEAN_MODEL"] == "ADCIRC"


def test_resolver_hercules_uses_profile_packing(monkeypatch):
    monkeypatch.setenv("NOS_MACHINE", "hercules")
    out = json.loads(yaml_to_env.export_env(YAML, framework="adcirc", output_format="json"))
    assert out["PPN"] == "80" and out["NNODES"] == "51"


def test_june_fixes_in_yaml():
    s = AdcircSettings.from_yaml(YAML, {})
    assert s.physics["coordinate_system"] == 22
    assert s.physics["coordinate_rotation"] == [114.16991, 0.77432]
    assert s.ncpu_compute == 4064
    data = yaml_to_env.load_yaml_with_inheritance(YAML, REPO / "parm")
    assert data["resources"]["nprocs"] == s.ncpu_compute + s.ncpu_writer


def test_env_overrides_settings():
    s = AdcircSettings.from_yaml(YAML, {"NCPU": "256", "ATMOSPHERIC_FORCING": "false",
                                        "NUM_WRITERS": "32"})
    assert (s.ncpu_compute, s.ncpu_writer) == (256, 32)
    assert s.atmospheric_forcing is False


def test_operator_overrides_survive_the_resolver(monkeypatch):
    monkeypatch.setenv("COLDSTART_SPINUP_DAYS", "3")
    monkeypatch.setenv("NOWCAST_HOURS", "24")
    out = json.loads(yaml_to_env.export_env(YAML, framework="adcirc", output_format="json"))
    assert out["COLDSTART_SPINUP_DAYS"] == "3"
    s = AdcircSettings.from_yaml(YAML, {"COLDSTART_SPINUP_DAYS": "3", "NOWCAST_HOURS": "24"})
    assert s.coldstart_spinup_days == 3.0 and s.nowcast_interval_hours == 24.0


def test_once_a_day_finds_previous_12z(tmp_path):
    env = _env(tmp_path, NOWCAST_HOURS="24")
    ctx = CycleContext.from_env(AdcircSettings.from_yaml(YAML, env), env)
    assert ctx.prev_nowcast_dir == ctx.cycle_dir(CYCLE - timedelta(days=1), "nowcast")
    assert ctx.nowcast_start == CYCLE - timedelta(days=1)


def test_yaml_met_variables_are_the_10m_strings():
    from nos_utils.forcing import adcirc_met
    s = AdcircSettings.from_yaml(YAML, {})
    assert s.met_variables == adcirc_met.DEFAULT_VARIABLES
    lines = ["1:0:d=2026100512:UGRD:10 m above ground:anl:", "2:1:d=2026100512:UGRD:850 mb:anl:"]
    assert len(adcirc_met.match_inventory(lines, s.met_variables)) == 1


def test_cards_node_math_against_machine_layer():
    sp = JobSpec(name="stofs_2d_glo_nc_00", walltime="03:00:00", total_ranks=jobs.nprocs_for("stofs_2d_glo"),
                 threads_per_rank=1, ranks_per_node=jobs.ranks_per_node_for("stofs_2d_glo"))
    assert sp.total_ranks == 4064 and sp.ranks_per_node == {"wcoss2": 128}
    w = MachineProfile.load("wcoss2", validate=False)
    h = MachineProfile.load("hercules", validate=False)
    assert w.nodes(4064, w.ranks_per_node_for(sp.ranks_per_node)) == 32
    assert h.nodes(4064, h.ranks_per_node_for(sp.ranks_per_node)) == 51
    wl = render_directives(sp, w)
    assert any("select=32:ncpus=128:mpiprocs=128:ompthreads=1" in l for l in wl)
    hl = render_directives(sp, MachineProfile.load("hercules", env={"NOS_ACCOUNT": "a"}))
    assert "#SBATCH --nodes=51" in hl and "#SBATCH --ntasks-per-node=80" in hl


def test_other_systems_render_unchanged():
    sp = jobs.build_job_spec("stofs_3d_atl_ufs_standalone", "nowcast")
    assert sp.ranks_per_node == {}


# ---- mesh staging -----------------------------------------------------------

def test_mesh_linked_as_fort14_fort13(tmp_path):
    ctx, _ = _ctx(tmp_path)
    rd = tmp_path / "rd"
    rd.mkdir()
    prep.link_mesh_files(ctx, rd)
    assert (rd / "fort.14").is_symlink() and (rd / "fort.13").is_symlink()
    assert (rd / "fort.14").read_text() == "grid\n"
    prep.link_mesh_files(ctx, rd)


def test_missing_fix_file_is_named(tmp_path):
    ctx, env = _ctx(tmp_path)
    (Path(env["FIXofs"]) / "stofs_2d_glo_attr").unlink()
    rd = tmp_path / "rd"
    rd.mkdir()
    with pytest.raises(AdcircConfigError, match="stofs_2d_glo_attr"):
        prep.link_mesh_files(ctx, rd)


# ---- adcprep cache ----------------------------------------------------------

def _rd(tmp_path):
    rd = tmp_path / "run"
    rd.mkdir(exist_ok=True)
    (rd / "fort.14").write_text("grid\n")
    (rd / "fort.13").write_text("attr\n")
    return rd


def test_first_run_is_full_then_cached(tmp_path):
    rd, arch = _rd(tmp_path), decomp.archive_path(tmp_path / "ges", "stofs_2d_glo", NC)
    r1 = FakeAdcprep()
    assert decomp.run_adcprep("adcprep", rd, NC, arch, r1) == "full"
    assert r1.calls == [["--partmesh", "--np", "4"], ["--prepall", "--np", "4"]]
    assert arch.name == "stofs_2d_glo_4.tar" and arch.is_file()
    rd2 = tmp_path / "run2"
    rd2.mkdir()
    (rd2 / "fort.14").write_text("grid\n")
    (rd2 / "fort.13").write_text("attr\n")
    r2 = FakeAdcprep()
    assert decomp.run_adcprep("adcprep", rd2, NC, arch, r2) == "prep15"
    assert r2.calls == [["--prep15", "--np", "4"]]
    assert (rd2 / "partmesh.txt").is_file()
    assert (rd2 / "PE0003" / "fort.15").read_text() == "new"


def test_cache_rebuilt_when_mesh_changes(tmp_path):
    rd, arch = _rd(tmp_path), decomp.archive_path(tmp_path / "ges", "r", NC)
    decomp.run_adcprep("adcprep", rd, NC, arch, FakeAdcprep())
    (rd / "fort.14").write_text("a much bigger grid\n")
    r = FakeAdcprep()
    assert decomp.run_adcprep("adcprep", rd, NC, arch, r) == "full"


def test_cache_keyed_on_ncpu(tmp_path):
    assert decomp.archive_path(tmp_path, "r", 4064).name == "r_4064.tar"


def test_adcprep_failure_raises(tmp_path):
    with pytest.raises(RuntimeError, match="partmesh"):
        decomp.run_adcprep("adcprep", _rd(tmp_path), NC, None, lambda c, d: 3)


# ---- hotstart ---------------------------------------------------------------

def _restart(path: Path, seconds: float, fill=False):
    import netCDF4

    ds = netCDF4.Dataset(path, "w")
    ds.createDimension("t", 1)
    v = ds.createVariable("time", "f8", ("t",), fill_value=-99999.0)
    if not fill:
        v[0] = seconds
    ds.close()


def _prev(tmp_path, coldstart, end, **units):
    d = tmp_path / "prev"
    d.mkdir(exist_ok=True)
    hs.write_timing(d, coldstart, coldstart, end, None)
    for unit, secs in units.items():
        _restart(d / f"fort.{unit[1:]}.nc", secs)
    return d


def test_cold_start_when_no_prior_cycle(tmp_path):
    info = hs.resolve_nowcast_hotstart(tmp_path / "none", CYCLE, CYCLE - timedelta(hours=6), 18.0)
    assert info.is_coldstart and info.unit == 0 and info.hotstart_file is None
    assert info.coldstart_time == CYCLE - timedelta(days=18)
    assert info.start_time == info.coldstart_time


def test_hotstart_picks_later_valid_restart(tmp_path):
    cold = CYCLE - timedelta(days=20)
    end = CYCLE - timedelta(hours=6)
    secs = (end - cold).total_seconds()
    d = _prev(tmp_path, cold, end, u67=secs - 10800, u68=secs)
    info = hs.resolve_nowcast_hotstart(d, CYCLE, end, 18.0)
    assert info.unit == 67 and not info.is_coldstart
    assert info.hotstart_file.endswith("fort.68.nc")
    assert info.coldstart_time == cold and info.start_time == end


def test_restart_time_mismatch_raises(tmp_path):
    cold = CYCLE - timedelta(days=20)
    d = _prev(tmp_path, cold, CYCLE, u67=123.0)
    with pytest.raises(RuntimeError, match="does not match"):
        hs.select_restart_file(d)


def test_fill_value_restart_skipped(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    hs.write_timing(d, CYCLE, CYCLE, CYCLE, None)
    _restart(d / "fort.67.nc", 0.0, fill=True)
    assert hs.select_restart_file(d) is None


def test_stage_hotstart_copies_not_links(tmp_path):
    src = tmp_path / "fort.68.nc"
    src.write_text("x")
    rd = tmp_path / "rd"
    rd.mkdir()
    hs.stage_hotstart(hs.HotstartInfo(67, CYCLE, CYCLE, str(src)), rd)
    assert (rd / "fort.67.nc").read_text() == "x" and not (rd / "fort.67.nc").is_symlink()


def test_forecast_restart_requires_nowcast(tmp_path):
    with pytest.raises(RuntimeError, match="forecast cannot run"):
        hs.forecast_restart(tmp_path)


# ---- prep -------------------------------------------------------------------

def test_prep_cold_cycle_nowcast_and_forecast(tmp_path, mesh):
    ctx, _ = _ctx(tmp_path)
    runner = FakeAdcprep()
    assert prep.run_prep(ctx, runner, fake_acquire) == 0
    nc, fc = ctx.run_dir("nowcast"), ctx.run_dir("forecast")
    assert nc.name == "stofs_2d_glo.t12z.nowcast"
    t = hs.read_timing(nc)
    assert datetime.fromisoformat(t["coldstart_time"]) == CYCLE - timedelta(days=18)
    assert t["hotstart_file"] is None
    nc_text = (nc / "fort.15").read_text()
    assert "0                   ! IHOT" in nc_text
    assert "14014" not in nc_text and not (nc / "fort.221.nc").exists()  # tide-only cold spin-up
    ft = hs.read_timing(fc)
    assert ft["coldstart_time"] == t["coldstart_time"]
    assert datetime.fromisoformat(ft["end_time"]) == CYCLE + timedelta(hours=180)
    text = (fc / "fort.15").read_text()
    assert "567                 ! IHOT" in text and "14014" in text
    assert (fc / "fort.222.nc").read_text() == "forecast"
    assert runner.calls[:2] == [["--partmesh", "--np", "4"], ["--prepall", "--np", "4"]]
    assert ["--prep15", "--np", "4"] in runner.calls[2:]
    assert not (fc / "fort.67.nc").exists()


def test_prep_tide_only_skips_met(tmp_path, mesh):
    ctx, _ = _ctx(tmp_path, ATMOSPHERIC_FORCING="false")
    called = []
    prep.run_prep(ctx, FakeAdcprep(), lambda *a: called.append(a))
    assert called == []
    assert "NWS" in (ctx.run_dir("nowcast") / "fort.15").read_text()
    assert "14014" not in (ctx.run_dir("nowcast") / "fort.15").read_text()


def test_cold_nowcast_asks_for_no_gfs_forecast_does(tmp_path, mesh):
    ctx, _ = _ctx(tmp_path)
    phases = []

    def spy(ctx_, phase, *a):
        phases.append(phase)
        return fake_acquire(ctx_, phase, *a)
    prep.run_prep(ctx, FakeAdcprep(), spy)
    assert phases == ["forecast"]


def _nws_of(text):
    return int(next(l for l in text.splitlines() if l.endswith("! NWS")).split("!")[0])


def test_no_ice_file_means_no_ice_flag(tmp_path, mesh):
    ctx, _ = _ctx(tmp_path)
    prep.run_prep(ctx, FakeAdcprep(), fake_acquire_no_ice)
    text = (ctx.run_dir("forecast") / "fort.15").read_text()
    assert _nws_of(text) == 14
    (tmp_path / "ice").mkdir()
    ctx2, _ = _ctx(tmp_path / "ice")
    prep.run_prep(ctx2, FakeAdcprep(), fake_acquire)
    assert _nws_of((ctx2.run_dir("forecast") / "fort.15").read_text()) == 14014


def test_prep_hot_cycle_copies_restart(tmp_path, mesh):
    ctx, _ = _ctx(tmp_path)
    cold = CYCLE - timedelta(days=30)
    prev = ctx.prev_nowcast_dir
    prev.mkdir(parents=True)
    end = CYCLE - timedelta(hours=6)
    hs.write_timing(prev, cold, cold, end, None)
    _restart(prev / "fort.67.nc", (end - cold).total_seconds())
    prep.prep_nowcast(ctx, FakeAdcprep(), fake_acquire)
    nc = ctx.run_dir("nowcast")
    assert "14014" in (nc / "fort.15").read_text()  # warm nowcast uses GFS
    assert (nc / "fort.67.nc").is_file() and not (nc / "fort.67.nc").is_symlink()
    assert "567                 ! IHOT" in (nc / "fort.15").read_text()
    assert json.loads((nc / "timing.json").read_text())["hotstart_file"].endswith("fort.67.nc")


def test_prep_forecast_needs_nowcast(tmp_path, mesh):
    ctx, _ = _ctx(tmp_path)
    with pytest.raises(RuntimeError, match="prep_nowcast"):
        prep.prep_forecast(ctx, FakeAdcprep(), fake_acquire)


def test_prev_nowcast_dir_crosses_midnight(tmp_path):
    env = _env(tmp_path, cyc="00")
    ctx = CycleContext.from_env(AdcircSettings.from_yaml(YAML, env), env)
    assert ctx.prev_nowcast_dir.parent.name == "stofs_2d_glo.20261003"
    assert ctx.prev_nowcast_dir.name == "stofs_2d_glo.t18z.nowcast"


def test_executable_resolution_and_error(tmp_path):
    ctx, env = _ctx(tmp_path)
    assert ctx.settings.executable("padcirc").endswith("bin/padcirc")
    s = AdcircSettings.from_yaml(YAML, {"ADCIRC_EXEC_DIR": str(tmp_path / "nope")})
    with pytest.raises(AdcircConfigError, match="adcprep"):
        s.executable("adcprep")
