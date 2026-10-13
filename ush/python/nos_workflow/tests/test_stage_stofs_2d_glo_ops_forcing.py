"""Tests for tools/stage_stofs_2d_glo_ops_forcing.py and tools/hercules_2d_glo_stage_forcing.sh. Synthetic 5x4 grids; the
nos-utils reference is its own build_sfcf_forcing run on a fake GFS sfcf tank, and the 'ops' files are built from the same
sfcf files by a separate mini ncecat+ncwa below. The shell tool runs end to end against a fake curl that serves those files.

STAGE_TEST_NET=1 adds the real-data header check against the public S3 bucket (metadata + one icec record). MJ (10/13/26)
"""
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

nc = pytest.importorskip("netCDF4")

REPO = Path(__file__).resolve().parents[4]
TOOL = REPO / "tools" / "stage_stofs_2d_glo_ops_forcing.py"
SHELL = REPO / "tools" / "hercules_2d_glo_stage_forcing.sh"
NU = str(REPO / "ush" / "python" / "nos-utils")
if not (Path(NU) / "nos_utils" / "forcing" / "adcirc_met.py").is_file():
    pytest.skip("nos-utils submodule not initialised", allow_module_level=True)

_spec = importlib.util.spec_from_file_location("stage_stofs_2d_glo_ops_forcing", str(TOOL))
S = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = S
_spec.loader.exec_module(S)

am = S.load_nos_utils(NU)
NY, NX = 5, 4
CYC = datetime(2026, 10, 4, 0)
FILL = np.float32(9.99e20)
VARS = {"pressfc": 0, "ugrd10m": 1, "vgrd10m": 2, "icec": 3}


def mk_sfcf(comin, cycle, fhr):
    p = am.sfcf_path(comin, cycle, fhr)
    p.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(int((cycle - datetime(2026, 1, 1)).total_seconds() // 3600) * 1000 + fhr)
    ds = nc.Dataset(str(p), "w", format="NETCDF4_CLASSIC")
    ds.fhzero, ds.dtp, ds.source = 6, np.float32(150.0), "FV3GFS"
    ds.createDimension("grid_xt", NX)
    ds.createDimension("grid_yt", NY)
    ds.createDimension("time", 1)
    x = ds.createVariable("grid_xt", "f8", ("grid_xt",))
    x[:] = np.arange(NX)
    x.units = "degrees_E"
    y = ds.createVariable("grid_yt", "f8", ("grid_yt",))
    y[:] = np.arange(NY)
    lon = ds.createVariable("lon", "f8", ("grid_yt", "grid_xt"))
    lon[:] = np.tile(np.arange(NX, dtype="f8"), (NY, 1))
    lat = ds.createVariable("lat", "f8", ("grid_yt", "grid_xt"))
    lat[:] = np.tile(np.arange(NY, dtype="f8")[:, None], (1, NX))
    t = ds.createVariable("time", "f8", ("time",))
    t.units = "hours since {:%Y-%m-%d %H:%M:%S}".format(cycle)
    t.cartesian_axis = "T"
    t[:] = fhr
    for name in sorted(VARS):
        v = ds.createVariable(name, "f4", ("time", "grid_yt", "grid_xt"), fill_value=FILL)
        v.long_name, v.cell_methods, v.output_file, v.missing_value = name, "time: point", "sfc", FILL
        a = (1e5 if name == "pressfc" else 0.0) + rng.standard_normal((NY, NX)) * (1e3 if name == "pressfc" else 10.0)
        if name == "icec":
            a = rng.uniform(0, 1, (NY, NX))
            if fhr in (123, 126, 0):  # fill in both brackets of 121-125 and in f000
                a[0, 0] = FILL
            if fhr == 126:
                a[1, 1] = FILL
        if name == "vgrd10m" and fhr == 150:
            a[2, 3] = FILL
        v[0] = a.astype("f4")
    ds.close()
    p.with_name(p.name.replace("sfcf", "logf").replace(".nc", ".txt")).write_text("done")
    return p


def mk_ops(path, srcs, names):
    """What ncks + ncecat + ncwa -a time make of per-hour sfcf files: record dim, per-record lat/lon, scalar time, NCO attrs."""
    first = nc.Dataset(str(srcs[0]))
    o = nc.Dataset(str(path), "w", format="NETCDF4_CLASSIC")
    for k in first.ncattrs():
        o.setncattr(k, first.getncattr(k))
    o.history = "Mon Oct 12 04:18:27 2026: ncwa -a time tmp.nc fort.nc"
    o.NCO = "netCDF Operators version 5.0.6"
    o.createDimension("grid_xt", NX)
    o.createDimension("grid_yt", NY)
    o.createDimension("record", None)
    for v in sorted(("grid_xt", "grid_yt", "lat", "lon", "time") + names):
        sv = first.variables[v]
        fill = sv.getncattr("_FillValue") if "_FillValue" in sv.ncattrs() else None
        if v in ("grid_xt", "grid_yt"):
            ov = o.createVariable(v, sv.dtype, (v,))
            ov[:] = sv[:]
        elif v == "time":
            ov = o.createVariable(v, sv.dtype, ())
            ov[...] = sv[0]
        else:
            kw = dict(zlib=True, complevel=1, shuffle=True) if v in names else {}
            ov = o.createVariable(v, sv.dtype, ("record", "grid_yt", "grid_xt"), fill_value=fill, chunksizes=(1, NY, NX), **kw)
        for a in sv.ncattrs():
            if a != "_FillValue":
                ov.setncattr(a, sv.getncattr(a))
        if v in names or v == "time":
            cm = getattr(sv, "cell_methods", "")
            ov.cell_methods = (cm + " " if cm else "") + "time: mean"
    first.close()
    for i, s in enumerate(srcs):
        with nc.Dataset(str(s)) as d:
            d.set_auto_maskandscale(False)
            for v in ("lat", "lon") + names:
                o.variables[v][i] = d.variables[v][0] if v in names else d.variables[v][:]
    o.close()


def snapshot(path):
    with nc.Dataset(str(path)) as d:
        d.set_auto_maskandscale(False)
        return {
            "format": d.data_model,
            "dims": {k: (len(v), v.isunlimited()) for k, v in d.dimensions.items()},
            "gattrs": {k: np.asarray(d.getncattr(k)).tolist() for k in d.ncattrs()},
            "vars": [(k, str(v.dtype), v.dimensions, v.chunking(), v.filters(),
                      {a: np.asarray(v.getncattr(a)).tolist() for a in v.ncattrs()}) for k, v in d.variables.items()],
            "data": {k: v[:] for k, v in d.variables.items()},
        }


def assert_same(a, b):
    da, db = a.pop("data"), b.pop("data")
    assert a == b
    assert list(da) == list(db)
    for k in da:
        assert da[k].dtype == db[k].dtype and da[k].shape == db[k].shape and np.array_equal(da[k], db[k]), k


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("world")
    tank, ops, ref = base / "gfs", base / "ops", base / "ref"
    c18, c12 = CYC - timedelta(hours=6), CYC - timedelta(hours=12)
    ncst_src = [(c12, 6)] + [(c18, h) for h in range(1, 6)] + [(CYC, 0)]
    f1_src = [(CYC, h) for h in range(0, 121)]
    f2_src = [(CYC, h) for h in range(120, 181, 3)]
    for cyc, h in set(ncst_src + f1_src + f2_src):
        mk_sfcf(tank, cyc, h)
    ops.mkdir()
    for n, names in am.SFC_OUTPUTS:
        for seg, lst in (("ncst", ncst_src), ("fcst1", f1_src), ("fcst2", f2_src)):
            mk_ops(ops / "stofs_2d_glo_{}.{}.nc".format(seg, n), [am.sfcf_path(tank, c, h) for c, h in lst], names)
    am.build_sfcf_forcing(tank, CYC, "ncst", ref)
    am.build_sfcf_forcing(tank, CYC, "fcst", ref)
    return {"base": base, "tank": tank, "ops": ops, "ref": ref}


@pytest.fixture(scope="module")
def staged(world):
    out, lines = world["base"] / "rerun", []
    S.stage(str(world["ops"]), out, NU, out=lines.append)
    return {"out": out, "lines": lines}


def rd(path, v):
    with nc.Dataset(str(path)) as d:
        d.set_auto_maskandscale(False)
        return d.variables[v][:]


def test_outputs_equal_nos_utils_reference_bitwise(world, staged):
    names = sorted(p.name for p in staged["out"].iterdir())
    assert names == sorted(p.name for p in world["ref"].iterdir())  # six .nc and two manifests, no .partial
    for n in S.NUMS:
        for seg in ("ncst", "fcst"):
            f = "stofs_2d_glo_{}.{}.nc".format(seg, n)
            assert_same(snapshot(staged["out"] / f), snapshot(world["ref"] / f))


def test_manifest_matches_reference(world, staged):
    import json
    for seg in ("ncst", "fcst"):
        f = "stofs_2d_glo_{}.sfcf_manifest.json".format(seg)
        a, b = (json.loads((d / f).read_text()) for d in (staged["out"], world["ref"]))
        assert {k: v for k, v in a.items() if k != "files"} == {k: v for k, v in b.items() if k != "files"}
        assert [e["valid_time"] for e in a["files"]] == [e["valid_time"] for e in b["files"]]
        assert all(Path(e["source_location"]).parent == world["ops"] for e in a["files"])


def test_fcst_record_mapping_and_interpolation(world, staged):
    ops, out = world["ops"], staged["out"]
    for n, names in am.SFC_OUTPUTS:
        for v in names:
            got = rd(out / "stofs_2d_glo_fcst.{}.nc".format(n), v)
            f1, f2 = (rd(ops / "stofs_2d_glo_{}.{}.nc".format(s, n), v) for s in ("fcst1", "fcst2"))
            assert got.shape[0] == 181 and f1.shape[0] == 121 and f2.shape[0] == 21
            assert np.array_equal(got[:121], f1)
            assert np.array_equal(got[120::3], f2)
            for fh in range(121, 180):
                if fh % 3 == 0:
                    continue
                lo, w = (fh - 120) // 3, (fh % 3) / 3.0
                a0, a1 = f2[lo].astype("f8"), f2[lo + 1].astype("f8")
                want = np.where((f2[lo] == FILL) | (f2[lo + 1] == FILL), FILL, a0 * (1 - w) + a1 * w).astype("f4")
                assert np.array_equal(got[fh], want), (n, v, fh)
    p = rd(out / "stofs_2d_glo_fcst.221.nc", "pressfc")
    f2 = rd(ops / "stofs_2d_glo_fcst2.221.nc", "pressfc")
    assert np.allclose(p[121], f2[0] * (2 / 3) + f2[1] * (1 / 3), rtol=1e-6)  # 121 is 1/3 of the way to f123
    assert np.allclose(p[122], f2[0] * (1 / 3) + f2[1] * (2 / 3), rtol=1e-6)


def test_fill_values_kept(staged):
    i = rd(staged["out"] / "stofs_2d_glo_fcst.225.nc", "icec")
    # f123 and f126 both hold fill at [0,0], only f126 at [1,1]
    assert all(i[h][0, 0] == FILL for h in range(121, 126))
    assert all(i[h][1, 1] == FILL for h in (124, 125)) and i[121][1, 1] != FILL and i[122][1, 1] != FILL
    assert i[121][0, 1] < 2 and i[0][0, 0] == FILL
    v = rd(staged["out"] / "stofs_2d_glo_fcst.222.nc", "vgrd10m")  # fill only in f150, whose neighbours interpolate against it
    assert all(v[h][2, 3] == FILL for h in (148, 149, 150, 151, 152)) and v[147][2, 3] != FILL and v[153][2, 3] != FILL


def test_interp_is_nos_utils_formula_bitwise():
    rng = np.random.RandomState(7)
    a0 = rng.standard_normal((50, 60)).astype("f4") * 1e3 + 1e5
    a1 = rng.standard_normal((50, 60)).astype("f4") * 1e3 + 1e5
    a0[3, 3] = a1[4, 4] = FILL
    for fh in range(121, 180):
        br = am._interp_bracket(CYC, CYC + timedelta(hours=fh))
        if fh % 3 == 0:
            assert br is None
            continue
        lo, hi, w = br
        assert (lo, hi) == (fh // 3 * 3, fh // 3 * 3 + 3) and w == (fh - lo) / 3.0
        r = a0.astype(np.float64) * (1.0 - w) + a1.astype(np.float64) * w  # the build_sfcf_forcing lines, copied
        r = np.where((a0 == FILL) | (a1 == FILL), FILL, r).astype(a0.dtype)
        assert np.array_equal(S.interp(a0, a1, w, FILL), r) and r[3, 3] == FILL and r[4, 4] == FILL
        assert S.interp(a0, a1, w, None).dtype == np.float32


def test_summary_lines_and_order(staged):
    lines = [x for x in staged["lines"] if x.startswith("stofs_2d_glo_")]
    assert len(lines) == 6
    assert lines[0].startswith("stofs_2d_glo_ncst.221.nc  7 records, pressfc min/max rec0 ")
    assert "rec6 " in lines[0] and "rec180 " in lines[3] and "181 records" in lines[5]
    assert "ugrd10m" in lines[4] and "vgrd10m" in lines[4] and "all fill" not in lines[3]


def test_existing_outputs_skipped_then_forced(world, staged):
    out = staged["out"]
    before = {p.name: p.stat().st_mtime_ns for p in out.iterdir()}
    lines = []
    S.stage(str(world["ops"]), out, NU, out=lines.append)
    assert sum(x.startswith("skip ") for x in lines) == 2 and {p.name: p.stat().st_mtime_ns for p in out.iterdir()} == before
    S.stage(str(world["ops"]), out, NU, force=True, out=lines.append)
    assert all(p.stat().st_mtime_ns > before[p.name] for p in out.iterdir() if p.name in before)
    assert not list(out.glob("*.partial"))
    assert_same(snapshot(out / "stofs_2d_glo_fcst.222.nc"), snapshot(world["ref"] / "stofs_2d_glo_fcst.222.nc"))


def run_main(ops, out, *extra):
    return S.main(["--ops-dir", str(ops), "--out", str(out), "--nos-utils", NU] + list(extra))


def test_missing_input_fails_cleanly(world, tmp_path, capsys):
    ops = tmp_path / "ops"
    shutil.copytree(world["ops"], ops)
    (ops / "stofs_2d_glo_fcst2.222.nc").unlink()
    assert run_main(ops, tmp_path / "o") == 1
    err = capsys.readouterr().err
    assert "ERROR: missing ops input" in err and "stofs_2d_glo_fcst2.222.nc" in err
    assert not (tmp_path / "o").exists() or not list((tmp_path / "o").iterdir())


def test_unexpected_record_counts_fail(world, tmp_path, capsys):
    src = [am.sfcf_path(world["tank"], CYC, h) for h in range(120, 178, 3)]  # 20 records
    ops = tmp_path / "ops"
    shutil.copytree(world["ops"], ops)
    mk_ops(ops / "stofs_2d_glo_fcst2.225.nc", src, ("icec",))
    assert run_main(ops, tmp_path / "o") == 1
    assert "fcst2.225.nc has 20 records, expected 21" in capsys.readouterr().err
    assert run_main(world["ops"], tmp_path / "o2", "--ncst-records", "6") == 1
    assert "ncst.221.nc has 7 records, expected 6" in capsys.readouterr().err
    assert run_main(world["ops"], tmp_path / "o3", "--check") == 0 and not (tmp_path / "o3").exists()


def test_mixed_cycles_fail(world, tmp_path, capsys):
    other = CYC + timedelta(hours=6)
    for h in range(120, 181, 3):
        mk_sfcf(tmp_path / "g", other, h)
    ops = tmp_path / "ops"
    shutil.copytree(world["ops"], ops)
    mk_ops(ops / "stofs_2d_glo_fcst2.221.nc", [am.sfcf_path(tmp_path / "g", other, h) for h in range(120, 181, 3)], ("pressfc",))
    assert run_main(ops, tmp_path / "o") == 1
    assert "not one cycle" in capsys.readouterr().err


def test_grid_mismatch_leaves_nothing_behind(world, tmp_path, capsys):
    ops = tmp_path / "ops"
    shutil.copytree(world["ops"], ops)
    with nc.Dataset(str(ops / "stofs_2d_glo_fcst2.222.nc"), "a") as d:
        d.variables["lon"][5] = d.variables["lon"][5] + 0.5
    with pytest.raises(S.StageError, match="grid differs"):
        S.stage(str(ops), tmp_path / "o", NU, out=lambda s: None)
    # ncst finished before fcst failed; nothing of fcst remains, not even a .partial
    assert sorted(p.name for p in (tmp_path / "o").iterdir() if "fcst" in p.name) == []


def test_load_nos_utils_errors(tmp_path):
    with pytest.raises(S.StageError, match="nos-utils checkout"):
        S.load_nos_utils(str(tmp_path))


def test_load_nos_utils_default_is_the_repo_submodule(monkeypatch, tmp_path):
    monkeypatch.setenv("NOS_UTILS_DIR", str(tmp_path))  # an inherited, wrong checkout must not win. MJ (10/13/26)
    mod = S.load_nos_utils(None)
    assert Path(mod.__file__).resolve() == (Path(NU) / "nos_utils" / "forcing" / "adcirc_met.py").resolve()


FAKE_CURL = """#!/bin/bash
# serves $FAKE_SRV by basename for the two curl forms the tool uses; logs 'HEAD|GET name' to $FAKE_LOG. MJ (10/13/26)
head=0; out=; url=
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift ;;
    --retry|--retry-delay|-C) shift ;;
    -*I*) head=1 ;;
    -*) ;;
    *) url=$1 ;;
  esac
  shift
done
name=$(basename "$url"); f=$FAKE_SRV/$name
if [ $head = 1 ]; then
  echo "HEAD $name" >> "$FAKE_LOG"
  [ -z "${FAKE_HEAD_FAIL:-}" ] && [ -f "$f" ] || exit 22
  printf 'HTTP/1.1 200 OK\\r\\nContent-Length: %s\\r\\n\\r\\n' "$(stat -c %s "$f")"
  exit 0
fi
echo "GET $name" >> "$FAKE_LOG"
[ -f "$f" ] || exit 22
cp "$f" "$out"
"""


@pytest.fixture()
def shell_env(world, tmp_path):
    srv, bindir = tmp_path / "srv", tmp_path / "bin"
    srv.mkdir()
    bindir.mkdir()
    for p in world["ops"].iterdir():
        shutil.copy(str(p), str(srv / p.name))
    for k in ("htp", "cwl.noanomaly", "swl"):
        (srv / "stofs_2d_glo.t00z.points.{}.nc".format(k)).write_bytes(b"x" * 100)
    (bindir / "curl").write_text(FAKE_CURL)
    (bindir / "curl").chmod(0o755)
    env = {
        "PATH": os.pathsep.join([str(bindir), str(Path(sys.executable).parent), os.environ["PATH"]]),
        "HOME": str(tmp_path), "LOGNAME": "tester", "NOS_PTMP": str(tmp_path / "ptmp"),
        "COMROOT_2DGLO": str(tmp_path / "com"), "OPS_WORK": str(tmp_path / "work"), "NOS_VENV": str(tmp_path / "novenv"),
        "FAKE_SRV": str(srv), "FAKE_LOG": str(tmp_path / "curl.log"),
    }
    return {"env": env, "rerun": tmp_path / "com" / "nos" / "stofs_2d_glo.20261004" / "00" / "rerun",
            "work": tmp_path / "work", "log": tmp_path / "curl.log"}


def run_shell(se, *args, **extra):
    env = dict(se["env"], **extra)
    return subprocess.run(["bash", str(SHELL)] + list(args), env=env, capture_output=True, text=True, timeout=600)


def curl_log(se):
    return sorted(se["log"].read_text().split("\n")[:-1]) if se["log"].exists() else []


def test_shell_tool_syntax_and_arguments(shell_env):
    subprocess.run(["bash", "-n", str(SHELL)], check=True)
    assert run_shell(shell_env).returncode == 2
    assert run_shell(shell_env, "2026100", "00").returncode == 2
    assert run_shell(shell_env, "20261004", "03").returncode == 2
    assert run_shell(shell_env, "--bogus", "20261004", "00").returncode == 2
    h = run_shell(shell_env, "-h")
    assert h.returncode == 0 and "STAGE_SRUN" in h.stdout and "--rm-raw" in h.stdout
    assert not shell_env["work"].exists() and not shell_env["rerun"].exists() and not curl_log(shell_env)


def test_shell_tool_downloads_stages_skips_and_resumes(world, shell_env):
    se, rerun = shell_env, shell_env["rerun"]
    r = run_shell(se, "20261004", "00")
    assert r.returncode == 0, r.stdout + r.stderr
    # the layout the Slurm cards and the ops runner read: <COMROOT_2DGLO>/nos/stofs_2d_glo.<PDY>/<CC>/rerun. MJ (10/13/26)
    assert sorted(p.name for p in rerun.iterdir()) == sorted(p.name for p in world["ref"].iterdir())
    for seg, n in (("ncst", 7), ("fcst", 181)):
        assert "stofs_2d_glo_{}.221.nc record = {}".format(seg, n) in r.stdout
    assert sorted(p.name for p in (se["work"] / "forcing").iterdir()) == sorted(
        "stofs_2d_glo_{}.{}.nc".format(g, n) for g in ("ncst", "fcst1", "fcst2") for n in S.NUMS)
    assert sorted(p.name for p in (se["work"] / "products").iterdir()) == [
        "stofs_2d_glo.t00z.points.cwl.noanomaly.nc", "stofs_2d_glo.t00z.points.htp.nc", "stofs_2d_glo.t00z.points.swl.nc"]
    log = curl_log(se)
    assert sum(x.startswith("GET ") for x in log) == 12 and sum(x.startswith("HEAD ") for x in log) == 12
    assert_same(snapshot(rerun / "stofs_2d_glo_fcst.222.nc"), snapshot(world["ref"] / "stofs_2d_glo_fcst.222.nc"))

    # second run: every size matches its HEAD, so nothing is fetched and the staged outputs are kept. MJ (10/13/26)
    se["log"].unlink()
    before = {p.name: p.stat().st_mtime_ns for p in rerun.iterdir()}
    r = run_shell(se, "20261004", "00")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("SKIP ") == 12 and not any(x.startswith("GET ") for x in curl_log(se))
    assert {p.name: p.stat().st_mtime_ns for p in rerun.iterdir()} == before

    # a failing HEAD must not skip: all twelve are fetched again, then --rm-raw drops the forcing only. MJ (10/13/26)
    se["log"].unlink()
    r = run_shell(se, "--rm-raw", "20261004", "00", FAKE_HEAD_FAIL="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert sum(x.startswith("GET ") for x in curl_log(se)) == 12 and "SKIP " not in r.stdout
    assert not (se["work"] / "forcing").exists() and len(list((se["work"] / "products").iterdir())) == 3
    assert not list(rerun.glob("*.partial"))


def test_shell_tool_keeps_raw_and_fails_on_wrong_record_counts(world, shell_env):
    se, rerun = shell_env, shell_env["rerun"]
    shutil.copytree(str(world["ref"]), str(rerun))
    shutil.copy(str(rerun / "stofs_2d_glo_ncst.221.nc"), str(rerun / "stofs_2d_glo_fcst.221.nc"))  # 7 records where 181 belong. MJ (10/13/26)
    r = run_shell(se, "--rm-raw", "20261004", "00")
    assert r.returncode == 1 and "stofs_2d_glo_fcst.221.nc record = 7   EXPECTED 181" in r.stdout
    assert len(list((se["work"] / "forcing").iterdir())) == 9


def test_shell_tool_exit_3_when_a_reference_file_is_missing(shell_env):
    se = shell_env
    (Path(se["env"]["FAKE_SRV"]) / "stofs_2d_glo.t00z.points.swl.nc").unlink()
    r = run_shell(se, "20261004", "00")
    assert r.returncode == 3 and "forcing staged" in r.stdout and "FAIL stofs_2d_glo.t00z.points.swl.nc" in r.stderr
    assert (se["rerun"] / "stofs_2d_glo_fcst.221.nc").is_file()


def test_shell_tool_stops_when_a_forcing_file_cannot_be_fetched(shell_env):
    se = shell_env
    (Path(se["env"]["FAKE_SRV"]) / "stofs_2d_glo_fcst2.225.nc").unlink()
    r = run_shell(se, "20261004", "00")
    assert r.returncode == 1 and "FATAL: forcing download failed" in r.stderr
    assert not se["rerun"].exists() or not list(se["rerun"].iterdir())


@pytest.mark.skipif(not os.environ.get("STAGE_TEST_NET"), reason="needs the public S3 bucket")
def test_real_ops_headers_over_http():
    base = "https://noaa-gestofs-pds.s3.amazonaws.com/stofs_2d_glo.20261012/00/rerun"
    cyc = S.check_inputs(nc, base, 7)
    assert cyc == datetime(2026, 10, 12, 0)
    with nc.Dataset(S.ops_path(base, "fcst2", "225")) as d:
        d.set_auto_maskandscale(False)
        assert d.data_model == "NETCDF4_CLASSIC" and len(d.dimensions["record"]) == 21
        assert (len(d.dimensions["grid_yt"]), len(d.dimensions["grid_xt"])) == (1536, 3072)
        assert list(d.variables) == ["grid_xt", "grid_yt", "icec", "lat", "lon", "time"]
        v = d.variables["icec"]
        assert v.dtype == np.float32 and v.getncattr("_FillValue") == FILL and v.getncattr("cell_methods") == "time: point time: mean"
        assert d.variables["lat"].dtype == np.float64 and d.variables["time"].dimensions == ()
        a = v[0]
        assert a.shape == (1536, 3072) and a.dtype == np.float32
        ok = a != FILL
        assert 0 <= a[ok].min() and a[ok].max() <= 1


@pytest.mark.skipif(not os.environ.get("STAGE_TEST_NET"), reason="needs the public S3 bucket")
@pytest.mark.parametrize("seg,num", [("fcst2", "225"), ("fcst1", "222"), ("ncst", "221")])
def test_writer_header_equals_real_ops_header(tmp_path, seg, num):
    """The header nos-utils' writer makes from a real ops file is that file's own header (less NCO history), without any record."""
    base = "https://noaa-gestofs-pds.s3.amazonaws.com/stofs_2d_glo.20261012/00/rerun"
    names = dict(am.SFC_OUTPUTS)[num]

    def head(d):
        d.set_auto_maskandscale(False)
        return {
            "format": d.data_model,
            "dims": {k: v.isunlimited() for k, v in d.dimensions.items()},
            "gattrs": {k: np.asarray(d.getncattr(k)).tolist() for k in d.ncattrs() if k not in S._NCO_ATTRS},
            "vars": [(k, str(v.dtype), v.dimensions, v.chunking(), v.filters(),
                      {a: np.asarray(v.getncattr(a)).tolist() for a in v.ncattrs()}) for k, v in d.variables.items()],
            "coords": [d.variables[k][:].tolist() for k in ("grid_xt", "grid_yt")] + [float(d.variables["time"][...])],
        }
    with nc.Dataset(S.ops_path(base, seg, num)) as real:
        o = am._open_sfcf_output(nc, tmp_path / "h.nc", S._SrcDs(real), names)
        o.close()
        want = head(real)
    with nc.Dataset(str(tmp_path / "h.nc")) as mine:
        got = head(mine)
    assert got == want
