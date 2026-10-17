"""STOFS-2D-Global job cards and fix-fetch tool. Offline."""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.machine import MachineProfile  # noqa: E402

RANKS = 4064
WALL = {"prep": "06:00:00", "nowcast": "06:00:00", "forecast": "03:00:00"}
STAGES = list(WALL)
PBS = REPO / "pbs" / "stofs_2d_glo"
SLURM = REPO / "slurm" / "stofs_2d_glo"
FETCH = REPO / "tools" / "fetch_stofs_2d_glo_fix.sh"
LAUNCH = PBS / "launch_stofs_2d_glo.sh"
TAG = "MJ (10/05/26)"
GATE = "grep -q 'STAGE_SUMMARY .*status=PASS' \"${_LOG_PREFIX}.out\" || exit 1"
LAST = {"prep": "JNOS_PREP", "nowcast": "JNOS_NOWCAST", "forecast": "JNOS_FORECAST"}


def _lines(path: Path, prefix: str) -> list:
    return [l.rstrip("\n") for l in path.read_text().splitlines() if l.startswith(prefix)]


@pytest.fixture()
def hercules():
    return MachineProfile.load("hercules", machines_dir=REPO / "parm" / "machines", validate=False)


@pytest.fixture()
def wcoss2():
    return MachineProfile.load("wcoss2", machines_dir=REPO / "parm" / "machines", validate=False)


def test_wcoss2_node_math(wcoss2):
    # The system yaml packs 128 ranks per node on WCOSS2 (ops layout); the profile default is 120.
    assert wcoss2.allocation.cores_per_node == 128
    nodes = math.ceil(RANKS / 128)
    assert nodes == 32
    for stage in ("nowcast", "forecast"):
        pbs = _lines(PBS / f"jnos_{stage}_00.pbs", "#PBS")
        assert f"#PBS  -l place=vscatter:excl,select={nodes}:ncpus=128:mpiprocs=128:ompthreads=1" in pbs
        assert f"#PBS  -l walltime={WALL[stage]}" in pbs
        assert f"#PBS  -A {wcoss2.account}" in pbs and f"#PBS  -q {wcoss2.queue}" in pbs
    # 4064 + up to 32 writer ranks must fit the 32 x 128 slots (the surf default is 4 writers). MJ (10/17/26)
    assert nodes * 128 - RANKS == 32


def test_wcoss2_prep_card():
    pbs = _lines(PBS / "jnos_prep_00.pbs", "#PBS")
    assert "#PBS  -l select=1:ncpus=8:mpiprocs=8:mem=100GB" in pbs
    assert "#PBS  -l place=vscatter" in pbs
    assert f"#PBS  -l walltime={WALL['prep']}" in pbs


def test_hercules_node_math(hercules):
    assert hercules.allocation.ranks_per_node == 80
    nodes = hercules.nodes(RANKS)
    assert nodes == 51 == math.ceil(RANKS / 80)
    for stage in ("nowcast", "forecast"):
        sb = _lines(SLURM / f"jnos_{stage}_00.sh", "#SBATCH")
        assert f"#SBATCH --nodes={nodes}" in sb
        assert "#SBATCH --ntasks-per-node=80" in sb
        assert "#SBATCH --exclusive" in sb
        assert f"#SBATCH --time={WALL[stage]}" in sb
        assert f"export TOTAL_TASKS=${{TOTAL_TASKS:-{RANKS}}}" in (SLURM / f"jnos_{stage}_00.sh").read_text()
    sb = _lines(SLURM / "jnos_prep_00.sh", "#SBATCH")
    assert "#SBATCH --nodes=1" in sb and "#SBATCH --ntasks=8" in sb and "#SBATCH --mem=0" in sb
    assert f"#SBATCH --time={WALL['prep']}" in sb
    for stage in STAGES:
        sb = _lines(SLURM / f"jnos_{stage}_00.sh", "#SBATCH")
        for want in ("--account=nos-surge", "--qos=batch", "--partition=hercules"):
            assert f"#SBATCH {want}" in sb


@pytest.mark.parametrize("stage", STAGES)
def test_pbs_card_exports(stage):
    card = PBS / f"jnos_{stage}_00.pbs"
    text = card.read_text()
    subprocess.run(["bash", "-n", str(card)], check=True)
    for needle in ("export OFS=stofs_2d_glo\n", "export NET=nos RUN=stofs_2d_glo PREFIXNOS=stofs_2d_glo\n",
                   "export cyc=${CYC:-12}", "export PDY=${PDY:?", "export framework=adcirc",
                   "COMROOT=${COMROOT_2DGLO:-/lfs/h1/nos/ptmp/$LOGNAME/com}", "export HOMEnos\n",
                   "OFS_CONFIG=${HOMEnos}/parm/systems/stofs_2d_glo.yaml", "ADCIRC_EXEC_DIR",
                   "stofs_2d_glo_grid stofs_2d_glo_attr", "fetch_stofs_2d_glo_fix.sh", TAG):
        assert needle in text, needle
    assert "OFS:-" not in text and "COMROOT=${COMROOT:-" not in text and "DATAROOT:-" not in text
    assert text.rstrip().endswith(GATE) and LAST[stage] in text
    assert text.index("_py_ver=${python_ver:-}") < text.index('. "${STOFS_RUNVER}"') < text.index("python_ver=${_py_ver}")


@pytest.mark.parametrize("stage", STAGES)
def test_slurm_card_exports(stage):
    card = SLURM / f"jnos_{stage}_00.sh"
    text = card.read_text()
    subprocess.run(["bash", "-n", str(card)], check=True)
    for needle in ("PACKAGEROOT=${PACKAGEROOT:?", "slurm/stofs_2d_glo", "versions/run.hercules.ver",
                   "export NOS_MACHINE=hercules", "export OFS=stofs_2d_glo\n",
                   "export NET=nos RUN=stofs_2d_glo PREFIXNOS=stofs_2d_glo\n", "export cyc=${CYC:-12}",
                   "export PDY=${PDY:?", "COMROOT=${COMROOT_2DGLO:-${NOS_PTMP}/$LOGNAME/com}",
                   "ADCIRC_EXEC_DIR=${ADCIRC_EXEC_DIR:?", "stofs_2d_glo.yaml",
                   "export NOS_UTILS_DIR=${HOMEnos}/ush/python/nos-utils\n",
                   "export NOS_WORKFLOW_DIR=${HOMEnos}/ush/python\n",
                   "import nos_utils", 'readlink -f "${NOS_UTILS_DIR}"', "NOS_ALLOW_NU_MISMATCH",
                   "stofs_2d_glo_grid stofs_2d_glo_attr", TAG):
        assert needle in text, needle
    assert text.index("export NOS_UTILS_DIR=") < text.index("import nos_utils")
    assert "MPICH_" not in text and "mpiexec" not in text and "qsub" not in text
    assert "COMROOT=${COMROOT:-" not in text and "DATAROOT:-" not in text and "OFS:-" not in text
    unset_line = next(l for l in text.splitlines() if l.startswith("unset NCPU"))
    for var in ("NCPU", "NUM_WRITERS", "TOT_NCPU", "NTASKS", "USHnos", "SCRIPTSnos", "PARMnos", "FIXofs"):
        assert var in unset_line.split(), var
    assert any(l.startswith("unset COMOUT") for l in text.splitlines())
    assert text.rstrip().endswith(GATE) and LAST[stage] in text
    if stage != "prep":
        assert "I_MPI_EXTRA_FILESYSTEM=ON" in text and "FI_MLX_INJECT_LIMIT=0" in text
        assert "export ADCIRC_ALLOC_RANKS=${SLURM_NTASKS}" in text


def test_cards_never_touch_secofs_or_atl():
    for card in list(PBS.iterdir()) + list(SLURM.iterdir()):
        text = card.read_text()
        for bad in ("secofs", "stofs_3d_atl", "com_atl", "COMROOT_SA", "COMROOT_UFS"):
            assert bad not in text.replace("SECOFS or ATL", "").replace("SECOFS and ATL", ""), (card, bad)
    for other in [REPO / "pbs" / "stofs_3d_atl_ufs", REPO / "pbs" / "stofs_3d_atl_ufs_standalone",
                  REPO / "slurm" / "stofs_3d_atl_ufs", REPO / "slurm" / "stofs_3d_atl_ufs_standalone",
                  REPO / "slurm" / "secofs_ufs"]:
        for f in other.glob("*"):
            assert "2d_glo" not in f.read_text(), f
    for f in (REPO / "pbs").glob("*.pbs"):
        assert "2d_glo" not in f.read_text(), f


def test_launcher():
    subprocess.run(["bash", "-n", str(LAUNCH)], check=True)
    text = LAUNCH.read_text()
    assert os.access(LAUNCH, os.X_OK)
    assert "afterok" in text and 'STAGES="${STAGES:-prep nowcast forecast}"' in text
    assert "COMROOT_2DGLO" in text and "OFS=" not in text.replace("OFS_", "")
    for v in ("ATMOSPHERIC_FORCING", "COLDSTART_SPINUP_DAYS", "NOWCAST_HOURS"):
        assert v in text.split("for _v in")[1].split(";")[0], v


def test_prep_cards_preflight_cfgrib():
    for card in (PBS / "jnos_prep_00.pbs", SLURM / "jnos_prep_00.sh"):
        text = card.read_text()
        assert "import xarray, cfgrib, eccodes" in text, card
        assert text.index("import xarray, cfgrib, eccodes") < text.index("jobs/JNOS_PREP"), card
    r = subprocess.run(["bash", str(LAUNCH), "20261005", "07"], capture_output=True, text=True)
    assert r.returncode == 2 and "CYC must be" in r.stderr
    assert subprocess.run(["bash", str(LAUNCH)], capture_output=True).returncode == 2


def test_fetch_tool(tmp_path):
    subprocess.run(["bash", "-n", str(FETCH)], check=True)
    text = FETCH.read_text()
    for needle in ("1,726,781,115", "1,531,075,596", "3,900,032,696", ".partial", "curl -sf -C -", TAG):
        assert needle in text
    ops, dest = tmp_path / "ops", tmp_path / "fix"
    ops.mkdir()
    for n in ("attr", "rotm", "elev_stat", "met", "station.ctl", "msl2mllw", "surf.15", "tide.15"):
        (ops / f"stofs_2d_glo_{n}").write_text(f"x{n}\n")
    (ops / "stofs_2d_glo_grid").write_text("mesh\n24875000 12785000\n")
    env = {**os.environ, "OPS_DIR": str(ops)}
    r = subprocess.run(["bash", str(FETCH), str(dest)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (dest / "stofs_2d_glo_grid").is_file() and (dest / "stofs_2d_glo_attr").is_file()
    assert not list(dest.glob("*.partial")) and not (dest / "stofs_2d_glo_body").exists()
    r2 = subprocess.run(["bash", str(FETCH), str(dest)], env=env, capture_output=True, text=True)
    assert r2.stdout.count("SKIP") == 9 and "COPY" not in r2.stdout
    # a wrong-size existing file is re-copied; a missing source fails and says so
    (dest / "stofs_2d_glo_rotm").write_text("short")
    r3 = subprocess.run(["bash", str(FETCH), str(dest)], env=env, capture_output=True, text=True)
    assert "COPY  stofs_2d_glo_rotm" in r3.stdout
    (ops / "stofs_2d_glo_met").unlink()
    env["OPS_URL"] = "file:///nonexistent"
    r4 = subprocess.run(["bash", str(FETCH), str(tmp_path / "d2")], env=env, capture_output=True, text=True)
    assert r4.returncode == 1 and "FAIL  stofs_2d_glo_met" in r4.stdout
    # an implausible mesh is flagged
    (ops / "stofs_2d_glo_grid").write_text("mesh\n10 5\n")
    (ops / "stofs_2d_glo_met").write_text("m\n")
    r5 = subprocess.run(["bash", str(FETCH), str(tmp_path / "d3")], env={**os.environ, "OPS_DIR": str(ops)},
                        capture_output=True, text=True)
    assert r5.returncode == 2 and "WARNING" in r5.stdout


@pytest.mark.parametrize("card", sorted(PBS.glob("jnos_*.pbs")) + sorted(SLURM.glob("jnos_*.sh")))
def test_ops_mode_is_chosen_at_submit_time(card):
    text = card.read_text()
    assert "export ADCIRC_MODE=${ADCIRC_MODE:-single}\n" in text
    assert not [l for l in text.splitlines() if l.startswith(("export ADCIRC_STREAM", "export ADCIRC_SEGMENT",
                                                              "export ADCIRC_MODE=ops"))]
    if "nowcast" in card.name:
        for needle in ("four jobs", "adcprep", "spinup", "ADCIRC_STREAM", "done-markers", "-t 3:50:00" if card.suffix == ".sh" else "walltime=3:50:00"):
            assert needle in text, needle
        assert "ADCIRC_STREAM=tide,ADCIRC_SEGMENT" not in text  # the 11-job per-step examples are gone MJ (10/14/26)
        # a hand-typed list is space separated and the whole -v / --export value is double-quoted, or qsub / sbatch refuse the stray words. MJ (10/14/26)
        forms = [l for l in text.splitlines() if l.startswith("#   ") and ("qsub " in l or "sbatch " in l)]
        assert len(forms) == 4 and not [l for l in forms if "'" in l]
        assert all(('-v "PDY=' in l) if card.suffix == ".pbs" else ('--export="ALL,PDY=' in l) for l in forms)
    if "prep" not in card.name:
        assert "export ADCIRC_ALLOC_RANKS=" in text and "_tot" not in text


def test_keepdata_is_a_submit_time_override():
    for card in list(PBS.glob("jnos_*_00.pbs")) + list(SLURM.glob("jnos_*_00.sh")):
        text = card.read_text()
        assert "export KEEPDATA=${KEEPDATA:-YES}" in text and "KEEPDATA=YES\n" not in text.replace(":-YES}", "")


def _ops_launch(tmp_path, args=("20261005", "12"), **env):
    qsub = tmp_path / "bin" / "qsub"
    qsub.parent.mkdir()
    # one tab-separated line per call: the -v value carries spaces. MJ (10/14/26)
    qsub.write_text('#!/bin/bash\nn=$(cat $QLOG.n 2>/dev/null || echo 0); n=$((n+1)); echo $n > $QLOG.n\n'
                    '{ printf "%s" "$n.pbs"; printf "\\t%s" "$@"; echo; } >> $QLOG; echo $n.pbs\n')
    qsub.chmod(0o755)
    log = tmp_path / "q.log"
    e = {k: v for k, v in os.environ.items() if k not in ("STAGES", "STREAMS", "COLDSTART", "KEEPDATA", "PLACE")}
    e.update({"PATH": f"{qsub.parent}:{os.environ['PATH']}", "QLOG": str(log), "PKG": str(REPO), "ADCIRC_MODE": "ops", **env})
    r = subprocess.run(["bash", str(LAUNCH), *args], env=e, capture_output=True, text=True)
    if r.returncode != 0:
        return r
    jobs = {}
    for ln in log.read_text().splitlines():
        jid, *a = ln.split("\t")
        # qsub -v splits at commas, so a list value is space separated: ADCIRC_SEGMENT=ncst fcst. MJ (10/14/26)
        v = dict(kv.split("=", 1) for kv in a[a.index("-v") + 1].split(","))
        dep = a[a.index("-W") + 1].split(":")[1:] if "-W" in a else []
        ls = [a[i + 1] for i, x in enumerate(a) if x == "-l"]
        pick = lambda k: next((x.split("=", 1)[1] for x in ls if x.startswith(k + "=")), "")  # noqa: E731
        jobs[a[1 + a.index("-N")][len("stofs_2d_glo_"):]] = dict(
            jid=jid, dep=dep, v=v, wall=pick("walltime"), sel=pick("select"), place=pick("place"), card=Path(a[-1]).name, raw=a)
    return jobs


def _deps(j):
    ids = {v["jid"]: k for k, v in j.items()}
    return {k: sorted(ids[d] for d in v["dep"]) for k, v in j.items()}


def test_launcher_ops_job_graph(tmp_path):
    j = _ops_launch(tmp_path)
    assert list(j) == ["prep", "nowcast", "forecast", "post"]
    assert _deps(j) == {"prep": [], "nowcast": ["prep"], "forecast": ["nowcast"], "post": ["forecast"]}
    assert {k: v["card"] for k, v in j.items()} == {"prep": "jnos_prep_00.pbs", "nowcast": "jnos_nowcast_00.pbs",
                                                    "forecast": "jnos_forecast_00.pbs", "post": "jnos_prep_00.pbs"}
    for v in j.values():
        assert v["v"]["PDY"] == "20261005" and v["v"]["CYC"] == "12" and v["v"]["KEEPDATA"] == "NO"
        assert v["v"]["ADCIRC_MODE"] == "ops" and "COLDSTART" not in v["v"]
    assert {k: v["v"]["ADCIRC_SEGMENT"] for k, v in j.items()} == {
        "prep": "ncst fcst", "nowcast": "ncst", "forecast": "fcst", "post": "anomaly bias ncdiff grib2 ncrcat"}
    assert {k: v["v"].get("ADCIRC_STREAM") for k, v in j.items()} == {"prep": None, "nowcast": "tide surf", "forecast": "tide surf", "post": None}
    # the walltimes are the sums of the former per-job ones (warm). MJ (10/14/26)
    assert {k: v["wall"] for k, v in j.items()} == {"prep": "0:50:00", "nowcast": "0:50:00", "forecast": "2:00:00", "post": "3:10:00"}
    assert {k: v["sel"] for k, v in j.items()} == {"prep": "1:ncpus=1:prepost=true:mem=400gb", "nowcast": "", "forecast": "",
                                                   "post": "8:ncpus=32:prepost=true:mem=800gb"}
    assert {k: v["place"] for k, v in j.items()} == {"prep": "", "nowcast": "", "forecast": "", "post": "vscatter:exclhost"}


def test_launcher_ops_cold_start_and_forwarded_overrides(tmp_path):
    j = _ops_launch(tmp_path, COLDSTART="YES", NOWCAST_HOURS="24", KEEPDATA="YES")
    assert list(j) == ["prep", "nowcast", "forecast", "post"] and _deps(j)["nowcast"] == ["prep"]
    assert all(v["v"]["KEEPDATA"] == "YES" and v["v"]["NOWCAST_HOURS"] == "24" for v in j.values())
    assert (j["prep"]["v"]["ADCIRC_SEGMENT"], j["prep"]["wall"]) == ("adcprep ncst fcst", "3:50:00")
    assert (j["nowcast"]["v"]["ADCIRC_SEGMENT"], j["nowcast"]["wall"]) == ("spinup ncst", "1:50:00")
    assert (j["forecast"]["wall"], j["post"]["wall"]) == ("2:00:00", "3:10:00")
    # COLDSTART is the launcher's own switch: a job that reads it from the environment would repeat the cold start. MJ (10/14/26)
    assert not any("COLDSTART" in v["v"] for v in j.values())


def test_launcher_ops_stages_link_only_the_submitted_jobs(tmp_path):
    j = _ops_launch(tmp_path, STAGES="nowcast forecast")
    assert list(j) == ["nowcast", "forecast"] and _deps(j) == {"nowcast": [], "forecast": ["nowcast"]}
    (tmp_path / "bin").rename(tmp_path / "bin1")
    (tmp_path / "q.log").unlink()
    (tmp_path / "q.log.n").unlink()
    j = _ops_launch(tmp_path, STAGES="prep post")
    assert list(j) == ["prep", "post"] and _deps(j) == {"prep": [], "post": ["prep"]}
    assert j["post"]["v"]["ADCIRC_SEGMENT"] == "anomaly bias ncdiff grib2 ncrcat"


@pytest.mark.parametrize("stages", ["nowcast prep", "prep prep", "gfs", "prep nowcast forecast post extra", "forecast prep"])
def test_launcher_ops_stages_must_be_an_ordered_subset(tmp_path, stages):
    r = _ops_launch(tmp_path, STAGES=stages)
    assert r.returncode == 2 and "STAGES must be a subset" in r.stderr and not (tmp_path / "q.log").exists()


@pytest.mark.parametrize("streams,want", [("surf", "surf"), ("tide", "tide"), ("tide surf", "tide surf"), ("tide,surf", "tide surf"), ("tide, surf", "tide surf")])
def test_launcher_ops_streams_are_passed_as_adcirc_stream(tmp_path, streams, want):
    j = _ops_launch(tmp_path, STREAMS=streams)
    assert j["nowcast"]["v"]["ADCIRC_STREAM"] == j["forecast"]["v"]["ADCIRC_STREAM"] == want
    assert "," not in want and not any("," in x for v in j.values() for x in (v["v"].get("ADCIRC_SEGMENT", ""), v["v"].get("ADCIRC_STREAM", "")))


@pytest.mark.parametrize("streams", ["surf tide", "tide tide", "tide surf surf", "ocean", "tide sea"])
def test_launcher_ops_streams_must_be_tide_and_surf_in_order(tmp_path, streams):
    r = _ops_launch(tmp_path, STREAMS=streams)
    assert r.returncode == 2 and "STREAMS must be" in r.stderr and not (tmp_path / "q.log").exists()


def test_launcher_ops_prints_the_stage_list_and_notes_a_subset(tmp_path):
    out = _launcher_stdout(tmp_path / "subset", STAGES="forecast post")
    assert "STAGES='forecast post'" in out and "NOTE: STAGES is a subset, so only these jobs are submitted: forecast post" in out
    out = _launcher_stdout(tmp_path / "all")
    assert "STAGES='prep nowcast forecast post'" in out and "NOTE" not in out


def _launcher_stdout(tmp_path, **env):
    tmp_path.mkdir()
    qsub = tmp_path / "bin" / "qsub"
    qsub.parent.mkdir(exist_ok=True)
    qsub.write_text("#!/bin/bash\necho 1.pbs\n")
    qsub.chmod(0o755)
    e = {k: v for k, v in os.environ.items() if k not in ("STAGES", "STREAMS", "COLDSTART", "KEEPDATA", "PLACE")}
    e.update({"PATH": f"{qsub.parent}:{os.environ['PATH']}", "PKG": str(REPO), "ADCIRC_MODE": "ops", **env})
    r = subprocess.run(["bash", str(LAUNCH), "20261005", "12"], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_launcher_single_mode_graph_unchanged(tmp_path):
    qsub = tmp_path / "bin" / "qsub"
    qsub.parent.mkdir()
    qsub.write_text('#!/bin/bash\necho "$*" >> $QLOG; echo j$RANDOM.pbs\n')
    qsub.chmod(0o755)
    env = {**os.environ, "PATH": f"{qsub.parent}:{os.environ['PATH']}", "QLOG": str(tmp_path / "q.log"), "PKG": str(REPO)}
    env.pop("ADCIRC_MODE", None)
    r = subprocess.run(["bash", str(LAUNCH), "20261005", "12"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = (tmp_path / "q.log").read_text().splitlines()
    assert [Path(l.split()[-1]).name for l in lines] == [f"jnos_{s}_00.pbs" for s in STAGES]
    assert "depend" not in lines[0] and all("afterok:j" in l for l in lines[1:])
    assert not any("ADCIRC_MODE" in l or "-N" in l.split() for l in lines)


@pytest.mark.parametrize("card", [PBS / "jnos_prep_00.pbs", SLURM / "jnos_prep_00.sh"])
def test_prep_card_runs_one_jnos_job_and_then_the_pass_gate(card):
    text = card.read_text()
    assert text.index("jobs/JNOS_POST") < text.index("# JNOS_* exits 0") < text.index(GATE)
    assert text.index("jobs/JNOS_PREP") < text.index("# JNOS_* exits 0") and text.rstrip().endswith(GATE)
    if card.suffix == ".pbs":
        assert "module load nco/" in text


def _dispatch(card, tmp_path, segment):
    """Runs the card's module and J-job dispatch block with a stub `module` and stub J-jobs; returns (rc, stdout, stderr, calls). MJ (10/14/26)"""
    text = card.read_text()
    block = text[text.index("# ncdiff/ncrcat/anomaly/bias/grib2 are the ops post steps"):text.index("# JNOS_* exits 0")]
    home, log = tmp_path / "home", tmp_path / "calls.log"
    for job in ("JNOS_POST", "JNOS_PREP"):
        f = home / "jobs" / job
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('#!/bin/bash\necho "%s" >> "$CALLS"\n' % job)
        f.chmod(0o755)
    script = 'module() { echo "module $*" >> "$CALLS"; }\n_dcom_in=\n' + block
    env = {k: v for k, v in os.environ.items() if k != "ADCIRC_SEGMENT"}
    env.update(HOMEnos=str(home), CALLS=str(log), cfp_ver="C", util_shared_ver="U", grib_util_ver="G", ve_stofs="V")
    if segment is not None:
        env["ADCIRC_SEGMENT"] = segment
    r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    return r, (log.read_text().splitlines() if log.exists() else [])


@pytest.mark.parametrize("card", [PBS / "jnos_prep_00.pbs", SLURM / "jnos_prep_00.sh"])
@pytest.mark.parametrize("segment,job", [(None, "JNOS_PREP"), ("", "JNOS_PREP"), ("ncst", "JNOS_PREP"), ("ncst fcst", "JNOS_PREP"),
                                         ("ncst,fcst", "JNOS_PREP"), ("adcprep ncst fcst", "JNOS_PREP"), ("ncdiff", "JNOS_POST"),
                                         ("ncdiff ncrcat", "JNOS_POST"), ("anomaly bias ncdiff grib2 ncrcat", "JNOS_POST"),
                                         ("anomaly,bias,ncdiff,grib2,ncrcat", "JNOS_POST")])
def test_prep_card_dispatches_a_segment_list_to_one_jnos_job(card, tmp_path, segment, job):
    r, calls = _dispatch(card, tmp_path, segment)
    assert r.returncode == 0, r.stderr
    assert [c for c in calls if c.startswith("JNOS")] == [job]


@pytest.mark.parametrize("card", [PBS / "jnos_prep_00.pbs", SLURM / "jnos_prep_00.sh"])
@pytest.mark.parametrize("segment", ["ncst ncdiff", "ncst,ncdiff", "adcprep ncst fcst ncrcat", "ncrcat fcst"])
def test_prep_card_rejects_a_list_that_mixes_prep_and_post(card, tmp_path, segment):
    r, calls = _dispatch(card, tmp_path, segment)
    assert r.returncode == 1 and "mixes prep and post segments" in r.stdout and calls == []


@pytest.mark.parametrize("segment,mods", [
    ("ncdiff ncrcat", []),
    ("ncst fcst", []),
    ("anomaly", ["unload python", "load ve/stofs/V"]),
    ("bias", ["unload python", "load cfp/C util_shared/U", "load ve/stofs/V"]),
    ("grib2", ["load cfp/C util_shared/U", "load grib_util/G"]),
    # the post job: the union of the three, each once, python unloaded before ve/stofs is loaded MJ (10/14/26)
    ("anomaly bias ncdiff grib2 ncrcat", ["unload python", "load cfp/C util_shared/U", "load grib_util/G", "load ve/stofs/V"]),
    ("anomaly,bias,ncdiff,grib2,ncrcat", ["unload python", "load cfp/C util_shared/U", "load grib_util/G", "load ve/stofs/V"]),
    ("anomaly   bias ncdiff", ["unload python", "load cfp/C util_shared/U", "load ve/stofs/V"]),
    ("ncdiff grib2 ncrcat", ["load cfp/C util_shared/U", "load grib_util/G"]),
])
def test_pbs_prep_card_loads_the_union_of_the_listed_post_modules_once(tmp_path, segment, mods):
    r, calls = _dispatch(PBS / "jnos_prep_00.pbs", tmp_path, segment)
    assert r.returncode == 0, r.stderr
    assert [c[len("module "):] for c in calls if c.startswith("module")] == mods


def test_slurm_prep_card_loads_no_post_modules(tmp_path):
    r, calls = _dispatch(SLURM / "jnos_prep_00.sh", tmp_path, "ncdiff ncrcat")
    assert r.returncode == 0 and calls == ["JNOS_POST"]


@pytest.mark.parametrize("launcher", [
    "stofs_3d_atl_ufs/launch_stofs_3d_atl_ufs.sh",
    "stofs_3d_atl_ufs_standalone/launch_stofs_standalone.sh",
])
def test_atl_launchers_forward_own_clone(launcher, tmp_path):
    """With PKG unset, the clone a launcher lives in is the one the jobs run, whatever it is named."""
    clone = tmp_path / "my_clone"
    (clone / "pbs").mkdir(parents=True)
    shutil.copytree(PBS.parent / Path(launcher).parent, clone / "pbs" / Path(launcher).parent)
    log = tmp_path / "qsub.log"
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "qsub").write_text('#!/bin/bash\necho "$@" >> "%s"\necho 1.stub\n' % log)
    (stub / "qsub").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("PKG", "PACKAGEROOT", "HOMEnos")}
    env["PATH"] = "%s:%s" % (stub, env["PATH"])
    env.setdefault("LOGNAME", "tester")
    subprocess.run(["bash", str(clone / "pbs" / launcher), "20261001", "12"],
                   env=env, cwd=str(tmp_path), check=True, capture_output=True)
    vars_ = log.read_text().splitlines()[0]
    assert "PACKAGEROOT=%s," % tmp_path in vars_
    assert vars_.split(" ")[-2].endswith("HOMEnos=%s" % clone) or "HOMEnos=%s" % clone in vars_


def test_surf_writers_fit_both_machines():
    import yaml
    w = yaml.safe_load((REPO / "parm" / "systems" / "stofs_2d_glo.yaml").read_text())["adcirc"]["ops_surf_writers"]
    assert w == 4
    assert RANKS + w <= 51 * 80 and RANKS + w <= 32 * 128
