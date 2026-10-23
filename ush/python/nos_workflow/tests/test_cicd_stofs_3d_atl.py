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
AMBIENT = ("WAIT_S", "POLL_S", "CMP_TOL", "OPS_DIR", "OPS_WARN_MM", "OPS_FAIL_MEDIAN_MM", "OPS_FAIL_OVER_10CM", "SEED_RT", "FORCE", "NOS_VENV", "VENV_PATH", "WORKSPACE",
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
        self.com = self.ptmp / "tester" / "com"
        self.rpt = self.ptmp / "tester" / "rpt" / RUN   # the card's own RPTDIR default (OFS pinned to the run name). MJ (10/15/26)
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
    assert "return ofs in ['stofs_3d_atl_ufs_standalone', 'stofs_3d_atl_ufs']" in text


def _runs(cond: str, ofs: str, level: str = "smoke") -> bool:
    """Evaluates a stage `when` expression for one (OFS, LEVEL): only the two operators and isAtlOfs() the Jenkinsfile uses. MJ (10/15/26)"""
    py = re.sub(r"^expression \{ | \}$", "", cond).replace("env.RUN_CYCLE == 'true'", "True").replace("&&", " and ").replace("||", " or ")
    py = py.replace("isAtlOfs(env.CI_OFS)", str(ofs.startswith("stofs_3d_atl"))).replace("!=", " != ")
    return bool(eval(re.sub(r"env\.CI_OFS", repr(ofs), re.sub(r"env\.LEVEL", repr(level), py))))


@pytest.mark.parametrize("ofs,level,want", [
    ("secofs_ufs", "smoke", ["Prep", "Nowcast", "Forecast", "Post", "Verify"]),
    ("stofs_3d_atl_ufs_standalone", "smoke", ["Prep", "Nowcast", "Verify"]),
    ("stofs_3d_atl_ufs", "smoke", ["Prep", "Nowcast", "Verify"]),
    ("stofs_3d_atl_ufs_standalone", "cycle", ["Prep", "Nowcast", "Forecast", "Post", "Verify"]),
    ("stofs_3d_atl_ufs", "full", ["Prep", "Nowcast", "Forecast", "Post", "Verify"]),
    ("stofs_2d_glo", "cycle", ["Prep", "Nowcast", "Forecast", "Post", "Verify"]),   # the 2D-GLO stages are the shared ones. MJ (10/15/26)
])
def test_jenkinsfile_stage_conditions(ofs, level, want):
    cond = _stage_conditions()
    ran = [n for n, c in cond.items() if n not in ("Checkout", "Gate") and "RUN_CYCLE == 'true'" in c and "environment" not in c and _runs(c, ofs, level)]
    assert ran == want, (ran, want)


def test_jenkinsfile_has_no_atl_run_chain_and_verifies_atl_through_the_secofs_stage():
    text = JENKINSFILE.read_text()
    cond = _stage_conditions()
    assert "Run ATL" not in cond and "Verify ATL" not in cond and 'stofs_3d_atl.sh" run' not in text
    assert 'stofs_3d_atl.sh" verify' in text and 'scripts/verify.sh"' in text
    assert "ci_logs/current_jobid" in text
    assert not re.search(r"\brun\)|cmd_run|afterok|WAIT_S|POLL_S|BAD_STATES", SCRIPT.read_text())


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


def test_frozen_stage_links_only_the_com_state_and_reads_comin_and_dcom_in_place(ci):
    ci.dataset()
    day = ci.com / "nos" / f"{RUN}.{PDY}"
    _touch(day / "stale", "old")
    _touch(ci.com / "nos" / f"{RUN}.{PDYM1}" / "stale", "old")
    r = ci.run("stage")
    assert r.returncode == 0 and "stage_data PASS" in r.stdout, r.stderr + r.stdout
    assert _tree(ci.com) == _tree(ci.ds / "input" / "com")
    init = f"nos/{RUN}.{PDY}/{RUN}.t12z.{PDY}.init.nowcast.nc"
    assert (ci.com / init).samefile(ci.ds / "input" / "com" / init)
    assert not (ci.ptmp / "tester" / f"atl_ci_{ci.var}").exists() and not (ci.com.parent / "comin").exists() and not (ci.com.parent / "dcom").exists()


def test_frozen_stage_lists_what_is_missing_and_needs_the_sentinel(ci):
    ds = ci.dataset(sentinel=False)
    r = ci.run("stage")
    assert r.returncode == 1 and ".seeded_ok" in r.stdout and "seed 20261001 standalone" in r.stdout
    _touch(ds / ".seeded_ok", "")
    (ds / "input/com/nos" / f"{RUN}.{PDYM1}" / "staout_1").unlink()
    shutil.rmtree(ds / "input/comin/nwm")
    keep = _touch(ci.com / "nos" / f"{RUN}.{PDY}" / "keep", "old")
    r = ci.run("stage")
    assert r.returncode == 1 and "staout_1" in r.stderr and "comin/nwm" in r.stderr and keep.is_file()


def test_stage_deletes_every_earlier_atl_day_directory_and_keeps_everything_else(ci):
    ci.dataset()
    secofs = _touch(ci.com / "nos" / f"secofs_ufs.{PDY}" / "f", "keep")
    secofs2 = _touch(ci.com / "nos" / f"secofs_ufs.{PDYM1}" / "f", "keep")
    other_day = _touch(ci.com / "nos" / f"{RUN}.20260929" / "f", "gone")
    odd = [_touch(ci.com / "nos" / n / "f", "keep") for n in (f"{RUN}.2026092", f"{RUN}.20260929x", f"{RUN}_standalone.20260929", f"{RUN}.latest")]
    live_old = _touch(ci.rt / "stofs_3d_atl" / "live" / "2026092912" / "comin" / "f", "gone")
    live_now = _touch(ci.rt / "stofs_3d_atl" / "live" / f"{PDY}12" / "comin" / "f", "keep")
    live_odd = _touch(ci.rt / "stofs_3d_atl" / "live" / "notes" / "f", "keep")
    dsx = _touch(ci.rt / "stofs_3d_atl" / "standalone" / "2026092912" / "f", "keep")
    loose = _touch(ci.com / "other" / "f", "keep")
    hand = _touch(ci.ptmp / "tester" / "com_atl_sa" / "nos" / "mine", "keep")
    gone = [_touch(ci.com / "nos" / f"{RUN}.{d}" / "stale", "old") for d in (PDY, PDYM1)]
    assert ci.run("stage").returncode == 0
    assert not any(g.exists() for g in gone + [other_day, live_old])
    assert all(f.is_file() for f in (secofs, secofs2, loose, hand, live_now, live_odd, dsx, *odd))


def test_stage_refuses_symlinked_or_odd_com_targets(ci):
    ci.dataset()
    victim = _touch(ci.tmp / "victim" / "f", "keep")
    day = ci.com / "nos" / f"{RUN}.{PDY}"
    day.parent.mkdir(parents=True)
    day.symlink_to(victim.parent)
    r = ci.run("stage")
    assert r.returncode == 1 and "is a symlink" in r.stderr and victim.is_file()
    day.unlink()
    shutil.rmtree(ci.com)
    ci.com.symlink_to(victim.parent)
    r = ci.run("stage")
    assert r.returncode == 1 and "refusing to clear" in r.stderr and victim.is_file()
    ci.com.unlink()
    ci.com.mkdir()
    (ci.com / "nos").symlink_to(victim.parent)
    assert ci.run("stage").returncode == 1 and victim.is_file()
    (ci.com / "nos").unlink()
    (ci.com / "nos").mkdir()
    other = ci.com / "nos" / f"{RUN}.20260929"
    other.symlink_to(victim.parent)
    r = ci.run("stage")
    assert r.returncode == 1 and "is a symlink" in r.stderr and victim.is_file()
    other.unlink()
    (ci.rt / "stofs_3d_atl" / "live").mkdir(parents=True)
    (ci.rt / "stofs_3d_atl" / "live" / "2026092912").symlink_to(victim.parent)
    r = ci.run("stage")
    assert r.returncode == 1 and "is a symlink" in r.stderr and victim.is_file()
    for bad in ("..", ".", "a/b"):
        r = ci.run("stage", LOGNAME=bad)
        assert r.returncode == 1 and "odd LOGNAME" in r.stderr, bad
    assert victim.is_file()


def test_stage_removes_the_old_per_variant_roots_once(ci):
    ci.dataset()
    old = [_touch(ci.ptmp / "tester" / f"atl_ci_{v}" / "com" / "f", "old") for v in ("standalone", "coupled")]
    keep = _touch(ci.ptmp / "tester" / "atl_ci_other" / "f", "keep")
    r = ci.run("stage")
    assert r.returncode == 0 and r.stdout.count("removed the old per-variant CI root") == 2, r.stdout
    assert not any(o.exists() for o in old) and keep.is_file()
    assert "removed the old" not in ci.run("stage").stdout
    link = ci.ptmp / "tester" / "atl_ci_standalone"
    link.symlink_to(keep.parent)
    r = ci.run("stage")
    assert r.returncode == 0 and "leaving" in r.stderr and keep.is_file()


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


def test_stage_links_the_day_dirs_only_and_keeps_modes_and_the_dataset_read_only(ci):
    ds = ci.dataset()
    _touch(ds / "input/com/extra/f", "must not be copied")
    for f in (ds / "input").rglob("*"):
        if f.is_file():
            f.chmod(0o444)
    (ci.com / "nos").mkdir(parents=True)
    ci.com.chmod(0o775)
    (ci.com / "nos").chmod(0o775)
    assert ci.run("stage").returncode == 0
    assert oct(ci.com.stat().st_mode & 0o777) == "0o775" and oct((ci.com / "nos").stat().st_mode & 0o777) == "0o775"
    assert not (ci.com / "extra").exists()
    day = ci.com / "nos" / f"{RUN}.{PDY}"
    init = day / f"{RUN}.t12z.{PDY}.init.nowcast.nc"
    assert init.samefile(ds / "input/com/nos" / day.name / init.name) and not os.access(init, os.W_OK) and os.access(day, os.W_OK)
    # a writer replaces the file by name (new file + rename) without touching the shared inode. MJ (10/15/26)
    tmp = _touch(day / "x.tmp", "new")
    os.replace(tmp, init)
    assert init.read_text() == "new" and (ds / "input/com/nos" / day.name / init.name).read_text() == "init"
    # the next Stage Data clears the replaced day and links the dataset again
    assert ci.run("stage").returncode == 0 and init.read_text() == "init"


def test_a_relative_rt_data_root_still_hard_links(ci):
    ci.dataset()
    r = ci.run("stage", RT_DATA_ROOT=os.path.relpath(ci.rt, ci.tmp))
    init = f"nos/{RUN}.{PDY}/{RUN}.t12z.{PDY}.init.nowcast.nc"
    assert r.returncode == 0 and (ci.com / init).samefile(ci.ds / "input/com" / init), r.stderr


def test_seed_makes_dataset_files_read_only_and_the_smoke_upgrade_and_force_still_work(ci):
    com, comin, dcom = _source(ci)
    _nowcast_only(com)
    env = dict(SEED_RT=str(ci.rt))
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), SEED_LEVEL="smoke", **env).returncode == 0
    files = [f for f in (ci.ds / "input").rglob("*") if f.is_file()]
    assert files and not any(os.access(f, os.W_OK) for f in files) and all(os.access(d, os.W_OK) for d in (ci.ds / "input").rglob("*") if d.is_dir())
    com, comin, dcom = _source(ci)
    (com / "nos" / f"{RUN}.{PDYM1}" / "staout_1").write_text("changed")
    r = ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), **env)
    assert r.returncode == 0 and "upgrading" in r.stdout, r.stderr
    assert (ci.ds / "input/com/nos" / f"{RUN}.{PDYM1}" / "staout_1").read_text() == "changed"
    assert ci.run("seed", PDY, "coupled", str(com), str(comin), str(dcom), **env).returncode == 0
    assert ci.run("seed", PDY, "standalone", str(com), str(comin), str(dcom), FORCE="1", **env).returncode == 0


def test_bootstrap_copy_is_read_only_and_a_recopy_over_read_only_files_works(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path)
    sd = seed_rt / "stofs_3d_atl" / "standalone" / f"{PDY}{CYC}"
    boot = dict(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    _touch(sd / "input" / "data", "d")
    assert ci.run(**boot).returncode == 0
    f = ci.ds / "input" / "data"
    assert f.read_text() == "d" and not os.access(f, os.W_OK) and os.access(f.parent, os.W_OK)
    (ci.ds / ".seeded_ok").unlink()
    (sd / "input" / "data").write_text("newer-content")
    assert ci.run(**boot).returncode == 0 and f.read_text() == "newer-content"


def _live(ci: Ci):
    """A DCOM_BUNDLE and stub stage_comin.py / seed scripts that record their arguments. MJ (10/15/26)"""
    b = ci.tmp / "bundle"
    for d in (PDY, PDYM1):
        _touch(b / "dcom" / d / "validation_data/marine/cmems/ssh" / f"nrt_global_allsat_phy_l4_{d}_{d}.nc", "adt")
    sd = b / "seeds" / f"dyn_seed_{PDYM1}"
    _touch(sd / "staout_1", "s")
    _touch(sd / f"{RUN}.t12z.avg_bias", "b")
    _stub(ci.home / "ush" / "stage_comin.py", "import os, sys\na = sys.argv[1:]\nopen(os.environ['STUB_DIR'] + '/stage.calls', 'a').write(' '.join(a) + '\\n')\nos.makedirs(a[a.index('--comroot') + 1] + '/gfs')\n")
    for t in ("init", "prev"):
        _stub(ci.home / "tools" / f"hercules_atl_seed_{t}.sh", f'#!/bin/bash\necho "$*" >> "$STUB_DIR/seed_{t}.calls"\n')
    return b, sd


def test_live_stage_puts_comin_under_rt_data_root_and_the_seeds_in_the_shared_com(ci):
    b, sd = _live(ci)
    stale = _touch(ci.com / "nos" / f"{RUN}.{PDY}" / "stale", "old")
    live = ci.rt / "stofs_3d_atl" / "live" / f"{PDY}{CYC}"
    r = ci.run("stage", DATA_MODE="live", DCOM_BUNDLE=str(b))
    assert r.returncode == 0 and "stage_data PASS" in r.stdout, r.stdout + r.stderr
    assert f"--comroot {live}/comin " in (ci.stubs / "stage.calls").read_text() and (live / "comin" / "gfs").is_dir()
    assert (ci.stubs / "seed_init.calls").read_text().split() == [PDY, f"{ci.com}/nos/{RUN}.{PDY}"]
    assert (ci.stubs / "seed_prev.calls").read_text().split() == [str(sd), str(ci.com), PDY]
    assert not stale.exists() and not (ci.ptmp / "tester" / f"atl_ci_{ci.var}").exists()
    env = ci.run("card-env", "prep", DATA_MODE="live", DCOM_BUNDLE=str(b)).stdout
    assert f"ATL_COMIN={live}/comin" in env and f"DCOMROOT={b}/dcom" in env.replace("\\", "")


def test_live_full_verify_keeps_the_ops_products_beside_the_live_comin(ci):
    _stub(ci.bin / "curl", '#!/bin/bash\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\necho ops > "$out"\n')
    r = ci.run("verify", LEVEL="full", DATA_MODE="live")
    live = ci.rt / "stofs_3d_atl" / "live" / f"{PDY}{CYC}"
    assert r.returncode == 0, r.stdout + r.stderr
    assert (live / "ops" / "stofs_3d_atl.t12z.ncast.station.profile.nc").is_file()
    assert _calls(ci)[-1][:3] == ["ops", "--ops-dir", str(live / "ops")] and _calls(ci)[-1][4] == str(ci.com)


def test_stage_data_sh_hands_over_to_the_atl_stage(ci):
    ci.dataset()
    r = ci.run(script=SCRIPTS / "stage_data.sh")
    assert r.returncode == 0 and (ci.com / "nos").is_dir(), r.stderr + r.stdout


# ---- Prep/Nowcast/Forecast/Post: run_stage.sh with the ATL card-env ---- MJ (10/15/26)

RUN_STAGE = SCRIPTS / "run_stage.sh"


def _job(ci: Ci, stage: str, state="COMPLETED", ok=True, ofs_in_log=RUN, jid=101):
    """Stub sbatch (prints the jobid, records its arguments and a few inherited variables), sacct, scancel, and the card's log. MJ (10/15/26)"""
    _stub(ci.bin / "sbatch", f"""#!/bin/bash
echo "$*" >> "$STUB_DIR/sbatch.calls"; echo "COMOUT=${{COMOUT:-unset}} RPTDIR=${{RPTDIR:-unset}}" >> "$STUB_DIR/sbatch.env"
echo "Submitted batch job {jid}"
""")
    _stub(ci.bin / "sacct", f'#!/bin/bash\necho "{state}"\n')
    _stub(ci.bin / "scancel", '#!/bin/bash\necho "$@" >> "$STUB_DIR/scancel.log"\n')
    pfx = "stofs_3d_atl_ufs_standalone" if ci.var == "standalone" else "stofs_3d_atl_ufs"
    _touch(ci.rpt / f"{pfx}_{stage}_00.{jid}.out", f"STAGE_SUMMARY stage={stage} ofs={ofs_in_log} status={'PASS' if ok else 'FAIL'} runtime_s=1\n")
    _touch(ci.rpt / f"{pfx}_{stage}_00.{jid}.err", "err")
    _touch(ci.ws / f"slurm-{jid}.out", "epilogue")


def _stage(ci: Ci, stage: str, **extra):
    return ci.run(stage, PDY, CYC, script=RUN_STAGE, **extra)


@pytest.mark.parametrize("ofs,comvar,carddir", [("stofs_3d_atl_ufs_standalone", "COMROOT_SA", "stofs_3d_atl_ufs_standalone"), ("stofs_3d_atl_ufs", "COMROOT_UFS", "stofs_3d_atl_ufs")])
@pytest.mark.parametrize("stage", ["prep", "nowcast", "forecast", "post"])
def test_run_stage_submits_the_atl_card_with_its_exports_and_gates_on_the_run_name(tmp_path, ofs, comvar, carddir, stage):
    ci = Ci(tmp_path, ofs)
    _job(ci, stage)
    r = _stage(ci, stage, SLURM_CI_ACCOUNT="nosofs", SLURM_CI_QOS="batch", COMOUT="/leak", RPTDIR="/leak/rpt", COMROOT="/leak/com")
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"PASS[{stage}]: {ci.rpt}/{carddir}_{stage}_00.101.out" in r.stdout
    line = (ci.stubs / "sbatch.calls").read_text()
    assert "--account=nosofs --qos=batch" in line and line.split()[-1] == f"{ci.home}/slurm/{carddir}/jnos_{stage}_00.sh"
    for want in (f"PDY={PDY}", "CYC=12", f"PACKAGEROOT={ci.pk}", f"{comvar}={ci.com}", f"COMROOT_STAGED={ci.ds}/input/comin",
                 f"DCOMROOT={ci.ds}/input/dcom", f"EXECnos={ci.home}/exec", "COLDSTART=NO",
                 f"NOS_VENV={ci.venv}", f"NOS_PTMP={ci.ptmp}", f"OFS={RUN}"):
        assert want in line, (want, line)
    assert line.count("COMROOT_STAGED=") == 1 and line.count("--export=") == 1 and "RPTDIR" not in line and "atl_ci" not in line
    assert (ci.stubs / "sbatch.env").read_text().strip() == "COMOUT=unset RPTDIR=unset"
    assert ci.rpt.is_dir() and not (ci.rpt.parent / "stofs_3d_atl_ufs_standalone").exists()
    assert (ci.ws / "ci_logs" / "current_jobid").read_text().split()[-1] == "101"
    logs = sorted(p.name for p in (ci.ws / "ci_logs").iterdir())
    pfx = carddir
    assert f"{pfx}_{stage}_00.101.out" in logs and f"{pfx}_{stage}_00.101.err" in logs and "slurm_epilogue.slurm-101.out" in logs


def test_run_stage_gate_uses_the_run_name_for_the_standalone_variant_and_rejects_the_ofs_name(ci):
    _job(ci, "prep", ofs_in_log="stofs_3d_atl_ufs_standalone")
    r = _stage(ci, "prep")
    assert r.returncode == 1 and "FAIL[prep]: no STAGE_SUMMARY PASS" in r.stdout


@pytest.mark.parametrize("state,ok", [("COMPLETED", False), ("FAILED", False), ("TIMEOUT", False)])
def test_run_stage_fails_on_a_bad_log_or_state_and_keeps_the_run_directory(ci, state, ok):
    w = _work(ci, "stofs_3d_atl_ufs_standalone")
    _job(ci, "nowcast", state=state, ok=ok)
    r = _stage(ci, "nowcast")
    assert r.returncode == 1 and "FAIL[nowcast]" in r.stdout
    assert len(list(w.iterdir())) == 3


def test_run_stage_pass_deletes_only_that_jobs_run_directory(ci):
    w = _work(ci, "stofs_3d_atl_ufs_standalone")
    secofs = _touch(ci.ptmp / "tester" / "work" / "secofs_ufs" / "job.101" / "x", "keep")
    other = _touch(ci.ptmp / "tester" / "work" / "stofs_3d_atl_ufs" / "job.101" / "x", "keep")
    _job(ci, "prep")
    assert _stage(ci, "prep").returncode == 0
    assert not list(w.glob("*.101")) and list(w.glob("*.102")) and list(w.glob("*.999"))
    assert secofs.is_file() and other.is_file()


def test_clean_job_keeps_the_depth_and_symlink_guards(ci):
    assert ci.run("clean-job", "101", NOS_PTMP=str(ci.ptmp)).returncode == 0
    work = ci.ptmp / "tester" / "work"
    work.mkdir(parents=True, exist_ok=True)
    victim = _touch(ci.tmp / "victim" / "x.101" / "f", "keep")
    (work / "stofs_3d_atl_ufs_standalone").symlink_to(victim.parent.parent)
    r = ci.run("clean-job", "101")
    assert r.returncode == 1 and "refusing to clean" in r.stderr and victim.is_file()
    assert ci.run("clean-job").returncode == 1


def test_card_env_refuses_a_comma_in_a_path(ci):
    r = ci.run("card-env", "prep", PACKAGEROOT=str(ci.tmp / "a,b"))
    assert r.returncode != 0


@pytest.mark.parametrize("ofs,stage,secs", [
    ("stofs_3d_atl_ufs_standalone", "prep", 12600), ("stofs_3d_atl_ufs_standalone", "nowcast", 10800), ("stofs_3d_atl_ufs_standalone", "forecast", 23400),
    ("stofs_3d_atl_ufs_standalone", "post", 9000), ("stofs_3d_atl_ufs", "post", 16200),
])
def test_run_stage_timeout_cancels_a_hung_atl_job_after_its_limit(tmp_path, ofs, stage, secs):
    ci = Ci(tmp_path, ofs)
    # a stub date that jumps past the limit on its second +%s call; the first is t0 (other date calls pass through). MJ (10/15/26)
    _job(ci, stage, state="RUNNING", ok=False)
    _stub(ci.bin / "date", f'#!/bin/bash\n[ "$1" = +%s ] || exec /bin/date "$@"\nn=$(cat "$STUB_DIR/d" 2>/dev/null || echo 0); echo $((n+1)) > "$STUB_DIR/d"\n[ $n -eq 0 ] && echo 1000 || echo {1000 + secs}\n')
    r = _stage(ci, stage)
    assert r.returncode == 1 and f"rc=timeout" in r.stdout and (ci.stubs / "scancel.log").read_text().split() == ["101"]
    assert f"after {secs}s" in r.stdout


def test_run_stage_queue_wait_does_not_count_against_the_limit(tmp_path):
    ci = Ci(tmp_path, "stofs_3d_atl_ufs_standalone")
    # PENDING for twice the limit, then COMPLETED: the clock restarts while queued, so the stage passes (build #24 timed out this way). MJ (10/19/26)
    _job(ci, "nowcast")
    _stub(ci.bin / "sacct", '#!/bin/bash\nn=$(cat "$STUB_DIR/s" 2>/dev/null || echo 0); echo $((n+1)) > "$STUB_DIR/s"\n[ $n -eq 0 ] && echo PENDING || echo COMPLETED\n')
    _stub(ci.bin / "date", '#!/bin/bash\n[ "$1" = +%s ] || exec /bin/date "$@"\nn=$(cat "$STUB_DIR/d" 2>/dev/null || echo 0); echo $((n+1)) > "$STUB_DIR/d"\n[ $n -eq 0 ] && echo 1000 || echo 22600\n')
    _stub(ci.bin / "squeue", "#!/bin/bash\necho Priority\n")
    _stub(ci.bin / "sleep", "#!/bin/bash\n")
    r = _stage(ci, "nowcast")
    assert r.returncode == 0 and "PASS[nowcast]" in r.stdout and "rc=timeout" not in r.stdout
    assert not (ci.stubs / "scancel.log").exists()


@pytest.mark.parametrize("why", ["JobHeldUser", "QOSMaxNodePerJobLimit", "PartitionTimeLimit", "InvalidAccount"])
def test_run_stage_cancels_a_job_that_can_never_start(tmp_path, why):
    ci = Ci(tmp_path, "stofs_3d_atl_ufs_standalone")
    _job(ci, "nowcast", state="PENDING", ok=False)
    _stub(ci.bin / "squeue", f"#!/bin/bash\necho {why}\n")
    r = _stage(ci, "nowcast")
    assert r.returncode == 1 and f"rc=unstartable -- jobid 101 pending ({why})" in r.stdout
    assert (ci.stubs / "scancel.log").read_text().split() == ["101"]


@pytest.mark.parametrize("stage,card", [(s, c) for s in ("prep", "nowcast", "forecast", "post") for c in ("stofs_3d_atl_ufs_standalone", "stofs_3d_atl_ufs")])
def test_atl_timeouts_cover_the_card_walltimes(stage, card):
    text = (REPO / ".cicd" / "scripts" / "run_stage.sh").read_text()
    block = text[text.index("stofs_3d_atl_ufs_standalone|stofs_3d_atl_ufs)"):]
    m = re.search(rf"^\s*{stage}\)\s*TIMEOUT_S=(\d+)(?:; \[ \"\$\{{OFS\}}\" = stofs_3d_atl_ufs \] && TIMEOUT_S=(\d+))?", block, re.M)
    limit = int(m.group(2) or m.group(1)) if card == "stofs_3d_atl_ufs" else int(m.group(1))
    h, mi, sec = map(int, re.search(r"^#SBATCH\s+--time=(\d+):(\d+):(\d+)", (REPO / "slurm" / card / f"jnos_{stage}_00.sh").read_text(), re.M).groups())
    assert limit >= h * 3600 + mi * 60 + sec + 1800


def test_the_secofs_path_of_run_stage_is_untouched_by_the_atl_hooks(tmp_path):
    ci = Ci(tmp_path, "secofs_ufs")
    _stub(ci.bin / "sbatch", '#!/bin/bash\necho "$*" >> "$STUB_DIR/sbatch.calls"\necho "Submitted batch job 7"\n')
    _stub(ci.bin / "sacct", '#!/bin/bash\necho COMPLETED\n')
    (ci.home / "slurm").unlink()
    card = _touch(ci.home / "slurm" / "secofs_ufs" / "jnos_prep_00.sh", "RPTDIR=" + str(ci.tmp / "rptdir") + "\n")
    _touch(ci.tmp / "rptdir" / "secofs_ufs_prep_00.7.out", "STAGE_SUMMARY stage=prep ofs=secofs_ufs status=PASS\n")
    r = _stage(ci, "prep")
    assert r.returncode == 0, r.stdout + r.stderr
    call = (ci.stubs / "sbatch.calls").read_text().strip()
    assert call == f"--export=ALL,PDY={PDY},CYC=12,COMROOT_STAGED={ci.rt}/comin_{PDY}12,NOS_VENV={ci.venv},NOS_PTMP={ci.ptmp} {card}"


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
    assert ops == ["ops", "--ops-dir", str(ci.ds / "ref" / "ops"), "--out", str(ci.com), "--variant", "standalone", "--pdy", PDY, "--warn-mm", "500",
                   "--fail-median-mm", "5", "--fail-over-10cm", "10"]
    (ci.stubs / "cmp.calls").unlink()
    assert ci.run("verify", LEVEL="full", OPS_FAIL_MEDIAN_MM="2", OPS_FAIL_OVER_10CM="3").returncode == 0
    assert _calls(ci)[1][-4:] == ["--fail-median-mm", "2", "--fail-over-10cm", "3"]
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
    (ci.stubs / "cmp.calls").unlink()
    assert ci.run("verify", LEVEL="full").returncode == 0
    assert _calls(ci)[1][-4:] == ["--fail-median-mm", "15", "--fail-over-10cm", "10"]
    (ci.stubs / "cmp.calls").unlink()
    assert ci.run("verify", LEVEL="full", OPS_FAIL_MEDIAN_MM="8", OPS_FAIL_OVER_10CM="4").returncode == 0
    assert _calls(ci)[1][-4:] == ["--fail-median-mm", "8", "--fail-over-10cm", "4"]


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


def test_a_failed_stage_leaves_its_directories_for_the_next_stage_data_to_clear(ci):
    ci.dataset()
    w = _work(ci, "stofs_3d_atl_ufs_standalone")
    secofs = _touch(ci.ptmp / "tester" / "work" / "secofs_ufs" / "job.1" / "x", "keep")
    assert ci.run("stage").returncode == 0
    assert not w.exists() and secofs.is_file()


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
    for e in ("stofs_3d_atl_tide_fac", "schism_combine_hotstart7.exe", "fv3_stofs_3d_atl.exe", "stofs_3d_atl_pschism_v3.1.5", "combine_output11_MPI", "other_tool"):
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
    assert (ci.home / "exec" / "combine_output11_MPI").exists() == (not ofs.endswith("standalone"))  # coupled only. MJ (10/22/26)
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
    keep = _touch(ci.com / "nos" / f"{RUN}.{PDY}" / "keep", "old")
    for level in ("cycle", "full"):
        r = ci.run("stage", LEVEL=level)
        assert r.returncode == 1 and f"dataset {ci.ds} holds smoke references only; run LEVEL=smoke, or re-seed with SEED_LEVEL=cycle once the source run has forecast and post" in r.stdout
        assert keep.is_file()
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


# bootstrap: readable-file preflight and the quiet dataset copy. MJ (10/15/26)
def _boot(tmp_path, ofs="stofs_3d_atl_ufs_standalone"):
    ci = Ci(tmp_path, ofs)
    src = _atl_seed_src(ci, ofs)
    _stub(ci.venv / "bin" / "python")
    _stub(ci.home / "exec" / "schism_combine_hotstart7.exe")
    seed_rt = tmp_path / "seed_rt"
    _touch(seed_rt / "stofs_3d_atl" / ci.var / f"{PDY}{CYC}" / "data", "d")
    log = tmp_path / "rsync.argv"
    real = shutil.which("rsync")
    _stub(ci.bin / "rsync", f'#!/bin/bash\necho "$@" >> {log}\nexec {real} "$@"\n')
    return ci, src, seed_rt, log


def _preseed(ci, ofs):
    """A CI exec/ seeded before combine_output11_MPI was needed: sentinel, an old fv3 exe, no combiner. MJ (10/22/26)"""
    _stub(ci.home / "exec" / "stofs_3d_atl_tide_fac")
    _stub(ci.home / "exec" / "fv3_stofs_3d_atl.exe", "#!/bin/bash\n# old\n")
    _touch(ci.home / "exec" / f".seeded_ok.{ofs}")
    _touch(ci.home / "fix" / "stofs_3d_atl_ufs" / ".seeded_ok")


def test_bootstrap_coupled_adds_a_missing_executable_without_replacing_others(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path, "stofs_3d_atl_ufs")
    _preseed(ci, "stofs_3d_atl_ufs")
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "bootstrap: adding missing executables to exec/: combine_output11_MPI" in r.stdout
    assert (ci.home / "exec" / "combine_output11_MPI").is_file()
    assert "# old" in (ci.home / "exec" / "fv3_stofs_3d_atl.exe").read_text()
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    assert "already present, skipping exec/ seed" in r.stdout


def test_bootstrap_coupled_fails_when_the_source_has_no_combiner(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path, "stofs_3d_atl_ufs")  # MJ (10/22/26)
    _preseed(ci, "stofs_3d_atl_ufs")
    (src / "exec" / "combine_output11_MPI").unlink()
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    assert r.returncode == 1 and "combine_output11_MPI still missing" in r.stdout


def test_bootstrap_standalone_with_a_sentinel_adds_nothing(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path)
    _stub(ci.home / "exec" / "stofs_3d_atl_tide_fac")
    _stub(ci.home / "exec" / "stofs_3d_atl_pschism_v3.1.5")
    _touch(ci.home / "exec" / ".seeded_ok.stofs_3d_atl_ufs_standalone")
    _touch(ci.home / "fix" / "stofs_3d_atl_ufs" / ".seeded_ok")
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    assert r.returncode == 0 and "adding missing" not in r.stdout and not (ci.home / "exec" / "combine_output11_MPI").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_bootstrap_coupled_unreadable_combiner_gets_the_chmod_hint(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path, "stofs_3d_atl_ufs")
    _preseed(ci, "stofs_3d_atl_ufs")
    bad = src / "exec" / "combine_output11_MPI"
    bad.chmod(0)
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    assert r.returncode == 1 and f"chmod o+rx {bad}" in r.stdout and not (ci.home / "exec" / "combine_output11_MPI").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_bootstrap_fails_before_rsync_on_an_unreadable_fix_file(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path)
    bad = src / "fix" / "stofs_3d_atl_ufs" / "grid"
    bad.chmod(0)
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    assert r.returncode == 1 and f"FATAL: {bad} is not readable by" in r.stdout
    assert f"chmod -R o+rX {src}/fix/stofs_3d_atl_ufs" in r.stdout and not log.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_bootstrap_fails_before_rsync_on_an_unreadable_executable(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path)
    bad = src / "exec" / "stofs_3d_atl_pschism_v3.1.5"
    bad.chmod(0)
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    assert r.returncode == 1 and f"chmod o+rx {bad}" in r.stdout
    assert [l for l in (log.read_text().splitlines() if log.exists() else []) if "exec" in l] == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_bootstrap_preflight_ignores_a_symlink_to_an_unreadable_target(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path)
    target = _touch(tmp_path / "other_pkg" / "secret", "x")
    target.chmod(0)
    (src / "fix" / "stofs_3d_atl_ufs" / "link").symlink_to(target)
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    assert r.returncode == 0 and "is not readable" not in r.stdout, r.stdout + r.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_bootstrap_preflight_fails_on_an_unreadable_subdirectory(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path)
    sub = src / "fix" / "stofs_3d_atl_ufs" / "closed"
    _touch(sub / "f", "x")
    sub.chmod(0)
    try:
        r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    finally:
        sub.chmod(0o755)
    assert r.returncode == 1 and f"FATAL: {sub} is not readable by" in r.stdout and f"chmod -R o+rX {sub}" in r.stdout and not log.exists()


def test_run_stage_never_submits_when_card_env_fails(ci):
    _job(ci, "prep")
    r = _stage(ci, "prep", DCOM_BUNDLE=None, DATA_MODE="live")
    assert r.returncode == 2 and not (ci.stubs / "sbatch.calls").exists()


def test_bootstrap_dataset_copy_prints_one_summary_line_and_no_progress(tmp_path):
    ci, src, seed_rt, log = _boot(tmp_path)
    r = ci.run(script=SCRIPTS / "bootstrap.sh", SEED_SRC=str(src), SEED_RT=str(seed_rt))
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(re.findall(r"^bootstrap: dataset copied: \d+ files, \S+, \d+ s$", r.stdout, re.M)) == 1
    calls = log.read_text()
    assert "progress2" not in calls and "--exclude=/.seeded_ok" in calls and "--stats" in calls
    assert "to-chk" not in r.stdout
