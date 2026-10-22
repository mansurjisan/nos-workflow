"""Manual STOFS-2D-Global support in the Hercules Jenkins pipeline (.cicd): the shared Prep/Nowcast/Forecast/Post stages through run_stage.sh, Stage Data, Verify and the seed, against stub sbatch/sacct/module/rsync inputs. Offline. MJ (10/15/26)"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

nc = pytest.importorskip("netCDF4")
np = pytest.importorskip("numpy")

REPO = Path(__file__).resolve().parents[4]
CICD = REPO / ".cicd"
SCRIPTS = CICD / "scripts"
JENKINSFILE = CICD / "Jenkinsfile"
SCRIPT = SCRIPTS / "stofs_2d_glo.sh"
LAUNCHER = REPO / "slurm" / "stofs_2d_glo" / "launch_stofs_2d_glo.sh"
STATUS = REPO / "slurm" / "stofs_2d_glo" / "status_stofs_2d_glo.sh"
needs_rsync = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
PDY, CYC = "20261012", "06"
PREV = ("20261012", "00")
AMBIENT = ("COMROOT_2DGLO", "WAIT_S", "POLL_S", "CMP_TOL", "OPS_DIR", "OPS_WORK", "OPS_WARN_MM", "SEED_RT", "SEED_ADCIRC", "FORCE",
           "NOS_VENV", "VENV_PATH", "WORKSPACE", "RT_DATA_ROOT", "DATA_MODE", "LEVEL", "CI_OFS", "SLURM_CI_ACCOUNT", "SLURM_CI_QOS",
           "SLURM_JOB_ID", "PACKAGEROOT", "NOS_PTMP", "SEED_SRC", "STUB_LABELS", "STUB_DIR")


def _stub(path: Path, body: str = "#!/bin/bash\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)
    return path


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class Ci:
    """A throw-away CI root: PACKAGEROOT/nos-workflow (HOMEnos), NOS_PTMP, the RT root and a workspace. MJ (10/13/26)"""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.pk = tmp / "pk"
        self.home = self.pk / "nos-workflow"
        self.ptmp = tmp / "ptmp"
        self.rt = tmp / "rt"
        self.ws = tmp / "ws"
        self.bin = tmp / "bin"
        self.stubs = tmp / "stubs"
        self.venv = tmp / "venv"
        self.com = self.ptmp / "tester" / "com"   # the shared com, as SECOFS and ATL. MJ (10/15/26)
        self.rpt = self.ptmp / "tester" / "rpt" / "stofs_2d_glo"
        self.ds = self.rt / "stofs_2d_glo" / f"{PDY}{CYC}"
        for d in (self.home, self.ptmp, self.rt, self.ws, self.bin, self.stubs):
            d.mkdir(parents=True, exist_ok=True)
        (self.home / "slurm").symlink_to(REPO / "slurm")   # run_stage.sh and card-env read the real cards. MJ (10/15/26)
        _touch(self.venv / "bin" / "activate", "")
        _stub(self.bin / "module")
        self.env = {k: v for k, v in os.environ.items() if k not in AMBIENT}
        self.env.update(PATH=f"{self.bin}:{os.environ['PATH']}", PACKAGEROOT=str(self.pk), NOS_PTMP=str(self.ptmp),
                        RT_DATA_ROOT=str(self.rt), WORKSPACE=str(self.ws), LOGNAME="tester", VENV_PATH=str(self.venv),
                        CI_OFS="stofs_2d_glo", PDY=PDY, CYC=CYC, LEVEL="smoke", DATA_MODE="frozen", STUB_DIR=str(self.stubs),
                        PYTHONDONTWRITEBYTECODE="1")

    def run(self, script: Path, *args: str, **extra):
        env = {**self.env, **{k: v for k, v in extra.items() if v is not None}}
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
        return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, cwd=str(self.tmp))

    def script(self, *args: str, **extra):
        return self.run(SCRIPT, *args, **extra)

    def dataset(self, state: bool = True, ref: bool = True, ops: bool = True, sentinel: bool = True) -> Path:
        ds, inp = self.ds, self.ds / "input" / "nos"
        for seg in ("ncst", "fcst"):
            for n in (221, 222, 225):
                _touch(inp / f"stofs_2d_glo.{PDY}" / CYC / "rerun" / f"stofs_2d_glo_{seg}.{n}.nc", f"forcing {seg} {n}")
        if state:
            for f in ("stofs_2d_glo_nod_equi", "stofs_2d_glo_4064.tar", "stofs_2d_glo_4064.tar.json"):
                _touch(inp / "stofs_2d_glo" / f, f"ges {f}")
            for kind in ("hotstart", "restart"):
                _touch(inp / f"stofs_2d_glo.{PREV[0]}" / f"stofs_2d_glo.t{PREV[1]}z.{kind}", f"chain {kind}")
        if ref:
            for s in ("tide", "surf"):
                _touch(ds / "ref" / "nos" / f"stofs_2d_glo.{PDY}" / CYC / "rerun" / f"stofs_2d_glo_{s}.61.nc", f"ref {s}")
            for p in ("htp", "cwl", "cwl.noanomaly", "swl"):
                _touch(ds / "ref" / "nos" / f"stofs_2d_glo.{PDY}" / f"stofs_2d_glo.t{CYC}z.points.{p}.nc", f"ref {p}")
        if ops:
            for p in ("htp", "cwl.noanomaly", "swl"):
                _touch(ds / "ops" / f"stofs_2d_glo.t{CYC}z.points.{p}.nc", f"ops {p}")
        if sentinel:
            _touch(ds / ".seeded_ok", "")
        return ds


@pytest.fixture()
def ci(tmp_path):
    return Ci(tmp_path)


def test_every_cicd_script_is_valid_bash_and_python_compiles():
    for f in sorted(SCRIPTS.glob("*.sh")):
        subprocess.run(["bash", "-n", str(f)], check=True)
    for f in (LAUNCHER, STATUS):
        subprocess.run(["bash", "-n", str(f)], check=True)
    compile((SCRIPTS / "compare_2dglo.py").read_text(), "compare_2dglo.py", "exec")


def test_jenkinsfile_parameters_default_to_the_secofs_pipeline():
    text = JENKINSFILE.read_text()
    assert re.search(r"choice\(name: 'OFS', choices: \['secofs_ufs', 'stofs_2d_glo', 'stofs_3d_atl_ufs_standalone', 'stofs_3d_atl_ufs'\]", text)
    assert re.search(r"choice\(name: 'LEVEL', choices: \['smoke', 'cycle', 'full'\]", text)
    assert "CI_OFS       = \"${params.OFS ?: 'secofs_ufs'}\"" in text
    assert "LEVEL        = \"${params.LEVEL ?: 'smoke'}\"" in text
    assert "PDY          = \"${resolvePdy(params.PDY, params.OFS?.startsWith('stofs_3d_atl') ? '12' : params.CYC)}\"" in text
    assert "isNightly" not in text and "cron(" not in text   # the schedule lives in the dashboard. MJ (10/22/26)


def _stage_conditions():
    text = JENKINSFILE.read_text()
    return dict(re.findall(r"stage\('([^']+)'\) \{\n\s+when \{ (.+?) \}\n\s+steps", text))


def _runs(cond: str, ofs: str, level: str) -> bool:
    """Evaluates a stage `when` expression for one (OFS, LEVEL): only the operators and isAtlOfs() the Jenkinsfile uses. MJ (10/15/26)"""
    py = re.sub(r"^expression \{ | \}$", "", cond).replace("env.RUN_CYCLE == 'true'", "True").replace("&&", " and ").replace("||", " or ")
    py = py.replace("isAtlOfs(env.CI_OFS)", str(ofs.startswith("stofs_3d_atl"))).replace("!=", " != ")
    return bool(eval(re.sub(r"env\.CI_OFS", repr(ofs), re.sub(r"env\.LEVEL", repr(level), py))))


MODEL_STAGES = ["Prep", "Nowcast", "Forecast", "Post", "Verify"]


@pytest.mark.parametrize("ofs", ["secofs_ufs", "stofs_2d_glo", "stofs_3d_atl_ufs_standalone", "stofs_3d_atl_ufs"])
@pytest.mark.parametrize("level", ["smoke", "cycle", "full"])
def test_jenkinsfile_stage_conditions_for_every_ofs_and_level(ofs, level):
    """SECOFS always runs all five; the manual systems (2D-GLO and both ATL variants) drop Forecast and Post at smoke. MJ (10/15/26)"""
    cond = _stage_conditions()
    ran = [n for n in MODEL_STAGES if _runs(cond[n], ofs, level)]
    want = ["Prep", "Nowcast", "Verify"] if ofs != "secofs_ufs" and level == "smoke" else MODEL_STAGES
    assert ran == want, (ofs, level, ran)
    for name in ("Bootstrap", "Deploy", "Environment Check", "Stage Data"):
        assert cond[name] == "environment name: 'RUN_CYCLE', value: 'true'", name
    for name in MODEL_STAGES:
        assert "env.RUN_CYCLE == 'true'" in cond[name], name


def test_jenkinsfile_has_no_2dglo_run_chain_and_verifies_2dglo_through_the_shared_stage():
    text = JENKINSFILE.read_text()
    assert not {"Run 2D-GLO", "Verify 2D-GLO"} & set(_stage_conditions())
    assert 'stofs_2d_glo.sh" run' not in text and 'stofs_2d_glo.sh" verify' in text
    assert not re.search(r"\brun\)|cmd_run|afterok|WAIT_S|POLL_S|BAD_STATES", SCRIPT.read_text().split("\nset -euo pipefail\n", 1)[1])


def test_2dglo_is_never_selected_by_the_pr_label_path():
    """Only an explicit OFS=stofs_2d_glo started by a user turns RUN_CYCLE on without the label; the label code itself is kept. MJ (10/13/26)"""
    text = JENKINSFILE.read_text()
    assert "pullRequest.labels.contains('hercules-nos-RT')" in text
    assert "return ofs in ['stofs_2d_glo', 'stofs_3d_atl_ufs_standalone', 'stofs_3d_atl_ufs']" in text
    m = re.search(r"if \(env\.RUN_CYCLE != 'true' && isManualOfs\(params\.OFS\) && currentBuild\.getBuildCauses\('hudson\.model\.Cause\$UserIdCause'\)\)", text)
    assert m, "the manual override must require both the explicit selection and a user-started build"
    assert text.index("hasLabel ? 'true' : 'false'") < m.start() < text.index("mkdir (no -p) is atomic")
    assert "!isManualOfs(env.CI_OFS)" in text, "the hercules-nos-RT label must not be removed after a manual build"
    assert re.search(r"def postStatus\(String state, String description\) \{\n    if \(isManualOfs\(env\.CI_OFS\)\)", text)


def test_common_sh_defaults_to_secofs_and_rejects_an_unknown_system(ci):
    probe = ci.tmp / "probe.sh"
    probe.write_text(f'source "{SCRIPTS}/common.sh"\necho "OFS=$OFS HOMEnos=$HOMEnos"\n')
    r = ci.run(probe, CI_OFS=None)
    assert r.returncode == 0 and f"OFS=secofs_ufs HOMEnos={ci.home}" in r.stdout
    assert f"OFS=stofs_2d_glo" in ci.run(probe).stdout
    r = ci.run(probe, CI_OFS="stofs_3d_atl")
    assert r.returncode == 2 and "CI_OFS must be" in r.stderr


def _tree(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_frozen_smoke_stages_state_and_both_forcing_segments(ci):
    ci.dataset()
    _touch(ci.com / "nos" / "stofs_2d_glo.20260101" / "stale_from_an_earlier_build", "old")
    r = ci.script("stage")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "stage_data PASS" in r.stdout
    got = _tree(ci.com)
    day = f"nos/stofs_2d_glo.{PDY}/{CYC}/rerun"
    assert got == sorted([
        "nos/stofs_2d_glo/stofs_2d_glo_4064.tar", "nos/stofs_2d_glo/stofs_2d_glo_4064.tar.json", "nos/stofs_2d_glo/stofs_2d_glo_nod_equi",
        f"nos/stofs_2d_glo.{PREV[0]}/stofs_2d_glo.t{PREV[1]}z.hotstart", f"nos/stofs_2d_glo.{PREV[0]}/stofs_2d_glo.t{PREV[1]}z.restart",
        *[f"{day}/stofs_2d_glo_{seg}.{n}.nc" for seg in ("ncst", "fcst") for n in (221, 222, 225)]])
    assert (ci.com / day / "stofs_2d_glo_ncst.221.nc").read_text() == "forcing ncst 221"
    # the big read-only inputs are hard links of the dataset, the .json (rewritten in place on a rebuild) is a copy. MJ (10/13/26)
    ges = Path("nos/stofs_2d_glo")
    for f in (day + "/stofs_2d_glo_ncst.221.nc", str(ges / "stofs_2d_glo_4064.tar"), str(ges / "stofs_2d_glo_nod_equi")):
        assert (ci.com / f).samefile(ci.ds / "input" / f), f
    assert not (ci.com / ges / "stofs_2d_glo_4064.tar.json").samefile(ci.ds / "input" / ges / "stofs_2d_glo_4064.tar.json")
    assert (ci.com / ges / "stofs_2d_glo_4064.tar.json").read_text() == "ges stofs_2d_glo_4064.tar.json"


def test_frozen_cycle_at_midnight_uses_the_chain_files_of_the_previous_day(ci):
    ci.ds = ci.rt / "stofs_2d_glo" / "2026101300"
    inp = ci.ds / "input" / "nos"
    for n in (221, 222, 225):
        for seg in ("ncst", "fcst"):
            _touch(inp / "stofs_2d_glo.20261013" / "00" / "rerun" / f"stofs_2d_glo_{seg}.{n}.nc")
    for f in ("stofs_2d_glo_nod_equi", "stofs_2d_glo_4064.tar", "stofs_2d_glo_4064.tar.json"):
        _touch(inp / "stofs_2d_glo" / f)
    for kind in ("hotstart", "restart"):
        _touch(inp / "stofs_2d_glo.20261012" / f"stofs_2d_glo.t18z.{kind}")
    _touch(ci.ds / ".seeded_ok", "")
    r = ci.script("stage", PDY="20261013", CYC="00")
    assert r.returncode == 0, r.stderr
    assert (ci.com / "nos" / "stofs_2d_glo.20261012" / "stofs_2d_glo.t18z.restart").is_file()


def test_frozen_stage_lists_every_missing_piece_and_keeps_the_old_comroot(ci):
    ci.dataset(state=False)           # a cold-start dataset cannot feed a COLD=0 level. MJ (10/13/26)
    _touch(ci.com / "keep_me", "old")
    r = ci.script("stage")
    assert r.returncode == 1 and r.stderr.count("MISSING") == 5 and "stofs_2d_glo_nod_equi" in r.stderr
    assert "t00z.hotstart" in r.stderr and "cold dataset" in r.stdout
    assert (ci.com / "keep_me").is_file()


def test_frozen_stage_needs_the_sentinel(ci):
    ci.dataset(sentinel=False)
    r = ci.script("stage")
    assert r.returncode == 1 and ".seeded_ok" in r.stdout and "stofs_2d_glo.sh seed 20261012 06" in r.stdout
    assert ci.script("stage", LEVEL="full").stdout.count("seed 20261012 06 cold") == 1


COM_RUN = "stofs_2d_glo"


def test_stage_deletes_only_the_2dglo_directories_and_keeps_everything_else(ci):
    ci.dataset()
    nos = ci.com / "nos"
    keep = [_touch(nos / n / "f", "keep") for n in (
        f"secofs_ufs.{PDY}", f"secofs_ufs.20261011", "secofs_ufs", f"stofs_3d_atl_ufs.{PDY}", "stofs_3d_atl_ufs", "stofs_3d_atl_ufs.20261011",
        "stofs_2d_glo.2026101", "stofs_2d_glo.20261011x", "stofs_2d_glo_ww3.20261011", "stofs_2d_glo.latest", "stofs_2d_glo_x", "xstofs_2d_glo.20261011")]
    keep += [_touch(ci.com / "other" / "f", "keep"), _touch(ci.ptmp / "tester" / "com_atl_sa" / "nos" / "mine", "keep"), _touch(ci.ptmp / "tester" / "com_other" / "f", "keep"),
             _touch(ci.ptmp / "tester" / "work" / "stofs_2d_glo" / "job.1" / "f", "keep"), _touch(ci.rt / "stofs_2d_glo" / "2026101012" / "f", "keep"),
             _touch(ci.ptmp / "other_user" / "com" / "nos" / "stofs_2d_glo.20261011" / "f", "keep")]
    gone = [_touch(nos / n / "f", "old") for n in (f"stofs_2d_glo.{PDY}", "stofs_2d_glo.20261011", "stofs_2d_glo.20260101", "stofs_2d_glo")]
    r = ci.script("stage")
    assert r.returncode == 0, r.stderr + r.stdout
    assert not any(g.exists() for g in gone), [g for g in gone if g.exists()]
    assert all(k.is_file() for k in keep), [k for k in keep if not k.is_file()]


def test_stage_refuses_symlinked_or_odd_com_targets_and_deletes_nothing_first(ci):
    ci.dataset()
    victim = _touch(ci.tmp / "victim" / "f", "keep")
    nos = ci.com / "nos"
    # a valid target that sorts before the bad one must survive: every target is checked before the first rm. MJ (10/15/26)
    early = _touch(nos / "stofs_2d_glo.20260101" / "f", "must survive a refusal")
    (nos / "stofs_2d_glo.20261011").symlink_to(victim.parent)
    r = ci.script("stage")
    assert r.returncode == 1 and "is a symlink or not a plain directory" in r.stderr and victim.is_file() and early.is_file()
    (nos / "stofs_2d_glo.20261011").unlink()
    ges = nos / "stofs_2d_glo"
    ges.symlink_to(victim.parent)
    r = ci.script("stage")
    assert r.returncode == 1 and victim.is_file() and early.is_file()
    ges.unlink()
    shutil.rmtree(ci.com)
    ci.com.symlink_to(victim.parent)
    r = ci.script("stage")
    assert r.returncode == 1 and "refusing to clear" in r.stderr and victim.is_file()
    ci.com.unlink()
    ci.com.mkdir()
    (ci.com / "nos").symlink_to(victim.parent)
    r = ci.script("stage")
    assert r.returncode == 1 and "is a symlink" in r.stderr and victim.is_file()
    (ci.com / "nos").unlink()
    for bad in ("..", ".", "a/b"):
        r = ci.script("stage", LOGNAME=bad)
        assert r.returncode == 1 and "odd LOGNAME" in r.stderr, bad
    assert victim.is_file()


def test_stage_ignores_an_inherited_comroot_2dglo_and_clears_the_old_ci_root_once(ci):
    ci.dataset()
    precious = _touch(ci.tmp / "precious" / "nos" / "stofs_2d_glo.20261011" / "f", "keep")
    old = _touch(ci.ptmp / "tester" / "com_2dglo_ci" / "nos" / "f", "old")
    r = ci.script("stage", COMROOT_2DGLO=str(ci.tmp / "precious"))
    assert r.returncode == 0 and precious.is_file() and not old.exists() and r.stdout.count("removed the old CI com") == 1
    assert (ci.com / "nos" / f"stofs_2d_glo.{PDY}" / CYC / "rerun" / "stofs_2d_glo_ncst.221.nc").is_file()
    assert "removed the old CI com" not in ci.script("stage").stdout
    link = ci.ptmp / "tester" / "com_2dglo_ci"
    link.symlink_to(precious.parent)
    r = ci.script("stage")
    assert r.returncode == 0 and "leaving" in r.stderr and precious.is_file()


@needs_rsync
def test_stage_links_the_forcing_into_a_writable_rerun_directory_from_a_read_only_dataset(ci):
    ds = ci.dataset()
    for f in ds.rglob("*"):
        if f.is_file() and ("rerun" in f.parts or f.parent.name == "stofs_2d_glo") and f.suffix != ".json":
            f.chmod(0o444)
    for d in sorted((ds / "input").rglob("*"), reverse=True):
        if d.is_dir():
            d.chmod(0o555)
    try:
        r = ci.script("stage")
        assert r.returncode == 0, r.stderr + r.stdout
        rr = ci.com / "nos" / f"stofs_2d_glo.{PDY}" / CYC / "rerun"
        assert os.access(rr, os.W_OK) and os.access(ci.com / "nos" / "stofs_2d_glo", os.W_OK) and os.access(ci.com / "nos" / f"stofs_2d_glo.{PREV[0]}", os.W_OK)
        # the jobs publish their products beside the forcing, and a rebuilt decomposition replaces the tar by rename and rewrites the .json. MJ (10/15/26)
        (rr / "stofs_2d_glo_tide.61.nc").write_text("product")
        (ci.com / "nos" / "stofs_2d_glo" / "stofs_2d_glo_4064.tar.json").write_text("{}")
        assert (rr / "stofs_2d_glo_ncst.221.nc").samefile(ds / "input" / "nos" / f"stofs_2d_glo.{PDY}" / CYC / "rerun" / "stofs_2d_glo_ncst.221.nc")
        assert (ds / "input" / "nos" / "stofs_2d_glo" / "stofs_2d_glo_4064.tar.json").read_text() == "ges stofs_2d_glo_4064.tar.json"
        assert ci.script("stage").returncode == 0     # a second stage clears the linked tree and links it again. MJ (10/15/26)
    finally:
        for d in (ds / "input").rglob("*"):
            if d.is_dir():
                d.chmod(0o755)


def test_bad_arguments_are_rejected(ci):
    assert ci.script("stage", LEVEL="weekly").returncode == 2
    assert ci.script("stage", PDY="2026101").returncode == 2
    assert ci.script("stage", CYC="07").returncode == 2
    assert ci.script("bogus").returncode == 2
    assert ci.script().returncode == 2
    r = ci.script("stage", CI_OFS="secofs_ufs")
    assert r.returncode == 2 and "CI_OFS=stofs_2d_glo" in r.stderr


def test_stage_data_sh_hands_over_to_the_2dglo_stage(ci):
    ci.dataset()
    r = ci.run(SCRIPTS / "stage_data.sh")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "staging" in r.stdout and (ci.com / "nos").is_dir()


def _live_tool(ci: Ci, rc: int):
    return _stub(ci.home / "tools" / "hercules_2d_glo_stage_forcing.sh",
                 f'#!/bin/bash\necho "$@ | $COMROOT_2DGLO | $NOS_PTMP" > "$STUB_DIR/tool.args"\nexit {rc}\n')


def test_live_stage_runs_the_login_node_tool_and_keeps_the_chain_state(ci):
    _live_tool(ci, 0)
    _touch(ci.com / "nos" / "chain_state", "keep")
    r = ci.script("stage", DATA_MODE="live", LEVEL="full")
    assert r.returncode == 0, r.stderr + r.stdout
    assert (ci.stubs / "tool.args").read_text().strip() == f"--rm-raw {PDY} {CYC} | {ci.com} | {ci.ptmp}"
    assert (ci.com / "nos" / "chain_state").is_file() and "stage_data PASS" in r.stdout


def test_live_stage_checks_the_chain_state_before_downloading(ci):
    _live_tool(ci, 0)
    r = ci.script("stage", DATA_MODE="live", LEVEL="cycle")
    assert r.returncode == 1 and r.stderr.count("MISSING") == 5 and "stofs_2d_glo.t00z.restart" in r.stderr
    assert "LEVEL=full DATA_MODE=live" in r.stdout and not (ci.stubs / "tool.args").exists()
    _finished_run(ci.com)
    assert ci.script("stage", DATA_MODE="live", LEVEL="cycle").returncode == 0 and (ci.stubs / "tool.args").is_file()


def test_live_stage_prunes_other_days_and_ops_s3_cycles_but_keeps_comges_and_the_pdy_and_previous_days(ci):
    _live_tool(ci, 0)
    nos, ops = ci.com / "nos", ci.ptmp / "tester" / "ops_s3"
    keep = [_touch(nos / n / "f", "keep") for n in ("stofs_2d_glo", "stofs_2d_glo.20261012", "stofs_2d_glo.20261011", "secofs_ufs.20260101", "stofs_2d_glo.latest", "stofs_2d_glo.2026101")]
    keep += [_touch(ops / n / "f", "keep") for n in ("2026101200", "notes", "202610120")]
    gone = [_touch(nos / "stofs_2d_glo.20261009" / "f"), _touch(nos / "stofs_2d_glo.20260101" / "f"), _touch(ops / "2026100912" / "f"), _touch(ops / "2026101206" / "f")]
    r = ci.script("stage", DATA_MODE="live", LEVEL="full", CYC="00")
    assert r.returncode == 0, r.stderr + r.stdout
    assert all(k.exists() for k in keep), [k for k in keep if not k.exists()]
    assert not any(g.parent.exists() for g in gone), [g for g in gone if g.parent.exists()]
    assert f"removed {os.path.realpath(nos)}/stofs_2d_glo.20261009" in r.stdout and f"removed {ops}/2026100912" in r.stdout
    # an OPS_WORK of the caller's own leaves ops_s3 alone. MJ (10/22/26)
    other = _touch(ops / "2026100912" / "f")
    assert ci.script("stage", DATA_MODE="live", LEVEL="full", CYC="00", OPS_WORK=str(ci.tmp / "w")).returncode == 0 and other.is_file()


def test_live_stage_prune_refuses_a_symlinked_target_and_deletes_nothing_first(ci):
    _live_tool(ci, 0)
    nos = ci.com / "nos"
    victim = _touch(ci.tmp / "victim" / "f", "keep")
    early = _touch(nos / "stofs_2d_glo.20260101" / "f", "must survive a refusal")
    (nos / "stofs_2d_glo.20261009").symlink_to(victim.parent)
    r = ci.script("stage", DATA_MODE="live", LEVEL="full", CYC="00")
    assert r.returncode == 1 and "is a symlink or not a plain directory" in r.stderr and victim.is_file() and early.is_file()
    assert not (ci.stubs / "tool.args").exists()
    (nos / "stofs_2d_glo.20261009").unlink()
    ops = ci.ptmp / "tester" / "ops_s3"
    (ops / "2026100912").parent.mkdir(parents=True)
    (ops / "2026100912").symlink_to(victim.parent)
    assert ci.script("stage", DATA_MODE="live", LEVEL="full", CYC="00").returncode == 0 and victim.is_file() and (ops / "2026100912").is_symlink()


def test_live_cycle_prune_runs_after_the_chain_state_check(ci):
    _live_tool(ci, 0)
    old = _touch(ci.com / "nos" / "stofs_2d_glo.20260101" / "f")
    assert ci.script("stage", DATA_MODE="live", LEVEL="cycle").returncode == 1 and old.is_file()


def test_live_stage_tolerates_only_the_reference_download_failure(ci):
    _live_tool(ci, 3)
    r = ci.script("stage", DATA_MODE="live", LEVEL="full")
    assert r.returncode == 0 and "WARN" in r.stdout and "stage_data PASS" in r.stdout
    _live_tool(ci, 1)
    r = ci.script("stage", DATA_MODE="live", LEVEL="full")
    assert r.returncode == 1 and "rc=1" in r.stdout
    assert ci.script("stage", DATA_MODE="sometimes").returncode == 1


# ---- Prep/Nowcast/Forecast/Post: run_stage.sh with the 2D-GLO card-env ---- MJ (10/15/26)

RUN_STAGE = SCRIPTS / "run_stage.sh"
WALL = {("prep", False): "0:50:00", ("prep", True): "3:50:00", ("nowcast", False): "1:20:00", ("nowcast", True): "2:20:00",
        ("forecast", False): "2:00:00", ("forecast", True): "2:00:00", ("post", False): "1:15:00", ("post", True): "1:15:00"}
# stage: (card, ADCIRC_SEGMENT warm, cold, ADCIRC_STREAM, sbatch node flags). MJ (10/15/26)
JOB = {"prep": ("prep", "ncst fcst", "adcprep ncst fcst", "", "-N 1 -n 1 --mem=64G"),
       "nowcast": ("nowcast", "ncst", "spinup ncst", "tide surf", "-N 52"),
       "forecast": ("forecast", "fcst", "fcst", "tide surf", "-N 52"),
       "post": ("prep", "ncdiff ncrcat", "ncdiff ncrcat", "", "-N 1 -n 1 --mem=100G")}


def _job(ci: Ci, stage: str, state="COMPLETED", ok=True, summary_stage=None, jid=101):
    """Stub sbatch (prints the jobid, records its arguments and the inherited variables the hook sets), sacct, scancel, and the job's log. MJ (10/15/26)"""
    _stub(ci.bin / "sbatch", f"""#!/bin/bash
echo "$*" >> "$STUB_DIR/sbatch.calls"
echo "SEG=[${{ADCIRC_SEGMENT-unset}}] STREAM=[${{ADCIRC_STREAM-unset}}] MODE=[${{ADCIRC_MODE-unset}}] PYTHONPATH=[${{PYTHONPATH-unset}}] COMOUT=[${{COMOUT-unset}}] RPTDIR=[${{RPTDIR-unset}}]" >> "$STUB_DIR/sbatch.env"
echo "Submitted batch job {jid}"
""")
    _stub(ci.bin / "sacct", f'#!/bin/bash\necho "{state}"\n')
    _stub(ci.bin / "scancel", '#!/bin/bash\necho "$@" >> "$STUB_DIR/scancel.log"\n')
    pfx = f"stofs_2d_glo_{JOB[stage][0]}_00"
    _touch(ci.rpt / f"{pfx}.{jid}.out", f"STAGE_SUMMARY stage={summary_stage or stage} ofs=stofs_2d_glo status={'PASS' if ok else 'FAIL'} runtime_s=1\n")
    _touch(ci.rpt / f"{pfx}.{jid}.err", "err")
    _touch(ci.ws / f"slurm-{jid}.out", "epilogue")
    return pfx


def _stage(ci: Ci, stage: str, **extra):
    return ci.run(RUN_STAGE, stage, PDY, CYC, **extra)


@pytest.mark.parametrize("level", ["smoke", "cycle", "full"])
@pytest.mark.parametrize("stage", ["prep", "nowcast", "forecast", "post"])
def test_run_stage_submits_the_2dglo_job_with_the_launchers_flags_lists_and_exports(ci, stage, level):
    cold = level == "full"
    card, seg_warm, seg_cold, stream, flags = JOB[stage]
    pfx = _job(ci, stage)
    r = _stage(ci, stage, LEVEL=level, SLURM_CI_ACCOUNT="nosofs", SLURM_CI_QOS="batch", ADCIRC_SEGMENT="leak", ADCIRC_MODE="single", PYTHONPATH="/leak",
               COMOUT="/leak", RPTDIR="/leak/rpt", COMROOT="/leak/com", COMROOT_2DGLO="/leak/com2d")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"PASS[{stage}]: {ci.rpt}/{pfx}.101.out" in r.stdout
    line = (ci.stubs / "sbatch.calls").read_text().strip()
    assert "--account=nosofs --qos=batch" in line and line.split()[-1] == f"{ci.home}/slurm/stofs_2d_glo/jnos_{card}_00.sh"
    assert f"-J stofs_2d_glo_{stage} -t {WALL[(stage, cold)]} {flags} --export=" in line, line
    export = re.search(r"--export=(\S+)", line).group(1)
    for want in ("ALL", f"PDY={PDY}", f"CYC={CYC}", f"COMROOT_STAGED={ci.ptmp}/tester/comin_2dglo", f"NOS_VENV={ci.venv}", f"NOS_PTMP={ci.ptmp}", "ADCIRC_MODE=ops", "KEEPDATA=NO",
                 f"COMROOT_2DGLO={ci.com}", f"ADCIRC_EXEC_DIR={ci.pk}/adcirc_v56.1.0_exec", f"PACKAGEROOT={ci.pk}"):
        assert want in export.split(","), (want, export)
    assert "ADCIRC_SEGMENT" not in line and "ADCIRC_STREAM" not in line and line.count("--export=") == 1
    # the space separated lists travel in the environment (--export=ALL), the inherited leaks are replaced or gone. MJ (10/15/26)
    seg = seg_cold if cold else seg_warm
    assert (ci.stubs / "sbatch.env").read_text().strip() == f"SEG=[{seg}] STREAM=[{stream}] MODE=[unset] PYTHONPATH=[unset] COMOUT=[unset] RPTDIR=[unset]"
    assert (ci.ws / "ci_logs" / "current_jobid").read_text().split()[-1] == "101"
    logs = sorted(p.name for p in (ci.ws / "ci_logs").iterdir())
    assert f"{pfx}.101.out" in logs and f"{pfx}.101.err" in logs and "slurm_epilogue.slurm-101.out" in logs


@needs_rsync
def test_stage_keeps_the_mode_of_the_shared_com_nos_and_copies_the_chain_files(ci):
    """MJ (10/15/26): --no-implied-dirs keeps the mode of com/nos (shared with SECOFS and ATL); the chain files and json are copies, the rest links."""
    ds = ci.dataset()
    nos = ci.com / "nos"
    nos.mkdir(parents=True)
    nos.chmod(0o2770)
    before = nos.stat()
    assert ci.script("stage").returncode == 0
    after = nos.stat()
    assert after.st_mode == before.st_mode, oct(after.st_mode)
    inp = ds / "input" / "nos"
    for kind in ("hotstart", "restart"):
        f = Path("nos") / f"stofs_2d_glo.{PREV[0]}" / f"stofs_2d_glo.t{PREV[1]}z.{kind}"
        assert (ci.com / f).read_text() == f"chain {kind}" and not (ci.com / f).samefile(ds / "input" / f)
    assert (ci.com / "nos" / f"stofs_2d_glo.{PDY}" / CYC / "rerun" / "stofs_2d_glo_fcst.222.nc").samefile(inp / f"stofs_2d_glo.{PDY}" / CYC / "rerun" / "stofs_2d_glo_fcst.222.nc")


def test_stage_makes_an_existing_dataset_read_only_for_the_linked_kinds(ci):
    ds = ci.dataset()
    assert ci.script("stage").returncode == 0
    inp = ds / "input" / "nos"
    ro = [inp / f"stofs_2d_glo.{PDY}" / CYC / "rerun" / "stofs_2d_glo_ncst.221.nc", inp / "stofs_2d_glo" / "stofs_2d_glo_4064.tar", inp / "stofs_2d_glo" / "stofs_2d_glo_nod_equi"]
    assert os.geteuid() == 0 or not any(os.access(f, os.W_OK) for f in ro)
    assert (inp / "stofs_2d_glo" / "stofs_2d_glo_4064.tar.json").stat().st_mode & 0o200


def test_the_post_job_runs_on_the_prep_card_and_logs_under_its_name(ci):
    pfx = _job(ci, "post")
    assert pfx == "stofs_2d_glo_prep_00"
    r = _stage(ci, "post")
    assert r.returncode == 0 and "slurm/stofs_2d_glo/jnos_prep_00.sh" in (ci.stubs / "sbatch.calls").read_text()
    assert "jnos_post_00" not in (ci.stubs / "sbatch.calls").read_text()


@pytest.mark.parametrize("state,ok,summary", [("COMPLETED", False, None), ("FAILED", False, None), ("COMPLETED", True, "prep")])
def test_run_stage_fails_on_a_bad_log_state_or_stage_name(ci, state, ok, summary):
    _job(ci, "post", state=state, ok=ok, summary_stage=summary)
    r = _stage(ci, "post")
    assert r.returncode == 1 and "FAIL[post]" in r.stdout


def test_run_stage_gate_needs_the_run_name_in_the_summary(ci):
    pfx = _job(ci, "nowcast")
    (ci.rpt / f"{pfx}.101.out").write_text("STAGE_SUMMARY stage=nowcast ofs=secofs_ufs status=PASS runtime_s=1\n")
    assert _stage(ci, "nowcast").returncode == 1


def test_run_stage_keeps_the_work_directory_alone_and_never_calls_clean_job(ci):
    """The jobs run with KEEPDATA=NO and remove their own work directory; the CI must not delete anything else there. MJ (10/15/26)"""
    keep = [_touch(ci.ptmp / "tester" / "work" / "stofs_2d_glo" / "nc.101" / "x", "keep"), _touch(ci.ptmp / "tester" / "work" / "stofs_3d_atl_ufs" / "j.101" / "x", "keep")]
    _job(ci, "nowcast")
    assert _stage(ci, "nowcast").returncode == 0 and all(k.is_file() for k in keep)
    assert "KEEPDATA=NO" in (ci.stubs / "sbatch.calls").read_text()


@pytest.mark.parametrize("stage,level,secs", [(s, lv, int(re.sub(r"(\d+):(\d+):(\d+)", lambda m: str(int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])), WALL[(s, lv == "full")])) + 3600)
                                              for s in ("prep", "nowcast", "forecast", "post") for lv in ("cycle", "full")])
def test_run_stage_timeout_is_the_card_walltime_plus_margin_and_cancels(ci, stage, level, secs):
    # a stub date that jumps past the limit on its second +%s call; the first is t0. MJ (10/15/26)
    _job(ci, stage, state="RUNNING", ok=False)
    _stub(ci.bin / "date", f'#!/bin/bash\n[ "$1" = +%s ] || exec /bin/date "$@"\nn=$(cat "$STUB_DIR/d" 2>/dev/null || echo 0); echo $((n+1)) > "$STUB_DIR/d"\n[ $n -eq 0 ] && echo 1000 || echo {1000 + secs}\n')
    r = _stage(ci, stage, LEVEL=level)
    assert r.returncode == 1 and "rc=timeout" in r.stdout and (ci.stubs / "scancel.log").read_text().split() == ["101"]
    assert f"after {secs}s" in r.stdout


def test_the_walltimes_and_flags_are_the_launchers_and_fit_the_pipeline_timeout(ci):
    """card-env repeats the launcher's per-job sbatch flags and walltimes; a drift in either shows here. MJ (10/15/26)"""
    launcher = LAUNCHER.read_text()
    warm = re.search(r"PW=([0-9:]+); NSEG=ncst; NW=([0-9:]+)\n", launcher).groups()
    cold = re.search(r"1\)\s+PSEG=.*?PW=([0-9:]+);.*?NW=([0-9:]+) ;;", launcher).groups()
    fcst, post = (re.search(rf"W_{k}:-([0-9:]+)\}}", launcher).group(1) for k in ("FORECAST", "POST"))
    assert (WALL[("prep", False)], WALL[("nowcast", False)], WALL[("prep", True)], WALL[("nowcast", True)]) == (warm[0], warm[1], cold[0], cold[1])
    assert (WALL[("forecast", False)], WALL[("post", False)]) == (fcst, post)
    assert f'PFLAGS="{JOB["prep"][4]}"' in launcher
    for label, stage in (("nowcast", "nowcast"), ("forecast", "forecast"), ("post", "post")):   # MJ (10/15/26)
        assert re.search(rf'sub {label} "\$\{{\w+\}}" "\$\{{W_\w+:-\S+\}}" "{JOB[stage][4]}" ', launcher), label
    # the segment and stream lists of card-env are the launcher's. MJ (10/15/26)
    assert f'PSEG="{JOB["prep"][1]}"' in launcher and f'PSEG="adcprep ${{PSEG}}"' in launcher and f'NSEG="spinup ${{NSEG}}"' in launcher
    assert f"NSEG={JOB['nowcast'][1]};" in launcher and f'-N 52" {JOB["forecast"][1]} "${{STREAMS}}"' in launcher and f'"{JOB["post"][1]}"' in launcher
    assert "STREAMS:-tide surf" in launcher and JOB["nowcast"][3] == JOB["forecast"][3] == "tide surf"
    assert JOB["prep"][2] == "adcprep " + JOB["prep"][1] and JOB["nowcast"][2] == "spinup " + JOB["nowcast"][1]
    assert 'sub post "${PREP}"' in launcher
    totals = {lv: sum(int(h) * 3600 + int(m) * 60 + int(x) + 3600 for h, m, x in (w.split(":") for w in (WALL[(s, lv == "full")] for s in JOB))) for lv in ("cycle", "full")}
    pipeline = int(re.search(r"timeout\(time: (\d+), unit: 'HOURS'\)", JENKINSFILE.read_text()).group(1)) * 3600
    assert totals["full"] + 7200 <= pipeline, "the full level must leave the pipeline timeout room for bootstrap and staging"   # +1 h queue margin per job. MJ (10/15/26)
    cards = REPO / "slurm" / "stofs_2d_glo"
    for stage, (card, *_rest) in JOB.items():     # no walltime above the card's own limit. MJ (10/15/26)
        h, m, x = map(int, re.search(r"^#SBATCH\s+--time=(\d+):(\d+):(\d+)", (cards / f"jnos_{card}_00.sh").read_text(), re.M).groups())
        for cold in (False, True):
            hh, mm, xx = map(int, WALL[(stage, cold)].split(":"))
            assert hh * 3600 + mm * 60 + xx <= h * 3600 + m * 60 + x, (stage, cold)


def test_card_env_refuses_a_comma_in_a_path_and_an_unknown_stage(ci):
    r = ci.run(SCRIPT, "card-env", "prep", PACKAGEROOT=str(ci.tmp / "a,b"))
    assert r.returncode != 0
    assert ci.run(SCRIPT, "card-env", "bogus").returncode == 2
    assert ci.run(SCRIPT, "card-env").returncode != 0


def test_run_stage_never_submits_when_card_env_fails(ci):
    _job(ci, "prep")
    r = _stage(ci, "prep", LEVEL="weekly")
    assert r.returncode == 2 and not (ci.stubs / "sbatch.calls").exists()


def test_the_secofs_and_atl_paths_of_run_stage_still_see_no_2dglo_state(tmp_path):
    ci = Ci(tmp_path)
    (ci.home / "slurm").unlink()
    _stub(ci.bin / "sbatch", '#!/bin/bash\necho "$*" >> "$STUB_DIR/sbatch.calls"\necho "Submitted batch job 7"\n')
    _stub(ci.bin / "sacct", '#!/bin/bash\necho COMPLETED\n')
    card = _touch(ci.home / "slurm" / "secofs_ufs" / "jnos_prep_00.sh", "RPTDIR=" + str(ci.tmp / "rptdir") + "\n")
    _touch(ci.tmp / "rptdir" / "secofs_ufs_prep_00.7.out", "STAGE_SUMMARY stage=prep ofs=secofs_ufs status=PASS\n")
    r = _stage(ci, "prep", CI_OFS="secofs_ufs", ADCIRC_SEGMENT="x", STAGE_SBATCH="-N 9", STAGE_CARD="/nonexistent", ATL_EXPORTS="X=1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ci.stubs / "sbatch.calls").read_text().strip() == f"--export=ALL,PDY={PDY},CYC={CYC},COMROOT_STAGED={ci.rt}/comin_{PDY}{CYC},NOS_VENV={ci.venv},NOS_PTMP={ci.ptmp} {card}"


def _load_compare():
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("compare_2dglo", SCRIPTS / "compare_2dglo.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = keep
    return mod


cmp2d = _load_compare()


def _station_file(path: Path, zeta, x=None, masked=(), t0="2026-10-12 06:00:00", dt=3600.0, with_vel=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    zeta = np.array(zeta, dtype="f8")
    nt, ns = zeta.shape
    with nc.Dataset(path, "w") as d:
        d.createDimension("time", None)
        d.createDimension("station", ns)
        d.createDimension("namelen", 6)
        t = d.createVariable("time", "f8", ("time",))
        t.units = f"seconds since {t0}"
        t[:] = np.arange(nt) * dt
        xv = d.createVariable("x", "f8", ("station",))
        xv[:] = np.arange(ns) * 1.5 if x is None else x
        z = d.createVariable("zeta", "f8", ("time", "station"), fill_value=-99999.0)
        z[:] = np.ma.masked_array(zeta, mask=np.zeros_like(zeta, dtype=bool))
        for (i, j) in masked:
            z[i, j] = np.ma.masked
        if with_vel:
            u = d.createVariable("u-vel", "f8", ("time", "station"), fill_value=-99999.0)
            u[:] = zeta * 0.5
        sn = d.createVariable("station_name", "S1", ("station", "namelen"))
        sn[:] = nc.stringtochar(np.array([("sta%d" % i) for i in range(ns)], dtype="S6"), encoding="ascii")
    return path


def _pair(tmp: Path, ref_zeta, out_zeta, **kw):
    ref = _station_file(tmp / "ref" / "f.nc", ref_zeta, **kw)
    out = _station_file(tmp / "out" / "f.nc", out_zeta, **kw)
    return ref, out


Z = np.linspace(-1, 1, 12).reshape(3, 4)


def test_compare_identical_files_are_bitwise(tmp_path):
    ref, out = _pair(tmp_path, Z, Z, with_vel=True)
    ok, text = cmp2d.compare_file(ref, out, 1e-3)
    assert ok and text == "bitwise identical (5 variables)"


def test_compare_small_difference_passes_with_the_stated_tolerance_and_big_one_fails(tmp_path):
    ref, out = _pair(tmp_path, Z, Z + 4e-4)
    ok, text = cmp2d.compare_file(ref, out, 1e-3)
    assert ok and "max |diff| 0.0004 (zeta) <= tol 0.001" in text
    ref, out = _pair(tmp_path / "b", Z, Z + 2e-3)
    ok, text = cmp2d.compare_file(ref, out, 1e-3)
    assert not ok and "zeta: max |diff| 0.002 > tol 0.001" in text


def test_compare_fails_on_missing_masks_shapes_and_static_variables(tmp_path):
    ref = _station_file(tmp_path / "ref.nc", Z, masked=[(0, 1)])
    assert cmp2d.compare_file(ref, tmp_path / "nope.nc", 1e-3) == (False, "missing in this run")
    ok, text = cmp2d.compare_file(ref, _station_file(tmp_path / "o1.nc", Z), 1e-3)
    assert not ok and "mask differs at 1 points" in text
    ok, text = cmp2d.compare_file(ref, _station_file(tmp_path / "o2.nc", Z[:2]), 1e-3)
    assert not ok and "shape" in text
    ref = _station_file(tmp_path / "r3.nc", Z)
    ok, text = cmp2d.compare_file(ref, _station_file(tmp_path / "o3.nc", Z, x=np.arange(4) * 1.5 + 1e-9), 1e-3)
    assert not ok and "x: differs but is not a time-dependent variable" in text
    ok, text = cmp2d.compare_file(ref, _station_file(tmp_path / "o4.nc", Z, dt=1800.0), 1e-3)
    assert not ok and text.startswith("time: differs")
    ok, text = cmp2d.compare_file(ref, _station_file(tmp_path / "o5.nc", Z, with_vel=True), 1e-3)
    assert not ok and "variables differ" in text
    (tmp_path / "bad.nc").write_text("not netcdf")
    ok, text = cmp2d.compare_file(ref, tmp_path / "bad.nc", 1e-3)
    assert not ok and text.startswith("unreadable")


def test_compare_fails_on_a_nan_in_only_one_file(tmp_path):
    ref = _station_file(tmp_path / "ref.nc", Z)
    ok, text = cmp2d.compare_file(ref, _station_file(tmp_path / "all.nc", np.full(Z.shape, np.nan)), 1e-3)
    assert not ok and "zeta: NaN in only one of the two files at 12 points" in text
    one = Z.copy()
    one[1, 2] = np.nan
    ok, text = cmp2d.compare_file(ref, _station_file(tmp_path / "one.nc", one), 1e-3)
    assert not ok and "NaN in only one of the two files at 1 points" in text
    ok, text = cmp2d.compare_file(_station_file(tmp_path / "rn.nc", one), _station_file(tmp_path / "on.nc", one), 1e-3)
    assert ok and text.startswith("bitwise")
    ok, text = cmp2d.compare_file(_station_file(tmp_path / "rd.nc", one), _station_file(tmp_path / "od.nc", np.where(np.isnan(one), np.nan, one + 2e-3)), 1e-3)
    assert not ok and "zeta: max |diff| 0.002 > tol 0.001" in text


def _comroot(tmp: Path, name: str, zeta, skip=()):
    day = tmp / name / "nos" / f"stofs_2d_glo.{PDY}"
    for s in ("tide", "surf"):
        if f"{s}.61" not in skip:
            _station_file(day / CYC / "rerun" / f"stofs_2d_glo_{s}.61.nc", zeta)
    for p in ("htp", "cwl.noanomaly", "swl"):
        if p not in skip:
            _station_file(day / f"stofs_2d_glo.t{CYC}z.points.{p}.nc", zeta)
    return tmp / name


def _regress(tmp, level, **kw):
    argv = ["regress", "--ref", str(tmp / "ref"), "--out", str(tmp / "out"), "--pdy", PDY, "--cyc", CYC, "--level", level]
    for k, v in kw.items():
        argv += [f"--{k}", str(v)]
    return cmp2d.main(argv)


def test_regress_smoke_checks_the_two_ncst_files_and_cycle_adds_the_points_files(tmp_path, capsys):
    _comroot(tmp_path, "ref", Z)
    _comroot(tmp_path, "out", Z, skip=("htp",))
    assert _regress(tmp_path, "smoke") == 0
    out = capsys.readouterr().out
    assert "2 files, 2 bitwise, 0 within tolerance, 0 failed" in out and "0.001" in out
    assert _regress(tmp_path, "cycle") == 1
    out = capsys.readouterr().out
    assert "FAIL  stofs_2d_glo.t06z.points.htp.nc: missing in this run" in out
    assert "5 files, 4 bitwise, 0 within tolerance, 1 failed" in out


def test_regress_reports_per_file_results_and_the_tolerance_argument(tmp_path, capsys):
    _comroot(tmp_path, "ref", Z)
    _comroot(tmp_path, "out", Z + 5e-4)
    assert _regress(tmp_path, "cycle") == 0
    out = capsys.readouterr().out
    assert out.count("PASS  ") == 5 and "5 within tolerance" in out
    assert _regress(tmp_path, "cycle", tol=1e-4) == 1
    assert "FAIL  " in capsys.readouterr().out


def _ops_setup(tmp: Path, mine, ops_zeta, **kw):
    _comroot(tmp, "out", mine)
    ops = tmp / "ops"
    for p in ("htp", "cwl.noanomaly", "swl"):
        _station_file(ops / f"stofs_2d_glo.t{CYC}z.points.{p}.nc", ops_zeta, **kw)
    return ["ops", "--out", str(tmp / "out"), "--ops-dir", str(ops), "--pdy", PDY, "--cyc", CYC]


def test_ops_comparison_prints_the_cmp_points_summary_and_warns_without_failing(tmp_path, capsys):
    argv = _ops_setup(tmp_path, Z + 0.05, Z)
    assert cmp2d.main(argv) == 0
    out = capsys.readouterr().out
    assert out.count("per-station max |dWL|: median 50.00 mm; within 1 mm 0, within 1 cm 0, over 10 cm 0") == 3
    assert "3 common times (3 this run, 3 ops), 4 stations compared, 0 skipped" in out and "WARN" not in out
    argv = _ops_setup(tmp_path / "far", Z + 0.8, Z)
    assert cmp2d.main(argv) == 0
    assert capsys.readouterr().out.count("WARN median 800.0 mm is above the 500 mm report threshold (not a failure)") == 3
    assert cmp2d.main([*argv, "--warn-mm", "1000"]) == 0 and "WARN" not in capsys.readouterr().out


def test_ops_comparison_skips_absent_ops_files_but_fails_on_a_missing_own_product(tmp_path, capsys):
    argv = _ops_setup(tmp_path, Z, Z)
    (tmp_path / "ops" / f"stofs_2d_glo.t{CYC}z.points.swl.nc").unlink()
    assert cmp2d.main(argv) == 0
    assert "SKIP  stofs_2d_glo.t06z.points.swl.nc: no ops product" in capsys.readouterr().out
    shutil.rmtree(tmp_path / "ops")
    assert cmp2d.main(argv) == 0 and capsys.readouterr().out.count("SKIP") == 3
    (tmp_path / "out" / "nos" / f"stofs_2d_glo.{PDY}" / f"stofs_2d_glo.t{CYC}z.points.htp.nc").unlink()
    assert cmp2d.main(argv) == 1
    assert "FAIL  stofs_2d_glo.t06z.points.htp.nc: missing in this run" in capsys.readouterr().out


def test_ops_comparison_handles_odd_ops_stations_and_mismatched_files(tmp_path, capsys):
    zops = Z.copy()
    zops[:, 2] = 25.0                       # ops itself beyond 20 m: not a usable station. MJ (10/13/26)
    argv = _ops_setup(tmp_path, Z, zops)
    assert cmp2d.main(argv) == 0 and "3 stations compared, 1 skipped" in capsys.readouterr().out
    argv = _ops_setup(tmp_path / "n", Z, Z[:, :3])
    assert cmp2d.main(argv) == 0 and "WARN station counts differ: 4 (this run) vs 3 (ops)" in capsys.readouterr().out
    argv = _ops_setup(tmp_path / "t", Z, Z, t0="2026-10-20 00:00:00")
    assert cmp2d.main(argv) == 0 and "WARN no common times" in capsys.readouterr().out


def _verify_tree(ci: Ci, ours, ref=None, ops=None, skip=()):
    ref = Z if ref is None else ref
    shutil.rmtree(ci.com, ignore_errors=True)
    _comroot(ci.ds, "ref", ref)
    for p in ("htp", "cwl.noanomaly", "swl"):
        _station_file(ci.ds / "ops" / f"stofs_2d_glo.t{CYC}z.points.{p}.nc", Z if ops is None else ops)
    _touch(ci.ds / ".seeded_ok", "")
    day = ci.com / "nos" / f"stofs_2d_glo.{PDY}"
    for s in ("tide", "surf"):
        if f"{s}.61" not in skip:
            _station_file(day / CYC / "rerun" / f"stofs_2d_glo_{s}.61.nc", ours)
    for p in ("htp", "cwl", "cwl.noanomaly", "swl"):
        if p not in skip:
            _station_file(day / f"stofs_2d_glo.t{CYC}z.points.{p}.nc", ours)


def test_verify_smoke_passes_on_a_reproduced_run_and_writes_the_report(ci):
    _verify_tree(ci, Z)
    r = ci.script("verify", LEVEL="smoke")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS[verify]: LEVEL=smoke" in r.stdout and "2 files, 2 bitwise" in r.stdout and "points" not in r.stdout.split("regress:")[1]
    assert "ops:" not in r.stdout
    assert "2 bitwise" in (ci.ws / "ci_logs" / "compare_2dglo.txt").read_text()


def test_verify_fails_when_the_run_drifts_from_the_reference(ci):
    _verify_tree(ci, Z + 0.01)
    r = ci.script("verify", LEVEL="smoke")
    assert r.returncode == 1 and "FAIL  " in r.stdout and "FAIL[verify]: LEVEL=smoke" in r.stdout
    assert ci.script("verify", LEVEL="smoke", CMP_TOL="0.1").returncode == 0


def test_verify_cycle_adds_points_files_and_reports_the_ops_comparison(ci):
    _verify_tree(ci, Z)
    r = ci.script("verify", LEVEL="cycle")
    assert r.returncode == 0, r.stdout
    assert "5 files, 5 bitwise" in r.stdout and "ops: 2026101206: report only" in r.stdout
    _verify_tree(ci, Z, ops=Z + 2.0)               # far from ops: reported, not a failure. MJ (10/13/26)
    r = ci.script("verify", LEVEL="cycle")
    assert r.returncode == 0 and "WARN median" in r.stdout


def test_verify_full_regresses_against_the_cold_seed_reference_and_reports_the_ops_comparison(ci):
    _verify_tree(ci, Z)
    r = ci.script("verify", LEVEL="full")
    assert r.returncode == 0, r.stdout
    assert "regress: LEVEL=cycle" in r.stdout and "5 files, 5 bitwise" in r.stdout and "ops: 2026101206: report only" in r.stdout
    _verify_tree(ci, Z + 0.3)                      # drifts from the reference and from ops: the reference decides
    r = ci.script("verify", LEVEL="full")
    assert r.returncode == 1 and "FAIL  " in r.stdout and "300.00 mm" in r.stdout and "FAIL[verify]: LEVEL=full" in r.stdout
    _verify_tree(ci, Z, skip=("swl",))
    r = ci.script("verify", LEVEL="full")
    assert r.returncode == 1 and "points.swl.nc: missing in this run" in r.stdout


def test_verify_needs_a_reference_in_frozen_mode_but_not_in_live_mode(ci):
    _verify_tree(ci, Z)
    shutil.rmtree(ci.ds / "ref")
    r = ci.script("verify", LEVEL="smoke")
    assert r.returncode == 1 and "has no reference outputs" in r.stdout
    r = ci.script("verify", LEVEL="smoke", DATA_MODE="live")
    assert r.returncode == 0 and "regression comparison skipped" in r.stdout
    # live ops products come from the staging tool's download area. MJ (10/13/26)
    ops = ci.ptmp / "tester" / "ops_s3" / f"{PDY}{CYC}" / "products"
    for p in ("htp", "cwl.noanomaly", "swl"):
        _station_file(ops / f"stofs_2d_glo.t{CYC}z.points.{p}.nc", Z)
    r = ci.script("verify", LEVEL="cycle", DATA_MODE="live")
    assert r.returncode == 0 and "SKIP" not in r.stdout and "4 stations compared" in r.stdout


def _finished_run(root: Path, state=True):
    day = root / "nos" / f"stofs_2d_glo.{PDY}"
    for seg in ("ncst", "fcst"):
        for n in (221, 222, 225):
            _touch(day / CYC / "rerun" / f"stofs_2d_glo_{seg}.{n}.nc", f"forcing {seg} {n}")
    if state:
        for f in ("stofs_2d_glo_nod_equi", "stofs_2d_glo_4064.tar", "stofs_2d_glo_4064.tar.json"):
            _touch(root / "nos" / "stofs_2d_glo" / f, f)
        for kind in ("hotstart", "restart"):
            _touch(root / "nos" / f"stofs_2d_glo.{PREV[0]}" / f"stofs_2d_glo.t{PREV[1]}z.{kind}", kind)
    for s in ("tide", "surf"):
        for k in (61, 63):
            _touch(day / CYC / "rerun" / f"stofs_2d_glo_{s}.{k}.nc", f"{s} {k}")
    for p in ("htp", "cwl", "cwl.noanomaly", "cwl.vel", "swl"):
        _touch(day / f"stofs_2d_glo.t{CYC}z.points.{p}.nc", p)
    _touch(day / f"stofs_2d_glo.t{CYC}z.hotstart", "must not be copied")
    return root


def _seed_env(ci: Ci, run: Path, ops: bool = True):
    opsdir = ci.tmp / "opsdl"
    if ops:
        for p in ("htp", "cwl.noanomaly", "swl"):
            _touch(opsdir / f"stofs_2d_glo.t{CYC}z.points.{p}.nc", f"ops {p}")
    return dict(COMROOT_2DGLO=str(run), SEED_RT=str(ci.tmp / "seed_rt"), OPS_DIR=str(opsdir))


def test_seed_builds_the_dataset_the_stage_reads(ci):
    run = _finished_run(ci.tmp / "run")
    env = _seed_env(ci, run)
    r = ci.run(SCRIPT, "seed", PDY, CYC, **env)
    assert r.returncode == 0, r.stderr + r.stdout
    dest = ci.tmp / "seed_rt" / "stofs_2d_glo" / f"{PDY}{CYC}"
    assert (dest / ".seeded_ok").is_file() and "seed PASS" in r.stdout and "chmod o+x" in r.stdout
    inputs = _tree(dest / "input")
    assert len(inputs) == 3 + 2 + 6 and not any("points" in f or ".61." in f for f in inputs)
    refs = _tree(dest / "ref")
    assert sorted(Path(f).name for f in refs) == sorted(
        [f"stofs_2d_glo_{s}.61.nc" for s in ("tide", "surf")] + [f"stofs_2d_glo.t{CYC}z.points.{p}.nc" for p in ("htp", "cwl", "cwl.noanomaly", "cwl.vel", "swl")])
    assert sorted(Path(f).name for f in _tree(dest / "ops")) == [f"stofs_2d_glo.t{CYC}z.points.{p}.nc" for p in ("cwl.noanomaly", "htp", "swl")]
    # the seeded directory is what Bootstrap copies into the RT root and Stage Data then reads. MJ (10/13/26)
    shutil.copytree(dest, ci.ds)
    for level, n in (("smoke", 5 + 6), ("cycle", 5 + 6), ("full", 6)):
        r = ci.script("stage", LEVEL=level)
        assert r.returncode == 0, (level, r.stdout, r.stderr)
        assert len(_tree(ci.com)) == n, level


def test_seed_marks_the_dataset_complete_readably_under_a_restrictive_umask(ci):
    run = _finished_run(ci.tmp / "run")
    wrap = _stub(ci.tmp / "umask077.sh", '#!/bin/bash\numask 077\nexec bash "$@"\n')
    r = ci.run(wrap, str(SCRIPT), "seed", PDY, CYC, **_seed_env(ci, run))
    assert r.returncode == 0, r.stderr + r.stdout
    dest = ci.tmp / "seed_rt" / "stofs_2d_glo" / f"{PDY}{CYC}"
    assert (dest / ".seeded_ok").stat().st_mode & 0o004 and (dest / "input").stat().st_mode & 0o005 == 0o005


def test_seed_cold_dataset_leaves_out_the_cold_start_products(ci):
    run = _finished_run(ci.tmp / "run")
    r = ci.run(SCRIPT, "seed", PDY, CYC, "cold", **_seed_env(ci, run))
    assert r.returncode == 0, r.stderr
    dest = ci.tmp / "seed_rt" / "stofs_2d_glo" / f"{PDY}{CYC}"
    assert len(_tree(dest / "input")) == 6 and "ges" not in " ".join(_tree(dest / "input"))
    shutil.copytree(dest, ci.ds)
    assert ci.script("stage", LEVEL="full").returncode == 0
    r = ci.script("stage", LEVEL="smoke")
    assert r.returncode == 1 and "cold dataset" in r.stdout


def test_seed_refuses_an_unfinished_run_and_an_existing_dataset(ci):
    run = _finished_run(ci.tmp / "run", state=False)
    env = _seed_env(ci, run)
    r = ci.run(SCRIPT, "seed", PDY, CYC, **env)
    assert r.returncode == 1 and r.stderr.count("MISSING") == 5 and not (ci.tmp / "seed_rt").exists()
    assert ci.run(SCRIPT, "seed", PDY, CYC, "cold", **env).returncode == 0
    r = ci.run(SCRIPT, "seed", PDY, CYC, "cold", **env)
    assert r.returncode == 1 and "FORCE=1" in r.stderr
    assert ci.run(SCRIPT, "seed", PDY, CYC, "cold", FORCE="1", **env).returncode == 0
    (run / "nos" / f"stofs_2d_glo.{PDY}" / f"stofs_2d_glo.t{CYC}z.points.swl.nc").unlink()
    assert ci.run(SCRIPT, "seed", PDY, CYC, "cold", FORCE="1", **env).returncode == 1


def test_seed_makes_forcing_tar_and_nod_equi_read_only_and_leaves_the_chain_files_and_json_writable(ci):
    run = _finished_run(ci.tmp / "run")
    assert ci.run(SCRIPT, "seed", PDY, CYC, **_seed_env(ci, run)).returncode == 0
    inp = ci.tmp / "seed_rt" / "stofs_2d_glo" / f"{PDY}{CYC}" / "input"
    for f in _tree(inp):
        ro = bool(re.search(r"\.2[0-9][0-9]\.nc$|_4064\.tar$|_nod_equi$", f))
        assert os.access(inp / f, os.W_OK) != ro or os.geteuid() == 0, f
    assert not os.access(inp / "nos" / f"stofs_2d_glo.{PDY}" / CYC / "rerun" / "stofs_2d_glo_fcst.225.nc", os.W_OK) or os.geteuid() == 0
    assert (inp / "nos" / "stofs_2d_glo" / "stofs_2d_glo_4064.tar.json").stat().st_mode & 0o200
    assert (inp / "nos" / f"stofs_2d_glo.{PREV[0]}" / f"stofs_2d_glo.t{PREV[1]}z.hotstart").stat().st_mode & 0o200


def test_seed_without_comroot_reads_the_shared_com(ci):
    r = ci.run(SCRIPT, "seed", PDY, CYC, SEED_RT=str(ci.tmp / "seed_rt"))
    missing = [l for l in r.stderr.splitlines() if l.startswith("MISSING:")]
    assert r.returncode == 1 and missing and not (ci.tmp / "seed_rt").exists()
    assert all(l.startswith(f"MISSING: {ci.ptmp}/tester/com/") for l in missing), missing


def test_seed_warns_about_missing_ops_products_and_validates_arguments(ci):
    run = _finished_run(ci.tmp / "run")
    r = ci.run(SCRIPT, "seed", PDY, CYC, "cold", **_seed_env(ci, run, ops=False))
    assert r.returncode == 0 and r.stderr.count("WARN: no ops product") == 3
    assert ci.run(SCRIPT, "seed", PDY, CYC, "warm", **_seed_env(ci, run)).returncode == 2
    assert ci.run(SCRIPT, "seed", PDY).returncode != 0
    assert ci.run(SCRIPT, "seed", "2026", CYC).returncode == 2



def _seed_src(ci: Ci, system: str, also_secofs: bool = False):
    src = ci.tmp / "seed" / "nos-workflow"
    _touch(src / "fix" / system / "grid", "grid")
    if also_secofs:       # a SEED_SRC clone holds both systems; 2D-Global bootstrap must not copy the SECOFS side. MJ (10/13/26)
        _touch(src / "fix" / "secofs_ufs" / "grid", "seed secofs grid")
        _touch(src / "exec" / "fv3_coastalS.exe", "seed secofs exe")
        _touch(src / "exec" / "other_tool", "seed other")
    if system == "stofs_2d_glo":
        _stub(src / "exec" / "stofs_2d_glo_tide_fac")
        for exe in ("padcirc", "adcprep"):
            _stub(ci.tmp / "seed" / "adcirc_v56.1.0_exec" / exe)
    else:
        _stub(src / "exec" / "fv3_coastalS.exe")
        _stub(src / "exec" / "schism_combine_hotstart7.exe")
    return src


def _fake_venv(ci: Ci):
    _stub(ci.venv / "bin" / "python")          # the payload gate (import scipy, nos_utils) passes, so no pip runs. MJ (10/13/26)


@needs_rsync
def test_bootstrap_seeds_the_2dglo_tree_once(ci):
    src = _seed_src(ci, "stofs_2d_glo")
    _fake_venv(ci)
    seed_rt = ci.tmp / "seed_rt"
    shutil.copytree(_seeded_dataset(ci), seed_rt / "stofs_2d_glo" / f"{PDY}{CYC}")
    env = dict(SEED_SRC=str(src), SEED_RT=str(seed_rt), DATA_MODE="frozen")
    r = ci.run(SCRIPTS / "bootstrap.sh", **env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ci.home / "fix" / "stofs_2d_glo" / ".seeded_ok").is_file()
    assert (ci.home / "exec" / ".seeded_ok.stofs_2d_glo").is_file() and not (ci.home / "exec" / ".seeded_ok").exists()
    assert (ci.pk / "adcirc_v56.1.0_exec" / "padcirc").is_file() and (ci.pk / "adcirc_v56.1.0_exec" / ".seeded_ok").is_file()
    assert (ci.rt / "stofs_2d_glo" / f"{PDY}{CYC}" / ".seeded_ok").is_file() and "bootstrap PASS" in r.stdout
    r = ci.run(SCRIPTS / "bootstrap.sh", **env)
    assert r.returncode == 0 and "skipping the ADCIRC seed" in r.stdout and "frozen dataset already present" in r.stdout


@needs_rsync
def test_bootstrap_copy_makes_the_same_files_read_only_and_a_recopy_over_them_works(ci):
    src = _seed_src(ci, "stofs_2d_glo")
    _fake_venv(ci)
    seed_rt = ci.tmp / "seed_rt"
    shutil.copytree(_seeded_dataset(ci), seed_rt / "stofs_2d_glo" / f"{PDY}{CYC}")
    env = dict(SEED_SRC=str(src), SEED_RT=str(seed_rt), DATA_MODE="frozen")
    assert ci.run(SCRIPTS / "bootstrap.sh", **env).returncode == 0
    inp = ci.ds / "input" / "nos"
    assert not os.access(inp / f"stofs_2d_glo.{PDY}" / CYC / "rerun" / "stofs_2d_glo_ncst.221.nc", os.W_OK) or os.geteuid() == 0
    assert (inp / "stofs_2d_glo" / "stofs_2d_glo_4064.tar.json").stat().st_mode & 0o200
    assert (inp / f"stofs_2d_glo.{PREV[0]}" / f"stofs_2d_glo.t{PREV[1]}z.hotstart").stat().st_mode & 0o200
    shutil.rmtree(ci.ds / ".seeded_ok", ignore_errors=True) if (ci.ds / ".seeded_ok").is_dir() else (ci.ds / ".seeded_ok").unlink()
    assert ci.run(SCRIPTS / "bootstrap.sh", **env).returncode == 0 and (ci.ds / ".seeded_ok").is_file()


def _seeded_dataset(ci: Ci) -> Path:
    keep = ci.ds
    ci.ds = ci.tmp / "built_ds"
    ci.dataset(sentinel=False)
    built, ci.ds = ci.ds, keep
    _touch(built / ".seeded_ok", "")
    return built


@needs_rsync
def test_bootstrap_2dglo_copies_only_its_own_fix_and_executable(ci):
    src = _seed_src(ci, "stofs_2d_glo", also_secofs=True)
    _fake_venv(ci)
    _touch(ci.home / "fix" / "secofs_ufs" / "grid", "shared secofs grid")
    _stub(ci.home / "exec" / "fv3_coastalS.exe", "#!/bin/bash\n# shared secofs exe\n")
    seed_rt = ci.tmp / "seed_rt"
    shutil.copytree(_seeded_dataset(ci), seed_rt / "stofs_2d_glo" / f"{PDY}{CYC}")
    r = ci.run(SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt), DATA_MODE="frozen")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ci.home / "fix" / "stofs_2d_glo" / "grid").read_text() == "grid" and (ci.home / "exec" / "stofs_2d_glo_tide_fac").is_file()
    assert (ci.home / "fix" / "secofs_ufs" / "grid").read_text() == "shared secofs grid"
    assert "shared secofs exe" in (ci.home / "exec" / "fv3_coastalS.exe").read_text() and not (ci.home / "exec" / "other_tool").exists()


@needs_rsync
def test_bootstrap_2dglo_names_a_seed_tree_without_its_fix_directory(ci):
    src = _seed_src(ci, "secofs_ufs")
    _stub(src / "exec" / "stofs_2d_glo_tide_fac")
    _fake_venv(ci)
    r = ci.run(SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(ci.tmp / "none"), DATA_MODE="live")
    assert r.returncode == 1 and f"{src}/fix/stofs_2d_glo not readable" in r.stdout and "fetch_stofs_2d_glo_fix.sh" in r.stdout
    assert not (ci.home / "fix").exists() and not (ci.home / "exec" / "fv3_coastalS.exe").exists()


@needs_rsync
def test_bootstrap_names_the_missing_adcirc_build_and_dataset(ci):
    src = _seed_src(ci, "stofs_2d_glo")
    shutil.rmtree(ci.tmp / "seed" / "adcirc_v56.1.0_exec")
    _fake_venv(ci)
    r = ci.run(SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(ci.tmp / "none"), DATA_MODE="live")
    assert r.returncode == 1 and "adcirc_v56.1.0_exec not readable" in r.stdout and "SEED_ADCIRC" in r.stdout
    _stub(ci.tmp / "seed" / "padcirc")
    _stub(ci.tmp / "seed" / "adcprep")
    r = ci.run(SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_ADCIRC=str(ci.tmp / "seed"), SEED_RT=str(ci.tmp / "none"), DATA_MODE="frozen")
    assert r.returncode == 1 and "none/stofs_2d_glo/2026101206 not readable" in r.stdout
    assert "stofs_2d_glo.sh seed 20261012 06" in r.stdout


@needs_rsync
def test_bootstrap_secofs_seeding_is_unchanged(ci):
    src = _seed_src(ci, "secofs_ufs")
    _fake_venv(ci)
    seed_rt = ci.tmp / "seed_rt"
    _touch(seed_rt / f"comin_{PDY}{CYC}" / "data", "d")
    r = ci.run(SCRIPTS / "bootstrap.sh", CI_OFS=None, SEED_SRC=str(src), SEED_RT=str(seed_rt), DATA_MODE="frozen")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ci.home / "exec" / ".seeded_ok").is_file() and not list((ci.home / "exec").glob(".seeded_ok.*"))
    assert (ci.home / "fix" / "secofs_ufs" / ".seeded_ok").is_file()
    assert (ci.rt / f"comin_{PDY}{CYC}" / ".seeded_ok").is_file() and not (ci.pk / "adcirc_v56.1.0_exec").exists()
    assert "seeding frozen dataset (~80GB)" in r.stdout
    r = ci.run(SCRIPTS / "bootstrap.sh", CI_OFS=None, SEED_SRC=str(src), SEED_RT=str(seed_rt), DATA_MODE="frozen")
    assert f"bootstrap: {ci.home}/exec/.seeded_ok already present, skipping exec/ seed" in r.stdout


def _workspace(ci: Ci):
    _touch(ci.ws / "tools" / "t.sh", "t")
    _touch(ci.ws / ".git" / "HEAD", "ref")
    _touch(ci.ws / "ush" / "python" / "nos-utils" / ".git", "gitdir: ../../../.git/modules/x")
    _touch(ci.ws / "ush" / "python" / "nos-utils" / "nos_utils" / "forcing" / "adcirc_met.py", "# nu")


@needs_rsync
def test_deploy_copies_nos_utils_for_2dglo_only(ci):
    _workspace(ci)
    r = ci.run(SCRIPTS / "deploy.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    nu = ci.home / "ush" / "python" / "nos-utils"
    assert (nu / "nos_utils" / "forcing" / "adcirc_met.py").is_file() and not (nu / ".git").exists()
    assert (ci.home / "tools" / "t.sh").is_file() and not (ci.home / ".git").exists()
    # a second deploy refreshes it and still leaves fix/ and exec/ alone. MJ (10/13/26)
    _touch(ci.home / "exec" / "keep", "k")
    _touch(nu / "stale.py", "s")
    assert ci.run(SCRIPTS / "deploy.sh").returncode == 0
    assert (ci.home / "exec" / "keep").is_file() and not (nu / "stale.py").exists()


@needs_rsync
def test_deploy_for_secofs_does_not_create_the_nos_utils_copy_and_removes_a_2dglo_one(ci):
    _workspace(ci)
    assert ci.run(SCRIPTS / "deploy.sh", CI_OFS=None).returncode == 0
    assert (ci.home / "tools" / "t.sh").is_file() and not (ci.home / "ush" / "python" / "nos-utils").exists()
    # the exnos scripts put this directory first on PYTHONPATH, so a 2D-Global copy must not outlive the next SECOFS deploy. MJ (10/13/26)
    assert ci.run(SCRIPTS / "deploy.sh").returncode == 0
    assert (ci.home / "ush" / "python" / "nos-utils" / "nos_utils" / "forcing" / "adcirc_met.py").is_file()
    assert ci.run(SCRIPTS / "deploy.sh", CI_OFS=None).returncode == 0
    assert not (ci.home / "ush" / "python" / "nos-utils").exists() and (ci.home / "tools" / "t.sh").is_file()


@needs_rsync
def test_deploy_for_2dglo_needs_the_submodule_checkout(ci):
    _workspace(ci)
    (ci.ws / "ush" / "python" / "nos-utils" / "nos_utils" / "forcing" / "adcirc_met.py").unlink()
    r = ci.run(SCRIPTS / "deploy.sh")
    assert r.returncode == 1 and "is empty" in r.stdout


def _env_stubs(ci: Ci, tools=("python3", "wgrib2", "ncdiff", "ncrcat", "ncks", "sbatch", "sacct")):
    for t in tools:
        _stub(ci.bin / t)


def test_env_check_for_2dglo_needs_tide_fac_adcirc_nco_and_slurm(ci):
    _env_stubs(ci)
    _stub(ci.home / "exec" / "stofs_2d_glo_tide_fac")
    _touch(ci.home / "ush" / "python" / "nos-utils" / "nos_utils" / "forcing" / "adcirc_met.py", "")
    r = ci.run(SCRIPTS / "env_check.sh")
    assert r.returncode == 1 and "padcirc not found" in r.stdout
    for exe in ("padcirc", "adcprep"):
        _stub(ci.pk / "adcirc_v56.1.0_exec" / exe)
    r = ci.run(SCRIPTS / "env_check.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: ncdiff" in r.stdout and "env_check PASS" in r.stdout
    (ci.bin / "ncrcat").unlink()
    r = ci.run(SCRIPTS / "env_check.sh", PATH=f"{ci.bin}:/usr/bin:/bin")
    assert r.returncode == 1 and "ncrcat not on PATH" in r.stdout


def test_env_check_for_secofs_still_checks_the_schism_executables(ci):
    _env_stubs(ci)
    _stub(ci.home / "exec" / "fv3_coastalS.exe")
    r = ci.run(SCRIPTS / "env_check.sh", CI_OFS=None)
    assert r.returncode == 1 and "schism_combine_hotstart7.exe not found" in r.stdout and "sorc/build_hercules.sh" in r.stdout
    _stub(ci.home / "exec" / "schism_combine_hotstart7.exe")
    r = ci.run(SCRIPTS / "env_check.sh", CI_OFS=None)
    assert r.returncode == 0 and "padcirc" not in r.stdout
