"""Unit tests for ``nos_workflow.runners.schism_ufs.setup_paths``.

Pins the behavior of the Python port of ``_schism_setup_paths`` (lines
128-285 of ``ush/nos_run.sh``). All cases use ``tmp_path`` + monkeypatch
so they're hermetic -- no real $COMOUT / $DATA / $FIXofs needed.

Coverage:

  - Minimal env: required NCO vars set; filename + time-anchor fields
    populated; optional fix files absent and produce warnings.
  - Time anchors: BASE_DATE, time_hotstart, time_nowcastend,
    time_forecastend computed via ``_dateutils.ndate``; NSTEP / NTIMES
    derived from LEN_* and DELT_MODEL.
  - Filename conventions: INI_FILE_*, RST_OUT_*, OBC_FORCING_FILE,
    NWM_SOURCE_SINK_*, MET_NETCDF_*, etc. follow the
    ``${prefix}.${cycle}.${pdy1}.<suffix>`` pattern.
  - Fix-file staging: required + optional files copied from $FIXofs to
    $DATA; missing required files log ERROR but don't raise.
  - Prep mode: raises NotImplementedError (PR 6 wires this).
  - Schema invariant: returned context is frozen.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import pytest

from nos_workflow.env import NCOEnv
from nos_workflow.runners.schism_ufs.context import SchismRunContext
from nos_workflow.runners.schism_ufs.setup_paths import (
    compute_paths,
    to_shell_filenames,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
              *, pdy: str = "20260512", cyc: str = "00",
              ofs: str = "secofs_ufs", run: Optional[str] = None) -> NCOEnv:
    """Build an :class:`NCOEnv` with $COMOUT/$DATA/$FIXofs rooted under
    ``tmp_path``.

    ``run`` defaults to ``nos.{ofs}`` (matching every non-wave system,
    where $RUN and $PREFIXNOS coincide); pass it explicitly to build a
    fixture where they differ (e.g. the secofs_ufs_ww3 wave variant).
    """
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    fixofs = tmp_path / "fix"
    comout.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    fixofs.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("OFS", ofs)
    monkeypatch.setenv("RUN", run or f"nos.{ofs}")
    monkeypatch.setenv("PDY", pdy)
    monkeypatch.setenv("cyc", cyc)
    monkeypatch.setenv("COMOUT", str(comout))
    monkeypatch.setenv("DATA", str(data))
    monkeypatch.setenv("FIXofs", str(fixofs))

    return NCOEnv.from_env(ofs=ofs)


def _seed_fix_files(fixofs: Path, monkeypatch: pytest.MonkeyPatch,
                    *, gridfile: str = "hgrid.gr3",
                    sta_out_ctl: str = "station.in",
                    runtime_ctl: str = "param.nml",
                    with_optional: bool = True) -> None:
    """Populate ``$FIXofs`` with the required + optional files
    ``_schism_setup_paths`` expects, and set the matching env vars."""
    monkeypatch.setenv("GRIDFILE", gridfile)
    monkeypatch.setenv("STA_OUT_CTL", sta_out_ctl)
    monkeypatch.setenv("RUNTIME_CTL", runtime_ctl)

    for fname in (gridfile, sta_out_ctl, runtime_ctl):
        (fixofs / fname).write_text(f"# {fname} content\n")

    if with_optional:
        monkeypatch.setenv("GRIDFILE_LL", "hgrid.ll")
        monkeypatch.setenv("VGRID_CTL", "vgrid.in")
        (fixofs / "hgrid.ll").write_text("# hgrid.ll\n")
        (fixofs / "vgrid.in").write_text("# vgrid.in\n")


# ---------------------------------------------------------------------------
# Minimal construction
# ---------------------------------------------------------------------------


def test_compute_paths_minimal(tmp_path, monkeypatch):
    """With the bare-minimum env, compute_paths returns a populated
    :class:`SchismRunContext`."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    ctx = compute_paths(env, phase="nowcast")

    assert isinstance(ctx, SchismRunContext)
    assert ctx.comout == env.comout
    assert ctx.data == env.data
    assert ctx.phase == "nowcast"
    assert ctx.run == env.run
    assert ctx.cycle == env.cycle
    assert ctx.pdy == "20260512"
    assert ctx.cyc == "00"
    assert ctx.fixofs == env.fixofs


def test_compute_paths_uses_default_prefix_when_unset(tmp_path, monkeypatch):
    """If PREFIXNOS is not set, fall back to ``nos.{ofs}``."""
    env = _make_env(tmp_path, monkeypatch, ofs="secofs_ufs")
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.delenv("PREFIXNOS", raising=False)

    ctx = compute_paths(env, phase="nowcast")

    assert ctx.prefixnos == "nos.secofs_ufs"


def test_compute_paths_respects_explicit_prefix(tmp_path, monkeypatch):
    """Operator-supplied PREFIXNOS wins over the default."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("PREFIXNOS", "nos.custom_prefix")

    ctx = compute_paths(env, phase="nowcast")

    assert ctx.prefixnos == "nos.custom_prefix"


# ---------------------------------------------------------------------------
# Time anchors
# ---------------------------------------------------------------------------


def test_compute_paths_populates_time_anchors(tmp_path, monkeypatch):
    """BASE_DATE / time_hotstart / time_nowcastend / time_forecastend
    derived from PDY + cyc + LEN_NOWCAST + LEN_FORECAST."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("LEN_NOWCAST", "6")
    monkeypatch.setenv("LEN_FORECAST", "48")

    ctx = compute_paths(env, phase="nowcast")

    # time_nowcastend = PDY || cyc
    assert ctx.time_nowcastend == "2026051200"
    # time_hotstart = time_nowcastend - 6 hours
    assert ctx.time_hotstart == "2026051118"
    # time_forecastend = time_nowcastend + 48 hours
    assert ctx.time_forecastend == "2026051400"
    # BASE_DATE defaults to time_hotstart in the non-prep path
    assert ctx.base_date == "2026051118"


def test_compute_paths_nstep_derived_from_delt_model(tmp_path, monkeypatch):
    """NSTEP_NOWCAST = LEN_NOWCAST * 3600 / DELT_MODEL."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("LEN_NOWCAST", "6")
    monkeypatch.setenv("LEN_FORECAST", "48")
    monkeypatch.setenv("DELT_MODEL", "120")

    ctx = compute_paths(env, phase="nowcast")

    # 6 hr * 3600 s/hr / 120 s/step = 180 steps
    assert ctx.nstep_nowcast == "180"
    assert ctx.ntimes_nowcast == "180"
    # 48 hr * 3600 / 120 = 1440
    assert ctx.nstep_forecast == "1440"
    assert ctx.ntimes_forecast == "1440"
    assert ctx.delt_model == "120"


def test_compute_paths_dstart_forecast_in_decimal_days(tmp_path, monkeypatch):
    """DSTART_FORECAST = LEN_NOWCAST / 24.0 (decimal days)."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("LEN_NOWCAST", "6")

    ctx = compute_paths(env, phase="nowcast")

    # 6 hr / 24 hr/day = 0.25 day
    assert ctx.dstart_forecast == "0.2500"
    assert ctx.dstart_nowcast == "0.0"


def test_compute_paths_cold_start_defaults_false(tmp_path, monkeypatch):
    """In the non-prep path, COLD_START defaults to 'F'. PR 6 will set
    it to 'T' from _schism_find_hotstart when the COM-hunt fails."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    ctx = compute_paths(env, phase="nowcast")

    assert ctx.cold_start == "F"


# ---------------------------------------------------------------------------
# Filename conventions
# ---------------------------------------------------------------------------


def test_compute_paths_filename_conventions(tmp_path, monkeypatch):
    """All filename fields follow ``${prefix}.${cycle}.${pdy1}.<suffix>``."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("PREFIXNOS", "nos.secofs_ufs")

    ctx = compute_paths(env, phase="nowcast")

    base = "nos.secofs_ufs.t00z.20260512"
    assert ctx.ini_file_nowcast == f"{base}.init.nowcast.nc"
    assert ctx.rst_out_nowcast == f"{base}.rst.nowcast.nc"
    assert ctx.rst_out_forecast == f"{base}.rst.forecast.nc"
    # INI_FILE_FORECAST = RST_OUT_NOWCAST (the hand-off semantics)
    assert ctx.ini_file_forecast == f"{base}.rst.nowcast.nc"
    # Forcing -- OBC selects phase-specific tar (6h vs 48h sim windows)
    assert ctx.obc_forcing_file_nowcast == f"{base}.obc.nowcast.tar"
    assert ctx.obc_forcing_file_forecast == f"{base}.obc.forecast.tar"
    assert ctx.nwm_source_sink_nowcast == f"{base}.nwm.source.sink.now.tar"
    assert ctx.nwm_source_sink_forecast == f"{base}.nwm.source.sink.fore.tar"
    assert ctx.river_forcing_file == f"{base}.river.th.tar"
    assert ctx.met_netcdf_nowcast == f"{base}.met.nowcast.nc.tar"
    assert ctx.met_netcdf_forecast == f"{base}.met.forecast.nc.tar"


def test_compute_paths_comout_products_key_on_run_not_prefixnos(
    tmp_path, monkeypatch,
):
    """Per-cycle $COMOUT product filenames use $RUN; $FIXofs-keyed fields
    stay on $PREFIXNOS.

    Regression pin for the wave-variant bug: prep's archiver names
    $COMOUT products (obc.tar, river.th.tar, nwm tars, bctides.in,
    rst/init files) from $RUN, while a system that leaves system.prefix
    unoverridden (e.g. secofs_ufs_ww3, prefix=secofs_ufs, run=
    secofs_ufs_ww3) has $RUN != $PREFIXNOS. Every pre-existing system has
    $RUN == $PREFIXNOS, so this is the only fixture shape that can catch
    a regression back to PREFIXNOS-keyed $COMOUT names.
    """
    env = _make_env(
        tmp_path, monkeypatch, pdy="20260512", cyc="00",
        ofs="secofs_ufs_ww3", run="secofs_ufs_ww3",
    )
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("PREFIXNOS", "secofs_ufs")

    ctx = compute_paths(env, phase="nowcast")

    run_base = "secofs_ufs_ww3.t00z.20260512"
    assert ctx.ini_file_nowcast == f"{run_base}.init.nowcast.nc"
    assert ctx.ini_file_forecast == f"{run_base}.rst.nowcast.nc"
    assert ctx.rst_out_nowcast == f"{run_base}.rst.nowcast.nc"
    assert ctx.rst_out_forecast == f"{run_base}.rst.forecast.nc"
    assert ctx.bctides_in_nowcast == f"{run_base}.bctides.in"
    assert ctx.obc_forcing_file_nowcast == f"{run_base}.obc.nowcast.tar"
    assert ctx.obc_forcing_file_forecast == f"{run_base}.obc.forecast.tar"
    assert ctx.nwm_source_sink_nowcast == f"{run_base}.nwm.source.sink.now.tar"
    assert ctx.nwm_source_sink_forecast == f"{run_base}.nwm.source.sink.fore.tar"
    assert ctx.river_forcing_file == f"{run_base}.river.th.tar"
    assert ctx.met_netcdf_nowcast == f"{run_base}.met.nowcast.nc.tar"
    assert ctx.met_netcdf_forecast == f"{run_base}.met.forecast.nc.tar"

    # $FIXofs statics (the SCHISM-side fix set this variant deliberately
    # reuses) stay $PREFIXNOS-keyed, not $RUN-keyed.
    assert ctx.prefixnos == "secofs_ufs"
    assert ctx.run == "secofs_ufs_ww3"


def test_compute_paths_to_shell_filenames_helper(tmp_path, monkeypatch):
    """``to_shell_filenames`` returns the same dict shape the shell
    exports as env vars (NCO names, full ``${prefix}.${cycle}.${pdy1}``
    pattern)."""
    fns = to_shell_filenames("nos.secofs_ufs", "t12z", "20260507")

    # Spot-check a representative subset of the file names
    assert fns["OBC_FORCING_FILE"] == "nos.secofs_ufs.t12z.20260507.obc.tar"
    assert (
        fns["OBC_FORCING_FILE_NOWCAST"]
        == "nos.secofs_ufs.t12z.20260507.obc.nowcast.tar"
    )
    assert (
        fns["OBC_FORCING_FILE_FORECAST"]
        == "nos.secofs_ufs.t12z.20260507.obc.forecast.tar"
    )
    assert fns["RST_OUT_NOWCAST"] == "nos.secofs_ufs.t12z.20260507.rst.nowcast.nc"
    assert fns["MODEL_LOG_FORECAST"] == "nos.secofs_ufs.t12z.20260507.forecast.log"
    assert fns["BCTIDES_IN"] == "nos.secofs_ufs.t12z.20260507.bctides.in"
    assert fns["HIS_2D_NOWCAST"] == "nos.secofs_ufs.t12z.20260507.surface.nowcast.nc"


def test_compute_paths_bctides_split_uses_same_filename(tmp_path, monkeypatch):
    """The shell exports a single BCTIDES_IN; the Python port populates
    both _nowcast and _forecast SchismRunContext slots with the same
    value (downstream can override per-phase if needed)."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("PREFIXNOS", "nos.secofs_ufs")

    ctx = compute_paths(env, phase="nowcast")

    assert ctx.bctides_in_nowcast == ctx.bctides_in_forecast
    assert ctx.bctides_in_nowcast.endswith(".bctides.in")


# ---------------------------------------------------------------------------
# Wave restart filenames (wave-coupled systems only; gated on WAV_TASKS)
# ---------------------------------------------------------------------------


def test_compute_paths_wave_restart_filenames_none_without_wav_tasks(
    tmp_path, monkeypatch,
):
    """Non-wave systems (WAV_TASKS unset): all four wave restart fields
    stay None -- they never surface in to_shell_env() either."""
    monkeypatch.delenv("WAV_TASKS", raising=False)
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    ctx = compute_paths(env, phase="nowcast")

    assert ctx.wav_rst_out_nowcast is None
    assert ctx.wav_rst_out_forecast is None
    assert ctx.med_rst_out_nowcast is None
    assert ctx.med_rst_out_forecast is None
    out = ctx.to_shell_env()
    for key in ("WAV_RST_OUT_NOWCAST", "WAV_RST_OUT_FORECAST",
                "MED_RST_OUT_NOWCAST", "MED_RST_OUT_FORECAST"):
        assert key not in out


def test_compute_paths_wave_restart_filenames_cmeps_stamp(tmp_path, monkeypatch):
    """WAV_TASKS>0: wav/med restart names follow the CMEPS case_name
    convention (ufs.cpld.<comp>.r.<YYYY-MM-DD-SSSSS>.nc), keyed on
    time_nowcastend / time_forecastend -- NOT on PREFIXNOS or the
    ${prefix}.${cycle}.${pdy1} pattern every other filename field uses.
    """
    monkeypatch.setenv("WAV_TASKS", "4766")
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("LEN_NOWCAST", "6")
    monkeypatch.setenv("LEN_FORECAST", "48")

    ctx = compute_paths(env, phase="nowcast")

    # time_nowcastend = 2026051200 -> 2026-05-12-00000
    assert ctx.wav_rst_out_nowcast == "ufs.cpld.ww3.r.2026-05-12-00000.nc"
    assert ctx.med_rst_out_nowcast == "ufs.cpld.cpl.r.2026-05-12-00000.nc"
    # time_forecastend = 2026051400 -> 2026-05-14-00000
    assert ctx.wav_rst_out_forecast == "ufs.cpld.ww3.r.2026-05-14-00000.nc"
    assert ctx.med_rst_out_forecast == "ufs.cpld.cpl.r.2026-05-14-00000.nc"


def test_compute_paths_wave_restart_filenames_reach_shell_env(tmp_path, monkeypatch):
    """The four wave restart fields round-trip through to_shell_env()."""
    monkeypatch.setenv("WAV_TASKS", "4766")
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    ctx = compute_paths(env, phase="nowcast")
    out = ctx.to_shell_env()

    assert out["WAV_RST_OUT_NOWCAST"] == ctx.wav_rst_out_nowcast
    assert out["MED_RST_OUT_NOWCAST"] == ctx.med_rst_out_nowcast
    assert out["WAV_RST_OUT_FORECAST"] == ctx.wav_rst_out_forecast
    assert out["MED_RST_OUT_FORECAST"] == ctx.med_rst_out_forecast


# ---------------------------------------------------------------------------
# Fix-file staging
# ---------------------------------------------------------------------------


def test_compute_paths_stages_required_grid_files(tmp_path, monkeypatch):
    """Required fix files (GRIDFILE, STA_OUT_CTL, RUNTIME_CTL) copied
    from $FIXofs into $DATA. ``cp -p``-equivalent ``shutil.copy2`` so
    contents survive intact."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    compute_paths(env, phase="nowcast")

    assert (env.data / "hgrid.gr3").is_file()
    assert (env.data / "station.in").is_file()
    assert (env.data / "param.nml").is_file()
    assert (env.data / "hgrid.gr3").read_text() == "# hgrid.gr3 content\n"


def test_compute_paths_stages_optional_grid_files(tmp_path, monkeypatch):
    """When optional fix-file env vars are set and the file exists, it's
    copied. Missing optional files don't raise."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=True)

    compute_paths(env, phase="nowcast")

    assert (env.data / "hgrid.ll").is_file()
    assert (env.data / "vgrid.in").is_file()


def test_compute_paths_creates_outputs_and_sflux_subdirs(tmp_path, monkeypatch):
    """``mkdir -p $DATA/outputs $DATA/sflux`` (line 152 of nos_run.sh)
    is unconditional."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    compute_paths(env, phase="nowcast")

    assert (env.data / "outputs").is_dir()
    assert (env.data / "sflux").is_dir()


def test_compute_paths_missing_required_grid_file_logs_error(
        tmp_path, monkeypatch, caplog):
    """Required fix file missing from $FIXofs logs an ERROR but does
    NOT raise -- matches the shell's err_chk semantics (the dispatcher,
    not compute_paths, decides whether to err_exit)."""
    env = _make_env(tmp_path, monkeypatch)
    monkeypatch.setenv("GRIDFILE", "hgrid.gr3")
    monkeypatch.setenv("STA_OUT_CTL", "station.in")
    monkeypatch.setenv("RUNTIME_CTL", "param.nml")
    # Intentionally do NOT seed the fix files

    caplog.set_level(logging.ERROR,
                     logger="nos_workflow.runners.schism_ufs.setup_paths")
    ctx = compute_paths(env, phase="nowcast")

    assert isinstance(ctx, SchismRunContext), (
        "missing fix file should NOT raise; the dispatcher handles err_chk"
    )
    error_msgs = [r.getMessage() for r in caplog.records
                  if r.levelno >= logging.ERROR]
    assert any("hgrid.gr3" in m for m in error_msgs)


def test_compute_paths_stages_nudge_index_files_when_prefixed_match(
        tmp_path, monkeypatch):
    """``${FIXofs}/${PREFIXNOS}.nobc_nudge_index.dat`` is renamed to
    ``$DATA/nobc_nudge_index.dat`` (sans prefix). Confirms the rename."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("PREFIXNOS", "nos.secofs_ufs")

    (env.fixofs / "nos.secofs_ufs.nobc_nudge_index.dat").write_text("idx")
    (env.fixofs / "nos.secofs_ufs.nudge_point_at_ofs_grid.dat").write_text("pts")

    compute_paths(env, phase="nowcast")

    assert (env.data / "nobc_nudge_index.dat").read_text() == "idx"
    assert (env.data / "nudge_point_at_ofs_grid.dat").read_text() == "pts"


def test_compute_paths_vgrid_fake_overrides_vgrid_in(tmp_path, monkeypatch):
    """VGRID_FAKE_CTL is intentionally copied OVER the canonical
    VGRID_CTL name (matches launch.sh:154 quirk)."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("VGRID_CTL", "vgrid.in")
    monkeypatch.setenv("VGRID_FAKE_CTL", "vgrid.fake")
    (env.fixofs / "vgrid.in").write_text("# real vgrid\n")
    (env.fixofs / "vgrid.fake").write_text("# fake vgrid\n")

    compute_paths(env, phase="nowcast")

    # vgrid.fake content should now be at $DATA/vgrid.in (the rename)
    assert (env.data / "vgrid.in").read_text() == "# fake vgrid\n"


# ---------------------------------------------------------------------------
# Phase routing (PR 5 does not differentiate paths by phase)
# ---------------------------------------------------------------------------


def test_compute_paths_phase_nowcast_vs_forecast_paths_identical(
        tmp_path, monkeypatch):
    """phase=nowcast and phase=forecast produce contexts with identical
    file-path fields. The shell ``_schism_setup_paths`` doesn't branch on
    phase either -- the same filename env vars are exported regardless,
    and the consumer (``_schism_stage_files`` step 6) picks which one
    to actually stage."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    ctx_nowcast = compute_paths(env, phase="nowcast")
    ctx_forecast = compute_paths(env, phase="forecast")

    # Phase is the only difference
    assert ctx_nowcast.phase == "nowcast"
    assert ctx_forecast.phase == "forecast"
    # All filename + time anchor fields match
    for f in ("ini_file_nowcast", "ini_file_forecast",
              "rst_out_nowcast", "rst_out_forecast",
              "base_date", "time_hotstart", "time_nowcastend",
              "time_forecastend", "nstep_nowcast", "nstep_forecast"):
        assert getattr(ctx_nowcast, f) == getattr(ctx_forecast, f), (
            f"field {f!r} should not differ between phases at PR 5"
        )


# ---------------------------------------------------------------------------
# Prep mode (PR 6 wires the find_hotstart walk-back)
# ---------------------------------------------------------------------------


def test_compute_paths_prep_mode_empty_comout_falls_to_cold_start(
        tmp_path, monkeypatch):
    """``runtype="prep"`` with an empty $COMOUTroot should run
    :func:`hotstart.find_hotstart`, fail to locate a usable restart, and
    return a cold-start context (COLD_START="T", rst_file=None)."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("PREFIXNOS", "nos.secofs_ufs")

    ctx = compute_paths(env, phase="nowcast", runtype="prep")

    assert isinstance(ctx, SchismRunContext)
    assert ctx.cold_start == "T", "empty COMOUTroot must fall back to cold start"
    assert ctx.rst_file is None


def test_compute_paths_prep_mode_uppercase_also_runs(tmp_path, monkeypatch):
    """Shell accepts both ``PREP`` and ``prep`` (case-insensitive) -- the
    Python port normalizes to lowercase before dispatching."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    ctx = compute_paths(env, phase="nowcast", runtype="PREP")

    assert isinstance(ctx, SchismRunContext)


def test_compute_paths_prep_mode_writes_time_files(tmp_path, monkeypatch):
    """Prep mode must persist time_*.${cycle} text files into $COMOUT so
    downstream PBS jobs can recover the anchors without re-running the
    walk-back (matches the persistence block on lines 370-373 of
    nos_run.sh)."""
    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    ctx = compute_paths(env, phase="nowcast", runtype="prep")

    cycle = ctx.cycle
    for name in (
        f"time_hotstart.{cycle}",
        f"time_nowcastend.{cycle}",
        f"time_forecastend.{cycle}",
        f"base_date.{cycle}",
    ):
        assert (env.comout / name).is_file(), f"missing {name} in $COMOUT"


def test_compute_paths_prep_mode_finds_existing_restart(tmp_path, monkeypatch):
    """When $COMOUTroot has a usable restart 6 hours before time_nowcastend,
    prep mode locates it and returns COLD_START='F' with the rst_file set.

    NCOEnv defaults COMOUTroot to ``comout.parent``, so seeding a restart
    under ``tmp_path/{run}.YYYYMMDD/`` exposes it through the default
    lookup path.
    """
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    monkeypatch.setenv("PREFIXNOS", "nos.secofs_ufs")

    # Seed a restart at 2026-05-11 18z (6h before time_nowcastend=2026051200).
    rst_dir = tmp_path / "nos.secofs_ufs.20260511"
    rst_dir.mkdir(parents=True, exist_ok=True)
    rst_path = rst_dir / "nos.secofs_ufs.t18z.20260511.rst.nowcast.nc"
    rst_path.write_bytes(b"\x89HDF\r\nfake restart\n")

    ctx = compute_paths(env, phase="nowcast", runtype="prep")

    assert ctx.cold_start == "F"
    assert ctx.rst_file == str(rst_path)
    assert ctx.base_date == "2026051118"
    assert ctx.time_hotstart == "2026051118"


# ---------------------------------------------------------------------------
# $COMOUT time-file recovery (shell lines 418-440 parity)
# ---------------------------------------------------------------------------


def test_compute_paths_reads_time_hotstart_from_comout(tmp_path, monkeypatch):
    """For non-prep runtypes, ``$COMOUT/time_hotstart.${cycle}`` overrides
    the formula-based computation -- matches shell nos_run.sh:418-421
    where nowcast/forecast stages read the file prep wrote.

    Concretely: if prep wrote ``2026051118`` (warm-start, 6h back from
    a 2026-05-12 00z cycle) into $COMOUT/time_hotstart.${cycle}, Python
    must return that exact value -- NOT cycle-LEN_NOWCAST.
    """
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    cycle = env.cycle
    (env.comout / f"time_hotstart.{cycle}").write_text("2026051118\n")
    (env.comout / f"time_nowcastend.{cycle}").write_text("2026051200\n")
    (env.comout / f"time_forecastend.{cycle}").write_text("2026051400\n")
    (env.comout / f"base_date.{cycle}").write_text("2026051118\n")

    ctx = compute_paths(env, phase="nowcast", runtype="nowcast")

    assert ctx.time_hotstart == "2026051118"
    assert ctx.time_nowcastend == "2026051200"
    assert ctx.time_forecastend == "2026051400"
    assert ctx.base_date == "2026051118"


def test_compute_paths_reads_unconventional_time_hotstart_from_comout(
    tmp_path, monkeypatch,
):
    """If prep wrote a time_hotstart that is NOT cycle-LEN_NOWCAST
    (e.g., the cycle time itself, or a 12-hour-old restart anchor),
    compute_paths must honor that value rather than silently
    recomputing it.

    This is the bug the Cycle-A-vs-Cycle-B parity drill exposed:
    formula-based recomputation drove start_day/start_hour mismatches
    between shell and Python on warm-start cycles.
    """
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    # Intentionally non-standard: prep wrote the cycle time itself
    # as time_hotstart (e.g., zero-hour nowcast scenario).
    (env.comout / f"time_hotstart.{env.cycle}").write_text("2026051200\n")

    ctx = compute_paths(env, phase="nowcast", runtype="nowcast")

    assert ctx.time_hotstart == "2026051200"
    # The cycle time fallback for time_nowcastend (no file present).
    assert ctx.time_nowcastend == "2026051200"


def test_compute_paths_falls_back_to_formula_when_comout_missing(
    tmp_path, monkeypatch, caplog,
):
    """When $COMOUT/time_hotstart.${cycle} is absent (e.g. dev-machine
    smoke test, or prep skipped), compute_paths falls back to the
    formula-based computation AND logs a WARNING flagging this as a
    fatal-in-shell condition."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)
    # Do not seed $COMOUT/time_hotstart.${cycle}

    with caplog.at_level(logging.WARNING):
        ctx = compute_paths(env, phase="nowcast", runtype="nowcast")

    # Formula = cycle - LEN_NOWCAST (default 6h) = 2026051200 - 6h = 2026051118
    assert ctx.time_hotstart == "2026051118"
    assert any(
        "time_hotstart" in record.message for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Schema invariants
# ---------------------------------------------------------------------------


def test_compute_paths_returns_frozen_context(tmp_path, monkeypatch):
    """The returned :class:`SchismRunContext` is frozen -- attempting to
    mutate must raise :class:`FrozenInstanceError`."""
    from dataclasses import FrozenInstanceError

    env = _make_env(tmp_path, monkeypatch)
    _seed_fix_files(env.fixofs, monkeypatch, with_optional=False)

    ctx = compute_paths(env, phase="nowcast")

    with pytest.raises(FrozenInstanceError):
        ctx.phase = "forecast"  # type: ignore[misc]
