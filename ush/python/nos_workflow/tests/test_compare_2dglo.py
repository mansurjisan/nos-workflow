"""compare_2dglo.py fields / met: synthetic ADCIRC-like and grid netCDF files. MJ (10/15/26)"""
import importlib.util
import sys
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[4] / ".cicd" / "scripts" / "compare_2dglo.py"


def _load():
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec = importlib.util.spec_from_file_location("compare_2dglo_f", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = keep
    return mod


cmp2d = _load()
NN = 6


def _adcirc(path, zeta=None, zmax=None, t0=0, ntime=5):
    with nc.Dataset(path, "w") as d:
        d.createDimension("node", NN)
        x = d.createVariable("x", "f8", ("node",))
        y = d.createVariable("y", "f8", ("node",))
        x[:], y[:] = np.arange(NN) * 1.5, np.arange(NN) * 0.5
        if zeta is not None:
            d.createDimension("time", ntime)
            t = d.createVariable("time", "f8", ("time",))
            t.units = "seconds since 2026-05-26 12:00:00        ! NCDASE - BASE_DAT"
            t[:] = (np.arange(ntime) + t0) * 3600.0
            d.createVariable("zeta", "f4", ("time", "node"))[:] = zeta
        if zmax is not None:
            d.createVariable("zeta_max", "f8", ("node",), fill_value=-99999.0)[:] = zmax
    return path


def _base(ntime=5):
    return np.linspace(-1, 1, ntime * NN).reshape(ntime, NN).astype("f4")


def test_stats_masking_and_wetdry(tmp_path):
    a, b = _base(), _base()
    b[:, 1] += 0.0005
    b[2, 2] += 0.5
    a[0, 3] = -99999.0  # dry in ours only
    b[1, 4] = -99999.0
    a[1, 4] = -99999.0  # dry in both, not a mismatch
    fa, fb = _adcirc(tmp_path / "a.nc", a), _adcirc(tmp_path / "b.nc", b)
    with nc.Dataset(fa) as da, nc.Dataset(fb) as db:
        da.set_auto_mask(False)
        db.set_auto_mask(False)
        st = cmp2d.field_stats(da, db, "zeta", 8)
    assert st["ntimes"] == (5, 5, 5)
    assert st["nmis"] == 1 and st["mis_nodes"] == 1
    assert st["max"] == pytest.approx(0.5, abs=1e-6)
    assert st["maxd"][2] == pytest.approx(0.5, abs=1e-6)
    assert st["maxd"][1] == pytest.approx(0.0005, abs=1e-6)
    assert st["w1cm"] == 5 and st["o10cm"] == 1 and st["ncompared"] == 6
    assert st["npair"] == 5 * NN - 2


def test_common_times_and_chunk_equivalence(tmp_path):
    a = _base(5)
    b = _base(5)[2:] + 0.002
    fa, fb = _adcirc(tmp_path / "a.nc", a), _adcirc(tmp_path / "b.nc", b, t0=2, ntime=3)
    res = []
    for chunk in (1, 2, 100):
        with nc.Dataset(fa) as da, nc.Dataset(fb) as db:
            da.set_auto_mask(False)
            db.set_auto_mask(False)
            res.append(cmp2d.field_stats(da, db, "zeta", chunk))
    assert res[0]["ntimes"] == (3, 5, 3)
    for r in res[1:]:
        assert np.array_equal(r["maxd"], res[0]["maxd"])
        assert r["npair"] == res[0]["npair"]
        assert r["mean"] == pytest.approx(res[0]["mean"]) and r["rms"] == pytest.approx(res[0]["rms"])
    assert res[0]["mean"] == pytest.approx(0.002, abs=1e-6)


def test_maxele_cli(tmp_path, capsys):
    za, zb = np.arange(NN, dtype="f8"), np.arange(NN, dtype="f8")
    zb[3] += 0.25
    za[5] = -99999.0
    fa = _adcirc(tmp_path / "a.nc", zmax=za)
    fb = _adcirc(tmp_path / "b.nc", zmax=zb)
    assert cmp2d.main(["fields", "--ours", str(fa), "--ops", str(fb)]) == 0
    out = capsys.readouterr().out
    assert "zeta_max" in out and "wet/dry mismatches: 1 node-time pairs at 1 nodes" in out
    assert "node 4  lon 4.5000 lat 1.5000" in out


def test_fields_cli_missing_and_incompatible(tmp_path, capsys):
    fa = _adcirc(tmp_path / "a.nc", _base())
    assert cmp2d.main(["fields", "--ours", str(fa), "--ops", str(tmp_path / "none.nc")]) == 1
    fb = _adcirc(tmp_path / "b.nc", zmax=np.zeros(NN))
    assert cmp2d.main(["fields", "--ours", str(fa), "--ops", str(fb)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_map_written_or_skipped(tmp_path, capsys, monkeypatch):
    fa = _adcirc(tmp_path / "a.nc", _base())
    fb = _adcirc(tmp_path / "b.nc", _base() + 0.01)
    png = tmp_path / "m.png"
    argv = ["fields", "--ours", str(fa), "--ops", str(fb), "--map", str(png)]
    try:
        import matplotlib  # noqa: F401
        have = True
    except ImportError:
        have = False
    assert cmp2d.main(argv) == 0
    assert png.is_file() == have
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    if png.exists():
        png.unlink()
    assert cmp2d.main(argv) == 0
    assert "map skipped" in capsys.readouterr().out and not png.exists()


def _met(path, nrec, data, tval=0.0):
    with nc.Dataset(path, "w") as d:
        d.createDimension("record", nrec)
        d.createDimension("grid_yt", 2)
        d.createDimension("grid_xt", 3)
        t = d.createVariable("time", "f8", ())
        t.units = "hours since 2026-10-12 06:00:00"
        t[...] = tval
        for name, arr in data.items():
            d.createVariable(name, "f4", ("record", "grid_yt", "grid_xt"), fill_value=9.99e20)[:] = arr


def _met_day(root, cyc, nrec, shift=0.0, tval=0.0, skip=()):
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(1)
    for prod, names in cmp2d.MET_VARS.items():
        if prod in skip:
            continue
        data = {n: rng.rand(nrec, 2, 3).astype("f4") + shift for n in names}
        _met(root / f"stofs_2d_glo.t{cyc}z.{prod}.nc", nrec, data, tval)


def test_met_bitwise_and_counts(tmp_path, capsys):
    _met_day(tmp_path / "o", "12", 4)
    _met_day(tmp_path / "p", "12", 4)
    argv = ["met", "--ours-dir", str(tmp_path / "o"), "--ops-dir", str(tmp_path / "p"), "--cyc", "12", "--records", "4"]
    assert cmp2d.main(argv) == 0
    out = capsys.readouterr().out
    assert out.count("bitwise identical in all 4") == 4 and "time: equal" in out and "WARN" not in out


def test_met_differences_reported_not_failed(tmp_path, capsys):
    _met_day(tmp_path / "o", "12", 4)
    _met_day(tmp_path / "p", "12", 3, shift=0.5, tval=6.0)
    argv = ["met", "--ours-dir", str(tmp_path / "o"), "--ops-dir", str(tmp_path / "p"), "--cyc", "12", "--records", "4"]
    assert cmp2d.main(argv) == 0
    out = capsys.readouterr().out
    assert "4 records this run, 3 ops" in out and "WARN record count is not 4" in out
    assert "time: DIFFERS" in out and "0 of 3 compared records bitwise; max |d|" in out


def test_met_missing_file_exits_1(tmp_path, capsys):
    _met_day(tmp_path / "o", "12", 2)
    _met_day(tmp_path / "p", "12", 2, skip=("icec",))
    argv = ["met", "--ours-dir", str(tmp_path / "o"), "--ops-dir", str(tmp_path / "p"), "--cyc", "12", "--records", "2"]
    assert cmp2d.main(argv) == 1
    assert "FAIL  stofs_2d_glo.t12z.icec.nc" in capsys.readouterr().out
