"""STOFS-2D-Global Hercules build tools (ADCIRC v56.1.0, tide_fac). Offline: compilers and the network are stubbed."""
from __future__ import annotations

import os
import resource
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
ADCIRC = REPO / "tools" / "build_stofs_2d_glo_adcirc_hercules.sh"
TIDE_FAC = REPO / "tools" / "build_stofs_2d_glo_tide_fac_hercules.sh"
TAG = "MJ (10/13/26)"
HASH = "6e667fc9dcc759116f0620f4d9ac76cfd1361fbd"
DEFS = "-DADCNETCDF -DCMPI -DCSCA -DDATETIME -DHAVE_NETCDF4 -DLINUX -DNETCDF_CAN_DEFLATE"
FLAGS = "-O2 -g -module CMakeFiles/mod/padcirc -132 -assume byterecl -mcmodel=medium"
OPS_FLAGS_MAKE = (f"Fortran_DEFINES = {DEFS}\n\nFortran_INCLUDES = -I/lfs/h1/x/prep -I/apps/netcdf/include\n\n"
                  f"Fortran_FLAGS = {FLAGS}\n")
ORDER = "K1 O1 P1 Q1 M2 S2 N2 K2 MF MM M4 MS4 MN4 M6 2N2".split()


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(script, args, env, **kw):
    return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, **kw)


@pytest.fixture()
def env(tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    return {"PATH": f"{stubs}:/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path)}


def _compiler_stubs(stubs: Path) -> None:
    for name in ("mpiicc", "mpiicpc", "mpiifort", "ifort"):
        _stub(stubs / name, 'while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\n: > "$out"; chmod +x "$out"\n')


@pytest.mark.parametrize("script", [ADCIRC, TIDE_FAC])
def test_scripts_parse_tag_and_usage(script, env):
    subprocess.run(["bash", "-n", str(script)], check=True)
    text = script.read_text()
    assert TAG in text and text.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in text
    ok = _run(script, ["-h"], env)
    assert ok.returncode == 0 and "Usage:" in ok.stdout and "download" in ok.stdout
    bad = _run(script, ["bogus"], env)
    assert bad.returncode == 2 and "unknown mode" in bad.stderr


@pytest.mark.parametrize("script,var", [(ADCIRC, "SRC"), (TIDE_FAC, "SRC")])
def test_no_internet_inside_slurm_job_and_build_needs_download(script, var, env, tmp_path):
    env = {**env, var: str(tmp_path / "src"), "OPS_FLAGS": str(tmp_path / "ops.make"), "TIDE_FAC_EXEC_DIR": str(tmp_path / "x")}
    for mode in ("download", "all"):
        r = _run(script, [mode], {**env, "SLURM_JOB_ID": "123"})
        assert r.returncode == 1 and "compute nodes have no internet" in r.stderr
    r = _run(script, ["build"], env)
    assert r.returncode == 1 and "download" in r.stderr and "FATAL" in r.stderr


def test_adcirc_source_must_be_outside_git_checkout(env, tmp_path):
    repo = tmp_path / "checkout"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    r = _run(ADCIRC, ["download"], {**env, "SRC": str(repo / "adcirc_src"), "OPS_FLAGS": str(tmp_path / "o")})
    assert r.returncode == 1 and "inside a git checkout" in r.stderr


def _tide_fac_env(env, tmp_path, bad=False):
    stubs = tmp_path / "stubs"
    # the stub "ifort" writes an executable that mimics the Fortran simple output (header + 15 constituents) MJ (10/13/26)
    rows = "".join(f'echo " {c}    1.00000       0.00    0.0000"\n' for c in ORDER[:15 - (1 if bad else 0)])
    exe = ('while [ $# -gt 0 ]; do case "$1" in --outputdir) d=$2;; --outputname) n=$2;; esac; shift; done\n'
           f'{{ echo "  0  5 10 2026"\n{rows}}} > "$d/$n"\n')
    _stub(stubs / "ifort", 'while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
          f"cat > \"$out\" <<'EOS'\n#!/bin/bash\n{exe}EOS\nchmod +x \"$out\"\n")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "stofs_2d_glo_tide_fac.f").write_text("      PROGRAM TIDE_FAC\n      END\n")
    return {**env, "URL": f"file://{upstream}", "SRC": str(tmp_path / "tf_src"), "BLD": str(tmp_path / "tf_build"),
            "TIDE_FAC_EXEC_DIR": str(tmp_path / "exec")}


def test_tide_fac_download_build_install_and_smoke(env, tmp_path):
    e = _tide_fac_env(env, tmp_path)
    r = _run(TIDE_FAC, ["download"], e)
    assert r.returncode == 0 and (tmp_path / "tf_src" / "stofs_2d_glo_tide_fac.f").is_file()
    assert not (tmp_path / "exec").exists()
    r = _run(TIDE_FAC, ["all"], e)
    exe = tmp_path / "exec" / "stofs_2d_glo_tide_fac"
    assert r.returncode == 0, r.stderr
    assert os.access(exe, os.X_OK) and "source present" in r.stdout and "smoke test passed: 16 lines" in r.stdout


def _tide_fac_clone(tmp_path):
    """The script copied into <tmp>/pk/nos-workflow/tools, so its default <repo>/exec is inside the temp dir. MJ (10/13/26)"""
    tools = tmp_path / "pk" / "nos-workflow" / "tools"
    tools.mkdir(parents=True)
    shutil.copy(TIDE_FAC, tools)
    return tools / TIDE_FAC.name, tmp_path / "pk" / "nos-workflow" / "exec" / "stofs_2d_glo_tide_fac"


def test_tide_fac_installs_into_the_repo_exec_whatever_execnos_is_inherited(env, tmp_path):
    script, repo_exe = _tide_fac_clone(tmp_path)
    e = {k: v for k, v in _tide_fac_env(env, tmp_path).items() if k != "TIDE_FAC_EXEC_DIR"}
    other = tmp_path / "atl_exec"
    r = _run(script, ["all"], {**e, "EXECnos": str(other)})
    assert r.returncode == 0, r.stderr
    assert os.access(repo_exe, os.X_OK) and not other.exists()
    assert f"WARNING: inherited EXECnos={other} ignored; installing into {repo_exe.parent}" in r.stderr
    repo_exe.unlink()
    r = _run(script, ["build"], {**e, "EXECnos": str(repo_exe.parent)})  # the same dir: no warning MJ (10/13/26)
    assert r.returncode == 0 and os.access(repo_exe, os.X_OK) and "WARNING" not in r.stderr
    repo_exe.unlink()
    r = _run(script, ["build"], e)
    assert r.returncode == 0 and os.access(repo_exe, os.X_OK) and "WARNING" not in r.stderr


def test_tide_fac_exec_dir_override_wins_over_execnos(env, tmp_path):
    script, repo_exe = _tide_fac_clone(tmp_path)
    e = _tide_fac_env(env, tmp_path)
    r = _run(script, ["all"], {**e, "EXECnos": str(tmp_path / "atl_exec")})
    assert r.returncode == 0, r.stderr
    assert os.access(tmp_path / "exec" / "stofs_2d_glo_tide_fac", os.X_OK) and not repo_exe.exists() and "WARNING" in r.stderr


def test_tide_fac_smoke_fails_loudly_on_bad_output(env, tmp_path):
    r = _run(TIDE_FAC, ["all"], _tide_fac_env(env, tmp_path, bad=True))
    assert r.returncode == 1 and "expected 16" in r.stderr


def _adcirc_env(env, tmp_path, fetch=False, **flags):
    if resource.getrlimit(resource.RLIMIT_STACK)[1] != resource.RLIM_INFINITY:
        pytest.skip("hard stack limit: ulimit -s unlimited cannot be raised, the script refuses to build")
    stubs = tmp_path / "stubs"
    _compiler_stubs(stubs)
    nc, nf = tmp_path / "nc", tmp_path / "nf"
    for f in ("nc/include/netcdf.h", "nc/lib/libnetcdf.so", "nf/include/netcdf.mod", "nf/lib/libnetcdff.so"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("x")
    _stub(stubs / "nc-config", f'case "$1" in --includedir) echo {nc}/include;; --libdir) echo {nc}/lib;; --prefix) echo {nc};; esac\n')
    _stub(stubs / "nf-config", f'echo {nf}\n')
    extra = "-heap-arrays 10 " if flags.get("heap") else ""
    _stub(stubs / "cmake", f'[ "$1" = --version ] && {{ echo "cmake version 3.27.9"; exit 0; }}\n'
          f'echo "$@" > "{tmp_path}/cmake.args"\nmkdir -p CMakeFiles/padcirc.dir\n'
          f'printf "Fortran_DEFINES = {DEFS}\\nFortran_FLAGS = -xCORE-AVX2 {extra}{FLAGS}\\n" > CMakeFiles/padcirc.dir/flags.make\n'
          'echo "-- Unlimited stack size detected."; echo "-- Build files have been written to: $PWD"\n')
    ver = "v55.0.0" if flags.get("badver") else "v56.1.0"
    adc = f'case "$1" in -v) echo {ver};; --hash) echo {HASH};; esac\n'
    _stub(stubs / "make", f"printf '#!/bin/bash\\n%s' '{adc}' > padcirc; printf '#!/bin/bash\\n' > adcprep; chmod +x padcirc adcprep\n")
    libs = "libnetcdff.so.7 libnetcdf.so.19 libhdf5.so.310 libmpi.so.12".split()
    out = "echo 'libz.so => not found'" if flags.get("unresolved") else "; ".join(f"echo '{l} => /x/{l}'" for l in libs)
    _stub(stubs / "ldd", out + "\n")
    fixture = tmp_path / "fixture_src"
    for f in ("CMakeLists.txt", "cmake/FindNetCDF.cmake", "src/adcirc.F", "prep/adcprep.F", "wind/vortex.F",
              "thirdparty/KDTREE2/kdtree2.F", "thirdparty/metis/Lib/coarsen.c", "thirdparty/datetime_fortran/CMakeLists.txt",
              "scripts/adcirc_version.py"):
        (fixture / f).parent.mkdir(parents=True, exist_ok=True)
        (fixture / f).write_text("x\n")
    (fixture / "version.F").write_text(f'      character(80), parameter:: ADC_VERSION = "v56.1.0"\n'
                                       f'      character(80), parameter:: ADC_HASH = "{HASH}"\n')
    (tmp_path / "ops_fixture.make").write_text(OPS_FLAGS_MAKE)
    e = {**env, "SRC": str(tmp_path / "adc_src"), "BLD": str(tmp_path / "adc_bld"),
         "ADCIRC_EXEC_DIR": str(tmp_path / "adc_exec"), "OPS_FLAGS": str(tmp_path / "ops.make")}
    if not fetch:
        shutil.copytree(fixture, e["SRC"])
        shutil.copy(tmp_path / "ops_fixture.make", e["OPS_FLAGS"])
        return e
    # stub network: wget drops the source tree without execute bits (as the real one), curl the ops flags.make MJ (10/13/26)
    _stub(stubs / "wget", f'echo "$@" > "{tmp_path}/wget.args"\nwhile [ $# -gt 0 ]; do [ "$1" = -P ] && d=$2; shift; done\n'
          f'cp -r "{fixture}/." "$d/"; chmod -x "$d"/scripts/*.py\n')
    _stub(stubs / "curl", f'while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; last=$1; shift; done\n'
          f'echo "$last" > "{tmp_path}/curl.url"\ncp "{tmp_path}/ops_fixture.make" "$out"\n')
    return e


def test_adcirc_build_configures_installs_and_verifies(env, tmp_path):
    r = _run(ADCIRC, ["build"], _adcirc_env(env, tmp_path))
    assert r.returncode == 0, r.stderr
    for x in ("padcirc", "adcprep"):
        assert os.access(tmp_path / "adc_exec" / x, os.X_OK)
    args = (tmp_path / "cmake.args").read_text()
    for needle in ("-DCMAKE_BUILD_TYPE=RelWithDebInfo", "-DBUILD_PADCIRC=ON", "-DBUILD_ADCPREP=ON", "-DENABLE_DATETIME=ON",
                   "-DENABLE_OUTPUT_NETCDF=ON", "-DNETCDF_INCLUDE_DIR:PATH=", "-DNETCDF_LIBRARY:FILEPATH=",
                   "-DNETCDF_F90_INCLUDE_DIR:PATH=", "-DNETCDF_F90_LIBRARY:FILEPATH=", "-DCMAKE_Fortran_FLAGS=-xCORE-AVX2"):
        assert needle in args
    assert os.access(tmp_path / "adc_src" / "scripts" / "adcirc_version.py", os.X_OK)
    assert "flags verified" in r.stdout and "padcirc -v: v56.1.0" in r.stdout and f"padcirc --hash: {HASH}" in r.stdout
    assert f"export ADCIRC_EXEC_DIR={tmp_path / 'adc_exec'}" in r.stdout


@pytest.mark.parametrize("flag,message", [("badver", "did not print"), ("unresolved", "unresolved libraries"),
                                          ("heap", "Fortran_FLAGS differ from ops")])
def test_adcirc_verification_fails_loudly(flag, message, env, tmp_path):
    r = _run(ADCIRC, ["build"], _adcirc_env(env, tmp_path, **{flag: True}))
    assert r.returncode == 1 and message in r.stderr


def test_adcirc_build_refuses_a_stack_that_cannot_be_raised_before_cmake(env, tmp_path):
    e = _adcirc_env(env, tmp_path)
    eight_mb = 8 * 1024 * 1024
    lower = lambda: resource.setrlimit(resource.RLIMIT_STACK, (eight_mb, eight_mb))  # hard limit too, so ulimit -s unlimited fails MJ (10/13/26)
    for mode in ("build", "all"):
        r = _run(ADCIRC, [mode], e, preexec_fn=lower)
        assert r.returncode == 1 and "FATAL: stack 8192: cmake would add -heap-arrays; run 'build' under srun" in r.stderr, mode
    assert not (tmp_path / "cmake.args").exists() and not (tmp_path / "adc_exec").exists()
    r = _run(ADCIRC, ["download"], e, preexec_fn=lower)  # download needs no stack MJ (10/13/26)
    assert r.returncode == 0, r.stderr


def test_adcirc_all_downloads_with_the_ops_wget_then_builds(env, tmp_path):
    e = _adcirc_env(env, tmp_path, fetch=True)
    r = _run(ADCIRC, ["all"], e)
    assert r.returncode == 0, r.stderr
    wget = (tmp_path / "wget.args").read_text()
    for needle in ("-r -np -nH --cut-dirs=7 -l inf -e robots=off -nv", "-R index.html*", "-P " + e["SRC"],
                   "/adcirc/build,", "/adcirc/build.orig,", "/adcirc/thirdparty/nuopc",
                   "https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/stofs.v3.1.5/sorc/stofs_2d_glo/adcirc/"):
        assert needle in wget
    assert (tmp_path / "curl.url").read_text().strip().endswith("/adcirc/build/CMakeFiles/padcirc.dir/flags.make")
    assert os.access(tmp_path / "adc_src" / "scripts" / "adcirc_version.py", os.X_OK) and "flags verified" in r.stdout
