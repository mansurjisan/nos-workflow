"""Offline tests for stage_comin manifest generation. No network use."""
import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TOOL = _REPO_ROOT / "ush" / "stage_comin.py"
_SPEC = importlib.util.spec_from_file_location("stage_comin", _TOOL)
assert _SPEC is not None and _SPEC.loader is not None
sc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sc)


def keys_only(urls_and_paths_or_keys):
    return urls_and_paths_or_keys


# ---------------------------------------------------------------------------
# GFS
# ---------------------------------------------------------------------------

def test_gfs_default_secofs_ufs_covers_full_window():
    keys = sc.manifest_gfs("20260825", 12, nowcast_hours=6, forecast_hours=48)
    assert any("gfs.20260825/12/atmos/gfs.t12z.pgrb2.0p25.f000" in k for k in keys)
    # forecast horizon reaches forecast_hours + 3h buffer from the current cycle
    assert any(k.endswith("f051") for k in keys if "t12z" in k)
    assert not any(k.endswith("f052") for k in keys if "t12z" in k and "20260825/12" in k)


def test_gfs_nowcast_reaches_back_before_t0():
    # nowcast_hours=6 -> model t0 = cyc-6 = 06z; with the 3h buffer + margin
    # cycle the search must include the 00z cycle from the same day.
    keys = sc.manifest_gfs("20260825", 12, nowcast_hours=6, forecast_hours=48)
    assert any("gfs.20260825/00/atmos/gfs.t00z" in k for k in keys)


def test_gfs_cyc00_spills_into_previous_day():
    keys = sc.manifest_gfs("20260825", 0, nowcast_hours=6, forecast_hours=48)
    assert any("gfs.20260824/" in k for k in keys)


def test_gfs_resolution_is_configurable():
    keys = sc.manifest_gfs("20260825", 12, 6, 48, resolution="0p50")
    assert all("pgrb2.0p50" in k for k in keys)


def test_gfs_older_cycles_capped_current_cycle_full_depth():
    # 3 cycles searched for pdy=20260825 cyc=12: 00z, 06z (older), 12z
    # (current). Older cycles only ever win a valid time up to c0 (keep-
    # first dedup in gfs.py prefers any real lead over the current cycle's
    # f000), so they're capped at hours-to-c0 + 3h buffer instead of the
    # full forecast depth: 00z -> 12h+3=15 (16 files), 06z -> 6h+3=9
    # (10 files). 12z (current) keeps the full forecast_hours+3=51 (52
    # files). Total = 16 + 10 + 52 = 78 (down from 174 pre-fix, when every
    # cycle got the full 52-file depth: 3 * 58 = 174).
    keys = sc.manifest_gfs("20260825", 12, nowcast_hours=6, forecast_hours=48)
    assert len(keys) == 78

    def depth(cyc_hour):
        return len([k for k in keys if f".t{cyc_hour:02d}z." in k])

    assert depth(0) == 16
    assert depth(6) == 10
    assert depth(12) == 52
    assert not any(k.endswith("f016") for k in keys if "t00z" in k)
    assert not any(k.endswith("f010") for k in keys if "t06z" in k)


# ---------------------------------------------------------------------------
# HRRR
# ---------------------------------------------------------------------------

def test_hrrr_nowcast_lookback_and_forecast_range():
    keys = sc.manifest_hrrr("20260825", 12, nowcast_hours=6, forecast_hours=48)
    # nowcast: f01 from hour (cyc - nowcast_hours - 1) = 05 through cyc-1 = 11
    assert "hrrr.20260825/conus/hrrr.t05z.wrfsfcf01.grib2" in keys
    assert "hrrr.20260825/conus/hrrr.t11z.wrfsfcf01.grib2" in keys
    assert "hrrr.20260825/conus/hrrr.t04z.wrfsfcf01.grib2" not in keys  # one hour before the lookback start
    # forecast: f01..f48 from the current cycle (f01 here duplicates the
    # nowcast lookback's own f01 at the boundary hour -- harmless overlap)
    assert "hrrr.20260825/conus/hrrr.t12z.wrfsfcf01.grib2" in keys
    assert "hrrr.20260825/conus/hrrr.t12z.wrfsfcf48.grib2" in keys
    assert "hrrr.20260825/conus/hrrr.t12z.wrfsfcf49.grib2" not in keys


def test_hrrr_forecast_capped_at_max_forecast_hours():
    keys = sc.manifest_hrrr("20260825", 12, nowcast_hours=6, forecast_hours=120)
    assert "hrrr.20260825/conus/hrrr.t12z.wrfsfcf48.grib2" in keys
    assert "hrrr.20260825/conus/hrrr.t12z.wrfsfcf49.grib2" not in keys


def test_hrrr_cyc00_nowcast_spills_into_previous_day():
    # nowcast_start_hour = 0 - 6 - 1 = -7 -> previous day hours 17..23
    keys = sc.manifest_hrrr("20260825", 0, nowcast_hours=6, forecast_hours=48)
    assert "hrrr.20260824/conus/hrrr.t17z.wrfsfcf01.grib2" in keys
    assert "hrrr.20260824/conus/hrrr.t23z.wrfsfcf01.grib2" in keys
    assert "hrrr.20260824/conus/hrrr.t16z.wrfsfcf01.grib2" not in keys  # one hour before the lookback start
    # today's own nowcast loop (range(0, cyc)) is empty at cyc=0; the only
    # today's-date entry is the forecast branch's f01 from the cycle itself
    assert "hrrr.20260825/conus/hrrr.t00z.wrfsfcf01.grib2" in keys


# ---------------------------------------------------------------------------
# RTOFS
# ---------------------------------------------------------------------------

def test_rtofs_default_lag_is_previous_day():
    keys = sc.manifest_rtofs("20260825", 12, nowcast_hours=6, forecast_hours=48)
    assert all("rtofs.20260824/" in k for k in keys)
    assert not any("rtofs.20260825/" in k for k in keys)


def test_rtofs_2d_hourly_through_72_then_3hourly():
    lead = sc._rtofs_2d_lead
    assert lead(24) == 24
    assert lead(72) == 72
    assert lead(73) == 75
    assert lead(74) == 75
    assert lead(76) == 75
    assert lead(77) == 78
    assert lead(300) == 192


def test_rtofs_3d_files_are_6hourly_and_region_pinned():
    keys = sc.manifest_rtofs("20260825", 12, nowcast_hours=6, forecast_hours=48, region="US_east")
    threed = [k for k in keys if "3dz" in k]
    assert threed, "expected 3dz files in manifest"
    assert all(k.endswith("US_east.nc") for k in threed)
    for k in threed:
        lead = int(k.split("_f")[1].split("_")[0])
        assert lead % 6 == 0


def test_rtofs_only_forecast_tag_staged_not_nowcast_tag():
    # f-tag wins the valid-time dedup tie in rtofs.py's _sort_and_dedup, so
    # the manifest should never need n-tag files.
    keys = sc.manifest_rtofs("20260825", 12, nowcast_hours=6, forecast_hours=48)
    assert not any("_n0" in k or "_n1" in k for k in keys)


def _fake_probe(hit_dates):
    """Fake probe: succeeds only for keys dated one of hit_dates (a set of
    "%Y%m%d" strings). Never touches the network.
    """
    def probe(url):
        return any(f"rtofs.{d}/" in url for d in hit_dates)
    return probe


def test_resolve_rtofs_date_picks_pdy_minus_1_when_available():
    date, candidates, found = sc.resolve_rtofs_date("20260825", _fake_probe({"20260824"}))
    assert found is True
    assert date.strftime("%Y%m%d") == "20260824"
    assert [c.strftime("%Y%m%d") for c in candidates] == ["20260824", "20260823", "20260825"]


def test_resolve_rtofs_date_falls_back_to_pdy_minus_2():
    date, _, found = sc.resolve_rtofs_date("20260825", _fake_probe({"20260823"}))
    assert found is True
    assert date.strftime("%Y%m%d") == "20260823"


def test_resolve_rtofs_date_falls_back_to_pdy():
    date, _, found = sc.resolve_rtofs_date("20260825", _fake_probe({"20260825"}))
    assert found is True
    assert date.strftime("%Y%m%d") == "20260825"


def test_resolve_rtofs_date_all_fail_defaults_to_pdy_minus_1_and_flags_not_found():
    date, candidates, found = sc.resolve_rtofs_date("20260825", _fake_probe(set()))
    assert found is False
    assert date == candidates[0]
    assert date.strftime("%Y%m%d") == "20260824"


def test_build_manifest_rtofs_uses_probe_result():
    manifest = sc.build_manifest(
        ["rtofs"], "20260825", 12, 6, 48, "/comroot",
        rtofs_probe=_fake_probe({"20260823"}),
    )
    assert manifest
    assert all("/rtofs/rtofs.20260823/" in local for _, local in manifest)


def test_build_manifest_warns_when_all_rtofs_probes_fail(capsys):
    manifest = sc.build_manifest(
        ["rtofs"], "20260825", 12, 6, 48, "/comroot",
        rtofs_probe=_fake_probe(set()),
    )
    assert manifest  # still builds a manifest, against the PDY-1 fallback
    err = capsys.readouterr().err
    assert "warning" in err
    assert "20260824" in err and "20260823" in err and "20260825" in err


def test_no_probe_style_stub_short_circuits_to_pdy_minus_1_without_network():
    always_true = lambda url: True
    date, candidates, found = sc.resolve_rtofs_date("20260825", always_true)
    assert found is True
    assert date == candidates[0]  # first candidate (PDY-1) accepted immediately


def test_rtofs_window_spans_nowcast_and_forecast():
    keys_2d = [k for k in sc.manifest_rtofs("20260825", 12, 6, 48) if "2ds" in k]
    leads = sorted(int(k.split("_f")[1].split("_")[0]) for k in keys_2d)
    # rtofs date = pdy-1 00Z; cyc_dt = pdy 12Z -> offset 36h from rtofs date.
    # window_start = cyc_dt - 6 - 6 = pdy 00Z -> offset 24h.
    # window_end = cyc_dt + 48 + 6 = pdy+2 18Z -> offset 90h -> snapped to 90 (<=72? no, >72 -> snap)
    assert min(leads) == 24
    assert max(leads) == sc._rtofs_2d_lead(90)


# ---------------------------------------------------------------------------
# NWM
# ---------------------------------------------------------------------------

def test_nwm_analysis_covers_nowcast_window_tm00_only():
    keys = sc.manifest_nwm("20260825", 12, nowcast_hours=6, forecast_hours=48)
    analysis = [k for k in keys if "analysis_assim" in k]
    assert len(analysis) == 7  # hours 06..12 inclusive
    assert all("tm00" in k for k in analysis)
    assert "nwm.20260825/analysis_assim/nwm.t06z.analysis_assim.channel_rt.tm00.conus.nc" in analysis
    assert "nwm.20260825/analysis_assim/nwm.t12z.analysis_assim.channel_rt.tm00.conus.nc" in analysis


def test_nwm_analysis_spills_into_previous_day_at_cyc00():
    keys = sc.manifest_nwm("20260825", 0, nowcast_hours=6, forecast_hours=48)
    analysis = [k for k in keys if "analysis_assim" in k]
    assert any("nwm.20260824/" in k for k in analysis)
    assert any("nwm.t18z" in k for k in analysis)  # 00z - 6h = prior day 18z


def test_nwm_forecast_short_range_then_medium_range_handoff():
    keys = sc.manifest_nwm("20260825", 12, nowcast_hours=6, forecast_hours=48,
                            buffer_hours=3, extra_hours=18, short_range_max_lead=18)
    short = sorted(k for k in keys if "short_range" in k)
    medium = sorted(k for k in keys if "medium_range" in k)
    assert len(short) == 18
    assert short[-1].endswith("f018.conus.nc")
    # window_hours = 48 + 3 + 18 = 69
    assert len(medium) == 69 - 18
    assert medium[0].endswith("f019.conus.nc")
    assert medium[-1].endswith("f069.conus.nc")


def test_nwm_river_hourly_extra_hours_extends_tail():
    short_extra = sc.manifest_nwm("20260825", 12, 6, 48, extra_hours=0)
    short_default = sc.manifest_nwm("20260825", 12, 6, 48, extra_hours=18)
    assert len(short_default) > len(short_extra)


# ---------------------------------------------------------------------------
# build_manifest / local layout
# ---------------------------------------------------------------------------

def test_build_manifest_lays_out_comin_shaped_tree():
    manifest = sc.build_manifest(
        ["gfs", "rtofs"], "20260825", 12, 6, 48, "/comroot", rtofs_region="US_east",
    )
    gfs_entries = [(u, l) for u, l in manifest if "noaa-gfs" in u]
    rtofs_entries = [(u, l) for u, l in manifest if "noaa-nws-rtofs" in u]
    assert gfs_entries and rtofs_entries
    for _, local in gfs_entries:
        assert local.startswith("/comroot/gfs/gfs.")
    for _, local in rtofs_entries:
        assert local.startswith("/comroot/rtofs/rtofs.")


def test_build_manifest_url_uses_correct_bucket_per_source():
    manifest = sc.build_manifest(["hrrr", "nwm"], "20260825", 12, 6, 48, "/comroot")
    for url, _ in manifest:
        assert ("noaa-hrrr-bdp-pds" in url) or ("noaa-nwm-pds" in url)


# ---------------------------------------------------------------------------
# Download error handling
# ---------------------------------------------------------------------------

def test_download_one_non_404_head_error_no_crash_records_failed(monkeypatch, tmp_path):
    # A 403/5xx HEAD response used to leave head_err unbound, raising
    # UnboundLocalError at `last_err = head_err`. It must instead fall
    # through to the retry loop and come back as a clean "failed" status.
    def fake_urlopen(req, timeout=None):
        raise sc.urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", None, None)

    monkeypatch.setattr(sc.urllib.request, "urlopen", fake_urlopen)
    status, err = sc.download_one(
        "https://example.com/f", str(tmp_path / "f"), retries=0, backoff=0,
    )
    assert status == "failed"
    assert err is not None


def test_stage_records_failure_when_future_raises_unexpectedly(monkeypatch):
    # One file's unexpected exception (anything download_one itself doesn't
    # catch) must record a per-file failure, not kill the whole stage() run.
    def boom(url, local_path, retries=3, backoff=2.0, timeout=120):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(sc, "download_one", boom)
    results = sc.stage([("https://example.com/a", "/tmp/a")], jobs=1)
    assert len(results["failed"]) == 1
    _, _, err = results["failed"][0]
    assert "unexpected" in err
