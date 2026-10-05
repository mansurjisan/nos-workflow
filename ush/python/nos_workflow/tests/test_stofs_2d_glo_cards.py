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
    assert text.rstrip().endswith(LAST[stage]) or text.rstrip().endswith(LAST[stage] + "\nexit $?")


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
    assert text.rstrip().endswith(LAST[stage])
    if stage != "prep":
        assert "I_MPI_EXTRA_FILESYSTEM=ON" in text and "FI_MLX_INJECT_LIMIT=0" in text
        assert "-le 4080" in text


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
