"""Manual STOFS-2D-Global support in the Hercules Jenkins pipeline (.cicd), against stub sbatch/sacct/module/rsync inputs. Offline. MJ (10/13/26)"""
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
        self.com = self.ptmp / "tester" / "com_2dglo_ci"
        self.ds = self.rt / "stofs_2d_glo" / f"{PDY}{CYC}"
        for d in (self.home, self.ptmp, self.rt, self.ws, self.bin, self.stubs):
            d.mkdir(parents=True, exist_ok=True)
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


def _stage_conditions():
    text = JENKINSFILE.read_text()
    return dict(re.findall(r"stage\('([^']+)'\) \{\n\s+when \{ (.+?) \}\n\s+steps", text))


def test_secofs_stages_run_only_for_secofs_and_2dglo_stages_only_for_2dglo():
    cond = _stage_conditions()
    for name in ("Prep", "Nowcast", "Forecast", "Post", "Verify"):
        assert "env.CI_OFS == 'secofs_ufs'" in cond[name] and "env.RUN_CYCLE == 'true'" in cond[name], name
    for name in ("Run 2D-GLO", "Verify 2D-GLO"):
        assert "env.CI_OFS == 'stofs_2d_glo'" in cond[name] and "env.RUN_CYCLE == 'true'" in cond[name], name
    # the shared stages (Bootstrap, Deploy, Environment Check, Stage Data) run for both systems. MJ (10/13/26)
    for name in ("Bootstrap", "Deploy", "Environment Check", "Stage Data"):
        assert cond[name] == "environment name: 'RUN_CYCLE', value: 'true'", name


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


def _hms(text: str) -> int:
    h, m, s = (int(x) for x in text.split(":"))
    return h * 3600 + m * 60 + s


def test_poll_limits_cover_the_critical_path_of_each_level():
    """A limit below the chain's own walltimes would only ever mislabel a healthy run (same rule as run_stage.sh's TIMEOUT_S). MJ (10/13/26)"""
    launcher = LAUNCHER.read_text()
    warm = [_hms(x) for x in re.search(r"PW=([0-9:]+); NSEG=ncst; NW=([0-9:]+)\n", launcher).groups()]
    cold = [_hms(x) for x in re.search(r"1\)\s+PSEG=.*?PW=([0-9:]+);.*?NW=([0-9:]+) ;;", launcher).groups()]
    fcst, post = (_hms(re.search(rf"W_{k}:-([0-9:]+)\}}", launcher).group(1)) for k in ("FORECAST", "POST"))
    script = SCRIPT.read_text()
    wait = {lv: int(re.search(rf'{lv}\) +COLD=\d; STAGES=(?:\w+|"[^"]*"); +EXPECT=\d; WAIT_DEFAULT=(\d+)', script).group(1)) for lv in ("smoke", "cycle", "full")}
    crit = {"smoke": warm[1], "cycle": sum(warm) + fcst + post, "full": sum(cold) + fcst + post}
    for lv in wait:
        assert wait[lv] >= crit[lv] + 3600, (lv, wait[lv], crit[lv])
    pipeline = int(re.search(r"timeout\(time: (\d+), unit: 'HOURS'\)", JENKINSFILE.read_text()).group(1)) * 3600
    assert wait["full"] + 7200 <= pipeline, "the full level must leave the pipeline timeout room for bootstrap and staging"


def _tree(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_frozen_smoke_stages_state_and_the_ncst_forcing_only(ci):
    ci.dataset()
    _touch(ci.com / "stale_from_an_earlier_build", "old")
    r = ci.script("stage")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "stage_data PASS" in r.stdout
    got = _tree(ci.com)
    day = f"nos/stofs_2d_glo.{PDY}/{CYC}/rerun"
    assert got == sorted([
        "nos/stofs_2d_glo/stofs_2d_glo_4064.tar", "nos/stofs_2d_glo/stofs_2d_glo_4064.tar.json", "nos/stofs_2d_glo/stofs_2d_glo_nod_equi",
        f"nos/stofs_2d_glo.{PREV[0]}/stofs_2d_glo.t{PREV[1]}z.hotstart", f"nos/stofs_2d_glo.{PREV[0]}/stofs_2d_glo.t{PREV[1]}z.restart",
        *[f"{day}/stofs_2d_glo_ncst.{n}.nc" for n in (221, 222, 225)]])
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


def test_stage_refuses_to_clear_a_comroot_outside_nos_ptmp(ci):
    ci.dataset()
    outside = ci.tmp / "precious"
    _touch(outside / "file", "keep")
    r = ci.script("stage", COMROOT_2DGLO=str(outside))
    assert r.returncode == 1 and "not under NOS_PTMP" in r.stderr and (outside / "file").read_text() == "keep"
    r = ci.script("stage", COMROOT_2DGLO=f"{ci.ptmp}/a/../../precious")
    assert r.returncode == 1 and "contains .." in r.stderr and (outside / "file").is_file()
    r = ci.script("stage", COMROOT_2DGLO=str(ci.ptmp))
    assert r.returncode == 1
    # the shared com (live SECOFS and ATL cycles) and its parent are refused even though they sit under NOS_PTMP. MJ (10/13/26)
    keep = _touch(ci.ptmp / "tester" / "com" / "nos" / "live", "keep")
    for shared, why in ((f"{ci.ptmp}/tester/com", "shared com"), (f"{ci.ptmp}/tester/com/", "shared com"), (f"{ci.ptmp}/tester", "two levels")):
        r = ci.script("stage", COMROOT_2DGLO=shared)
        assert r.returncode == 1 and why in r.stderr and keep.read_text() == "keep", shared
    stale = _touch(ci.com / "stale", "old")
    r = ci.script("stage")
    assert r.returncode == 0 and not stale.exists() and keep.read_text() == "keep"


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


def test_live_stage_tolerates_only_the_reference_download_failure(ci):
    _live_tool(ci, 3)
    r = ci.script("stage", DATA_MODE="live", LEVEL="full")
    assert r.returncode == 0 and "WARN" in r.stdout and "stage_data PASS" in r.stdout
    _live_tool(ci, 1)
    r = ci.script("stage", DATA_MODE="live", LEVEL="full")
    assert r.returncode == 1 and "rc=1" in r.stdout
    assert ci.script("stage", DATA_MODE="sometimes").returncode == 1


LABELS = {"smoke": "nowcast", "cycle": "prep nowcast forecast post", "full": "prep nowcast forecast post"}
ALL_STAGES = "prep nowcast forecast post"


def _chain_stubs(ci: Ci, states, labels: str, passed=None):
    """Stub launcher (records its environment, writes the job list), real status script, sacct that steps through `states`
    (one snapshot per poll; the last repeats), scancel recorder, and the cards' STAGE_SUMMARY logs. MJ (10/13/26)"""
    sl = ci.home / "slurm" / "stofs_2d_glo"
    _stub(sl / "launch_stofs_2d_glo.sh", r'''#!/bin/bash
echo "$@" > "$STUB_DIR/launch.args"
env | grep -E '^(COLD|STAGES|SUBMIT_GFS|KEEPDATA|SLURM_CI_ACCOUNT|SLURM_CI_QOS|ADCIRC_EXEC_DIR|COMROOT_2DGLO|NOS_VENV)=' | sort > "$STUB_DIR/launch.env"
J="$NOS_PTMP/$LOGNAME/slurm_2dglo/jobs_$1$2.txt"; mkdir -p "$(dirname "$J")"; : > "$J"
i=100; for l in $STUB_LABELS; do i=$((i+1)); echo "$l $i" >> "$J"; done
''')
    shutil.copy(STATUS, sl / "status_stofs_2d_glo.sh")
    ids = [101 + i for i in range(len(labels.split()))]
    for i, snap in enumerate(states):
        _touch(ci.stubs / f"snap.{i}", "".join(f"{jid}|{st}\n" for jid, st in zip(ids, snap)))
    _touch(ci.stubs / "snap.last", "".join(f"{jid}|{st}\n" for jid, st in zip(ids, states[-1])))
    _stub(ci.bin / "sacct", r'''#!/bin/bash
cols=""; while [ $# -gt 0 ]; do case "$1" in -o) cols=$2; shift ;; -j) list=$2; shift ;; esac; shift; done
if [ "$cols" = "JobID,State" ]; then
  n=$(cat "$STUB_DIR/n" 2>/dev/null || echo 0); echo $((n+1)) > "$STUB_DIR/n"
  f="$STUB_DIR/snap.$n"; [ -f "$f" ] || f="$STUB_DIR/snap.last"; cat "$f"
else
  awk -F'|' -v i="$list" '$1==i{print $2"|00:10:00"}' "$STUB_DIR/snap.last"
fi
''')
    _stub(ci.bin / "scancel", '#!/bin/bash\necho "$@" >> "$STUB_DIR/scancel.log"\n')
    rpt = ci.ptmp / "tester" / "rpt" / "stofs_2d_glo"
    for i, label in enumerate(labels.split()):
        ok = True if passed is None else passed.get(label, True)
        _touch(rpt / f"stofs_2d_glo_nowcast_00.{101 + i}.out",
               f"run of {label}\nSTAGE_SUMMARY stage=nowcast ofs=stofs_2d_glo status={'PASS' if ok else 'FAIL'} runtime_s=10.0\n")
        _touch(rpt / f"stofs_2d_glo_nowcast_00.{101 + i}.err", "")


def _all(state: str, n: int):
    return [state] * n


@pytest.mark.parametrize("level,cold,stages", [("smoke", "0", "nowcast"), ("cycle", "0", ALL_STAGES), ("full", "1", ALL_STAGES)])
def test_run_launches_the_level_with_the_ci_account_and_waits_for_all_jobs(ci, level, cold, stages):
    labels = LABELS[level]
    n = len(labels.split())
    _chain_stubs(ci, [_all("PENDING", n), _all("RUNNING", n), _all("COMPLETED", n)], labels)
    r = ci.script("run", LEVEL=level, STUB_LABELS=labels, POLL_S="0", SLURM_CI_ACCOUNT="nosofs", SLURM_CI_QOS="batch")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"PASS[run]: LEVEL={level}, {n} jobs COMPLETED with status=PASS" in r.stdout
    env = dict(ln.split("=", 1) for ln in (ci.stubs / "launch.env").read_text().splitlines())
    assert (env["COLD"], env["STAGES"], env["SUBMIT_GFS"], env["KEEPDATA"]) == (cold, stages, "0", "NO")
    assert "SERIAL" not in env
    assert (env["SLURM_CI_ACCOUNT"], env["SLURM_CI_QOS"]) == ("nosofs", "batch")
    assert env["COMROOT_2DGLO"] == str(ci.com) and env["ADCIRC_EXEC_DIR"] == str(ci.pk / "adcirc_v56.1.0_exec")
    assert env["NOS_VENV"] == str(ci.venv)
    assert (ci.stubs / "launch.args").read_text().split() == [PDY, CYC]
    # the Jenkinsfile's post/unsuccessful scancels this file, so all ids sit on one line. MJ (10/13/26)
    assert (ci.ws / "ci_logs" / "current_jobid").read_text() == " ".join(str(101 + i) for i in range(n)) + " "
    assert len(list((ci.ws / "ci_logs").glob("stofs_2d_glo_nowcast_00.*.out"))) == n
    assert not (ci.stubs / "scancel.log").exists()


def test_run_fails_fast_on_a_failed_job_and_cancels_the_rest(ci):
    labels = LABELS["cycle"]
    states = [["RUNNING"] * 4, ["COMPLETED", "FAILED", "PENDING", "PENDING"]]
    _chain_stubs(ci, states, labels, passed={"nowcast": False})
    r = ci.script("run", LEVEL="cycle", STUB_LABELS=labels, POLL_S="0")
    assert r.returncode == 1 and "chain verdict: BAD 102:FAILED" in r.stdout and "FAIL[run]" in r.stdout
    assert (ci.stubs / "scancel.log").read_text().split() == [str(i) for i in range(101, 105)]


@pytest.mark.parametrize("bad", ["CANCELLED by 12345", "OUT_OF_MEMORY"])
def test_run_treats_every_bad_slurm_state_as_failure(ci, bad):
    _chain_stubs(ci, [["COMPLETED", bad, "PENDING", "PENDING"]], LABELS["cycle"])
    r = ci.script("run", LEVEL="cycle", STUB_LABELS=LABELS["cycle"], POLL_S="0")
    assert r.returncode == 1 and "chain verdict: BAD 102:" in r.stdout


def test_run_requires_status_pass_in_the_log_not_just_completed(ci):
    _chain_stubs(ci, [_all("COMPLETED", 4)], LABELS["cycle"], passed={"forecast": False})
    r = ci.script("run", LEVEL="cycle", STUB_LABELS=LABELS["cycle"], POLL_S="0")
    assert r.returncode == 1 and "not COMPLETED with status=PASS: forecast" in r.stdout
    (ci.ptmp / "tester" / "rpt" / "stofs_2d_glo" / "stofs_2d_glo_nowcast_00.101.out").write_text("no summary at all\n")
    r = ci.script("run", LEVEL="cycle", STUB_LABELS=LABELS["cycle"], POLL_S="0")
    assert r.returncode == 1 and "prep forecast" in r.stdout


def test_run_times_out_and_cancels(ci):
    _chain_stubs(ci, [_all("RUNNING", 1)], LABELS["smoke"])
    r = ci.script("run", LEVEL="smoke", STUB_LABELS=LABELS["smoke"], POLL_S="1", WAIT_S="1")
    assert r.returncode == 1 and "TIMEOUT after" in r.stdout
    assert (ci.stubs / "scancel.log").read_text().split() == ["101"]


def test_run_checks_the_number_of_queued_jobs(ci):
    _chain_stubs(ci, [_all("COMPLETED", 1)], LABELS["smoke"])
    r = ci.script("run", LEVEL="cycle", STUB_LABELS=LABELS["smoke"], POLL_S="0")
    assert r.returncode == 1 and "1 jobs queued, LEVEL=cycle expects 4" in r.stdout
    assert (ci.ws / "ci_logs" / "current_jobid").read_text() == "101 "   # the queued jobs are still cancelled by post/unsuccessful. MJ (10/13/26)


def test_run_stops_when_the_launcher_preflight_fails(ci):
    _chain_stubs(ci, [_all("COMPLETED", 1)], LABELS["smoke"])
    _stub(ci.home / "slurm" / "stofs_2d_glo" / "launch_stofs_2d_glo.sh", '#!/bin/bash\necho "MISSING: x" >&2\nexit 1\n')
    r = ci.script("run", LEVEL="smoke", STUB_LABELS=LABELS["smoke"], POLL_S="0")
    assert r.returncode == 1 and "MISSING: x" in r.stderr and not (ci.ws / "ci_logs" / "current_jobid").exists()


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
    for level, n in (("smoke", 5 + 3), ("cycle", 5 + 6), ("full", 6)):
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


needs_rsync = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")


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
