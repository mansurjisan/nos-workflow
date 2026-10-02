"""ush/nos_run.sh _schism_run_combine_fields: MPI rank placement and libraries.

Runs the real shell function against stubs (PBS node file, ldd, mpiexec) so
the actual launch line is checked, not a re-implementation of it.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
NOS_RUN = REPO / "ush" / "nos_run.sh"
USH_PYTHON = REPO / "ush" / "python"


def _setup(tmp_path: Path, n_stacks: int, n_nodes: int):
    nc_root = tmp_path / "lib" / "cray-mpich-8.1.4"
    (nc_root / "netcdf" / "4.7.4" / "lib").mkdir(parents=True)
    (nc_root / "hdf5" / "1.10.6" / "lib").mkdir(parents=True)
    bindir, exedir = tmp_path / "bin", tmp_path / "exec"
    outputs = tmp_path / "DATA" / "outputs"
    for d in (bindir, exedir, outputs):
        d.mkdir(parents=True)
    (bindir / "ldd").write_text(
        "#!/bin/bash\n"
        f'echo "  libnetcdf.so.18 => {nc_root}/netcdf/4.7.4/lib/libnetcdf.so.18 (0x0)"\n'
    )
    # Stub launcher: record argv + LD_LIBRARY_PATH, then write the last stack.
    (bindir / "mpiexec").write_text(
        "#!/bin/bash\n"
        f'echo "$*" > {tmp_path}/launch.txt\n'
        f'echo "$LD_LIBRARY_PATH" > {tmp_path}/ld.txt\n'
        f"echo x > {outputs}/schout_{n_stacks}.nc\n"
    )
    for exe in ("combine_output11_MPI", "combine_output11"):
        (exedir / exe).write_text("#!/bin/bash\nexit 0\n")
    for f in list(bindir.iterdir()) + list(exedir.iterdir()):
        f.chmod(0o755)
    for s in range(1, n_stacks + 1):
        (outputs / f"schout_000000_{s}.nc").write_text("")
    nodefile = tmp_path / "nodefile"
    nodefile.write_text("".join(f"node{i:03d}\n" * 120 for i in range(n_nodes)))
    env = dict(os.environ,
               PATH=f"{bindir}:{os.environ['PATH']}",
               PYTHONPATH=str(USH_PYTHON),
               DATA=str(tmp_path / "DATA"), EXECnos=str(exedir),
               PBS_NODEFILE=str(nodefile), LD_LIBRARY_PATH="/serial/hdf5/lib")
    env.pop("NOS_MACHINE", None)
    return env, nc_root


def _run(tmp_path, env):
    proc = subprocess.run(
        ["bash", "-c", f"source {NOS_RUN}; _schism_run_combine_fields forecast"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    launch = (tmp_path / "launch.txt").read_text().split()
    return proc, launch


@pytest.mark.parametrize("n_stacks,n_nodes,ppn", [(10, 42, "1"), (3, 1, "3"), (10, 4, "3")])
def test_one_rank_per_node_when_the_job_has_the_nodes(tmp_path, n_stacks, n_nodes, ppn):
    env, _ = _setup(tmp_path, n_stacks, n_nodes)
    proc, launch = _run(tmp_path, env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert launch[:5] == ["-n", str(n_stacks), "-ppn", ppn, "--cpu-bind"]
    assert "MPI fields combine failed" not in proc.stdout


def test_mpi_combine_gets_parallel_libraries_first(tmp_path):
    env, nc_root = _setup(tmp_path, 3, 42)
    _run(tmp_path, env)
    ld = (tmp_path / "ld.txt").read_text().strip().split(":")
    assert ld[0] == str(nc_root / "netcdf" / "4.7.4" / "lib")
    assert ld[1] == str(nc_root / "hdf5" / "1.10.6" / "lib")
    assert ld[-1] == "/serial/hdf5/lib"


def test_no_node_file_keeps_profile_packing(tmp_path):
    env, _ = _setup(tmp_path, 3, 1)
    env.pop("PBS_NODEFILE")
    _, launch = _run(tmp_path, env)
    assert launch[:4] == ["-n", "3", "-ppn", "120"]
