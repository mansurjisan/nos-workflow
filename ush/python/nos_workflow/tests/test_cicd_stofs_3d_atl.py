"""Manual STOFS-3D-ATL support in the Hercules Jenkins pipeline (.cicd), against stub sbatch/sacct/curl and a stub compare_atl.py. Offline. MJ (10/14/26)"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / ".cicd" / "scripts"
JENKINSFILE = REPO / ".cicd" / "Jenkinsfile"
SCRIPT = SCRIPTS / "stofs_3d_atl.sh"
PDY, PDYM1, CYC, RUN = "20261001", "20260930", "12", "stofs_3d_atl_ufs"
# the staged comin trees are nested below the day directory (what stage_comin.py lays out). MJ (10/14/26)
NEST = {"gfs": "12/atmos", "hrrr": "conus", "rtofs": "", "nwm": "medium_range_mem1"}
AMBIENT = ("ATL_CI_ROOT", "WAIT_S", "POLL_S", "CMP_TOL", "OPS_DIR", "OPS_WARN_MM", "SEED_RT", "FORCE", "NOS_VENV", "VENV_PATH", "WORKSPACE",
           "RT_DATA_ROOT", "DATA_MODE", "LEVEL", "CI_OFS", "SLURM_CI_ACCOUNT", "SLURM_CI_QOS", "PACKAGEROOT", "NOS_PTMP", "DCOMROOT",
           "DCOM_BUNDLE", "COMPARE_ATL", "STUB_DIR", "COMROOT_SA", "COMROOT_UFS")
needs_rsync = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
pytestmark = needs_rsync


def _stub(path: Path, body: str = "#!/bin/bash\nexit 0\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)
    return path


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _tree(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# a stand-in for compare_atl.py: prints the file lists, records the arguments of regress/ops. MJ (10/14/26)
FAKE_CMP = r'''#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
open(os.environ["STUB_DIR"] + "/cmp.calls", "a").write(" ".join(a) + "\n")
if a[0] == "files":
    print("nos/stofs_3d_atl_ufs.%s/stofs_3d_atl_ufs.t12z.restart_outputs/staout_1" % a[a.index("--pdy") + 1])
    if a[a.index("--level") + 1] == "cycle":
        print("nos/stofs_3d_atl_ufs.%s/stofs_3d_atl_ufs.t12z.forecast_outputs/staout_1" % a[a.index("--pdy") + 1])
elif a[0] == "ops-files":
    print("stofs_3d_atl.t12z.points.cwl.temp.salt.vel.nc"); print("stofs_3d_atl.t12z.ncast.station.profile.nc")
elif a[0] == "regress":
    sys.exit(int(os.environ.get("STUB_REGRESS_RC", "0")))
elif a[0] == "ops":
    sys.exit(int(os.environ.get("STUB_OPS_RC", "0")))
'''


class Ci:
    def __init__(self, tmp: Path, ofs="stofs_3d_atl_ufs_standalone"):
        self.tmp, self.ofs = tmp, ofs
        self.var = "standalone" if ofs.endswith("standalone") else "coupled"
        self.pk, self.ptmp, self.rt = tmp / "pk", tmp / "ptmp", tmp / "rt"
        self.home, self.ws, self.bin, self.stubs = self.pk / "nos-workflow", tmp / "ws", tmp / "bin", tmp / "stubs"
        self.venv = tmp / "venv"
        self.root = self.ptmp / "tester" / f"atl_ci_{self.var}"
        self.com = self.root / "com"
        self.ds = self.rt / "stofs_3d_atl" / self.var / f"{PDY}{CYC}"
        for d in (self.home, self.ptmp, self.rt, self.ws, self.bin, self.stubs):
            d.mkdir(parents=True, exist_ok=True)
        (self.home / "slurm").symlink_to(REPO / "slurm")
        _touch(self.venv / "bin" / "activate", "")
        _stub(self.bin / "module")
        self.cmp = _stub(tmp / "compare_atl.py", FAKE_CMP)
        self.env = {k: v for k, v in os.environ.items() if k not in AMBIENT}
        self.env.update(PATH=f"{self.bin}:{os.environ['PATH']}", PACKAGEROOT=str(self.pk), NOS_PTMP=str(self.ptmp), RT_DATA_ROOT=str(self.rt),
                        WORKSPACE=str(self.ws), LOGNAME="tester", VENV_PATH=str(self.venv), CI_OFS=ofs, PDY=PDY, CYC=CYC, LEVEL="smoke",
                        DATA_MODE="frozen", STUB_DIR=str(self.stubs), COMPARE_ATL=str(self.cmp), PYTHONDONTWRITEBYTECODE="1")

    def run(self, *args: str, script: Path = SCRIPT, **extra):
        env = {**self.env, **{k: v for k, v in extra.items() if v is not None}}
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
        return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, cwd=str(self.tmp))

    def dataset(self, sentinel=True, ref=True) -> Path:
        i, ds = self.ds / "input", self.ds
        _touch(i / "com" / "nos" / f"{RUN}.{PDY}" / f"{RUN}.t12z.{PDY}.init.nowcast.nc", "init")
        _touch(i / "com" / "nos" / f"{RUN}.{PDYM1}" / "staout_1", "staout")
        _touch(i / "com" / "nos" / f"{RUN}.{PDYM1}" / "rerun" / f"{RUN}.t12z.avg_bias", "bias")
        for s in ("gfs", "hrrr", "rtofs", "nwm"):
            _touch(i / "comin" / s / f"{s}.{PDY}" / NEST[s] / "f000", s)
        for d in (PDY, PDYM1):
            _touch(i / "dcom" / d / "validation_data/marine/cmems/ssh" / f"nrt_global_allsat_phy_l4_{d}_{d}.nc", "adt")
            _touch(i / "dcom" / d / "can_streamgauge" / "02OA016_hydrometric.csv", "csv")
        _touch(i / "dcom" / PDY / "coops_waterlvlobs" / "8570283.xml", "xml")
        if ref:
            _touch(ds / "ref" / "nos" / f"{RUN}.{PDY}" / f"{RUN}.t12z.restart_outputs" / "staout_1", "ref")
            _touch(ds / "ref" / "ops" / "stofs_3d_atl.t12z.points.cwl.temp.salt.vel.nc", "ops")
        if sentinel:
            _touch(ds / ".seeded_ok", "")
        return ds


@pytest.fixture()
def ci(tmp_path):
    return Ci(tmp_path)


def test_scripts_are_valid_bash():
    for f in sorted(SCRIPTS.glob("*.sh")):
        subprocess.run(["bash", "-n", str(f)], check=True)


def _stage_conditions():
    return dict(re.findall(r"stage\('([^']+)'\) \{\n\s+when \{ (.+?) \}\n\s+steps", JENKINSFILE.read_text()))


def test_jenkinsfile_adds_the_atl_choices_and_keeps_the_secofs_default():
    text = JENKINSFILE.read_text()
    assert "choices: ['secofs_ufs', 'stofs_2d_glo', 'stofs_3d_atl_ufs_standalone', 'stofs_3d_atl_ufs']" in text
    assert "CI_OFS       = \"${params.OFS ?: 'secofs_ufs'}\"" in text
    cond = _stage_conditions()
    for name in ("Prep", "Nowcast", "Forecast", "Post", "Verify"):
        assert "env.CI_OFS == 'secofs_ufs'" in cond[name], name
    for name in ("Run ATL", "Verify ATL"):
        assert "isAtlOfs(env.CI_OFS)" in cond[name] and "env.RUN_CYCLE == 'true'" in cond[name], name
    assert "return ofs in ['stofs_3d_atl_ufs_standalone', 'stofs_3d_atl_ufs']" in text
    assert 'stofs_3d_atl.sh" run' in text and 'stofs_3d_atl.sh" verify' in text


def test_atl_is_manual_only_and_posts_no_github_status():
    text = JENKINSFILE.read_text()
    assert "isManualOfs(params.OFS) && currentBuild.getBuildCauses('hudson.model.Cause$UserIdCause')" in text
    assert text.index("hasLabel ? 'true' : 'false'") < text.index("isManualOfs(params.OFS) &&") < text.index("mkdir (no -p) is atomic")
    assert re.search(r"def postStatus\(String state, String description\) \{\n    if \(isManualOfs\(env\.CI_OFS\)\)", text)
    assert "!isManualOfs(env.CI_OFS)" in text


def test_common_sh_accepts_both_atl_variants_and_still_rejects_others(ci):
    probe = ci.tmp / "probe.sh"
    probe.write_text(f'source "{SCRIPTS}/common.sh"\necho "OFS=$OFS"\n')
    for ofs in ("stofs_3d_atl_ufs_standalone", "stofs_3d_atl_ufs"):
        assert f"OFS={ofs}" in ci.run(script=probe, CI_OFS=ofs).stdout
    assert ci.run(script=probe, CI_OFS="stofs_3d_atl").returncode == 2


@pytest.mark.parametrize("level,stages,expect", [("smoke", "prep nowcast", 2), ("cycle", "prep nowcast forecast post", 4), ("full", "prep nowcast forecast post", 4)])
def test_level_table_and_wait_limits(level, stages, expect):
    text = SCRIPT.read_text()
    m = re.search(rf'{level}\) +STAGES="([a-z ]+)"; +EXPECT=(\d+); WAIT_DEFAULT=(\d+)', text)
    assert (m.group(1), int(m.group(2))) == (stages, expect)
    # the wait covers the cards' healthy runtimes (smoke <= 1 h, cycle <= 4 h, per the run guide) with queue margin and leaves the pipeline timeout room. MJ (10/14/26)
    healthy = {"smoke": 3600, "cycle": 14400, "full": 14400}[level]
    pipeline = int(re.search(r"timeout\(time: (\d+), unit: 'HOURS'\)", JENKINSFILE.read_text()).group(1)) * 3600
    assert 2 * healthy <= int(m.group(3)) and int(m.group(3)) + 7200 <= pipeline


def test_frozen_stage_links_the_dataset_into_a_clean_root(ci):
    ci.dataset()
    _touch(ci.root / "stale", "old")
    r = ci.run("stage")
    assert r.returncode == 0 and "stage_data PASS" in r.stdout, r.stderr + r.stdout
    assert _tree(ci.root) == _tree(ci.ds / "input")
    init = f"com/nos/{RUN}.{PDY}/{RUN}.t12z.{PDY}.init.nowcast.nc"
    assert (ci.root / init).samefile(ci.ds / "input" / init)
    g = Path("comin/gfs") / f"gfs.{PDY}" / NEST["gfs"] / "f000"
    assert (ci.root / g).samefile(ci.ds / "input" / g)


def test_frozen_stage_lists_what_is_missing_and_needs_the_sentinel(ci):
    ds = ci.dataset(sentinel=False)
    r = ci.run("stage")
    assert r.returncode == 1 and ".seeded_ok" in r.stdout and "seed 20261001 standalone" in r.stdout
    _touch(ds / ".seeded_ok", "")
    (ds / "input/com/nos" / f"{RUN}.{PDYM1}" / "staout_1").unlink()
    shutil.rmtree(ds / "input/comin/nwm")
    _touch(ci.root / "keep", "old")
    r = ci.run("stage")
    assert r.returncode == 1 and "staout_1" in r.stderr and "comin/nwm" in r.stderr and (ci.root / "keep").is_file()


def test_stage_refuses_to_clear_shared_or_outside_roots(ci):
    ci.dataset()
    outside = _touch(ci.tmp / "precious" / "file", "keep")
    assert ci.run("stage", ATL_CI_ROOT=str(ci.tmp / "precious")).returncode == 1 and outside.is_file()
    assert "contains .." in ci.run("stage", ATL_CI_ROOT=f"{ci.ptmp}/a/../../precious").stderr
    assert ci.run("stage", ATL_CI_ROOT=str(ci.ptmp)).returncode == 1
    keep = _touch(ci.ptmp / "tester" / "com" / "nos" / "live", "keep")
    hand = _touch(ci.ptmp / "tester" / "com_atl_sa" / "nos" / "mine", "keep")
    for bad in (f"{ci.ptmp}/tester/com", f"{ci.ptmp}/tester/com/", f"{ci.ptmp}/tester", f"{ci.ptmp}/tester/com_atl_sa", f"{ci.ptmp}/tester/comin_atl"):
        r = ci.run("stage", ATL_CI_ROOT=bad)
        assert r.returncode == 1 and "refusing" in r.stderr and keep.is_file() and hand.is_file(), bad
    assert ci.run("stage").returncode == 0 and keep.is_file()


def test_bad_arguments_are_rejected(ci):
    assert ci.run("stage", LEVEL="weekly").returncode == 2
    assert ci.run("stage", PDY="2026100").returncode == 2
    r = ci.run("stage", CYC="06")
    assert r.returncode == 2 and "12z" in r.stderr
    assert ci.run("stage", CI_OFS="secofs_ufs").returncode == 2
    assert ci.run("bogus").returncode == 2 and ci.run().returncode == 2


def test_live_mode_needs_a_dcom_bundle_and_checks_it_before_downloading(ci):
    r = ci.run("stage", DATA_MODE="live")
    assert r.returncode == 1 and "DCOM_BUNDLE" in r.stderr
    b = ci.tmp / "bundle"
    r = ci.run("stage", DATA_MODE="live", DCOM_BUNDLE=str(b))
    assert r.returncode == 1 and "MISSING" in r.stderr and "before the ~100 GB download" in r.stdout


def test_stage_data_sh_hands_over_to_the_atl_stage(ci):
    ci.dataset()
    r = ci.run(script=SCRIPTS / "stage_data.sh")
    assert r.returncode == 0 and (ci.com / "nos").is_dir(), r.stderr + r.stdout


# ---- run ---- MJ (10/14/26)

def _chain(ci: Ci, states, labels, passed=None):
    """Stub sbatch (records its arguments, hands out ids 101...), sacct stepping through `states`, scancel, and the cards' logs. MJ (10/14/26)"""
    _stub(ci.bin / "sbatch", r'''#!/bin/bash
n=$(cat "$STUB_DIR/sb.n" 2>/dev/null || echo 100); n=$((n+1)); echo $n > "$STUB_DIR/sb.n"
echo "$n $*" >> "$STUB_DIR/sbatch.calls"; echo "$n"
''')
    ids = [101 + i for i in range(len(labels))]
    for i, snap in enumerate(states):
        _touch(ci.stubs / f"snap.{i}", "".join(f"{j}|{s}\n" for j, s in zip(ids, snap)))
    _touch(ci.stubs / "snap.last", "".join(f"{j}|{s}\n" for j, s in zip(ids, states[-1])))
    _stub(ci.bin / "sacct", r'''#!/bin/bash
n=$(cat "$STUB_DIR/n" 2>/dev/null || echo 0); echo $((n+1)) > "$STUB_DIR/n"
f="$STUB_DIR/snap.$n"; [ -f "$f" ] || f="$STUB_DIR/snap.last"; cat "$f"
''')
    _stub(ci.bin / "scancel", '#!/bin/bash\necho "$@" >> "$STUB_DIR/scancel.log"\n')
    pfx = "stofs_3d_atl_ufs_standalone" if ci.var == "standalone" else "stofs_3d_atl_ufs"
    for i, label in enumerate(labels):
        ok = True if passed is None else passed.get(label, True)
        _touch(ci.root / "rpt" / f"{pfx}_{label}_00.{101 + i}.out", f"STAGE_SUMMARY stage={label} status={'PASS' if ok else 'FAIL'} runtime_s=1\n")


CH = {"smoke": ["prep", "nowcast"], "cycle": ["prep", "nowcast", "forecast", "post"]}


def _ready(ci: Ci):
    _touch(ci.com / "nos" / f"{RUN}.{PDY}" / f"{RUN}.t12z.{PDY}.init.nowcast.nc")


@pytest.mark.parametrize("ofs,comvar,carddir", [("stofs_3d_atl_ufs_standalone", "COMROOT_SA", "stofs_3d_atl_ufs_standalone"), ("stofs_3d_atl_ufs", "COMROOT_UFS", "stofs_3d_atl_ufs")])
@pytest.mark.parametrize("level", ["smoke", "cycle", "full"])
def test_run_submits_an_afterok_chain_with_the_ci_account_and_waits(tmp_path, ofs, comvar, carddir, level):
    ci = Ci(tmp_path, ofs)
    labels = CH["smoke" if level == "smoke" else "cycle"]
    _ready(ci)
    _chain(ci, [["PENDING"] * len(labels), ["COMPLETED"] * len(labels)], labels)
    r = ci.run("run", LEVEL=level, POLL_S="0", SLURM_CI_ACCOUNT="nosofs", SLURM_CI_QOS="batch")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"PASS[run]: LEVEL={level}, {len(labels)} jobs COMPLETED with status=PASS" in r.stdout
    calls = (ci.stubs / "sbatch.calls").read_text().splitlines()
    assert len(calls) == len(labels)
    for i, (label, line) in enumerate(zip(labels, calls)):
        assert f"--account=nosofs --qos=batch" in line and "--kill-on-invalid-dep=yes" in line
        assert line.endswith(f"{ci.home}/slurm/{carddir}/jnos_{label}_00.sh")
        assert (f"--dependency=afterok:{100 + i}" in line) == (i > 0)
        for want in (f"PDY={PDY}", "CYC=12", f"PACKAGEROOT={ci.pk}", f"{comvar}={ci.com}", f"COMROOT_STAGED={ci.root}/comin",
                     f"DCOMROOT={ci.root}/dcom", f"RPTDIR={ci.root}/rpt", f"NOS_VENV={ci.venv}", "OFS=stofs_3d_atl_ufs"):
            assert want in line, (want, line)
    assert (ci.ws / "ci_logs" / "current_jobid").read_text() == " ".join(str(101 + i) for i in range(len(labels))) + " "
    assert len(list((ci.ws / "ci_logs").glob("*_00.*.out"))) == len(labels)
    assert not (ci.stubs / "scancel.log").exists()


def test_run_fails_fast_on_a_bad_state_and_cancels(ci):
    labels = CH["cycle"]
    _ready(ci)
    _chain(ci, [["COMPLETED", "FAILED", "CANCELLED", "CANCELLED"]], labels, passed={"nowcast": False})
    r = ci.run("run", LEVEL="cycle", POLL_S="0")
    assert r.returncode == 1 and "chain verdict: BAD 102:FAILED" in r.stdout and "FAIL[run]" in r.stdout
    assert (ci.stubs / "scancel.log").read_text().split() == ["101", "102", "103", "104"]


def test_run_requires_status_pass_in_the_log_not_just_completed(ci):
    _ready(ci)
    _chain(ci, [["COMPLETED"] * 2], CH["smoke"], passed={"nowcast": False})
    r = ci.run("run", LEVEL="smoke", POLL_S="0")
    assert r.returncode == 1 and "not COMPLETED with status=PASS: nowcast" in r.stdout


def test_run_times_out_and_cancels(ci):
    _ready(ci)
    _chain(ci, [["RUNNING"] * 2], CH["smoke"])
    r = ci.run("run", LEVEL="smoke", POLL_S="1", WAIT_S="1")
    assert r.returncode == 1 and "TIMEOUT after" in r.stdout and (ci.stubs / "scancel.log").read_text().split() == ["101", "102"]


def test_run_needs_the_staged_init_state(ci):
    _chain(ci, [["COMPLETED"] * 2], CH["smoke"])
    r = ci.run("run", LEVEL="smoke", POLL_S="0")
    assert r.returncode == 1 and "init state" in r.stderr and not (ci.stubs / "sbatch.calls").exists()


# ---- verify ---- MJ (10/14/26)

def _calls(ci: Ci):
    return [ln.split() for ln in (ci.stubs / "cmp.calls").read_text().splitlines()]


def test_verify_calls_regress_and_at_full_ops(ci):
    ci.dataset()
    r = ci.run("verify", LEVEL="smoke")
    assert r.returncode == 0 and "PASS[verify]: LEVEL=smoke" in r.stdout, r.stdout + r.stderr
    assert _calls(ci) == [["regress", "--ref", str(ci.ds / "ref"), "--out", str(ci.com), "--variant", "standalone", "--pdy", PDY, "--level", "smoke", "--tol", "1e-3"]]
    (ci.stubs / "cmp.calls").unlink()
    assert ci.run("verify", LEVEL="cycle", CMP_TOL="0.01").returncode == 0
    assert [c[0] for c in _calls(ci)] == ["regress"] and _calls(ci)[0][-3:] == ["cycle", "--tol", "0.01"]
    (ci.stubs / "cmp.calls").unlink()
    assert ci.run("verify", LEVEL="full").returncode == 0
    reg, ops = _calls(ci)
    assert reg[reg.index("--level") + 1] == "cycle"
    assert ops == ["ops", "--ops-dir", str(ci.ds / "ref" / "ops"), "--out", str(ci.com), "--variant", "standalone", "--pdy", PDY, "--warn-mm", "500"]
    assert (ci.ws / "ci_logs" / "compare_atl.txt").is_file()


def test_verify_fails_on_a_regression_and_on_a_missing_reference(ci):
    ci.dataset()
    r = ci.run("verify", LEVEL="smoke", STUB_REGRESS_RC="1")
    assert r.returncode == 1 and "FAIL[verify]: LEVEL=smoke" in r.stdout
    r = ci.run("verify", LEVEL="full", STUB_OPS_RC="1")
    assert r.returncode == 1
    shutil.rmtree(ci.ds / "ref")
    r = ci.run("verify", LEVEL="smoke")
    assert r.returncode == 1 and "has no reference outputs" in r.stdout
    r = ci.run("verify", LEVEL="smoke", DATA_MODE="live")
    assert r.returncode == 0 and "regression comparison skipped" in r.stdout


def test_coupled_verify_passes_its_variant(tmp_path):
    ci = Ci(tmp_path, "stofs_3d_atl_ufs")
    ci.dataset()
    assert ci.run("verify", LEVEL="smoke").returncode == 0
    assert _calls(ci)[0][_calls(ci)[0].index("--variant") + 1] == "coupled"


# ---- seed ---- MJ (10/14/26)

def _source(ci: Ci, coupled_link=False):
    com, comin, dcom = ci.tmp / "src_com", ci.tmp / "src_comin", ci.tmp / "src_dcom"
    init = com / "nos" / f"{RUN}.{PDY}" / f"{RUN}.t12z.{PDY}.init.nowcast.nc"
    _touch(init, "init")
    _touch(com / "nos" / f"{RUN}.{PDYM1}" / "staout_1", "staout")
    _touch(com / "nos" / f"{RUN}.{PDYM1}" / "rerun" / f"{RUN}.t12z.avg_bias", "bias")
    _touch(com / "nos" / f"{RUN}.{PDYM1}" / "rerun" / f"{RUN}.t12z.param.nml", "nml")
    _touch(com / "nos" / f"{RUN}.{PDY}" / f"{RUN}.t12z.restart_outputs" / "staout_1", "r")
    _touch(com / "nos" / f"{RUN}.{PDY}" / f"{RUN}.t12z.forecast_outputs" / "staout_1", "f")
    _touch(com / "nos" / f"{RUN}.{PDY}" / "junk.nc", "must not be copied")
    for s in ("gfs", "hrrr", "rtofs", "nwm"):
        _touch(comin / s / f"{s}.{PDY}" / NEST[s] / "f000", s)
    for d in (PDY, PDYM1):
        _touch(dcom / d / "validation_data/marine/cmems/ssh" / f"nrt_global_allsat_phy_l4_{d}_{d}.nc", "adt")
        _touch(dcom / d / "can_streamgauge" / "02OA016_hydrometric.csv", "csv")
        _touch(dcom / d / "other" / "big.dat", "must not be copied")
    _touch(dcom / PDY / "coops_waterlvlobs" / "8570283.xml", "xml")
    _stub(ci.bin / "curl", '#!/bin/bash\nfor a; do last=$a; done\nout=""\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\necho "$last" >> "$STUB_DIR/curl.urls"\necho ops > "$out"\n')
    return com, comin, dcom


def test_seed_builds_the_dataset_the_stage_reads(ci):
    com, comin, dcom = _source(ci)
    env = dict(SEED_RT=str(ci.rt))
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), **env)
    assert r.returncode == 0, r.stderr + r.stdout
    assert (ci.ds / ".seeded_ok").is_file() and "seed PASS" in r.stdout and "chmod o+x" in r.stdout
    got = _tree(ci.ds / "input")
    assert f"com/nos/{RUN}.{PDYM1}/rerun/{RUN}.t12z.param.nml" in got and not any("junk" in f or "big.dat" in f or "restart_outputs" in f for f in got)
    assert _tree(ci.ds / "ref") == sorted([f"nos/{RUN}.{PDY}/{RUN}.t12z.restart_outputs/staout_1", f"nos/{RUN}.{PDY}/{RUN}.t12z.forecast_outputs/staout_1",
                                           "ops/stofs_3d_atl.t12z.points.cwl.temp.salt.vel.nc", "ops/stofs_3d_atl.t12z.ncast.station.profile.nc"])
    assert f"STOFS-3D-Atl/stofs_3d_atl.{PDY}/stofs_3d_atl.t12z.ncast.station.profile.nc" in (ci.stubs / "curl.urls").read_text()
    # the seeded dataset is exactly what the frozen stage needs, and the second seed refuses to overwrite. MJ (10/14/26)
    assert ci.run("stage").returncode == 0, ci.run("stage").stderr
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), **env)
    assert r.returncode == 1 and "FORCE=1" in r.stderr
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), FORCE="1", **env).returncode == 0


def test_seed_of_the_second_variant_hard_links_the_shared_inputs(ci):
    com, comin, dcom = _source(ci)
    env = dict(SEED_RT=str(ci.rt))
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), **env).returncode == 0
    assert ci.run("seed", PDY, "coupled", str(com), str(comin), str(dcom), **env).returncode == 0
    a = ci.rt / "stofs_3d_atl" / "standalone" / f"{PDY}{CYC}" / "input"
    b = ci.rt / "stofs_3d_atl" / "coupled" / f"{PDY}{CYC}" / "input"
    g = Path("comin/gfs") / f"gfs.{PDY}" / NEST["gfs"] / "f000"
    assert (ci.rt / "stofs_3d_atl" / "standalone" / f"{PDY}{CYC}" / "input" / g).samefile(ci.rt / "stofs_3d_atl" / "coupled" / f"{PDY}{CYC}" / "input" / g)


def test_seed_uses_ops_dir_and_reports_an_unfinished_source(ci):
    com, comin, dcom = _source(ci)
    opsd = ci.tmp / "opsd"
    for f in ("stofs_3d_atl.t12z.points.cwl.temp.salt.vel.nc", "stofs_3d_atl.t12z.ncast.station.profile.nc"):
        _touch(opsd / f, "local")
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt), OPS_DIR=str(opsd))
    assert r.returncode == 0 and not (ci.stubs / "curl.urls").exists()
    assert (ci.ds / "ref/ops/stofs_3d_atl.t12z.ncast.station.profile.nc").read_text() == "local"
    (com / "nos" / f"{RUN}.{PDY}" / f"{RUN}.t12z.forecast_outputs" / "staout_1").unlink()
    shutil.rmtree(comin / "nwm")
    r = ci.run("seed", PDY, "coupled", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt))
    assert r.returncode == 1 and "forecast_outputs/staout_1" in r.stderr and "nwm" in r.stderr
    assert not (ci.rt / "stofs_3d_atl" / "coupled").exists()
    assert ci.run("seed", PDY, "other").returncode == 2


# ---- review follow-ups: cleanup, bootstrap, deploy, env_check, CYC, seed checks. MJ (10/14/26)

def _work(ci: Ci, cards: str, ids=("101", "102", "999")):
    w = ci.ptmp / "tester" / "work" / cards
    for i in ids:
        _touch(w / f"stofs_3d_atl_ufs_prep_00_dev.{i}" / "x", "d")
    return w


def test_a_passing_run_deletes_its_own_run_directories_only(ci):
    _ready(ci)
    w = _work(ci, "stofs_3d_atl_ufs_standalone")
    secofs = _touch(ci.ptmp / "tester" / "work" / "secofs_ufs" / "job.101" / "x", "keep")
    other = _touch(ci.ptmp / "tester" / "work" / "stofs_3d_atl_ufs" / "job.101" / "x", "keep")
    _chain(ci, [["COMPLETED"] * 2], CH["smoke"])
    r = ci.run("run", LEVEL="smoke", POLL_S="0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not list(w.glob("*.101")) and not list(w.glob("*.102")) and list(w.glob("*.999"))
    assert secofs.is_file() and other.is_file()


def test_a_failing_run_keeps_its_directories_until_the_next_stage(ci):
    ci.dataset()
    _ready(ci)
    w = _work(ci, "stofs_3d_atl_ufs_standalone")
    _chain(ci, [["COMPLETED", "FAILED"]], CH["smoke"], passed={"nowcast": False})
    assert ci.run("run", LEVEL="smoke", POLL_S="0").returncode == 1
    assert len(list(w.iterdir())) == 3
    secofs = _touch(ci.ptmp / "tester" / "work" / "secofs_ufs" / "job.1" / "x", "keep")
    assert ci.run("stage").returncode == 0
    assert not w.exists() and secofs.is_file()


def test_reset_root_refuses_a_root_inside_a_protected_directory(ci):
    ci.dataset()
    inside = _touch(ci.ptmp / "tester" / "com" / "sub" / "dir" / "f", "keep")
    r = ci.run("stage", ATL_CI_ROOT=f"{ci.ptmp}/tester/com/sub/dir")
    assert r.returncode == 1 and "inside the protected" in r.stderr and inside.is_file()


def test_run_pins_execnos_and_copies_early_sbatch_output(ci):
    _ready(ci)
    _chain(ci, [["COMPLETED"] * 2], CH["smoke"])
    _touch(ci.root / "slurm" / "stofs_3d_atl_ufs_sa_prep_00.101.out", "died in a card check")
    assert ci.run("run", LEVEL="smoke", POLL_S="0").returncode == 0
    assert f"EXECnos={ci.home}/exec" in (ci.stubs / "sbatch.calls").read_text()
    assert (ci.ws / "ci_logs" / "stofs_3d_atl_ufs_sa_prep_00.101.out").is_file()


def test_jenkinsfile_forces_cyc_12_for_atl():
    text = JENKINSFILE.read_text()
    assert "CYC          = \"${params.OFS?.startsWith('stofs_3d_atl') ? '12' : params.CYC}\"" in text
    assert 'echo "STOFS-3D-ATL runs 12z only: CYC ${params.CYC} -> 12"' in text
    assert "${params.CYC}z" not in text and "${params.PDY}/${params.CYC}" not in text


def test_live_stage_loads_the_modules_first(ci):
    r = ci.run("stage", DATA_MODE="live", DCOM_BUNDLE=str(ci.tmp / "b"), PATH=f"{ci.bin}:/usr/bin:/bin")
    assert r.returncode == 1 and "MISSING" in r.stderr   # module stub ran (no 'module: command not found' abort)
    assert "command not found" not in r.stderr


def _comin_day(root: Path, s: str, d: str):
    _touch(root / s / f"{s}.{d}" / NEST[s] / "f", s)


def test_seed_copies_only_the_two_day_directories_and_rejects_the_wrong_variant(ci):
    com, comin, dcom = _source(ci)
    for s in ("gfs", "hrrr", "rtofs", "nwm"):
        _comin_day(comin, s, "20260925")
        _comin_day(comin, s, PDYM1)
    _touch(com / "nos" / f"{RUN}.{PDY}" / "rerun" / f"{RUN}.t12z.param.nml", "  nws = 4 !coupled\n")
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt))
    assert r.returncode == 1 and "not a standalone run" in r.stderr and not ci.ds.exists()
    r = ci.run("seed", PDY, "coupled", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt))
    assert r.returncode == 0, r.stderr
    got = _tree(ci.rt / "stofs_3d_atl" / "coupled" / f"{PDY}{CYC}" / "input" / "comin")
    want = [str(Path(s) / f"{s}.{PDYM1}" / NEST[s] / "f") for s in NEST] + [str(Path(s) / f"{s}.{PDY}" / NEST[s] / "f000") for s in NEST]
    assert sorted(got) == sorted(want)
    assert oct((ci.rt / "stofs_3d_atl" / "coupled").stat().st_mode & 0o001) == "0o1"
    _touch(com / "nos" / f"{RUN}.{PDY}" / "rerun" / f"{RUN}.t12z.param.nml", "  nws = 2\n")
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt))
    assert r.returncode == 0, r.stderr


def test_seed_needs_the_st_lawrence_file(ci):
    com, comin, dcom = _source(ci)
    for d in (PDY, PDYM1):
        (dcom / d / "can_streamgauge" / "02OA016_hydrometric.csv").unlink()
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt))
    assert r.returncode == 1 and "02OA016_hydrometric.csv" in r.stderr


# ATL bootstrap and env_check, deploy: the same machinery as 2D-GLO. MJ (10/14/26)
ATL_OFS = ["stofs_3d_atl_ufs_standalone", "stofs_3d_atl_ufs"]


def _atl_seed_src(ci: Ci, ofs: str):
    src = ci.tmp / "seed" / "nos-workflow"
    _touch(src / "fix" / "stofs_3d_atl_ufs" / "grid", "grid")
    _touch(src / "fix" / "secofs_ufs" / "grid", "secofs grid")
    for e in ("stofs_3d_atl_tide_fac", "schism_combine_hotstart7.exe", "fv3_stofs_3d_atl.exe", "stofs_3d_atl_pschism_v3.1.5", "other_tool"):
        _stub(src / "exec" / e)
    return src


@pytest.mark.parametrize("ofs", ATL_OFS)
def test_bootstrap_atl_seeds_its_fix_and_only_its_executables(tmp_path, ofs):
    ci = Ci(tmp_path, ofs)
    src = _atl_seed_src(ci, ofs)
    _stub(ci.venv / "bin" / "python")
    _stub(ci.home / "exec" / "schism_combine_hotstart7.exe")        # already there from the SECOFS seed
    seed_rt = tmp_path / "seed_rt"
    for v in ("standalone", "coupled"):
        _touch(seed_rt / "stofs_3d_atl" / v / f"{PDY}{CYC}" / "data", v)
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt), DATA_MODE="frozen")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ci.home / "fix" / "stofs_3d_atl_ufs" / "grid").is_file() and not (ci.home / "fix" / "secofs_ufs").exists()
    mine = "stofs_3d_atl_pschism_v3.1.5" if ofs.endswith("standalone") else "fv3_stofs_3d_atl.exe"
    theirs = "fv3_stofs_3d_atl.exe" if ofs.endswith("standalone") else "stofs_3d_atl_pschism_v3.1.5"
    assert (ci.home / "exec" / mine).is_file() and (ci.home / "exec" / "stofs_3d_atl_tide_fac").is_file()
    assert not (ci.home / "exec" / theirs).exists() and not (ci.home / "exec" / "other_tool").exists()
    var = "standalone" if ofs.endswith("standalone") else "coupled"
    assert (ci.rt / "stofs_3d_atl" / var / f"{PDY}{CYC}" / ".seeded_ok").is_file()


def test_bootstrap_atl_hard_links_the_dataset_shared_with_the_sibling(tmp_path):
    ci = Ci(tmp_path, "stofs_3d_atl_ufs")
    src = _atl_seed_src(ci, ci.ofs)
    _stub(ci.venv / "bin" / "python")
    _stub(ci.home / "exec" / "schism_combine_hotstart7.exe")
    seed_rt = tmp_path / "seed_rt"
    for v in ("standalone", "coupled"):
        _touch(seed_rt / "stofs_3d_atl" / v / f"{PDY}{CYC}" / "shared", "same")
    sib = ci.rt / "stofs_3d_atl" / "standalone" / f"{PDY}{CYC}"
    shutil.copytree(seed_rt / "stofs_3d_atl" / "standalone" / f"{PDY}{CYC}", sib, copy_function=shutil.copy2)
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt), DATA_MODE="frozen")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ci.rt / "stofs_3d_atl" / "coupled" / f"{PDY}{CYC}" / "shared").samefile(sib / "shared")


@pytest.mark.parametrize("ofs", ATL_OFS)
def test_env_check_atl_needs_the_variant_executables(tmp_path, ofs):
    ci = Ci(tmp_path, ofs)
    for t in ("python3", "wgrib2", "sbatch", "sacct", "rsync"):
        _stub(ci.bin / t)
    mine = "stofs_3d_atl_pschism_v3.1.5" if ofs.endswith("standalone") else "fv3_stofs_3d_atl.exe"
    _touch(ci.home / "ush/python/nos-utils/nos_utils/orchestrator.py", "")
    r = ci.run(script=SCRIPTS / "env_check.sh")
    assert r.returncode == 1 and f"{mine} not found" in r.stdout
    for e in (mine, "stofs_3d_atl_tide_fac", "schism_combine_hotstart7.exe"):
        _stub(ci.home / "exec" / e)
    r = ci.run(script=SCRIPTS / "env_check.sh")
    assert r.returncode == 0 and "env_check PASS" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("ofs", ATL_OFS)
def test_deploy_atl_copies_nos_utils_and_a_secofs_deploy_removes_it(tmp_path, ofs):
    ci = Ci(tmp_path, ofs)
    _touch(ci.ws / "tools" / "t.sh", "t")
    _touch(ci.ws / "ush/python/nos-utils/.git", "gitdir")
    _touch(ci.ws / "ush/python/nos-utils/nos_utils/orchestrator.py", "# nu")
    assert ci.run(script=SCRIPTS / "deploy.sh").returncode == 0
    nu = ci.home / "ush/python/nos-utils"
    assert (nu / "nos_utils/orchestrator.py").is_file() and not (nu / ".git").exists()
    assert ci.run(script=SCRIPTS / "deploy.sh", CI_OFS="secofs_ufs").returncode == 0
    assert not nu.exists() and (ci.home / "tools/t.sh").is_file()
    (ci.ws / "ush/python/nos-utils/nos_utils/orchestrator.py").unlink()
    r = ci.run(script=SCRIPTS / "deploy.sh")
    assert r.returncode == 1 and "is empty" in r.stdout


# ---- SEED_LEVEL=smoke: a dataset from a run that has finished nowcast only. MJ (10/14/26) ----

def _nowcast_only(com: Path):
    shutil.rmtree(com / "nos" / f"{RUN}.{PDY}" / f"{RUN}.t12z.forecast_outputs")


def _fresh_cycle_files(ci: Ci, com, comin, dcom, sub: str) -> list:
    """the file tree of a fresh default (cycle) seed into a separate SEED_RT. MJ (10/14/26)"""
    rt = ci.tmp / sub
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(rt)).returncode == 0
    return _tree(rt / "stofs_3d_atl" / "standalone" / f"{PDY}{CYC}")


def test_smoke_seed_from_a_nowcast_only_run_copies_no_forecast_or_ops_files(ci):
    com, comin, dcom = _source(ci)
    _nowcast_only(com)
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt), SEED_LEVEL="smoke")
    assert r.returncode == 0 and "seed PASS" in r.stdout, r.stderr + r.stdout
    assert (ci.ds / ".seeded_ok").read_text().strip() == "level=smoke"
    assert _tree(ci.ds / "ref") == [f"nos/{RUN}.{PDY}/{RUN}.t12z.restart_outputs/staout_1"]
    assert not (ci.stubs / "curl.urls").exists()
    assert "--level smoke" in (ci.stubs / "cmp.calls").read_text() and "ops-files" not in (ci.stubs / "cmp.calls").read_text()


def test_the_default_seed_is_unchanged_and_needs_the_forecast_files(ci):
    com, comin, dcom = _source(ci)
    _nowcast_only(com)
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt))
    assert r.returncode == 1 and "forecast_outputs/staout_1" in r.stderr and not ci.ds.exists()
    com, comin, dcom = _source(ci)
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt)).returncode == 0
    assert (ci.ds / ".seeded_ok").read_text().strip() == "level=cycle" and len(_tree(ci.ds / "ref")) == 4
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt), SEED_LEVEL="bogus").returncode == 2


def test_cycle_and_full_refuse_a_smoke_dataset_at_stage_and_smoke_runs(ci):
    com, comin, dcom = _source(ci)
    _nowcast_only(com)
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt), SEED_LEVEL="smoke").returncode == 0
    _touch(ci.root / "keep", "old")
    for level in ("cycle", "full"):
        r = ci.run("stage", LEVEL=level)
        assert r.returncode == 1 and f"dataset {ci.ds} holds smoke references only; run LEVEL=smoke, or re-seed with SEED_LEVEL=cycle once the source run has forecast and post" in r.stdout
        assert (ci.root / "keep").is_file()
    r = ci.run("stage", LEVEL="smoke")
    assert r.returncode == 0 and "stage_data PASS" in r.stdout, r.stderr + r.stdout


def test_a_dataset_without_a_level_is_cycle(ci):
    ci.dataset()
    r = ci.run("stage", LEVEL="cycle")
    assert r.returncode == 0 and "stage_data PASS" in r.stdout, r.stderr + r.stdout


def test_reseeding_with_the_default_upgrades_a_smoke_dataset_to_what_a_fresh_cycle_seed_gives(ci):
    com, comin, dcom = _source(ci)
    fresh = _fresh_cycle_files(ci, com, comin, dcom, "rt_fresh")
    _nowcast_only(com)
    env = dict(SEED_RT=str(ci.rt))
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_LEVEL="smoke", **env).returncode == 0
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_LEVEL="smoke", **env).returncode == 1   # smoke over smoke still needs FORCE
    # the source run finishes forecast and post, then the default seed adds to the same dataset without FORCE. MJ (10/14/26)
    com, comin, dcom = _source(ci)
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), **env)
    assert r.returncode == 0 and "upgrading" in r.stdout, r.stderr + r.stdout
    assert (ci.ds / ".seeded_ok").read_text().strip() == "level=cycle"
    assert _tree(ci.ds) == fresh
    assert ci.run("stage", LEVEL="cycle").returncode == 0
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), **env)
    assert r.returncode == 1 and "FORCE=1" in r.stderr   # cycle over cycle is not an upgrade


def test_a_smoke_seed_never_overwrites_a_cycle_dataset(ci):
    com, comin, dcom = _source(ci)
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt)).returncode == 0
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_RT=str(ci.rt), SEED_LEVEL="smoke")
    assert r.returncode == 1 and (ci.ds / ".seeded_ok").read_text().strip() == "level=cycle"


def test_bootstrap_keeps_the_level_and_refreshes_a_smoke_copy_after_the_upgrade(tmp_path):
    ci = Ci(tmp_path, "stofs_3d_atl_ufs_standalone")
    src = _atl_seed_src(ci, ci.ofs)
    _stub(ci.venv / "bin" / "python")
    _stub(ci.home / "exec" / "schism_combine_hotstart7.exe")
    seed_rt = tmp_path / "seed_rt"
    sd = seed_rt / "stofs_3d_atl" / "standalone" / f"{PDY}{CYC}"
    _touch(sd / ".seeded_ok", "level=smoke\n")
    _touch(sd / "ref" / "a", "a")
    boot = dict(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt), DATA_MODE="frozen")
    assert ci.run(**boot).returncode == 0
    assert (ci.ds / ".seeded_ok").read_text().strip() == "level=smoke" and not (ci.ds / "ref" / "b").exists()
    _touch(sd / ".seeded_ok", "level=cycle\n")
    _touch(sd / "ref" / "b", "b")
    r = ci.run(**boot)
    assert r.returncode == 0 and "seeding frozen dataset" in r.stdout, r.stdout + r.stderr
    assert (ci.ds / ".seeded_ok").read_text().strip() == "level=cycle" and (ci.ds / "ref" / "b").is_file()
    assert "skipping" in ci.run(**boot).stdout or "already present" in ci.run(**boot).stdout
