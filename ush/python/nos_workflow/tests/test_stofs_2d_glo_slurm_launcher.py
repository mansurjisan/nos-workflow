"""STOFS-2D-Global Hercules Slurm chain launcher and status script, against stub sbatch/sacct. Offline."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SLURM = REPO / "slurm" / "stofs_2d_glo"
LAUNCH = SLURM / "launch_stofs_2d_glo.sh"
STATUS = SLURM / "status_stofs_2d_glo.sh"
FIX_FILES = [f"stofs_2d_glo_{n}" for n in ("grid", "attr", "body", "tide.15", "surf.15")]
CARDS = [SLURM / f"jnos_{x}_00.sh" for x in ("prep", "nowcast", "forecast")]
STAGE_TOOL = REPO / "tools" / "hercules_2d_glo_stage_forcing.sh"
GES_FILES = ["stofs_2d_glo_nod_equi", "stofs_2d_glo_4064.tar", "stofs_2d_glo_4064.tar.json"]
# Variables the launcher drops from the caller's shell, so sbatch cannot export another package's layout. MJ (10/13/26)
DIRTY = ("HOMEstofs EXECnos FIXnos FIXofs NOS_WORKFLOW_DIR NOS_UTILS_DIR PYTHONPATH OFS_CONFIG COMROOT DATAROOT COMIN COMINgfs "
         "COMOUT COMOUTroot COMGES DATA ADCIRC_STREAM ADCIRC_SEGMENT COLDSTART NCPU NUM_WRITERS TOT_NCPU NOWCAST_HOURS "
         "COLDSTART_SPINUP_DAYS ATMOSPHERIC_FORCING RPTDIR").split()
SBATCH = ('#!/bin/bash\nn=$(cat "$QLOG.n" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$QLOG.n"\n'
          '[ "$n" = 1 ] && { env > "$QLOG.env"; pwd > "$QLOG.pwd"; }\necho "$n $*" >> "$QLOG"; echo "$n;hercules"\n')


def _stub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture()
def cycle(tmp_path):
    """A clone named nos-workflow with the real cards, a stub sbatch, staged ops forcing, fix files, the cold-start products in
    COMGES, the previous cycle's chain files and ADCIRC executables. MJ (10/13/26)"""
    clone = tmp_path / "pk" / "nos-workflow"
    shutil.copytree(SLURM, clone / "slurm" / "stofs_2d_glo")
    _stub(clone / "exec" / "stofs_2d_glo_tide_fac", "#!/bin/bash\n")
    for f in FIX_FILES:
        _stub(clone / "fix" / "stofs_2d_glo" / f, "x")
    for exe in ("padcirc", "adcprep"):
        _stub(tmp_path / "adcirc" / exe, "#!/bin/bash\n")
    com = tmp_path / "com"
    rr = com / "nos" / "stofs_2d_glo.20261005" / "12" / "rerun"
    rr.mkdir(parents=True)
    for seg in ("ncst", "fcst"):
        for n in (221, 222, 225):
            (rr / f"stofs_2d_glo_{seg}.{n}.nc").write_text("x")
    for f in GES_FILES:
        _stub(com / "nos" / "stofs_2d_glo" / f, "x")
    for kind in ("hotstart", "restart"):  # the chain files of 20261005 06z, 6 h before the cycle. MJ (10/13/26)
        _stub(com / "nos" / "stofs_2d_glo.20261005" / f"stofs_2d_glo.t06z.{kind}", "x")
    _stub(tmp_path / "bin" / "sbatch", SBATCH)
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "QLOG": str(tmp_path / "q.log"),
           "NOS_PTMP": str(tmp_path / "ptmp"), "LOGNAME": "tester", "COMROOT_2DGLO": str(com),
           "ADCIRC_EXEC_DIR": str(tmp_path / "adcirc")}
    for k in ("PKG", "COLD", "STAGES", "SERIAL", "KEEPDATA", "SUBMIT_GFS", "PACKAGEROOT", "HOMEnos", "ADCIRC_MODE", *DIRTY) + tuple(
            k for k in os.environ if k.startswith(("W_", "SLURM_"))):
        env.pop(k, None)
    return tmp_path, clone, env


def _run(cycle, args, **extra):
    tmp, clone, env = cycle
    return subprocess.run(["bash", str(clone / "slurm" / "stofs_2d_glo" / "launch_stofs_2d_glo.sh"), *args],
                          env={**env, **extra}, capture_output=True, text=True, cwd=str(tmp))


def _launch(cycle, **extra):
    return _run(cycle, ("20261005", "12"), **extra)


def _jobs(tmp):
    out = {}
    for ln in (tmp / "q.log").read_text().splitlines():
        jid, rest = ln.split(" ", 1)
        a = rest.split()
        exp = next(x for x in a if x.startswith("--export=")).split("=", 1)[1].split(",")
        dep = next((x for x in a if x.startswith("--dependency=")), "")
        flags = [x for x in a[a.index("-t") + 2:-1] if not x.startswith(("--export=", "--dependency="))]
        out[a[a.index("-J") + 1][len("stofs_2d_glo_"):]] = dict(
            jid=jid, v=dict(kv.split("=", 1) for kv in exp[1:]), dep=dep.split(":")[1:] if dep else [],
            wall=a[a.index("-t") + 1], card=Path(a[-1]).name, sbatch=a, flags=flags)
    return out


def _deps(j):
    ids = {v["jid"]: k for k, v in j.items()}
    return {k: sorted(ids[d] for d in v["dep"]) for k, v in j.items()}


def test_scripts_are_valid_executable_bash():
    for f in (LAUNCH, STATUS):
        subprocess.run(["bash", "-n", str(f)], check=True)
        assert os.access(f, os.X_OK)
    text = LAUNCH.read_text()
    assert "MJ (10/13/26)" in text and "--kill-on-invalid-dep=yes" in text and "--parsable" in text and "qsub" not in text


def test_arguments_are_validated(cycle):
    for args in ((), ("20261005",), ("2026100", "12"), ("20261005", "12", "x")):
        assert _run(cycle, args).returncode == 2, args
    r = _run(cycle, ("20261005", "07"))
    assert r.returncode == 2 and "CYC must be" in r.stderr
    r = _launch(cycle, COLD="2")
    assert r.returncode == 2 and "COLD must be" in r.stderr
    assert not (cycle[0] / "q.log").exists()


def test_default_chain_is_a_cold_start_with_hercules_walltimes(cycle):
    tmp = cycle[0]
    r = _launch(cycle)
    assert r.returncode == 0, r.stderr
    j = _jobs(tmp)
    assert _deps(j) == {"cold_adcprep": [], "cold_spinup": ["cold_adcprep"], "tide_ncst": ["cold_spinup"],
                        "tide_fcst": ["tide_ncst"], "surf_ncst": ["cold_spinup"], "surf_fcst": ["surf_ncst"],
                        "post_ncdiff": ["surf_fcst", "tide_fcst"], "post_ncrcat": ["surf_fcst"]}
    assert {k: v["wall"] for k, v in j.items()} == {
        "cold_adcprep": "3:00:00", "cold_spinup": "1:00:00", "tide_ncst": "0:40:00", "tide_fcst": "0:55:00", "surf_ncst": "0:40:00",
        "surf_fcst": "1:05:00", "post_ncdiff": "0:30:00", "post_ncrcat": "0:45:00"}
    assert {k: v["card"] for k, v in j.items()} == {
        "cold_adcprep": "jnos_prep_00.sh", "cold_spinup": "jnos_nowcast_00.sh", "tide_ncst": "jnos_nowcast_00.sh",
        "tide_fcst": "jnos_forecast_00.sh", "surf_ncst": "jnos_nowcast_00.sh", "surf_fcst": "jnos_forecast_00.sh",
        "post_ncdiff": "jnos_prep_00.sh", "post_ncrcat": "jnos_prep_00.sh"}
    assert {k: " ".join(v["flags"]) for k, v in j.items() if v["flags"]} == {
        "cold_adcprep": "-N 1 -n 1 --mem=64G", "surf_ncst": "-N 52", "surf_fcst": "-N 52",
        "post_ncdiff": "-N 1 -n 1 --mem=100G", "post_ncrcat": "-N 1 -n 1 --mem=100G"}
    for k, v in j.items():
        assert (v["v"]["PDY"], v["v"]["CYC"], v["v"]["KEEPDATA"], v["v"]["ADCIRC_MODE"]) == ("20261005", "12", "NO", "ops"), k
    assert j["cold_adcprep"]["v"]["COLDSTART"] == "YES" and j["cold_spinup"]["v"]["ADCIRC_SEGMENT"] == "spinup"
    assert [(k, j[k]["v"]["ADCIRC_STREAM"], j[k]["v"]["ADCIRC_SEGMENT"]) for k in ("tide_ncst", "tide_fcst", "surf_ncst", "surf_fcst")] == [
        ("tide_ncst", "tide", "ncst"), ("tide_fcst", "tide", "fcst"), ("surf_ncst", "surf", "ncst"), ("surf_fcst", "surf", "fcst")]
    assert [j[k]["v"]["ADCIRC_SEGMENT"] for k in ("post_ncdiff", "post_ncrcat")] == ["ncdiff", "ncrcat"]
    assert not {"post_anomaly", "post_bias", "post_grib2", "gfs_ncst", "gfs_fcst"} & set(j)
    assert "afterok" in r.stdout and "status_stofs_2d_glo.sh 20261005 12" in r.stdout
    assert "post_anomaly, post_bias and post_grib2 are not submitted" in r.stdout


def test_job_list_file_and_previous_list_is_kept(cycle):
    tmp = cycle[0]
    assert _launch(cycle).returncode == 0
    jobs = tmp / "ptmp" / "tester" / "slurm_2dglo" / "jobs_2026100512.txt"
    rows = [ln.split() for ln in jobs.read_text().splitlines()]
    assert [r[0] for r in rows] == list(_jobs(tmp)) and [r[1] for r in rows] == [str(i) for i in range(1, 9)]
    assert _launch(cycle, COLD="0").returncode == 0
    kept = list(jobs.parent.glob("jobs_2026100512.txt.*"))
    assert len(kept) == 1 and len(kept[0].read_text().splitlines()) == 8 and len(jobs.read_text().splitlines()) == 6
    assert (tmp / "q.log.pwd").read_text().strip() == str(jobs.parent)


def test_environment_is_sanitised_and_pinned_to_the_own_clone(cycle):
    tmp, clone, _ = cycle
    r = _launch(cycle, HOMEnos="/bad/home", **{k: "/bad" for k in DIRTY}, ADCIRC_MODE="single")
    assert r.returncode == 0, r.stderr
    env = dict(ln.split("=", 1) for ln in (tmp / "q.log.env").read_text().splitlines() if "=" in ln)
    assert [k for k in DIRTY if k in env] == []
    assert env["PACKAGEROOT"] == str(clone.parent) and env["HOMEnos"] == str(clone)
    assert env["COMROOT_2DGLO"] == str(tmp / "com") and env["ADCIRC_EXEC_DIR"] == str(tmp / "adcirc")
    assert env["NOS_PTMP"] == str(tmp / "ptmp") and "ADCIRC_MODE" not in env


def test_cold_variants(cycle):
    tmp = cycle[0]
    assert _launch(cycle, COLD="0").returncode == 0
    j = _jobs(tmp)
    assert set(j) == {"tide_ncst", "tide_fcst", "surf_ncst", "surf_fcst", "post_ncdiff", "post_ncrcat"}
    assert _deps(j)["tide_ncst"] == [] and _deps(j)["surf_ncst"] == []
    (tmp / "q.log").unlink()
    assert _launch(cycle, COLD="spinup").returncode == 0
    j = _jobs(tmp)
    assert "cold_adcprep" not in j and _deps(j)["cold_spinup"] == [] and _deps(j)["tide_ncst"] == ["cold_spinup"]
    assert "COLDSTART" not in j["cold_spinup"]["v"]


def test_serial_keepdata_and_walltime_overrides(cycle):
    tmp = cycle[0]
    assert _launch(cycle, COLD="0", SERIAL="1", KEEPDATA="YES", W_SNC="0:20:00", W_CAT="1:00:00", W_TFC="2:00:00").returncode == 0
    j = _jobs(tmp)
    assert _deps(j)["surf_ncst"] == ["tide_fcst"] and all(v["v"]["KEEPDATA"] == "YES" for v in j.values())
    assert (j["surf_ncst"]["wall"], j["post_ncrcat"]["wall"], j["tide_fcst"]["wall"]) == ("0:20:00", "1:00:00", "2:00:00")
    (tmp / "q.log").unlink()
    assert _launch(cycle, COLD="0", SERIAL="0").returncode == 0
    assert _deps(_jobs(tmp))["surf_ncst"] == []


def test_gfs_jobs_are_optional_and_replace_the_staged_forcing_check(cycle):
    tmp = cycle[0]
    shutil.rmtree(tmp / "com" / "nos")
    r = _launch(cycle)
    assert r.returncode == 1 and r.stderr.count("MISSING") == 6 and not (tmp / "q.log").exists()
    assert _launch(cycle, SUBMIT_GFS="1").returncode == 0
    j = _jobs(tmp)
    assert _deps(j)["gfs_ncst"] == ["cold_spinup"] and _deps(j)["gfs_fcst"] == []
    assert _deps(j)["surf_ncst"] == ["cold_spinup", "gfs_ncst"] and _deps(j)["surf_fcst"] == ["gfs_fcst", "surf_ncst"]
    assert (j["gfs_ncst"]["v"]["ADCIRC_SEGMENT"], j["gfs_fcst"]["v"]["ADCIRC_SEGMENT"]) == ("ncst", "fcst")
    assert (j["gfs_ncst"]["wall"], j["gfs_fcst"]["wall"], j["gfs_fcst"]["card"]) == ("0:10:00", "0:40:00", "jnos_prep_00.sh")


def test_preflight_names_every_missing_piece_and_queues_nothing(cycle):
    tmp, clone, _ = cycle
    (tmp / "adcirc" / "adcprep").unlink()
    (clone / "exec" / "stofs_2d_glo_tide_fac").unlink()
    (clone / "slurm" / "stofs_2d_glo" / "jnos_forecast_00.sh").unlink()
    (tmp / "com" / "nos" / "stofs_2d_glo.20261005" / "12" / "rerun" / "stofs_2d_glo_fcst.225.nc").unlink()
    r = _launch(cycle)
    assert r.returncode == 1 and r.stderr.count("MISSING") == 4
    for want in ("adcprep", "stofs_2d_glo_tide_fac", "jnos_forecast_00.sh", "stofs_2d_glo_fcst.225.nc"):
        assert want in r.stderr
    assert not (tmp / "q.log").exists() and not (tmp / "ptmp").exists()
    env = {k: v for k, v in cycle[2].items() if k != "ADCIRC_EXEC_DIR"}
    r = _launch((tmp, clone, env))
    assert r.returncode == 1 and all(f"pk/adcirc_v56.1.0_exec/{x}" in r.stderr for x in ("padcirc", "adcprep"))


def test_adcirc_exec_dir_defaults_to_the_build_tools_install_dir(cycle):
    tmp, clone, env = cycle
    for exe in ("padcirc", "adcprep"):
        _stub(tmp / "pk" / "adcirc_v56.1.0_exec" / exe, "#!/bin/bash\n")
    env = {k: v for k, v in env.items() if k != "ADCIRC_EXEC_DIR"}
    assert _launch((tmp, clone, env)).returncode == 0
    sbatch_env = dict(ln.split("=", 1) for ln in (tmp / "q.log.env").read_text().splitlines() if "=" in ln)
    assert sbatch_env["ADCIRC_EXEC_DIR"] == str(tmp / "pk" / "adcirc_v56.1.0_exec")


def test_refuses_inside_a_slurm_allocation(cycle):
    r = _launch(cycle, SLURM_JOB_ID="123")
    assert r.returncode == 1 and "SLURM_JOB_ID=123" in r.stderr and "exit the allocation" in r.stderr
    assert not (cycle[0] / "q.log").exists() and not (cycle[0] / "ptmp").exists()


def test_preflight_checks_the_fix_files_of_the_runner(cycle):
    tmp, clone, _ = cycle
    for f in ("stofs_2d_glo_body", "stofs_2d_glo_tide.15"):
        (clone / "fix" / "stofs_2d_glo" / f).unlink()
    (clone / "fix" / "stofs_2d_glo" / "stofs_2d_glo_attr").write_text("")  # an empty file is as good as none. MJ (10/13/26)
    r = _launch(cycle)
    assert r.returncode == 1 and r.stderr.count("MISSING") == 3 and not (tmp / "q.log").exists()
    for want in ("fix/stofs_2d_glo/stofs_2d_glo_body", "fix/stofs_2d_glo/stofs_2d_glo_tide.15", "fix/stofs_2d_glo/stofs_2d_glo_attr"):
        assert want in r.stderr


def test_cold_start_needs_none_of_the_later_cycle_files(cycle):
    tmp, _, _ = cycle
    shutil.rmtree(tmp / "com" / "nos" / "stofs_2d_glo")
    for kind in ("hotstart", "restart"):
        (tmp / "com" / "nos" / "stofs_2d_glo.20261005" / f"stofs_2d_glo.t06z.{kind}").unlink()
    assert _launch(cycle).returncode == 0 and len(_jobs(tmp)) == 8


def test_spinup_preflight_lists_the_missing_cold_start_products(cycle):
    tmp = cycle[0]
    ges = tmp / "com" / "nos" / "stofs_2d_glo"
    (ges / "stofs_2d_glo_nod_equi").unlink()
    (ges / "stofs_2d_glo_4064.tar.json").unlink()
    r = _launch(cycle, COLD="spinup")
    assert r.returncode == 1 and r.stderr.count("MISSING") == 2 and not (tmp / "q.log").exists()
    assert "stofs_2d_glo_nod_equi" in r.stderr and "stofs_2d_glo_4064.tar.json" in r.stderr
    # the previous cycle's chain files are not needed for a spin-up, but nod_equi and the tar are. MJ (10/13/26)
    for kind in ("hotstart", "restart"):
        (tmp / "com" / "nos" / "stofs_2d_glo.20261005" / f"stofs_2d_glo.t06z.{kind}").unlink()
    _stub(ges / "stofs_2d_glo_nod_equi", "x")
    _stub(ges / "stofs_2d_glo_4064.tar.json", "x")
    assert _launch(cycle, COLD="spinup").returncode == 0 and "cold_spinup" in _jobs(tmp)


def test_cold0_preflight_needs_the_cold_start_products_and_the_previous_chain_files(cycle):
    tmp = cycle[0]
    ges, day = tmp / "com" / "nos" / "stofs_2d_glo", tmp / "com" / "nos" / "stofs_2d_glo.20261005"
    (ges / "stofs_2d_glo_4064.tar").unlink()
    (day / "stofs_2d_glo.t06z.restart").unlink()
    r = _launch(cycle, COLD="0")
    assert r.returncode == 1 and r.stderr.count("MISSING") == 2 and not (tmp / "q.log").exists()
    assert "stofs_2d_glo_4064.tar" in r.stderr and "stofs_2d_glo.20261005/stofs_2d_glo.t06z.restart" in r.stderr
    (day / "stofs_2d_glo.t06z.hotstart").unlink()
    (ges / "stofs_2d_glo_nod_equi").unlink()
    r = _launch(cycle, COLD="0")
    assert r.returncode == 1 and r.stderr.count("MISSING") == 4 and "t06z.hotstart" in r.stderr and "nod_equi" in r.stderr
    assert not (tmp / "q.log").exists() and not (tmp / "ptmp").exists()


def test_cold0_previous_cycle_crosses_midnight(cycle):
    tmp = cycle[0]
    rr = tmp / "com" / "nos" / "stofs_2d_glo.20261005" / "00" / "rerun"
    shutil.copytree(tmp / "com" / "nos" / "stofs_2d_glo.20261005" / "12" / "rerun", rr)
    r = _run(cycle, ("20261005", "00"), COLD="0")
    assert r.returncode == 1 and r.stderr.count("MISSING") == 2
    assert "stofs_2d_glo.20261004/stofs_2d_glo.t18z.hotstart" in r.stderr and "stofs_2d_glo.20261004/stofs_2d_glo.t18z.restart" in r.stderr
    for kind in ("hotstart", "restart"):
        _stub(tmp / "com" / "nos" / "stofs_2d_glo.20261004" / f"stofs_2d_glo.t18z.{kind}", "x")
    assert _run(cycle, ("20261005", "00"), COLD="0").returncode == 0


def test_clone_must_be_named_nos_workflow(cycle):
    tmp, clone, env = cycle
    other = tmp / "pk" / "my_clone"
    shutil.copytree(clone, other)
    r = _run((tmp, other, env), ("20261005", "12"))
    assert r.returncode == 1 and "nos-workflow" in r.stderr and not (tmp / "q.log").exists()


def test_sbatch_failure_points_at_the_queued_jobs(cycle):
    tmp = cycle[0]
    _stub(tmp / "bin" / "sbatch", SBATCH.replace('echo "$n;hercules"', '[ "$n" -lt 3 ] && echo "$n" || exit 1'))
    r = _launch(cycle, COLD="0")
    assert r.returncode == 1 and "sbatch failed for surf_ncst" in r.stderr and "scancel" in r.stderr


def test_stages_ncst_submits_only_the_two_nowcasts(cycle):
    """The Jenkins smoke level: COLD=0 STAGES=ncst runs tide_ncst and surf_ncst and nothing downstream. MJ (10/13/26)"""
    tmp = cycle[0]
    r = _launch(cycle, COLD="0", STAGES="ncst")
    assert r.returncode == 0, r.stderr
    j = _jobs(tmp)
    assert list(j) == ["tide_ncst", "surf_ncst"] and _deps(j) == {"tide_ncst": [], "surf_ncst": []}
    assert (j["tide_ncst"]["wall"], j["surf_ncst"]["wall"]) == ("0:40:00", "0:40:00")
    assert " ".join(j["surf_ncst"]["flags"]) == "-N 52" and j["tide_ncst"]["flags"] == []
    jobs = tmp / "ptmp" / "tester" / "slurm_2dglo" / "jobs_2026100512.txt"
    assert [ln.split()[0] for ln in jobs.read_text().splitlines()] == ["tide_ncst", "surf_ncst"]
    (tmp / "q.log").unlink()
    assert _launch(cycle, COLD="0", STAGES="all").returncode == 0 and len(_jobs(tmp)) == 6


def test_stages_ncst_cold_chain_and_gfs_jobs(cycle):
    tmp = cycle[0]
    assert _launch(cycle, STAGES="ncst").returncode == 0
    j = _jobs(tmp)
    assert set(j) == {"cold_adcprep", "cold_spinup", "tide_ncst", "surf_ncst"}
    assert _deps(j)["tide_ncst"] == ["cold_spinup"] and _deps(j)["surf_ncst"] == ["cold_spinup"]
    (tmp / "q.log").unlink()
    assert _launch(cycle, COLD="0", STAGES="ncst", SUBMIT_GFS="1").returncode == 0
    j = _jobs(tmp)
    assert set(j) == {"gfs_ncst", "tide_ncst", "surf_ncst"} and _deps(j)["surf_ncst"] == ["gfs_ncst"]


def test_stages_ncst_preflight_needs_only_the_ncst_forcing(cycle):
    tmp = cycle[0]
    rr = tmp / "com" / "nos" / "stofs_2d_glo.20261005" / "12" / "rerun"
    for n in (221, 222, 225):
        (rr / f"stofs_2d_glo_fcst.{n}.nc").unlink()
    r = _launch(cycle, COLD="0")
    assert r.returncode == 1 and r.stderr.count("MISSING") == 3 and "stofs_2d_glo_fcst.221.nc" in r.stderr
    assert not (tmp / "q.log").exists()
    assert _launch(cycle, COLD="0", STAGES="ncst").returncode == 0
    (rr / "stofs_2d_glo_ncst.222.nc").unlink()
    r = _launch(cycle, COLD="0", STAGES="ncst")
    assert r.returncode == 1 and r.stderr.count("MISSING") == 1 and "stofs_2d_glo_ncst.222.nc" in r.stderr


def test_stages_is_validated(cycle):
    r = _launch(cycle, STAGES="fcst")
    assert r.returncode == 2 and "STAGES must be" in r.stderr
    r = _launch(cycle, COLD="0", STAGES="ncst", SERIAL="1")
    assert r.returncode == 2 and "SERIAL=1" in r.stderr and not (cycle[0] / "q.log").exists()


def test_ci_account_and_qos_are_passed_to_every_sbatch(cycle):
    """The cards say #SBATCH --account=nos-surge; the CI agent charges another account through the CLI. MJ (10/13/26)"""
    tmp = cycle[0]
    assert _launch(cycle, SLURM_CI_ACCOUNT="nosofs", SLURM_CI_QOS="batch").returncode == 0
    j = _jobs(tmp)
    assert len(j) == 8
    for k, v in j.items():
        assert "--account=nosofs" in v["flags"] and "--qos=batch" in v["flags"], k
        assert v["sbatch"].index("--account=nosofs") > v["sbatch"].index("-t")
    assert " ".join(j["surf_ncst"]["flags"]) == "--account=nosofs --qos=batch -N 52"
    (tmp / "q.log").unlink()
    assert _launch(cycle, COLD="0", SLURM_CI_ACCOUNT="nosofs").returncode == 0
    assert all("--account=nosofs" in v["flags"] and not any(f.startswith("--qos") for f in v["flags"]) for v in _jobs(tmp).values())
    (tmp / "q.log").unlink()
    assert _launch(cycle, COLD="0").returncode == 0
    assert not any(f.startswith(("--account", "--qos")) for v in _jobs(tmp).values() for f in v["flags"])


def _status_cycle(tmp_path):
    jd = tmp_path / "ptmp" / "tester" / "slurm_2dglo"
    jd.mkdir(parents=True)
    (jd / "jobs_2026100512.txt").write_text("tide_ncst 7\nsurf_ncst 8\npost_ncrcat 9\n")
    rpt = tmp_path / "ptmp" / "tester" / "rpt" / "stofs_2d_glo"
    rpt.mkdir(parents=True)
    (rpt / "stofs_2d_glo_nowcast_00.7.out").write_text(
        "noise\nSTAGE_SUMMARY stage=nowcast ofs=stofs_2d_glo status=PASS runtime_s=1128.4 steps=3\n")
    (rpt / "stofs_2d_glo_nowcast_00.8.out").write_text("running\n")
    (rpt / "stofs_2d_glo_prep_00.17.out").write_text("STAGE_SUMMARY stage=prep ofs=stofs_2d_glo status=FAIL runtime_s=1.0\n")
    _stub(tmp_path / "bin" / "sacct", '#!/bin/bash\ncase "$2" in 7) echo "COMPLETED|00:18:48";; 8) echo "RUNNING|00:01:00";; '
                                      '*) echo "PENDING|00:00:00";; esac\n')
    return {**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "NOS_PTMP": str(tmp_path / "ptmp"), "LOGNAME": "tester"}


@pytest.mark.parametrize("by_file", [True, False])
def test_status_table(tmp_path, by_file):
    env = _status_cycle(tmp_path)
    args = [str(tmp_path / "ptmp" / "tester" / "slurm_2dglo" / "jobs_2026100512.txt")] if by_file else ["20261005", "12"]
    r = subprocess.run(["bash", str(STATUS), *args], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = [ln.split() for ln in r.stdout.splitlines()]
    assert rows[0] == ["job", "id", "state", "elapsed", "stage"]
    assert rows[1] == ["tide_ncst", "7", "COMPLETED", "00:18:48", "status=PASS", "runtime_s=1128.4"]
    assert rows[2] == ["surf_ncst", "8", "RUNNING", "00:01:00"]
    assert rows[3] == ["post_ncrcat", "9", "PENDING", "00:00:00"]


def test_status_without_sacct_and_with_bad_arguments(tmp_path):
    env = _status_cycle(tmp_path)
    (tmp_path / "bin" / "sacct").unlink()
    env["PATH"] = f"{tmp_path / 'bin'}:/usr/bin:/bin"
    r = subprocess.run(["bash", str(STATUS), "20261005", "12"], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.splitlines()[1].split()[:4] == ["tide_ncst", "7", "-", "-"]
    assert "status=PASS" in r.stdout.splitlines()[1]
    assert subprocess.run(["bash", str(STATUS)], env=env, capture_output=True).returncode == 2
    assert subprocess.run(["bash", str(STATUS), "a", "b", "c"], env=env, capture_output=True).returncode == 2
    for args in (["20261005"], ["20261005", "18"], [str(tmp_path / "nope.txt")]):
        r = subprocess.run(["bash", str(STATUS), *args], env=env, capture_output=True, text=True)
        assert r.returncode == 1 and "no job list" in r.stderr and r.stdout == "", args
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    assert subprocess.run(["bash", str(STATUS), str(empty)], env=env, capture_output=True).returncode == 1


def test_nowcast_card_points_at_the_launcher():
    text = (SLURM / "jnos_nowcast_00.sh").read_text()
    assert "launch_stofs_2d_glo.sh <PDY> <CYC>" in text and "status_stofs_2d_glo.sh" in text


def test_ptmp_and_comroot_defaults_are_the_same_string_everywhere():
    """The staging tool, the cards, the launcher and the status script find each other's files only through these defaults. MJ (10/13/26)"""
    ptmp = {f: set(re.findall(r"NOS_PTMP:-([^}]+)\}", f.read_text())) for f in (*CARDS, LAUNCH, STATUS, STAGE_TOOL)}
    assert all(len(v) == 1 for v in ptmp.values()), ptmp
    assert {next(iter(v)) for v in ptmp.values()} == {"/work2/noaa/nos-surge/mjisan/nos-run/ptmp"}
    # $LOGNAME, ${LOGNAME} and the staging tool's ${U} are one user. MJ (10/13/26)
    comroot = {f: {re.sub(r"\$\{(LOGNAME|U)\}", "$LOGNAME", m) for m in re.findall(r"COMROOT_2DGLO:-(.*?com_2dglo)\}", f.read_text())}
               for f in (*CARDS, LAUNCH, STAGE_TOOL)}
    assert all(len(v) == 1 for v in comroot.values()), comroot
    assert {next(iter(v)) for v in comroot.values()} == {"${NOS_PTMP}/$LOGNAME/com_2dglo"}
