"""Unit tests for ``runners.schism_ufs.configure`` -- PR 7b phase 7.

These tests verify the phase-aware configure-file patching.  The
underlying sed-vs-Python byte equivalence is covered by
:mod:`tests.runners.test_patches` (PR 7a); here we focus on the
phase-driven value resolution and the wiring of the helpers from
:mod:`runners.schism_ufs.configure`.

Each test seeds a synthetic ``$DATA/<file>`` with realistic template
text, calls the helper under test with a :class:`SchismRunContext`
populated for nowcast or forecast, and asserts the file contents
reflect the expected anchor values.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pytest

from nos_workflow.runners.schism_ufs.configure import (
    _resolve_phase_anchors,
    _split_yyyymmddhh,
    patch_datm_in,
    patch_model_configure,
    patch_param_nml,
    patch_ufs_configure,
    patch_ww3_shel,
)
from nos_workflow.runners.schism_ufs.context import SchismRunContext

# netCDF4 may be absent in stripped CI; the datm_in dim tests skip then.
try:
    from netCDF4 import Dataset
    import numpy as np
    _NETCDF4_AVAILABLE = True
except ImportError:
    _NETCDF4_AVAILABLE = False


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    tmp_path: Path,
    *,
    phase: str = "nowcast",
    time_hotstart: Optional[str] = "2026051200",
    time_nowcastend: Optional[str] = "2026051206",
    len_nowcast: Optional[str] = "6",
    len_forecast: Optional[str] = "48",
    pdy: Optional[str] = "20260512",
    cyc: Optional[str] = "00",
    wav_rst_out_nowcast: Optional[str] = None,
    med_rst_out_nowcast: Optional[str] = None,
) -> SchismRunContext:
    """Build a SchismRunContext with sensible time anchors."""
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    for p in (comout, data):
        p.mkdir(parents=True, exist_ok=True)
    return SchismRunContext(
        comout=comout,
        data=data,
        phase=phase,
        run="nos.secofs_ufs",
        cycle="t00z",
        time_hotstart=time_hotstart,
        time_nowcastend=time_nowcastend,
        len_nowcast=len_nowcast,
        len_forecast=len_forecast,
        pdy=pdy,
        cyc=cyc,
        wav_rst_out_nowcast=wav_rst_out_nowcast,
        med_rst_out_nowcast=med_rst_out_nowcast,
    )


_PARAM_NML_TEMPLATE = """\
&CORE
  rnday = rnday_value
  start_year = start_year_value
  start_month = start_month_value
  start_day = start_day_value
  start_hour = start_hour_value
  ihot = 0
/
"""


_PARAM_NML_LIVE = """\
&CORE
  rnday = 0.25
  start_year = 2020
  start_month = 1
  start_day = 1
  start_hour = 0
  ihot = 0
/
"""


_MODEL_CONFIGURE_TEMPLATE = """\
nhours_fcst:             6
start_year:              2020
start_month:             1
start_day:               1
start_hour:              0
"""


_UFS_CONFIGURE_TEMPLATE = """\
ATM_attributes::
  stop_n = 6
  start_type = continue
  orb_iyear = 2020
  orb_iyear_align = 2020
::
"""


_WW3_SHEL_TEMPLATE = """\
&domain_nml
  domain%start = '@[WW3_CYCLE_START]'
  domain%stop  = '@[WW3_CYCLE_STOP]'
/
&output_date_nml
  date%field%start    = '@[WW3_CYCLE_START]'
  date%field%stop     = '@[WW3_CYCLE_STOP]'
  date%restart%start  = '@[WW3_CYCLE_START]'
  date%restart%stride = '@[WW3_RESTART_STRIDE_SEC]'
  date%restart%stop   = '@[WW3_CYCLE_STOP]'
/
"""


# ---------------------------------------------------------------------------
# _split_yyyymmddhh / _resolve_phase_anchors
# ---------------------------------------------------------------------------


def test_split_yyyymmddhh_basic():
    """``2026051203`` -> (2026, 05, 12, 03) with zero-padding preserved."""
    y, m, d, h = _split_yyyymmddhh("2026051203")
    assert (y, m, d, h) == ("2026", "05", "12", "03")


def test_split_yyyymmddhh_january():
    """Leading-zero month + day round-trip correctly."""
    y, m, d, h = _split_yyyymmddhh("2026010100")
    assert (y, m, d, h) == ("2026", "01", "01", "00")


def test_resolve_phase_anchors_nowcast(tmp_path):
    """nowcast => (LEN_NOWCAST, time_hotstart)."""
    ctx = _make_ctx(tmp_path)
    nhours, sim_start = _resolve_phase_anchors(ctx, "nowcast")
    assert nhours == 6
    assert sim_start == "2026051200"


def test_resolve_phase_anchors_forecast(tmp_path):
    """forecast => (LEN_FORECAST, time_nowcastend)."""
    ctx = _make_ctx(tmp_path)
    nhours, sim_start = _resolve_phase_anchors(ctx, "forecast")
    assert nhours == 48
    assert sim_start == "2026051206"


def test_resolve_phase_anchors_forecast_falls_back_to_pdy_cyc(tmp_path):
    """forecast without time_nowcastend uses ${PDY}${cyc}."""
    ctx = _make_ctx(tmp_path, time_nowcastend=None)
    nhours, sim_start = _resolve_phase_anchors(ctx, "forecast")
    assert sim_start == "2026051200"  # pdy + cyc


def test_resolve_phase_anchors_nowcast_missing_time_hotstart_raises(tmp_path):
    """nowcast without time_hotstart raises (no NDATE fallback)."""
    ctx = _make_ctx(tmp_path, time_hotstart=None)
    with pytest.raises(RuntimeError, match="time_hotstart"):
        _resolve_phase_anchors(ctx, "nowcast")


def test_resolve_phase_anchors_invalid_phase_raises(tmp_path):
    """Unknown phase => ValueError."""
    ctx = _make_ctx(tmp_path)
    with pytest.raises(ValueError, match="unknown phase"):
        _resolve_phase_anchors(ctx, "post")


def test_resolve_phase_anchors_bad_len_raises(tmp_path):
    """Non-integer LEN_NOWCAST => RuntimeError."""
    ctx = _make_ctx(tmp_path, len_nowcast="abc")
    with pytest.raises(RuntimeError, match="must be an integer"):
        _resolve_phase_anchors(ctx, "nowcast")


def test_resolve_phase_anchors_bad_sim_start_raises(tmp_path):
    """Malformed time_hotstart => RuntimeError."""
    ctx = _make_ctx(tmp_path, time_hotstart="2026")
    with pytest.raises(RuntimeError, match="10-char YYYYMMDDHH"):
        _resolve_phase_anchors(ctx, "nowcast")


def test_resolve_phase_anchors_uses_default_len_nowcast(tmp_path):
    """No LEN_NOWCAST set => uses default 6."""
    ctx = _make_ctx(tmp_path, len_nowcast=None)
    nhours, _ = _resolve_phase_anchors(ctx, "nowcast")
    assert nhours == 6


def test_resolve_phase_anchors_uses_default_len_forecast(tmp_path):
    """No LEN_FORECAST set => uses default 48."""
    ctx = _make_ctx(tmp_path, len_forecast=None)
    nhours, _ = _resolve_phase_anchors(ctx, "forecast")
    assert nhours == 48


# ---------------------------------------------------------------------------
# patch_param_nml
# ---------------------------------------------------------------------------


def test_patch_param_nml_nowcast_replaces_placeholders(tmp_path):
    """Template placeholders all get replaced; ihot is forced to 1."""
    ctx = _make_ctx(tmp_path)
    target = ctx.data / "param.nml"
    target.write_text(_PARAM_NML_TEMPLATE)

    patch_param_nml(ctx, "nowcast")

    text = target.read_text()
    assert "rnday_value" not in text
    assert "start_year_value" not in text
    assert "start_month_value" not in text
    assert "start_day_value" not in text
    assert "start_hour_value" not in text
    # nhours=6 / 24.0 = 0.25
    assert "rnday = 0.25" in text
    # time_hotstart = 2026051200 -> year=2026, month=5, day=12, hour=00
    # The shell strips leading zeros from MM/DD/HH for param.nml's strict
    # patch (line 549: ``${sim_hh#0}``), so start_hour = 0 not 00.
    assert "start_year = 2026" in text
    assert "start_month = 5" in text  # zero-stripped
    assert "start_day = 12" in text
    assert "start_hour = 0" in text  # zero-stripped by strict-pattern patch
    assert "ihot = 1" in text


def test_patch_param_nml_forecast_uses_len_forecast(tmp_path):
    """forecast phase => rnday = LEN_FORECAST / 24.0."""
    ctx = _make_ctx(tmp_path)
    target = ctx.data / "param.nml"
    target.write_text(_PARAM_NML_TEMPLATE)

    patch_param_nml(ctx, "forecast")

    text = target.read_text()
    # 48 / 24.0 = 2.0
    assert "rnday = 2.0" in text


def test_patch_param_nml_sets_ihot_one_for_both_phases(tmp_path):
    """ihot is always 1 (NUOPC clock sync requirement)."""
    for phase in ("nowcast", "forecast"):
        ctx = _make_ctx(tmp_path)
        # Fresh file per phase iteration
        target = ctx.data / "param.nml"
        target.write_text(_PARAM_NML_LIVE)  # live values, ihot=0
        patch_param_nml(ctx, phase)
        assert "ihot = 1" in target.read_text(), f"phase={phase}"


def test_patch_param_nml_patches_live_namelist(tmp_path):
    """A live (non-template) param.nml with numeric values gets patched too."""
    ctx = _make_ctx(tmp_path)
    target = ctx.data / "param.nml"
    target.write_text(_PARAM_NML_LIVE)

    patch_param_nml(ctx, "nowcast")

    text = target.read_text()
    assert "rnday = 0.25" in text
    assert "start_year = 2026" in text
    assert "start_month = 5" in text
    assert "ihot = 1" in text


def test_patch_param_nml_missing_file_returns_zero(tmp_path):
    """No param.nml => return 0, no exception."""
    ctx = _make_ctx(tmp_path)
    # Do NOT write param.nml.
    n = patch_param_nml(ctx, "nowcast")
    assert n == 0


def test_patch_param_nml_empty_file_returns_zero(tmp_path):
    """Empty param.nml => return 0, no patches applied."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "param.nml").write_text("")
    n = patch_param_nml(ctx, "nowcast")
    assert n == 0


# ---------------------------------------------------------------------------
# patch_datm_in
# ---------------------------------------------------------------------------


_DATM_IN_TEMPLATE = """\
&datm_nml
  nx_global = 720
  ny_global = 361
  some_other_key = 'foo'
/
"""


@pytest.mark.skipif(
    not _NETCDF4_AVAILABLE, reason="netCDF4 not installed",
)
def test_patch_datm_in_sets_nx_ny_global_from_forcing_dims(tmp_path):
    """datm_in is patched with the actual forcing-file dims."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "datm_in").write_text(_DATM_IN_TEMPLATE)

    # Build a synthetic forcing file with longitude=1721, latitude=1721
    input_dir = ctx.data / "INPUT"
    input_dir.mkdir(parents=True, exist_ok=True)
    forcing = input_dir / "datm_forcing.nc"
    ds = Dataset(str(forcing), "w")
    ds.createDimension("longitude", 1721)
    ds.createDimension("latitude", 1721)
    ds.createVariable("longitude", "f8", ("longitude",))
    ds.createVariable("latitude", "f8", ("latitude",))
    ds.close()

    n = patch_datm_in(ctx, "nowcast")

    text = (ctx.data / "datm_in").read_text()
    assert "nx_global = 1721" in text
    assert "ny_global = 1721" in text
    assert "720" not in text  # the old value is gone
    assert "361" not in text
    assert n >= 2


@pytest.mark.skipif(
    not _NETCDF4_AVAILABLE, reason="netCDF4 not installed",
)
def test_patch_datm_in_uses_xy_fallback_dims(tmp_path):
    """If forcing has ``x``/``y`` dims (no longitude/latitude), those work."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "datm_in").write_text(_DATM_IN_TEMPLATE)

    input_dir = ctx.data / "INPUT"
    input_dir.mkdir(parents=True, exist_ok=True)
    forcing = input_dir / "datm_forcing.nc"
    ds = Dataset(str(forcing), "w")
    ds.createDimension("x", 500)
    ds.createDimension("y", 250)
    ds.close()

    n = patch_datm_in(ctx, "nowcast")
    text = (ctx.data / "datm_in").read_text()
    assert "nx_global = 500" in text
    assert "ny_global = 250" in text
    assert n >= 2


def test_patch_datm_in_missing_file_returns_zero(tmp_path):
    """No datm_in => return 0, no exception."""
    ctx = _make_ctx(tmp_path)
    n = patch_datm_in(ctx, "nowcast")
    assert n == 0


def test_patch_datm_in_missing_forcing_file_returns_zero(tmp_path):
    """No forcing.nc => return 0; warning logged."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "datm_in").write_text(_DATM_IN_TEMPLATE)
    # No INPUT/datm_forcing.nc.
    n = patch_datm_in(ctx, "nowcast")
    assert n == 0


@pytest.mark.skipif(
    not _NETCDF4_AVAILABLE, reason="netCDF4 not installed",
)
def test_patch_datm_in_honors_datm_input_dir_override(tmp_path, monkeypatch):
    """``$DATM_INPUT_DIR`` override changes the forcing search path."""
    monkeypatch.setenv("DATM_INPUT_DIR", "DATM_FORCING")
    ctx = _make_ctx(tmp_path)
    (ctx.data / "datm_in").write_text(_DATM_IN_TEMPLATE)

    forc_dir = ctx.data / "DATM_FORCING"
    forc_dir.mkdir(parents=True, exist_ok=True)
    forcing = forc_dir / "datm_forcing.nc"
    ds = Dataset(str(forcing), "w")
    ds.createDimension("longitude", 100)
    ds.createDimension("latitude", 50)
    ds.close()

    patch_datm_in(ctx, "nowcast")
    text = (ctx.data / "datm_in").read_text()
    assert "nx_global = 100" in text
    assert "ny_global = 50" in text


# ---------------------------------------------------------------------------
# patch_model_configure
# ---------------------------------------------------------------------------


def test_patch_model_configure_replaces_nhours_fcst(tmp_path):
    """nhours_fcst is set from LEN_NOWCAST / LEN_FORECAST per phase."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "model_configure").write_text(_MODEL_CONFIGURE_TEMPLATE)

    patch_model_configure(ctx, "nowcast")

    text = (ctx.data / "model_configure").read_text()
    # 13-space pad as the shell hard-codes (line 517).
    assert "nhours_fcst:             6" in text
    assert "start_year:             2026" in text
    assert "start_month:             05" in text  # NOT zero-stripped here


def test_patch_model_configure_forecast_phase(tmp_path):
    """forecast => nhours_fcst = LEN_FORECAST."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "model_configure").write_text(_MODEL_CONFIGURE_TEMPLATE)

    patch_model_configure(ctx, "forecast")

    text = (ctx.data / "model_configure").read_text()
    assert "nhours_fcst:             48" in text


def test_patch_model_configure_preserves_zero_padded_month_day(tmp_path):
    """model_configure does NOT strip leading zeros (unlike param.nml).

    The :func:`patches.patch_fv3_configure` helper uses a 13-space pad
    for all keys (the historic shell line 517 has 13 spaces; the helper
    standardized on that even though lines 518-521 in the shell vary
    between 14 and 15 spaces -- PR 7a opted for consistent 13).
    """
    ctx = _make_ctx(tmp_path, time_hotstart="2026010300")  # Jan 3
    (ctx.data / "model_configure").write_text(_MODEL_CONFIGURE_TEMPLATE)

    patch_model_configure(ctx, "nowcast")

    text = (ctx.data / "model_configure").read_text()
    assert "start_month:             01" in text
    assert "start_day:             03" in text  # 13 spaces (helper-standardized)


def test_patch_model_configure_missing_file_returns_zero(tmp_path):
    """No model_configure => return 0."""
    ctx = _make_ctx(tmp_path)
    n = patch_model_configure(ctx, "nowcast")
    assert n == 0


# ---------------------------------------------------------------------------
# patch_ufs_configure
# ---------------------------------------------------------------------------


def test_patch_ufs_configure_replaces_stop_n_and_start_type(tmp_path):
    """stop_n + start_type + orb_iyear all patched per phase."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "ufs.configure").write_text(_UFS_CONFIGURE_TEMPLATE)

    patch_ufs_configure(ctx, "nowcast")

    text = (ctx.data / "ufs.configure").read_text()
    assert "stop_n = 6" in text
    assert "start_type = startup" in text  # hard-coded
    assert "orb_iyear = 2026" in text
    assert "orb_iyear_align = 2026" in text


def test_patch_ufs_configure_forecast_phase(tmp_path):
    """forecast => stop_n = LEN_FORECAST, start_type still 'startup'."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "ufs.configure").write_text(_UFS_CONFIGURE_TEMPLATE)

    patch_ufs_configure(ctx, "forecast")

    text = (ctx.data / "ufs.configure").read_text()
    assert "stop_n = 48" in text
    assert "start_type = startup" in text


def test_patch_ufs_configure_missing_file_returns_zero(tmp_path):
    """No ufs.configure => return 0."""
    ctx = _make_ctx(tmp_path)
    n = patch_ufs_configure(ctx, "nowcast")
    assert n == 0


def test_patch_ufs_configure_orb_iyear_align_matches_orb_iyear(tmp_path):
    """orb_iyear and orb_iyear_align are always equal (both = sim_yyyy)."""
    ctx = _make_ctx(tmp_path, time_hotstart="2030070100")
    (ctx.data / "ufs.configure").write_text(_UFS_CONFIGURE_TEMPLATE)

    patch_ufs_configure(ctx, "nowcast")

    text = (ctx.data / "ufs.configure").read_text()
    assert "orb_iyear = 2030" in text
    assert "orb_iyear_align = 2030" in text


# ---------------------------------------------------------------------------
# patch_ufs_configure -- phase-aware start_type (wave systems only)
# ---------------------------------------------------------------------------


def test_patch_ufs_configure_non_wave_always_startup(tmp_path, monkeypatch):
    """Non-wave systems (WAV_TASKS unset): start_type is 'startup' for
    BOTH phases -- the exact pre-existing behavior, unchanged."""
    monkeypatch.delenv("WAV_TASKS", raising=False)
    for phase in ("nowcast", "forecast"):
        ctx = _make_ctx(tmp_path, phase=phase)
        target = ctx.data / "ufs.configure"
        target.write_text(_UFS_CONFIGURE_TEMPLATE)
        patch_ufs_configure(ctx, phase)
        assert "start_type = startup" in target.read_text(), f"phase={phase}"


def test_patch_ufs_configure_wave_nowcast_is_startup(tmp_path, monkeypatch):
    """Wave system, nowcast leg: still 'startup' (SCHISM/DATM/MED all
    cold-init the NUOPC clock at the start of every nowcast)."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    ctx = _make_ctx(tmp_path, phase="nowcast")
    target = ctx.data / "ufs.configure"
    target.write_text(_UFS_CONFIGURE_TEMPLATE)

    patch_ufs_configure(ctx, "nowcast")

    assert "start_type = startup" in target.read_text()


def test_patch_ufs_configure_wave_forecast_continues_when_restart_staged(
    tmp_path, monkeypatch,
):
    """Wave system, forecast leg, with the wave restart handoff already
    staged in $DATA (stage_wave_restarts ran and found something to
    restore): 'continue' -- WW3 + the CMEPS mediator pick up the CMEPS
    restart written at the end of this cycle's nowcast leg, instead of
    cold-starting the wave spectrum/mediator fields."""
    from nos_workflow.runners.schism_ufs._dateutils import cmeps_restart_stamp

    monkeypatch.setenv("WAV_TASKS", "2606")
    stamp = cmeps_restart_stamp("2026051206")  # ctx's default time_nowcastend
    wav_name = f"ufs.cpld.ww3.r.{stamp}.nc"
    med_name = f"ufs.cpld.cpl.r.{stamp}.nc"
    ctx = _make_ctx(
        tmp_path, phase="forecast",
        wav_rst_out_nowcast=wav_name, med_rst_out_nowcast=med_name,
    )
    target = ctx.data / "ufs.configure"
    target.write_text(_UFS_CONFIGURE_TEMPLATE)

    (ctx.data / "RESTART").mkdir(parents=True, exist_ok=True)
    (ctx.data / "RESTART" / med_name).write_bytes(b"mediator restart")
    (ctx.data / wav_name).write_bytes(b"ww3 restart")
    (ctx.data / f"rpointer.cpl.{stamp}").write_text(f"RESTART/{med_name}\n")

    patch_ufs_configure(ctx, "forecast")

    assert "start_type = continue" in target.read_text()


def test_patch_ufs_configure_wave_forecast_falls_back_to_startup_cold_start(
    tmp_path, monkeypatch, caplog,
):
    """Wave system, forecast leg, with NO wave restart staged in $DATA
    (the system's first-ever wave-coupled cycle, or stage_wave_restarts
    hit its cold-start branch): falls back to 'startup' with a loud
    warning rather than pointing CDEPS/WW3 at restart files that were
    never staged."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    ctx = _make_ctx(tmp_path, phase="forecast")
    target = ctx.data / "ufs.configure"
    target.write_text(_UFS_CONFIGURE_TEMPLATE)

    caplog.set_level(
        logging.WARNING, logger="nos_workflow.runners.schism_ufs.configure",
    )
    patch_ufs_configure(ctx, "forecast")

    assert "start_type = startup" in target.read_text()
    assert any(
        "no wave restart staged" in r.message for r in caplog.records
    )


# ---------------------------------------------------------------------------
# patch_ufs_configure -- phase-aware restart_n (wave systems only)
# ---------------------------------------------------------------------------


def test_patch_ufs_configure_wave_restart_n_matches_leg_length(tmp_path, monkeypatch):
    """restart_n = this leg's own nhours, for BOTH phases -- restart_option
    (nhours, hardcoded in the fix file) then writes exactly one mediator/
    WW3 restart at the end of the leg, instead of every fixed N hours
    regardless of leg length (8 restarts across a 48h forecast at the old
    hardcoded restart_n=6)."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    template = _UFS_CONFIGURE_TEMPLATE.replace(
        "::\n", "  restart_n = 6\n::\n", 1,
    )

    ctx = _make_ctx(tmp_path, phase="nowcast")
    target = ctx.data / "ufs.configure"
    target.write_text(template)
    patch_ufs_configure(ctx, "nowcast")
    assert "restart_n = 6" in target.read_text()

    ctx = _make_ctx(tmp_path, phase="forecast")
    target.write_text(template)
    patch_ufs_configure(ctx, "forecast")
    assert "restart_n = 48" in target.read_text()


def test_patch_ufs_configure_non_wave_restart_n_untouched(tmp_path, monkeypatch):
    """Non-wave systems: restart_n is NOT in the patch dict at all -- the
    fix file's own value (typically 9999, effectively "never mid-leg")
    passes through unpatched. Primary safety property: this class of
    system must stay byte-identical."""
    monkeypatch.delenv("WAV_TASKS", raising=False)
    template = _UFS_CONFIGURE_TEMPLATE.replace(
        "::\n", "  restart_n = 9999\n::\n", 1,
    )
    ctx = _make_ctx(tmp_path, phase="forecast")
    target = ctx.data / "ufs.configure"
    target.write_text(template)

    patch_ufs_configure(ctx, "forecast")

    assert "restart_n = 9999" in target.read_text()


# ---------------------------------------------------------------------------
# patch_ww3_shel (wave systems only)
# ---------------------------------------------------------------------------


def test_patch_ww3_shel_nowcast_start_stop_and_restart_stride(tmp_path):
    """nowcast: start=time_hotstart, stop=time_hotstart+LEN_NOWCAST,
    restart stride = LEN_NOWCAST*3600 (one restart, at leg end)."""
    ctx = _make_ctx(tmp_path, time_hotstart="2026051200",
                     len_nowcast="6")
    target = ctx.data / "ww3_shel.nml"
    target.write_text(_WW3_SHEL_TEMPLATE)

    n = patch_ww3_shel(ctx, "nowcast")

    text = target.read_text()
    assert "@[WW3_CYCLE_START]" not in text
    assert "@[WW3_CYCLE_STOP]" not in text
    assert "@[WW3_RESTART_STRIDE_SEC]" not in text
    assert "domain%start = '20260512 000000'" in text
    assert "domain%stop  = '20260512 060000'" in text
    assert "date%restart%stride = '21600'" in text
    assert n > 0


def test_patch_ww3_shel_forecast_uses_sentinel_restart_stride(tmp_path):
    """forecast: stop=time_nowcastend+LEN_FORECAST, restart stride is the
    far-beyond-FHMAX sentinel (no further hot-start consumer this cycle)."""
    ctx = _make_ctx(tmp_path, time_nowcastend="2026051206",
                     len_forecast="48")
    target = ctx.data / "ww3_shel.nml"
    target.write_text(_WW3_SHEL_TEMPLATE)

    patch_ww3_shel(ctx, "forecast")

    text = target.read_text()
    assert "domain%start = '20260512 060000'" in text
    assert "domain%stop  = '20260514 060000'" in text
    assert "date%restart%stride = '999999'" in text


def test_patch_ww3_shel_missing_file_returns_zero(tmp_path):
    """No ww3_shel.nml (non-wave system, or not yet staged) -> rc 0."""
    ctx = _make_ctx(tmp_path)
    n = patch_ww3_shel(ctx, "nowcast")
    assert n == 0


def test_patch_ww3_shel_empty_file_returns_zero(tmp_path):
    """Empty ww3_shel.nml -> rc 0, no patches applied."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "ww3_shel.nml").write_text("")
    n = patch_ww3_shel(ctx, "nowcast")
    assert n == 0
