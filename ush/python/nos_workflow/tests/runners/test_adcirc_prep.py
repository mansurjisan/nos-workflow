"""STOFS-2D-GLO prep helpers: yaml exports, mesh staging, adcprep cache, settings. MJ (10/05/26)"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.machine import MachineProfile, jobs, render_directives  # noqa: E402
from nos_workflow.machine.render import JobSpec  # noqa: E402
from nos_workflow.runners.adcirc import decomp, prep  # noqa: E402
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


def test_ranks_in_yaml():
    s = AdcircSettings.from_yaml(YAML, {})
    assert s.ncpu_compute == 4064
    data = yaml_to_env.load_yaml_with_inheritance(YAML, REPO / "parm")
    assert data["resources"]["nprocs"] == s.ncpu_compute + s.ncpu_writer


def test_env_overrides_settings():
    s = AdcircSettings.from_yaml(YAML, {"NCPU": "256", "ATMOSPHERIC_FORCING": "false",
                                        "NUM_WRITERS": "32"})
    assert (s.ncpu_compute, s.ncpu_writer) == (256, 32)
    assert s.atmospheric_forcing is False


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


# ---- restart file helper used by the ops tests ------------------------------

def _restart(path: Path, seconds: float, fill=False):
    import netCDF4

    ds = netCDF4.Dataset(path, "w")
    ds.createDimension("t", 1)
    v = ds.createVariable("time", "f8", ("t",), fill_value=-99999.0)
    if not fill:
        v[0] = seconds
    ds.close()


def test_executable_resolution_and_error(tmp_path):
    ctx, env = _ctx(tmp_path)
    assert ctx.settings.executable("padcirc").endswith("bin/padcirc")
    s = AdcircSettings.from_yaml(YAML, {"ADCIRC_EXEC_DIR": str(tmp_path / "nope")})
    with pytest.raises(AdcircConfigError, match="adcprep"):
        s.executable("adcprep")
