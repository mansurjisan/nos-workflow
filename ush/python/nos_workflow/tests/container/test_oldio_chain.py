"""Opt-in container test: the full OLDIO -> canonical-fields chain.

Compiles ``combine_output11`` from the SCHISM source bundled inside the
UFS-Coastal image (the same lineage as ``fv3_coastalS.exe``), fabricates
a tiny 2-rank per-rank output set, runs the REAL
``_schism_run_combine_fields`` shell function inside the container
(exercising exe resolution + the serial-fallback branch), then the real
``archive.run_python`` (flag-gated staging, per-rank exclusion) and the
real ``fields`` worker (schout split + canonical publish) on the host,
and value-verifies the final product against the analytic fixture.

Opt-in: requires ``NOS_CONTAINER_TESTS=1``, a working docker daemon,
and the image (override with ``NOS_OLDIO_IMAGE``); skips otherwise.
Runtime is dominated by two short ``docker run`` invocations (~30 s).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("NOS_CONTAINER_TESTS") != "1",
    reason="container tests are opt-in (set NOS_CONTAINER_TESTS=1)",
)

IMAGE = os.environ.get(
    "NOS_OLDIO_IMAGE", "ghcr.io/mansurjisan/ufs-coastal-nwm:demo1"
)
SCHISM_UTIL = "/opt/ufs-weather-model/SCHISM-interface/SCHISM/src/Utility"
NETCDF_FORTRAN = (
    "/opt/spack-stack/spack-stack-1.9.2/envs/ufs-wm-env/install"
    "/gcc/13.3.1/netcdf-fortran-4.6.1-r7upznh"
)
_REPO_USH = Path(__file__).resolve().parents[4]  # .../ush

_BUILD_SCRIPT = f"""
set -e
source /opt/rh/gcc-toolset-13/enable 2>/dev/null || true
NF={NETCDF_FORTRAN}
cp {SCHISM_UTIL}/Combining_Scripts/combine_output11.f90 \\
   {SCHISM_UTIL}/Combining_Scripts/netcdf_var_names.f90 \\
   {SCHISM_UTIL}/UtilLib/argparse.f90 \\
   {SCHISM_UTIL}/UtilLib/schism_geometry.f90 \\
   {SCHISM_UTIL}/UtilLib/schism_geometry.txt /b/
cd /b
FF="-O2 -ffree-line-length-none -cpp"
gfortran $FF -c argparse.f90
gfortran $FF -c schism_geometry.f90
gfortran $FF -c netcdf_var_names.f90 -I$NF/include
gfortran $FF -o combine_output11 combine_output11.f90 argparse.o \\
    schism_geometry.o netcdf_var_names.o \\
    -I$NF/include -L$NF/lib -lnetcdff -Wl,-rpath,$NF/lib
chmod -R a+rw /b
echo BUILD_OK
"""


def _docker(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout,
    )


@pytest.fixture(scope="session")
def docker_image():
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    probe = _docker("image", "inspect", IMAGE, timeout=60)
    if probe.returncode != 0:
        pytest.skip(f"image not available: {IMAGE}")
    return IMAGE


@pytest.fixture(scope="session")
def combiner_dir(docker_image, tmp_path_factory) -> Path:
    """Compile combine_output11 inside the image; return the build dir."""
    build = tmp_path_factory.mktemp("combiner")
    proc = _docker(
        "run", "--rm", "--entrypoint", "bash",
        "-v", f"{build}:/b", docker_image, "-c", _BUILD_SCRIPT,
    )
    assert "BUILD_OK" in proc.stdout, (
        f"combiner build failed:\n{proc.stdout}\n{proc.stderr}"
    )
    assert (build / "combine_output11").is_file()
    return build


def test_oldio_chain_end_to_end(docker_image, combiner_dir, tmp_path):
    netCDF4 = pytest.importorskip("netCDF4")
    np = pytest.importorskip("numpy")

    from nos_workflow.post.products import fields
    from nos_workflow.runners.schism_ufs.archive import run_python
    from nos_workflow.runners.schism_ufs.context import SchismRunContext
    from nos_workflow.tests.container import oldio_fixtures

    # 1. Per-rank OLDIO fixtures.
    data = tmp_path / "data"
    oldio_fixtures.generate(data / "outputs")

    # 2. The real shell combine wrapper, inside the container (serial
    #    fallback: only the serial exe exists in the build dir).
    proc = _docker(
        "run", "--rm", "--entrypoint", "bash",
        "-v", f"{tmp_path}:/work",
        "-v", f"{combiner_dir}:/exec",
        "-v", f"{_REPO_USH}:/repo_ush",
        docker_image, "-c",
        "export DATA=/work/data EXECnos=/exec HOMEnos=/nonexistent\n"
        "source /repo_ush/nos_run.sh\n"
        "_schism_run_combine_fields nowcast\n"
        "rc=$?\n"
        "chmod -R a+rw /work/data\n"
        "exit $rc\n",
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "combined schout_1..1.nc OK" in proc.stdout
    assert (data / "outputs" / "schout_1.nc").is_file()

    # 3. The real archive step with field staging on: combined stack is
    #    staged, per-rank files never leave DATA.
    comout = tmp_path / "comout"
    comout.mkdir()
    ctx = SchismRunContext(
        comout=comout, data=data, phase="nowcast",
        run="secofs_test", cycle="t00z",
    )
    os.environ["NOS_ARCHIVE_FIELDS"] = "yes"
    try:
        assert run_python(ctx, "nowcast") == 0
    finally:
        os.environ.pop("NOS_ARCHIVE_FIELDS", None)
    staging = comout / "secofs_test.t00z.restart_outputs"
    staged = {p.name for p in staging.iterdir()}
    assert "schout_1.nc" in staged
    assert not any(n.startswith("schout_0000") for n in staged)

    # 4. The real fields worker: split + canonical publish.
    result_json = tmp_path / "result.json"
    rc = fields.main([
        "--staging", str(staging),
        "--comout", str(comout),
        "--prefix", "secofs_test",
        "--cyc", "00",
        "--pdy", "20260710",
        "--phase", "nowcast",
        "--combine-script", str(_REPO_USH / "schism_combine_outputs.py"),
        "--result-json", str(result_json),
    ])
    assert rc == 0
    created = json.loads(result_json.read_text())["created"]
    names = [Path(p).name for p in created]
    assert "secofs_test.t00z.20260710.fields.out2d.n001_003.nc" in names

    # 5. Value verification through the whole chain.
    prod = comout / "secofs_test.t00z.20260710.fields.out2d.n001_003.nc"
    with netCDF4.Dataset(prod) as ds:
        assert np.allclose(
            ds["elevation"][:], oldio_fixtures.expected_elev()
        )
        assert ds.getncattr("product") == "fields_nc"
        assert ds.getncattr("ofs") == "secofs_test"
