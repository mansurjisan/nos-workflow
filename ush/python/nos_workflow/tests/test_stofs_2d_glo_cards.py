"""STOFS-2D-Global job cards and fix-fetch tool. Offline."""
from __future__ import annotations

import math
import os
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
    # 4064 + up to 32 writer ranks must fit the 32 x 128 slots.
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
                   "COMROOT=${COMROOT_2DGLO:-", "com_2dglo", "export HOMEnos=",
                   "OFS_CONFIG=${HOMEnos}/parm/systems/stofs_2d_glo.yaml", "ADCIRC_EXEC_DIR",
                   "stofs_2d_glo_grid stofs_2d_glo_attr", "fetch_stofs_2d_glo_fix.sh", TAG):
        assert needle in text, needle
    assert "OFS:-" not in text and "COMROOT=${COMROOT:-" not in text and "DATAROOT:-" not in text
    assert text.rstrip().endswith(GATE) and LAST[stage] in text


@pytest.mark.parametrize("stage", STAGES)
def test_slurm_card_exports(stage):
    card = SLURM / f"jnos_{stage}_00.sh"
    text = card.read_text()
    subprocess.run(["bash", "-n", str(card)], check=True)
    for needle in ("PACKAGEROOT=${PACKAGEROOT:?", "slurm/stofs_2d_glo", "versions/run.hercules.ver",
                   "export NOS_MACHINE=hercules", "export OFS=stofs_2d_glo\n",
                   "export NET=nos RUN=stofs_2d_glo PREFIXNOS=stofs_2d_glo\n", "export cyc=${CYC:-12}",
                   "export PDY=${PDY:?", "COMROOT=${COMROOT_2DGLO:-", "com_2dglo",
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
        for job in ("ADCIRC_SEGMENT=spinup", "ADCIRC_STREAM=tide,ADCIRC_SEGMENT=ncst", "COLDSTART=YES"):
            assert job in text
    if "prep" not in card.name:
        assert "export ADCIRC_ALLOC_RANKS=" in text and "_tot" not in text


def test_keepdata_is_a_submit_time_override():
    for card in list(PBS.glob("jnos_*_00.pbs")) + list(SLURM.glob("jnos_*_00.sh")):
        text = card.read_text()
        assert "export KEEPDATA=${KEEPDATA:-YES}" in text and "KEEPDATA=YES\n" not in text.replace(":-YES}", "")


def _ops_launch(tmp_path, **env):
    qsub = tmp_path / "bin" / "qsub"
    qsub.parent.mkdir()
    qsub.write_text('#!/bin/bash\nn=$(cat $QLOG.n 2>/dev/null || echo 0); n=$((n+1)); echo $n > $QLOG.n\n'
                    'echo "$n.pbs $*" >> $QLOG; echo $n.pbs\n')
    qsub.chmod(0o755)
    log = tmp_path / "q.log"
    e = {**os.environ, "PATH": f"{qsub.parent}:{os.environ['PATH']}", "QLOG": str(log), "PKG": str(REPO),
         "ADCIRC_MODE": "ops", **env}
    r = subprocess.run(["bash", str(LAUNCH), "20261005", "12"], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    jobs = {}
    for ln in log.read_text().splitlines():
        jid, rest = ln.split(" ", 1)
        a = rest.split()
        v = dict(kv.split("=", 1) for kv in a[a.index("-v") + 1].split(","))
        dep = a[a.index("-W") + 1].split(":")[1:] if "-W" in a else []
        ls = [a[i + 1] for i, x in enumerate(a) if x == "-l"]
        pick = lambda k: next((x.split("=", 1)[1] for x in ls if x.startswith(k + "=")), "")  # noqa: E731
        jobs[a[1 + a.index("-N")]] = dict(jid=jid, dep=dep, v=v, wall=ls[0], sel=pick("select"), place=pick("place"),
                                          card=Path(a[-1]).name)
    return jobs


def test_launcher_ops_job_graph(tmp_path):
    j = _ops_launch(tmp_path)
    assert len(j) == 14 and "stofs_2d_glo_cold_adcprep" not in j
    name = lambda label: j["stofs_2d_glo_" + label]  # noqa: E731
    deps = {k[len("stofs_2d_glo_"):]: sorted(x["jid"] for x in j.values() if x["jid"] in v["dep"]) for k, v in j.items()}
    want = {"tide_fcst1": ["tide_ncst"], "tide_fcst2": ["tide_fcst1"], "surf_ncst": ["gfs_ncst"],
            "surf_fcst1": ["surf_ncst", "gfs_fcst1"], "surf_fcst2": ["surf_fcst1", "gfs_fcst2"],
            "post_anomaly": ["surf_fcst2", "tide_fcst2"], "post_bias": ["post_anomaly"],
            "post_ncdiff": ["post_bias", "tide_fcst2"], "post_grib2": ["post_ncdiff"], "post_ncrcat": ["gfs_ncst", "gfs_fcst1", "gfs_fcst2"],
            "tide_ncst": [], "gfs_ncst": [], "gfs_fcst1": [], "gfs_fcst2": []}
    assert deps == {k: sorted(name(x)["jid"] for x in v) for k, v in want.items()}
    for v in j.values():
        assert v["v"]["PDY"] == "20261005" and v["v"]["CYC"] == "12" and v["v"]["KEEPDATA"] == "NO"
        assert v["v"]["ADCIRC_MODE"] == "ops"
    assert (name("surf_fcst1")["v"]["ADCIRC_STREAM"], name("surf_fcst1")["v"]["ADCIRC_SEGMENT"]) == ("surf", "fcst1")
    assert name("gfs_fcst1")["card"] == "jnos_prep_00.pbs" and name("gfs_fcst1")["v"]["ADCIRC_SEGMENT"] == "fcst1"
    assert name("post_ncdiff")["card"] == "jnos_prep_00.pbs" and name("post_ncrcat")["v"]["ADCIRC_SEGMENT"] == "ncrcat"
    assert [name(k)["v"]["ADCIRC_SEGMENT"] for k in ("post_anomaly", "post_bias", "post_grib2")] == ["anomaly", "bias", "grib2"]
    assert name("post_bias")["sel"] == "8:ncpus=32:prepost=true:mem=800gb" and name("post_bias")["place"] == "vscatter:exclhost"
    assert name("post_grib2")["sel"].startswith("1:ncpus=7:") and name("post_anomaly")["place"] == ""
    assert {k: name(k)["wall"] for k in ("tide_ncst", "surf_fcst1", "post_ncdiff", "post_ncrcat")} == {
        "tide_ncst": "walltime=0:15:00", "surf_fcst1": "walltime=0:40:00", "post_ncdiff": "walltime=0:10:00",
        "post_ncrcat": "walltime=0:15:00"}
    assert [name(k)["wall"] for k in ("post_anomaly", "post_bias", "post_grib2")] == [
        "walltime=0:15:00", "walltime=2:00:00", "walltime=0:20:00"]


def test_launcher_ops_cold_start_and_forwarded_overrides(tmp_path):
    j = _ops_launch(tmp_path, COLDSTART="YES", NOWCAST_HOURS="24")
    spin, adc = j["stofs_2d_glo_cold_spinup"], j["stofs_2d_glo_cold_adcprep"]
    assert adc["v"]["COLDSTART"] == "YES" and spin["dep"] == [adc["jid"]] and spin["v"]["ADCIRC_SEGMENT"] == "spinup"
    for k in ("tide_ncst", "surf_ncst"):
        assert spin["jid"] in j["stofs_2d_glo_" + k]["dep"]
        assert j["stofs_2d_glo_" + k]["v"]["NOWCAST_HOURS"] == "24"
    assert j["stofs_2d_glo_gfs_ncst"]["dep"] == [spin["jid"]]


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
def test_prep_card_dispatches_ops_post_jobs(card):
    text = card.read_text()
    assert ('case "${ADCIRC_SEGMENT:-}" in ncdiff|ncrcat|anomaly|bias|grib2) ${HOMEnos}/jobs/JNOS_POST ;; '
            '*) ${HOMEnos}/jobs/JNOS_PREP ;; esac\n# JNOS_* exits 0') in text
    assert "esac\n" in text and text.index("esac") < text.index(GATE)
    if card.suffix == ".pbs":
        assert "module load nco/" in text
