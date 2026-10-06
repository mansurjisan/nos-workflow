"""STOFS-2D-GLO ops mode: cold start and the tide/surf ncst, fcst1, fcst2 chain. MJ (10/05/26)"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "ush" / "python"))
from nos_workflow.machine import MachineProfile  # noqa: E402
from nos_workflow.runners.adcirc import hotstart, ops, post  # noqa: E402
from nos_workflow.runners.adcirc.settings import AdcircConfigError, AdcircSettings, CycleContext  # noqa: E402
from nos_workflow.tests.runners.test_adcirc_prep import YAML, _restart  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "adcirc" / "ops"
NC, RUN, CYCLE = 4, "stofs_2d_glo", datetime(2026, 10, 5, 12)
TIDE_FAC = ("#!/bin/bash\nout=\"${@: -3:1}/${@: -1}\"\nprintf '%3d%3d%3d%5d\\n' $((10#${10})) $((10#$8)) $((10#$6)) $4 > \"$out\"\n"
            "for c in K1 O1 P1 Q1 M2 S2 N2 K2 MF MM; do echo \" $c    1.00000      12.34\" >> \"$out\"; done\n")


def _ctx(tmp_path, tide_fac=True, **extra):
    fix, binp = tmp_path / "fix", tmp_path / "bin"
    if not fix.exists():
        fix.mkdir()
        for n in ("grid", "attr", "body", "rotm", "elev_stat", "met"):
            (fix / f"{RUN}_{n}").write_text(n)
        for n in ("tide.15", "surf.15"):
            shutil.copy(str(DATA / f"{RUN}_{n}"), str(fix / f"{RUN}_{n}"))
        binp.mkdir()
        for n in ("adcprep", "padcirc") + (("stofs_2d_glo_tide_fac",) if tide_fac else ()):
            (binp / n).write_text(TIDE_FAC if "fac" in n else "#!/bin/sh\n")
            (binp / n).chmod(0o755)
    env = {"PDY": "20261005", "cyc": "12", "RUN": RUN, "ADCIRC_MODE": "ops", "NCPU": str(NC),
           "COMOUT": str(tmp_path / "com" / f"{RUN}.20261005"), "COMOUTroot": str(tmp_path / "com"),
           "COMGES": str(tmp_path / "com" / RUN), "FIXofs": str(fix), "ADCIRC_EXEC_DIR": str(binp),
           "EXECnos": str(binp), "DATA": str(tmp_path / "work")}
    env.update(extra)
    return CycleContext.from_env(AdcircSettings.from_yaml(YAML, env), env)


class FakeAdcprep:
    def __call__(self, cmd, cwd):
        if cmd[1] == "--prepall":
            for i in range(NC):
                pe = cwd / f"PE{i:04d}"
                pe.mkdir(exist_ok=True)
                for n in ("fort.14", "fort.18", "fort.13", "fort.24", "elev_stat.151", "vel_stat.151"):
                    (pe / n).write_text(n)
        return 0


class FakeAdcirc:
    """Writes what padcirc would: the hotstart named by write-count parity, appended 61/63 output. MJ (10/05/26)"""

    def __init__(self, crash=""):
        self.argv, self.crash = [], crash

    def __call__(self, argv, cwd):
        self.argv.append(list(argv))
        f = {}
        for ln in (cwd / "fort.15").read_text().splitlines():
            if "!" in ln:
                head, tag = ln.split("!", 1)
                f.setdefault(tag.split()[0].rstrip(":,"), head.split())
        ihot, nws, end = int(f["IHOT"][0]), int(f["NWS"][0]), round(float(f["RNDY"][0]) * 86400)
        if ihot:
            assert (cwd / f"fort.{ihot - 300}.nc").is_file()
        _restart(cwd / f"fort.{68 if end // int(int(f['NHSTAR,NHSINC'][1]) * 6) % 2 == 0 else 67}.nc", float(end))
        for n in ["fort.61.nc", "fort.63.nc"] + (["fort.62.nc", "fort.64.nc", "maxele.63.nc", "maxvel.63.nc",
                                                  "maxwvel.63.nc"] if nws else []):
            (cwd / n).write_text(((cwd / n).read_text() if (cwd / n).exists() else "") + cwd.name + ";")
        (cwd / "adcirc.err").write_text(self.crash)
        return 0


def _go(tmp_path, stream, seg, fa=None, **extra):
    ctx = _ctx(tmp_path, ADCIRC_STREAM=stream, ADCIRC_SEGMENT=seg, **extra)
    fa = fa or FakeAdcirc()
    (ops.run_nowcast if seg == "ncst" else ops.run_forecast)(ctx, fa, MachineProfile.load("wcoss2", validate=False),
                                                              FakeAdcprep())
    return ctx, fa


def _cold(tmp_path):
    ctx = _ctx(tmp_path, COLDSTART="YES")
    ops.cold_adcprep(ctx, FakeAdcprep())
    cs = _ctx(tmp_path, ADCIRC_SEGMENT="spinup")
    ops.run_nowcast(cs, FakeAdcirc(), MachineProfile.load("wcoss2", validate=False), FakeAdcprep())
    for seg in ("ncst", "fcst1", "fcst2"):
        for n in ("221", "222", "225"):
            p = ops.rerun_dir(ctx) / f"{RUN}_{seg}.{n}.nc"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(seg)
    return ctx


def test_single_is_the_default_and_bad_mode_fails():
    assert AdcircSettings.from_yaml(YAML, {}).mode == "single"
    with pytest.raises(AdcircConfigError, match="single or ops"):
        AdcircSettings.from_yaml(YAML, {"ADCIRC_MODE": "both"})


def test_cold_start_seeds_both_chains(tmp_path):
    ctx = _cold(tmp_path)
    nod = ctx.comges / f"{RUN}_nod_equi"
    assert ops.read_nod_equi(nod)[0] == CYCLE - timedelta(hours=168)
    hot = ctx.cycle_dir(CYCLE - timedelta(hours=6), "hotstart")
    assert hot.read_bytes() == ctx.cycle_dir(CYCLE - timedelta(hours=6), "restart").read_bytes()
    assert hotstart.file_time(hot) == 583200
    assert (tmp_path / "work" / "tide_spinup" / "fort.15").is_file()  # run dirs live in DATA, not COMOUT MJ (10/05/26)
    ops.cold_adcprep(ctx, FakeAdcprep())
    assert (ctx.comges / f"{RUN}_nod_equi.old").is_file()


def test_missing_tide_fac_is_fatal_and_no_python_fallback(tmp_path):
    ctx = _ctx(tmp_path, tide_fac=False, COLDSTART="YES")
    with pytest.raises(AdcircConfigError, match="FATAL.*stofs_2d_glo_tide_fac.*stofs.v3.1.5"):
        ops.cold_adcprep(ctx, FakeAdcprep())
    assert not (ctx.comges / f"{RUN}_nod_equi").exists()


def test_missing_tide_fac_leaves_a_live_chain_untouched(tmp_path):
    _cold(tmp_path)
    (tmp_path / "bin" / "stofs_2d_glo_tide_fac").unlink()
    with pytest.raises(AdcircConfigError, match="tide_fac"):
        ops.cold_adcprep(_ctx(tmp_path, COLDSTART="YES"), FakeAdcprep())
    assert (tmp_path / "com" / RUN / f"{RUN}_nod_equi").is_file()
    assert not list((tmp_path / "com" / RUN).glob("*.old"))


def test_single_mode_cache_is_fatal(tmp_path):
    _cold(tmp_path)

    class Single:
        def __call__(self, cmd, cwd):
            return FakeAdcprep()(cmd, cwd) or [(cwd / f"PE{i:04d}" / "fort.24").unlink() for i in range(NC)] and 0
    with pytest.raises(AdcircConfigError, match="single-mode.*COLDSTART=YES"):
        ops.cold_spinup(_ctx(tmp_path, ADCIRC_SEGMENT="spinup"), FakeAdcirc(),
                        MachineProfile.load("wcoss2", validate=False), Single())


def test_bad_chain_file_time_is_named(tmp_path, monkeypatch):
    _cold(tmp_path)
    monkeypatch.setattr(hotstart, "file_time", lambda f: None)
    with pytest.raises(AdcircConfigError, match="no usable time in chain file.*hotstart"):
        _go(tmp_path, "tide", "ncst")


def test_no_nod_equi_asks_for_a_cold_start(tmp_path):
    with pytest.raises(AdcircConfigError, match="restart with COLDSTART=YES"):
        ops.run_prep(_ctx(tmp_path))


def test_tide_chain(tmp_path):
    _cold(tmp_path)
    ctx, fa = _go(tmp_path, "tide", "ncst")
    rr = ops.rerun_dir(ctx)
    assert fa.argv[0][1:3] == ["-n", "4"] and "-W" not in fa.argv[0]
    assert hotstart.file_time(ctx.cycle_dir(CYCLE, "hotstart")) == 604800
    assert (rr / f"{RUN}_hottime.out").read_text().split()[1:] == ["604800", "6.75000", "14.50000"]
    _go(tmp_path, "tide", "fcst1")
    assert (rr / f"{RUN}_tide.68.nc").is_file()
    assert (rr / f"{RUN}_tide.61.nc").read_text().count(";") == 2  # fcst1 appended to the ncst output MJ (10/05/26)
    _go(tmp_path, "tide", "fcst2")
    assert ctx.cycle_dir(CYCLE, "points.htp.nc").read_text().count(";") == 3
    assert ctx.cycle_dir(CYCLE, "fields.htp.nc").is_file()
    assert not list((tmp_path / "work" / "tide_fcst2").glob("PE[0-9]*"))


def test_fcst_rerun_after_success_is_refused(tmp_path):
    _cold(tmp_path)
    _go(tmp_path, "tide", "ncst")
    _go(tmp_path, "tide", "fcst1")
    with pytest.raises(AdcircConfigError, match="advanced.*redo the cycle from ncst"):
        _go(tmp_path, "tide", "fcst1")
    _go(tmp_path, "tide", "fcst2")
    with pytest.raises(AdcircConfigError, match="advanced"):
        _go(tmp_path, "tide", "fcst2")


def test_surf_chain_writers_and_forcing(tmp_path):
    _cold(tmp_path)
    ctx, fa = _go(tmp_path, "surf", "ncst")
    assert fa.argv[0][1:3] == ["-n", "36"] and fa.argv[0][-2:] == ["-W", "32"]
    assert hotstart.file_time(ctx.cycle_dir(CYCLE, "restart")) == 604800
    f222 = ops.rerun_dir(ctx) / f"{RUN}_fcst1.222.nc"
    f222.unlink()
    with pytest.raises(AdcircConfigError, match="fcst1.222.nc"):
        _go(tmp_path, "surf", "fcst1")
    f222.write_text("fcst1")
    _, fa = _go(tmp_path, "surf", "fcst1")
    assert fa.argv[0][-2:] == ["-W", "32"]
    assert (tmp_path / "work" / "surf_fcst1" / "fort.221.nc").read_text() == "fcst1"
    _, fa = _go(tmp_path, "surf", "fcst2")
    assert "-W" not in fa.argv[0]
    assert ctx.cycle_dir(CYCLE, "fields.cwl.maxwvel.nc").is_file()


def test_multistart_and_stale_68(tmp_path):
    ctx = _cold(tmp_path)
    _go(tmp_path, "tide", "ncst")
    _go(tmp_path, "tide", "fcst1")
    h68 = ops.rerun_dir(ctx) / f"{RUN}_tide.68.nc"
    assert h68.is_file()
    _go(tmp_path, "tide", "ncst")   # a re-run deletes the fcst1-end hotstart before running MJ (10/05/26)
    assert not h68.exists()
    nxt, _ = _go(tmp_path, "tide", "ncst", cyc="18")   # 18z steps back 6 h to the 12z chain file MJ (10/05/26)
    assert nxt.cycle_dir(nxt.cycle_time, "hotstart").is_file()
    _go(tmp_path, "tide", "ncst", cyc="00", PDY="20261006", COMOUT=str(tmp_path / "com" / f"{RUN}.20261006"))
    with pytest.raises(AdcircConfigError, match="restart with COLDSTART=YES"):
        _go(tmp_path, "tide", "ncst", cyc="12", PDY="20261012", COMOUT=str(tmp_path / "com" / f"{RUN}.20261012"))


@pytest.mark.parametrize("line", ["ADCIRC stopping", "ADCIRC Terminating."])
def test_crash_text_fails_with_rc_zero(tmp_path, line):
    _cold(tmp_path)
    with pytest.raises(RuntimeError, match="crashed"):
        _go(tmp_path, "tide", "ncst", FakeAdcirc(crash=line + "\n"))


def test_fcst_needs_its_nowcast_and_ranks_must_fit(tmp_path, monkeypatch):
    _cold(tmp_path)
    with pytest.raises(AdcircConfigError, match="run the tide nowcast first"):
        _go(tmp_path, "tide", "fcst1")
    monkeypatch.setenv("ADCIRC_ALLOC_RANKS", "35")
    with pytest.raises(AdcircConfigError, match="36 ranks.*35 allocated"):
        _go(tmp_path, "surf", "ncst")


def _seg(tmp_path, segment, **extra):
    return _ctx(tmp_path, ADCIRC_SEGMENT=segment, **extra)


def _touch(ctx, *names):
    for n in names:
        p = ctx.cycle_dir(CYCLE, n)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(n)


def _rerun_forcing(ctx, segs=("ncst", "fcst1", "fcst2")):
    for s in segs:
        for n in (221, 222, 225):
            f = ops.rerun_dir(ctx) / f"{RUN}_{s}.{n}.nc"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f.name)


class Recorder:
    def __init__(self, rc=0):
        self.cmds, self.rc = [], rc

    def __call__(self, cmd, cwd):
        self.cmds.append(list(cmd))
        return self.rc


def test_post_ncdiff_commands_match_ops(tmp_path):
    ctx = _seg(tmp_path, "ncdiff")
    _touch(ctx, "points.cwl.nc", "points.htp.nc", "fields.cwl.nc", "fields.htp.nc")
    rec = Recorder()
    with pytest.raises(FileNotFoundError):
        post.run_post(ctx, rec)  # the fake NCO wrote no swl file to publish. MJ (10/06/26)
    assert rec.cmds == [["ncdiff", "cwl.fort.61.nc", "htp.fort.61.nc", "swl.fort.61.nc"],
                        ["ncdiff", "-v", "zeta", "cwl.fort.63.nc", "htp.fort.63.nc", "swl.fort.63.nc"],
                        ["ncks", "-A", "-v", "x,y", "cwl.fort.61.nc", "swl.fort.61.nc"],
                        ["ncks", "-A", "-v", "x,y", "cwl.fort.63.nc", "swl.fort.63.nc"]]
    assert (tmp_path / "work" / "cwl.fort.63.nc").resolve() == ctx.cycle_dir(CYCLE, "fields.cwl.nc").resolve()


def test_post_ncdiff_missing_inputs_fail_like_ops(tmp_path):
    ctx = _seg(tmp_path, "ncdiff")
    with pytest.raises(RuntimeError, match="did not existed"):
        post.run_post(ctx, Recorder())
    _touch(ctx, "points.cwl.nc", "points.htp.nc", "fields.htp.nc")
    rec = Recorder(rc=1)
    with pytest.raises(RuntimeError, match="ncdiff cwl.fort.61.nc"):
        post.run_post(ctx, rec)
    assert len(rec.cmds) == 1


def test_post_ncrcat_commands_and_inputs(tmp_path):
    ctx = _seg(tmp_path, "ncrcat")
    with pytest.raises(RuntimeError, match="GFS surface forcing does not exist"):
        post.run_post(ctx, Recorder())
    _rerun_forcing(ctx)
    rec = Recorder()
    with pytest.raises(FileNotFoundError):
        post.run_post(ctx, rec)
    assert rec.cmds[0] == ["ncrcat", "ncst.221.nc", "fcst1.221.nc", "fcst2.221.nc", "fort.221.nc"]
    assert rec.cmds[2][-1] == "fort.225.nc"


def test_post_segment_is_required(tmp_path):
    with pytest.raises(AdcircConfigError, match="ncdiff"):
        post.run_post(_seg(tmp_path, "ncst"), Recorder())


def test_post_missing_nco_is_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(AdcircConfigError, match="module load nco"):
        post.default_runner(["ncdiff"], tmp_path)


@pytest.mark.skipif(not (shutil.which("ncdiff") and shutil.which("ncrcat") and shutil.which("ncks")), reason="NCO absent")
def test_post_with_real_nco(tmp_path):
    nc = pytest.importorskip("netCDF4")

    def mk(path, zeta, t=2):
        with nc.Dataset(str(path), "w") as d:
            d.createDimension("node", 3)
            d.createDimension("time", t)
            for v in "xy":
                d.createVariable(v, "f8", ("node",))[:] = [1.0, 2.0, 3.0]
            d.createVariable("zeta", "f8", ("time", "node"))[:] = zeta
            d.createVariable("time", "f8", ("time",))[:] = list(range(t))

    ctx = _seg(tmp_path, "ncdiff")
    _touch(ctx, "points.cwl.nc", "points.htp.nc", "fields.cwl.nc", "fields.htp.nc")
    mk(ctx.cycle_dir(CYCLE, "points.cwl.nc"), 5.0)
    mk(ctx.cycle_dir(CYCLE, "points.htp.nc"), 2.0)
    mk(ctx.cycle_dir(CYCLE, "fields.cwl.nc"), 5.0)
    mk(ctx.cycle_dir(CYCLE, "fields.htp.nc"), 2.0)
    post.run_post(ctx)
    with nc.Dataset(str(ctx.cycle_dir(CYCLE, "fields.swl.nc"))) as d:
        assert d["zeta"][:].min() == d["zeta"][:].max() == 3.0 and "x" in d.variables and "y" in d.variables
    assert ctx.cycle_dir(CYCLE, "points.swl.nc").is_file()

    ctx = _seg(tmp_path, "ncrcat")
    for s, base in (("ncst", 0), ("fcst1", 2), ("fcst2", 4)):
        for n in (221, 222, 225):
            f = ops.rerun_dir(ctx) / f"{RUN}_{s}.{n}.nc"
            f.parent.mkdir(parents=True, exist_ok=True)
            with nc.Dataset(str(f), "w") as d:
                d.createDimension("time", None)
                d.createVariable("time", "f8", ("time",))[:] = [base, base + 1]
    post.run_post(ctx)
    for name in ("pressfc", "uvgrd10m", "icec"):
        with nc.Dataset(str(ctx.cycle_dir(CYCLE, name + ".nc"))) as d:
            assert list(d["time"][:]) == [0, 1, 2, 3, 4, 5]
