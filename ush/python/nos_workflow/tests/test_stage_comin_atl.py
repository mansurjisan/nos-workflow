"""ATL profile of ush/stage_comin.py: the 20261001 12z file set. No network use."""
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SPEC = importlib.util.spec_from_file_location("stage_comin", _REPO_ROOT / "ush" / "stage_comin.py")
sc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sc)

ATL = sc.PROFILES["stofs_3d_atl"]


def _atl(source):
    return sc.build_manifest([source], "20261001", 12, ATL["nowcast_hours"], ATL["forecast_hours"],
                             "/c", profile="stofs_3d_atl", rtofs_probe=lambda u: True)


def test_profile_defaults():
    assert (ATL["nowcast_hours"], ATL["forecast_hours"]) == (24, 96)
    assert sc.PROFILES["secofs_ufs"]["builders"] == {}


def test_nwm_is_the_139_file_primary_list():
    keys = [local for _, local in _atl("nwm")]
    assert len(keys) == 139
    assert any(k.endswith("nwm.20260930/medium_range_mem1/nwm.t06z.medium_range.channel_rt_1.f006.conus.nc") for k in keys)
    assert any(k.endswith("nwm.20261001/medium_range_mem1/nwm.t06z.medium_range.channel_rt_1.f120.conus.nc") for k in keys)
    assert sum("20260930" in k for k in keys) == 13


def test_rtofs_is_same_day_ops_route():
    keys = {k.split("/")[-1] for _, k in _atl("rtofs")}
    assert {"rtofs_glo_2ds_n012_diag.nc", "rtofs_glo_2ds_n018_diag.nc", "rtofs_glo_2ds_f000_diag.nc",
            "rtofs_glo_2ds_f120_diag.nc"} <= keys
    assert {"rtofs_glo_3dz_n012_6hrly_hvr_US_east.nc", "rtofs_glo_3dz_n018_6hrly_hvr_US_east.nc",
            "rtofs_glo_3dz_n024_6hrly_hvr_US_east.nc", "rtofs_glo_3dz_f006_6hrly_hvr_US_east.nc",
            "rtofs_glo_3dz_f120_6hrly_hvr_US_east.nc"} <= keys
    assert not any("3dz_f000" in k for k in keys)
    assert all("rtofs.20261001" in k for _, k in _atl("rtofs"))
    hourly = sc.manifest_rtofs_ops("20261001", 12, 24, 96, hourly_2d=True)
    assert sum("2ds_f" in k for k in hourly) == 121


def test_hrrr_nowcast_lookback_and_forecast_cap():
    keys = [k for _, k in _atl("hrrr")]
    assert len(keys) == 13 + 12 + 48
    assert any(k.endswith("hrrr.20260930/conus/hrrr.t11z.wrfsfcf01.grib2") for k in keys)
    assert any(k.endswith("hrrr.20261001/conus/hrrr.t12z.wrfsfcf48.grib2") for k in keys)
    assert not any("wrfsfcf49" in k for k in keys)


def test_gfs_ops_chain_window():
    keys = [k for _, k in _atl("gfs")]
    assert len(keys) == 127
    assert any(k.endswith("gfs.20260930/06/atmos/gfs.t06z.pgrb2.0p25.f006") for k in keys)
    assert any(k.endswith("gfs.20261001/12/atmos/gfs.t12z.pgrb2.0p25.f099") for k in keys)
    assert not any("pgrb2.0p25.f000" in k for k in keys)
    assert not any("pgrb2.0p25.f100" in k for k in keys)


def test_gfs_matches_processor_chain():
    pytest.importorskip("numpy")
    try:
        from nos_utils.forcing.gfs import GFSProcessor
    except Exception:
        pytest.skip("nos_utils not importable")
    c0 = datetime(2026, 10, 1, 12)
    want = set()
    valid = c0 - timedelta(hours=27)
    while valid <= c0 + timedelta(hours=99):
        cyc_dt, fhr = GFSProcessor._ops_chain_cycle(valid, c0)
        want.add(f"gfs.{cyc_dt:%Y%m%d}/{cyc_dt.hour:02d}/atmos/gfs.t{cyc_dt.hour:02d}z.pgrb2.0p25.f{fhr:03d}")
        valid += timedelta(hours=1)
    assert set(sc.manifest_gfs_ops("20261001", 12, 24, 96)) == want


def test_default_profile_golden():
    """Pinned from 38c85df's stage_comin (20260825 12z, the secofs_ufs defaults)."""
    import hashlib
    golden = {"gfs": (78, "91a7a00054faaff5"), "hrrr": (55, "61d631be83c5d2e1"),
              "rtofs": (67, "0cc59738f5391dab"), "nwm": (76, "34f318d00311dde6")}
    for src, (n, h) in golden.items():
        m = sc.build_manifest([src], "20260825", 12, 6, 48, "/c", rtofs_probe=lambda u: True)
        assert len(m) == n, src
        assert hashlib.sha256("\n".join(u for u, _ in m).encode()).hexdigest()[:16] == h, src
        assert m == sc.build_manifest([src], "20260825", 12, 6, 48, "/c", rtofs_probe=lambda u: True,
                                      profile="secofs_ufs")


def test_cli_profile_defaults(capsys):
    rc = sc.main(["--pdy", "20261001", "--cyc", "12", "--comroot", "/c", "--profile", "stofs_3d_atl",
                  "--sources", "nwm", "--dry-run"])
    assert rc == 0
    assert "139 files in manifest" in capsys.readouterr().err
