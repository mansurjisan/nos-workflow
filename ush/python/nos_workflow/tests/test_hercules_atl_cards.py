"""STOFS-3D-ATL Hercules cards, helpers and build scripts. Offline."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.machine import MachineProfile, jobs, render_directives  # noqa: E402

VARIANTS = {
    "stofs_3d_atl_ufs": ("slurm/stofs_3d_atl_ufs", 5032, 63),
    "stofs_3d_atl_ufs_standalone": ("slurm/stofs_3d_atl_ufs_standalone", 4920, 62),
}
WALL = {"prep": "03:00:00", "nowcast": "02:30:00", "forecast": "06:00:00", "post": "02:00:00"}
STAGES = list(WALL)
SCRIPTS = [
    "tools/hercules_atl_seed_init.sh",
    "tools/hercules_atl_seed_prev.sh",
    "tools/build_stofs_3d_atl_ufs_hercules.sh",
    "tools/build_stofs_3d_atl_pschism_hercules.sh",
    "tools/build_stofs_3d_atl_tide_fac_hercules.sh",
]


def _sbatch(path: Path) -> list:
    return [l.rstrip("\n") for l in path.read_text().splitlines() if l.startswith("#SBATCH")]


def _cards():
    return [(s, st) for s in VARIANTS for st in STAGES]


@pytest.fixture()
def hercules():
    return MachineProfile.load("hercules", machines_dir=REPO / "parm" / "machines", validate=False)


@pytest.mark.parametrize("system,stage", _cards())
def test_card_allocation_matches_machine_layer(system, stage, hercules):
    d, ntasks, nodes = VARIANTS[system]
    card = REPO / d / f"jnos_{stage}_00.sh"
    assert card.is_file()
    lines = _sbatch(card)
    assert f"#SBATCH --time={WALL[stage]}" in lines
    for want in ("--account=nos-surge", "--qos=batch", "--partition=hercules"):
        assert f"#SBATCH {want}" in lines
    if stage in ("nowcast", "forecast"):
        spec = jobs.build_job_spec(system, stage)
        assert spec.total_ranks == ntasks
        rendered = render_directives(spec, hercules)
        for key in ("--nodes", "--ntasks-per-node", "--exclusive"):
            want = [l for l in rendered if l.startswith(f"#SBATCH {key}")]
            got = [l for l in lines if l.startswith(f"#SBATCH {key}")]
            assert got == want, (key, got, want)
        assert f"#SBATCH --nodes={nodes}" in lines
        assert hercules.nodes(ntasks) == nodes
        assert f"export TOTAL_TASKS=${{TOTAL_TASKS:-{ntasks}}}" in card.read_text()
    else:
        assert "#SBATCH --nodes=1" in lines and "#SBATCH --ntasks=8" in lines
        assert "#SBATCH --mem=0" in lines


@pytest.mark.parametrize("system,stage", _cards())
def test_card_env_and_syntax(system, stage):
    d, _, _ = VARIANTS[system]
    card = REPO / d / f"jnos_{stage}_00.sh"
    text = card.read_text()
    subprocess.run(["bash", "-n", str(card)], check=True)
    assert "export NOS_MACHINE=hercules" in text
    assert "export NOS_ARCHIVE_MANIFEST=${NOS_ARCHIVE_MANIFEST:-YES}" in text
    assert "export cyc=${CYC:-12}" in text
    assert "versions/run.hercules.ver" in text
    assert "MPICH_" not in text and "mpiexec" not in text and "qsub" not in text
    assert text.rstrip().endswith({"prep": "JNOS_PREP", "nowcast": "JNOS_NOWCAST",
                                    "forecast": "JNOS_FORECAST", "post": "JNOS_POST"}[stage])
    assert "export OFS=stofs_3d_atl_ufs\n" in text and "OFS:-" not in text
    assert "import nos_utils" in text and "ush/python/nos-utils" in text
    assert "MJ (10/04/26)" in text
    if stage == "prep":
        assert "DCOMROOT:?" in text
        assert "COMINrerun" in text
        for needle in ("stofs_3d_atl_tide_fac", "nrt_global_allsat_phy_l4_", "coops_waterlvlobs",
                       "02OA016_hydrometric.csv", "avg_bias", "staout_1"):
            assert needle in text
    else:
        assert "stofs_3d_atl_tide_fac" not in text
    if stage in ("nowcast", "forecast"):
        assert "I_MPI_EXTRA_FILESYSTEM=ON" in text and "FI_MLX_INJECT_LIMIT=0" in text
    if system.endswith("standalone"):
        assert "stofs_3d_atl_ufs_standalone.yaml" in text
        assert "COMROOT=${COMROOT_SA:-" in text and "com_atl_sa" in text
    else:
        assert "${HOMEnos}/parm/systems/${OFS}.yaml" in text
        assert "COMROOT=${COMROOT_UFS:-" in text and "com_atl_ufs" in text
    assert "COMROOT=${COMROOT:-" not in text and "DATAROOT:-" not in text


def test_comroots_are_separate():
    sa = (REPO / VARIANTS["stofs_3d_atl_ufs_standalone"][0] / "jnos_prep_00.sh").read_text()
    cp = (REPO / VARIANTS["stofs_3d_atl_ufs"][0] / "jnos_prep_00.sh").read_text()
    assert re.search(r"COMROOT=.*COMROOT_SA.*com_atl_sa", sa) and re.search(r"COMROOT=.*COMROOT_UFS.*com_atl_ufs", cp)


def test_hercules_ranks_per_node_is_single_setting(hercules):
    assert hercules.allocation.ranks_per_node == 80
    cards = [REPO / d / f"jnos_{st}_00.sh" for d, _, _ in VARIANTS.values() for st in ("nowcast", "forecast")]
    for c in cards:
        assert "--ntasks-per-node=80" in c.read_text()


@pytest.mark.parametrize("script", SCRIPTS)
def test_scripts_parse(script):
    path = REPO / script
    assert path.is_file()
    subprocess.run(["bash", "-n", str(path)], check=True)


def test_build_scripts_verify_flags():
    cpl = (REPO / "tools/build_stofs_3d_atl_ufs_hercules.sh").read_text()
    for needle in ("PREC_EVAP=ON", "NO_PARMETIS=ON", "stofs_atl_pe", "CMakeCache", "fv3_stofs_3d_atl.exe"):
        assert needle in cpl
    sa = (REPO / "tools/build_stofs_3d_atl_pschism_hercules.sh").read_text()
    for needle in ("-DNO_PARMETIS", "-DPREC_EVAP", "-DTVD_VL", "stofs_3d_atl_pschism_v3.1.5"):
        assert needle in sa
    ymls = [(REPO / "parm/systems/stofs_3d_atl_ufs.yaml").read_text()]
    assert "executable: stofs_3d_atl_pschism_v3.1.5" in ymls[0]
    assert "executable: fv3_stofs_3d_atl.exe" in ymls[0]


def test_script_comments_carry_tag_and_exec_bit():
    for script in SCRIPTS:
        text = (REPO / script).read_text()
        assert "MJ (10/04/26)" in text
    cpl = (REPO / "tools/build_stofs_3d_atl_ufs_hercules.sh").read_text()
    assert ': "${UFS_DIR:?' in cpl and "ufs-weather-model}" not in cpl
    assert "not found" in cpl and "stack_impi_ver" in cpl


def test_ufs_build_requires_ufs_dir(tmp_path):
    r = subprocess.run(["bash", str(REPO / "tools/build_stofs_3d_atl_ufs_hercules.sh")],
                       env={"PATH": "/usr/bin:/bin", "UFS_COMMIT": "abc", "EXECnos": str(tmp_path)},
                       capture_output=True, text=True)
    assert r.returncode != 0 and "UFS_DIR" in r.stderr


def test_seed_prev_layout(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "staout_1").write_text("x\n")
    (seed / "stofs_3d_atl_ufs.t12z.avg_bias").write_text("0.1\n")
    (seed / "param.nml").write_text("&core\n/\n")
    sa, cp = tmp_path / "sa", tmp_path / "cp"
    subprocess.run(["bash", str(REPO / "tools/hercules_atl_seed_prev.sh"), str(seed), str(sa), "20261001", str(cp)],
                   check=True, capture_output=True)
    for root in (sa, cp):
        prev = root / "nos" / "stofs_3d_atl_ufs.20260930"
        assert (prev / "staout_1").read_text() == "x\n"
        assert (prev / "rerun" / "stofs_3d_atl_ufs.t12z.avg_bias").read_text() == "0.1\n"
        assert (prev / "rerun" / "stofs_3d_atl_ufs.t12z.param.nml").is_file()
    bad = subprocess.run(["bash", str(REPO / "tools/hercules_atl_seed_prev.sh"), str(tmp_path / "nope"), str(sa), "20261001"],
                         capture_output=True)
    assert bad.returncode != 0
