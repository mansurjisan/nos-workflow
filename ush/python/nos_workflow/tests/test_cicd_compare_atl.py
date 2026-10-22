"""STOFS-3D-Atlantic CI comparison tool (.cicd/scripts/compare_atl.py) on small synthetic netCDF and staout files. Offline. MJ (10/14/26)"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

nc = pytest.importorskip("netCDF4")
np = pytest.importorskip("numpy")

SCRIPT = Path(__file__).resolve().parents[4] / ".cicd" / "scripts" / "compare_atl.py"
PDY = "20261011"
NSTA, NT = 6, 8
spec = importlib.util.spec_from_file_location("compare_atl", SCRIPT)
ca = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ca)


def _day(root: Path) -> Path:
    d = root / "nos" / f"stofs_3d_atl_ufs.{PDY}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _staout(path: Path, scale: float = 0.0, nt: int = NT):
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(1, nt + 1) * 360.0
    vals = np.sin(t[:, None] / 1000 + np.arange(NSTA)[None, :]) + scale
    np.savetxt(path, np.column_stack([t, vals]))


def _points(path: Path, bump: float = 0.0, base="2026-10-10 12:00:00 UTC", nt=NT, names=None, junk=()):
    names = names or [f"STA{i}" for i in range(NSTA)]
    with nc.Dataset(path, "w") as d:
        d.createDimension("time", None)
        d.createDimension("station", len(names))
        d.createDimension("namelen", 20)
        t = d.createVariable("time", "f8", ("time",))
        t.units = f"seconds since {base}"
        t[:] = np.arange(1, nt + 1) * 360.0
        n = d.createVariable("station_name", "S1", ("station", "namelen"))
        n[:] = np.array([list(name.ljust(20).encode()) for name in names], dtype="u1").view("S1")
        x = d.createVariable("x", "f8", ("station",))
        x[:] = np.arange(len(names))
        for v in ("zeta", "u", "v", "salinity", "temperature"):
            var = d.createVariable(v, "f8", ("time", "station"))
            a = np.cos(np.arange(nt)[:, None] / 3 + np.arange(len(names))[None, :])
            if v == "zeta":
                a = a + bump
                for j in junk:
                    a[:, j] = 9999999.5
            var[:] = a


def _profile(path: Path, bump: float = 0.0):
    with nc.Dataset(path, "w") as d:
        d.createDimension("time", None)
        d.createDimension("station", NSTA)
        d.createDimension("siglay", 3)
        t = d.createVariable("time", "f4", ("time",))
        t.units = "seconds since 2026-10-10 12:00:00 UTC"
        t[:] = np.arange(1, 5) * 3600.0
        for v in ("lon", "depth"):
            d.createVariable(v, "f4", ("station",))[:] = np.arange(NSTA)
        d.createVariable("zeta", "f4", ("time", "station"))[:] = np.ones((4, NSTA)) * 0.5 + bump
        d.createVariable("temperature", "f4", ("time", "station", "siglay"))[:] = np.ones((4, NSTA, 3)) * 20


def _cycle_tree(root: Path, **kw) -> None:
    day = _day(root)
    for rel in ca.regress_files("standalone", "cycle", PDY):
        p = root / rel
        if "staout_" in rel:
            _staout(p)
        elif ".points." in rel:
            _points(p, **kw)
        else:
            _profile(p)
    assert day.is_dir()


def _cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_files_lists_per_level_and_variant():
    smoke = ca.regress_files("standalone", "smoke", PDY)
    cycle = ca.regress_files("coupled", "cycle", PDY)
    assert smoke == [f"nos/stofs_3d_atl_ufs.{PDY}/stofs_3d_atl_ufs.t12z.restart_outputs/staout_{i}" for i in range(1, 9)]
    assert cycle[:8] == smoke and len(cycle) == 8 + 8 + 4
    assert f"nos/stofs_3d_atl_ufs.{PDY}/stofs_3d_atl_ufs.t12z.{PDY}.points.cwl.forecast.nc" in cycle
    assert f"nos/stofs_3d_atl_ufs.{PDY}/stofs_3d_atl_ufs.t12z.{PDY}.station.profile.nowcast.nc" in cycle
    assert ca.regress_files("coupled", "smoke", PDY) == smoke
    with pytest.raises(ValueError):
        ca.regress_files("bogus", "smoke", PDY)


def test_cli_files_and_ops_files():
    r = _cli("files", "--variant", "coupled", "--level", "smoke", "--pdy", PDY)
    assert r.returncode == 0 and len(r.stdout.split()) == 8
    r = _cli("ops-files", "--pdy", PDY)
    assert r.stdout.split() == ["stofs_3d_atl.t12z.points.cwl.temp.salt.vel.nc", "stofs_3d_atl.t12z.ncast.station.profile.nc",
                                "stofs_3d_atl.t12z.fcast.station.profile.nc"]


def _regress(ref, out, level="cycle", *extra):
    return _cli("regress", "--ref", str(ref), "--out", str(out), "--variant", "standalone", "--pdy", PDY, "--level", level, *extra)


def test_regress_bitwise_and_smoke_needs_only_nowcast(tmp_path):
    _cycle_tree(tmp_path / "ref")
    _cycle_tree(tmp_path / "out")
    r = _regress(tmp_path / "ref", tmp_path / "out")
    assert r.returncode == 0, r.stdout
    assert "20 files, 20 bitwise, 0 within tolerance, 0 failed" in r.stdout
    for p in (tmp_path / "out" / "nos" / f"stofs_3d_atl_ufs.{PDY}").glob("*.nc"):
        p.unlink()
    assert _regress(tmp_path / "ref", tmp_path / "out", "smoke").returncode == 0
    assert _regress(tmp_path / "ref", tmp_path / "out", "cycle").returncode == 1


def test_regress_tolerance_per_variable(tmp_path):
    _cycle_tree(tmp_path / "ref")
    _cycle_tree(tmp_path / "out", bump=5e-4)  # zeta shifts by 0.5 mm: inside the 1 mm water-level tolerance MJ (10/14/26)
    r = _regress(tmp_path / "ref", tmp_path / "out")
    assert r.returncode == 0 and "within tolerance" in r.stdout and "zeta" in r.stdout, r.stdout
    _cycle_tree(tmp_path / "out", bump=5e-3)
    r = _regress(tmp_path / "ref", tmp_path / "out")
    assert r.returncode == 1 and "zeta: max |diff|" in r.stdout
    assert _regress(tmp_path / "ref", tmp_path / "out", "cycle", "--tol", "1e-2").returncode == 0  # --tol scales the water level MJ (10/14/26)


def test_regress_staout_tolerance_and_time_column(tmp_path):
    _cycle_tree(tmp_path / "ref")
    _cycle_tree(tmp_path / "out")
    p = tmp_path / "out" / ca.regress_files("standalone", "smoke", PDY)[0]
    _staout(p, scale=5e-4)
    assert _regress(tmp_path / "ref", tmp_path / "out", "smoke").returncode == 0
    _staout(p, scale=5e-3)
    r = _regress(tmp_path / "ref", tmp_path / "out", "smoke")
    assert r.returncode == 1 and "staout_1" in r.stdout and "> tol" in r.stdout
    # staout_5 (temperature) has a 10x tolerance MJ (10/14/26)
    _staout(p, scale=0.0)
    p5 = tmp_path / "out" / ca.regress_files("standalone", "smoke", PDY)[4]
    _staout(p5, scale=5e-3)
    assert _regress(tmp_path / "ref", tmp_path / "out", "smoke").returncode == 0
    arr = np.loadtxt(p5)
    arr[:, 0] += 1
    np.savetxt(p5, arr)
    r = _regress(tmp_path / "ref", tmp_path / "out", "smoke")
    assert r.returncode == 1 and "time column" in r.stdout


@pytest.mark.parametrize("what", ["missing", "nan", "shape", "mask", "static", "unreadable", "noref"])
def test_regress_failures(tmp_path, what):
    _cycle_tree(tmp_path / "ref")
    _cycle_tree(tmp_path / "out")
    rels = ca.regress_files("standalone", "cycle", PDY)
    pts = tmp_path / "out" / rels[16]
    assert ".points.cwl.nowcast" in str(pts)
    if what == "missing":
        pts.unlink()
    elif what == "nan":
        with nc.Dataset(pts, "a") as d:
            z = d["zeta"][:]
            z[2, 1] = np.nan
            d["zeta"][:] = z
    elif what == "shape":
        _points(pts, nt=NT + 2)
    elif what == "mask":
        with nc.Dataset(pts, "a") as d:
            z = np.ma.masked_array(d["zeta"][:])
            z[0, 0] = np.ma.masked
            d["zeta"][:] = z
    elif what == "static":
        with nc.Dataset(pts, "a") as d:
            d["x"][:] = np.arange(NSTA) + 1e-9
    elif what == "unreadable":
        pts.write_text("not netcdf")
    else:
        (tmp_path / "ref" / rels[16]).unlink()
    r = _regress(tmp_path / "ref", tmp_path / "out")
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout and "1 failed" in r.stdout


def _ops_tree(tmp_path, ours_bump=0.0, **kw):
    out, opsd = tmp_path / "out", tmp_path / "ops"
    opsd.mkdir()
    day = _day(out)
    for ph in ("nowcast", "forecast"):
        _points(day / f"stofs_3d_atl_ufs.t12z.{PDY}.points.cwl.{ph}.nc", bump=ours_bump, **kw)
        _profile(day / f"stofs_3d_atl_ufs.t12z.{PDY}.station.profile.{ph}.nc", bump=ours_bump)
    _points(opsd / "stofs_3d_atl.t12z.points.cwl.temp.salt.vel.nc", junk=(5,))
    _profile(opsd / "stofs_3d_atl.t12z.ncast.station.profile.nc")
    _profile(opsd / "stofs_3d_atl.t12z.fcast.station.profile.nc")
    return out, opsd


def _ops(out, opsd, *extra):
    return _cli("ops", "--ops-dir", str(opsd), "--out", str(out), "--variant", "coupled", "--pdy", PDY, *extra)


def test_ops_report(tmp_path):
    out, opsd = _ops_tree(tmp_path, ours_bump=0.002, junk=(5,))
    r = _ops(out, opsd)
    assert r.returncode == 0, r.stdout
    assert "5 stations compared, 1 skipped" in r.stdout  # the out-of-mesh station is skipped MJ (10/14/26)
    assert "median 2.00 mm" in r.stdout
    assert "WARN" not in r.stdout
    r = _ops(out, opsd, "--warn-mm", "1")
    assert r.returncode == 0 and "WARN median" in r.stdout


def test_ops_time_axes_by_epoch(tmp_path):
    # nos-workflow nowcast axis starts a day earlier: only the overlapping instants are compared MJ (10/14/26)
    out, opsd = _ops_tree(tmp_path)
    _points(_day(out) / f"stofs_3d_atl_ufs.t12z.{PDY}.points.cwl.forecast.nc", base="2026-10-10 12:30:00")
    r = _ops(out, opsd)
    assert "no common times" not in r.stdout.split("points.cwl.forecast")[0]
    _points(_day(out) / f"stofs_3d_atl_ufs.t12z.{PDY}.points.cwl.forecast.nc", base="2026-10-20 12:00:00")
    assert "WARN no common times" in _ops(out, opsd).stdout


def test_ops_station_matching():
    ia, ib = ca.match_stations(["a", "b"], ["x", "y"], 2, 2)  # equal counts: row order, names ignored MJ (10/14/26)
    assert ia.tolist() == ib.tolist() == [0, 1]
    ia, ib = ca.match_stations(["a", "b", "c"], ["c", "a"], 3, 2)  # else exact names MJ (10/14/26)
    assert ia.tolist() == [0, 2] and ib.tolist() == [1, 0]
    assert ca.match_stations(["a", "b", "c"], ["x", "y"], 3, 2) is None
    assert ca.match_stations(None, None, 3, 2) is None


def test_ops_missing_run_output_fails_missing_ops_skips(tmp_path):
    out, opsd = _ops_tree(tmp_path)
    (opsd / "stofs_3d_atl.t12z.fcast.station.profile.nc").unlink()
    r = _ops(out, opsd)
    assert r.returncode == 0 and "SKIP" in r.stdout
    (_day(out) / f"stofs_3d_atl_ufs.t12z.{PDY}.points.cwl.forecast.nc").unlink()
    r = _ops(out, opsd)
    assert r.returncode == 1 and "FAIL" in r.stdout and "missing in this run" in r.stdout


def test_ops_station_count_mismatch_warns(tmp_path):
    out, opsd = _ops_tree(tmp_path, names=[f"STA{i}" for i in range(NSTA - 2)])
    r = _ops(out, opsd)
    assert r.returncode == 0 and "stations compared" in r.stdout


def _gate(out, opsd, med="5", over="10"):
    return _ops(out, opsd, "--fail-median-mm", med, "--fail-over-10cm", over)


def test_ops_gate_unset_stays_report_only(tmp_path):
    out, opsd = _ops_tree(tmp_path, ours_bump=0.5)  # MJ (10/22/26)
    r = _ops(out, opsd)
    assert r.returncode == 0 and "report only" in r.stdout and "FAIL" not in r.stdout and "PASS" not in r.stdout


def test_ops_gate_median_over_threshold_fails(tmp_path):
    out, opsd = _ops_tree(tmp_path, ours_bump=0.02)  # 20 mm everywhere, MJ (10/22/26)
    r = _gate(out, opsd)
    assert r.returncode == 1, r.stdout
    assert "FAIL  stofs_3d_atl_ufs.t12z.%s.points.cwl.nowcast.nc: median 20.00 mm > 5 mm" % PDY in r.stdout
    assert "PASS" not in r.stdout


def test_ops_gate_too_many_stations_over_10cm_fails(tmp_path):
    out, opsd = _ops_tree(tmp_path)  # MJ (10/22/26)
    for ph in ("nowcast", "forecast"):  # 2 of 5 compared stations 20 cm off, median stays 0. MJ (10/22/26)
        f = _day(out) / f"stofs_3d_atl_ufs.t12z.{PDY}.points.cwl.{ph}.nc"
        with nc.Dataset(f, "a") as d:
            d.variables["zeta"][:, 0:2] = d.variables["zeta"][:, 0:2] + 0.2
    r = _gate(out, opsd, over="1")
    assert r.returncode == 1 and "2 stations over 10 cm > 1" in r.stdout and "> 5 mm" not in r.stdout
    r = _gate(out, opsd, over="2")
    assert r.returncode == 0 and "over 10 cm 2" in r.stdout


def test_ops_gate_nothing_compared_fails(tmp_path):
    out, opsd = _ops_tree(tmp_path)  # MJ (10/22/26)
    _points(_day(out) / f"stofs_3d_atl_ufs.t12z.{PDY}.points.cwl.forecast.nc", base="2026-10-20 12:00:00")
    r = _gate(out, opsd)
    assert r.returncode == 1 and "nothing compared" in r.stdout
    assert _ops(out, opsd).returncode == 0


def test_ops_gate_boundary_is_strict(tmp_path):
    out, opsd = _ops_tree(tmp_path)  # MJ (10/22/26)
    r = _gate(out, opsd, med="0", over="0")
    assert r.returncode == 0 and r.stdout.count("PASS  ") == 4


def test_ops_gate_flags_go_together(tmp_path):
    out, opsd = _ops_tree(tmp_path)  # MJ (10/22/26)
    assert _ops(out, opsd, "--fail-median-mm", "5").returncode == 2


def test_ops_gate_within_thresholds_passes(tmp_path):
    out, opsd = _ops_tree(tmp_path, ours_bump=0.002)  # MJ (10/22/26)
    r = _gate(out, opsd)
    assert r.returncode == 0 and r.stdout.count("PASS  ") == 4 and "FAIL" not in r.stdout


def test_ops_gate_missing_ops_product_skips(tmp_path):
    out, opsd = _ops_tree(tmp_path)  # MJ (10/22/26)
    (opsd / "stofs_3d_atl.t12z.fcast.station.profile.nc").unlink()
    r = _gate(out, opsd)
    assert r.returncode == 0 and "SKIP" in r.stdout and r.stdout.count("PASS  ") == 3


# MJ (10/14/26)
def test_staout_parse_accepts_fortran_numbers_without_an_exponent_letter(tmp_path):
    f = tmp_path / "staout_1"
    f.write_text("  360.0  0.427-100  -1.5+101  2.25\n  720.0  0.5  -0.25  1.0\n")
    a = ca._load_staout(f)
    assert a.shape == (2, 4) and a[0, 1] == pytest.approx(0.427e-100) and a[0, 2] == pytest.approx(-1.5e101) and a[1, 3] == 1.0
    assert ca.compare_staout(f, f, 1e-3)[0]
