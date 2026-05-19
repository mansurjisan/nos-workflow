"""Unit tests for ``runners.schism_ufs.stage_files`` (PR 7a -- static
file staging phases of ``_schism_stage_files``).

Mirrors the behavior of lines 395-768 of ``ush/nos_run.sh``, restricted
to the four phases that PR 7a ports (the rest land in 7b/7c):

  - :func:`stage_ufs_configs`            -- lines 452-490
  - :func:`stage_schism_bare_names`      -- lines 571-586
  - :func:`stage_hotstart`               -- lines 628-657
  - :func:`stage_partition_props`        -- lines 602-607
  - :func:`stage_forecast_restart_outputs` -- lines 744-764

All fixtures are built under ``tmp_path`` -- no real $FIXofs / $COMOUT /
$DATA needed. Tests verify file presence + byte-identity round-trips
(``shutil.copy2`` preserves content; we check the destination has the
expected source contents).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

from nos_workflow.runners.schism_ufs.context import SchismRunContext
from nos_workflow.runners.schism_ufs.stage_files import (
    _NWM_FALLBACK_FILES,
    _RIVER_RENAMES,
    _SCHISM_PARTITION_FILES,
    _SCHISM_PROPERTY_FILES,
    _UFS_AUX_FILES,
    _UFS_CONFIG_FILES,
    copy_hgrid_to_outputs,
    fallback_nwm_files_from_fixofs,
    rename_river_th_files,
    stage_st_lawrence_river,
    stage_bctides_in,
    stage_executable,
    stage_forecast_restart_outputs,
    stage_hotstart,
    stage_partition_props,
    stage_schism_bare_names,
    stage_sflux_inputs_txt,
    stage_ufs_configs,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    tmp_path: Path,
    *,
    phase: str = "nowcast",
    run: str = "nos.secofs_ufs",
    cycle: str = "t00z",
    prefixnos: str = "nos.secofs_ufs",
    ini_file_nowcast: Optional[str] = None,
    ini_file_forecast: Optional[str] = None,
    rst_out_nowcast: Optional[str] = None,
    ini_file: Optional[str] = None,
    bctides_in_nowcast: Optional[str] = None,
    bctides_in_forecast: Optional[str] = None,
) -> SchismRunContext:
    """Construct a :class:`SchismRunContext` with $COMOUT / $DATA /
    $FIXofs / $EXECnos all rooted under ``tmp_path``. Caller decides
    which hotstart fields to populate."""
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    fixofs = tmp_path / "fix"
    execnos = tmp_path / "exec"
    for p in (comout, data, fixofs, execnos):
        p.mkdir(parents=True, exist_ok=True)
    return SchismRunContext(
        comout=comout, data=data, phase=phase, run=run, cycle=cycle,
        prefixnos=prefixnos,
        fixofs=fixofs, execnos=execnos,
        ini_file_nowcast=ini_file_nowcast,
        ini_file_forecast=ini_file_forecast,
        rst_out_nowcast=rst_out_nowcast,
        bctides_in_nowcast=bctides_in_nowcast,
        bctides_in_forecast=bctides_in_forecast,
        ini_file=ini_file,
    )


def _seed_ufs_config_sources(ctx: SchismRunContext) -> None:
    """Drop the four canonical UFS config files into
    ``$COMOUT/$RUN.$cycle.<file>`` with distinct contents."""
    prefix = f"{ctx.run}.{ctx.cycle}"
    for f in _UFS_CONFIG_FILES:
        (ctx.comout / f"{prefix}.{f}").write_text(f"contents of {f}\n")


def _seed_datm_input_dir(ctx: SchismRunContext, n: int = 3) -> Path:
    """Create ``$COMOUT/$RUN.$cycle.datm_input/{datm_forcing.nc,...}``."""
    d = ctx.comout / f"{ctx.run}.{ctx.cycle}.datm_input"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / f"datm_part_{i}.nc").write_bytes(b"\x89HDF\r\n")
    (d / "datm_forcing.nc").write_bytes(b"\x89HDF\r\n")
    return d


# ---------------------------------------------------------------------------
# stage_ufs_configs
# ---------------------------------------------------------------------------


def test_stage_ufs_configs_creates_required_subdirs(tmp_path):
    """``$DATA/{INPUT,RESTART,outputs}`` are created up-front."""
    ctx = _make_ctx(tmp_path)
    stage_ufs_configs(ctx, "nowcast")
    assert (ctx.data / "INPUT").is_dir()
    assert (ctx.data / "RESTART").is_dir()
    assert (ctx.data / "outputs").is_dir()


def test_stage_ufs_configs_honors_datm_input_dir_override(
    tmp_path, monkeypatch,
):
    """``$DATM_INPUT_DIR`` override controls the destination subdir."""
    monkeypatch.setenv("DATM_INPUT_DIR", "DATM_FORCING")
    ctx = _make_ctx(tmp_path)
    stage_ufs_configs(ctx, "nowcast")
    assert (ctx.data / "DATM_FORCING").is_dir()
    # Default subdir name is NOT created when override is set.
    assert not (ctx.data / "INPUT").exists()


def test_stage_ufs_configs_copies_all_present_configs(tmp_path):
    """When every UFS config exists in $COMOUT, all four land in $DATA."""
    ctx = _make_ctx(tmp_path)
    _seed_ufs_config_sources(ctx)
    n = stage_ufs_configs(ctx, "nowcast")

    for f in _UFS_CONFIG_FILES:
        dst = ctx.data / f
        assert dst.is_file(), f"missing {f}"
        assert dst.read_text() == f"contents of {f}\n"
    # n counts UFS configs (4) -- DATM dir is absent so no NetCDFs copied.
    assert n >= 4


def test_stage_ufs_configs_skips_missing_configs(tmp_path):
    """Only the configs that exist in $COMOUT are copied (the rest
    are silently skipped with a WARNING)."""
    ctx = _make_ctx(tmp_path)
    # Only stage 2 of the 4 configs.
    prefix = f"{ctx.run}.{ctx.cycle}"
    (ctx.comout / f"{prefix}.model_configure").write_text("mc\n")
    (ctx.comout / f"{prefix}.datm_in").write_text("din\n")

    stage_ufs_configs(ctx, "nowcast")

    assert (ctx.data / "model_configure").is_file()
    assert (ctx.data / "datm_in").is_file()
    assert not (ctx.data / "datm.streams").exists()
    assert not (ctx.data / "ufs.configure").exists()


def test_stage_ufs_configs_copies_datm_forcing_files(tmp_path):
    """All ``*.nc`` files in ``$COMOUT/$RUN.$cycle.datm_input/`` are
    copied to ``$DATA/INPUT/``."""
    ctx = _make_ctx(tmp_path)
    _seed_datm_input_dir(ctx, n=3)
    stage_ufs_configs(ctx, "nowcast")
    # 3 datm_part_*.nc + datm_forcing.nc = 4 files
    input_dir = ctx.data / "INPUT"
    nc_files = sorted(input_dir.glob("*.nc"))
    assert len(nc_files) == 4
    assert (input_dir / "datm_forcing.nc").is_file()


def test_stage_ufs_configs_aux_files_prefer_fixofs(tmp_path):
    """``fd_ufs.yaml`` / ``noahmptable.tbl`` come from $FIXofs when
    BOTH $FIXofs and $COMOUT have them."""
    ctx = _make_ctx(tmp_path)
    for f in _UFS_AUX_FILES:
        (ctx.fixofs / f).write_text(f"FIX {f}\n")
        (ctx.comout / f"{ctx.run}.{ctx.cycle}.{f}").write_text(f"COM {f}\n")

    stage_ufs_configs(ctx, "nowcast")

    for f in _UFS_AUX_FILES:
        assert (ctx.data / f).read_text() == f"FIX {f}\n"


def test_stage_ufs_configs_aux_files_fall_back_to_comout(tmp_path):
    """``fd_ufs.yaml`` / ``noahmptable.tbl`` come from $COMOUT when
    $FIXofs version is absent."""
    ctx = _make_ctx(tmp_path)
    for f in _UFS_AUX_FILES:
        (ctx.comout / f"{ctx.run}.{ctx.cycle}.{f}").write_text(f"COM {f}\n")
    # No $FIXofs copies.

    stage_ufs_configs(ctx, "nowcast")

    for f in _UFS_AUX_FILES:
        assert (ctx.data / f).read_text() == f"COM {f}\n"


def test_stage_executable_staged_from_execnos(tmp_path):
    """The executable is staged from $EXECnos to $DATA and marked
    executable. (Exe-copy is mode-common: split out of stage_ufs_configs
    into stage_executable so standalone-SCHISM also stages its binary.)"""
    ctx = _make_ctx(tmp_path)
    src = ctx.execnos / "fv3_coastalS.exe"
    src.write_bytes(b"#!fake binary\n")
    os.chmod(src, 0o755)

    stage_executable(ctx, "nowcast")

    dst = ctx.data / "fv3_coastalS.exe"
    assert dst.is_file()
    assert dst.read_bytes() == b"#!fake binary\n"
    assert os.access(dst, os.X_OK), "executable bit must be preserved"


def test_stage_executable_skipped_if_present(tmp_path):
    """An already-staged executable in $DATA is not overwritten."""
    ctx = _make_ctx(tmp_path)
    dst = ctx.data / "fv3_coastalS.exe"
    dst.write_bytes(b"already here\n")
    os.chmod(dst, 0o755)
    # Source has different content -- proves the early-return skipped.
    src = ctx.execnos / "fv3_coastalS.exe"
    src.write_bytes(b"new content\n")
    os.chmod(src, 0o755)

    stage_executable(ctx, "nowcast")

    assert dst.read_bytes() == b"already here\n"


def test_stage_executable_honors_ufs_exec_name_override(
    tmp_path, monkeypatch,
):
    """``$UFS_EXEC_NAME`` override changes the executable filename
    (standalone sets it to pschism_WCOSS2 via Phase-1's resolver)."""
    monkeypatch.setenv("UFS_EXEC_NAME", "schism.exe")
    ctx = _make_ctx(tmp_path)
    src = ctx.execnos / "schism.exe"
    src.write_bytes(b"#!schism\n")
    os.chmod(src, 0o755)

    stage_executable(ctx, "nowcast")

    assert (ctx.data / "schism.exe").is_file()
    assert not (ctx.data / "fv3_coastalS.exe").exists()


# ---------------------------------------------------------------------------
# stage_schism_bare_names
# ---------------------------------------------------------------------------


def test_stage_schism_bare_names_copies_hgrid(tmp_path):
    """``$PREFIXNOS.hgrid.gr3`` -> ``$DATA/hgrid.gr3``."""
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.hgrid.gr3").write_text("hgrid data\n")
    stage_schism_bare_names(ctx, "nowcast")
    assert (ctx.data / "hgrid.gr3").read_text() == "hgrid data\n"


def test_stage_schism_bare_names_copies_vgrid(tmp_path, monkeypatch):
    """``$VGRID_CTL`` -> ``$DATA/vgrid.in`` (bare-name rename)."""
    ctx = _make_ctx(tmp_path)
    monkeypatch.setenv("VGRID_CTL", "nos.secofs_ufs.vgrid.in")
    (ctx.fixofs / "nos.secofs_ufs.vgrid.in").write_text("vgrid data\n")
    stage_schism_bare_names(ctx, "nowcast")
    assert (ctx.data / "vgrid.in").read_text() == "vgrid data\n"


def test_stage_schism_bare_names_copies_vgrid_nu(tmp_path, monkeypatch):
    """``$VGRID_NU_CTL`` -> ``$DATA/vgrid_nu.in``."""
    ctx = _make_ctx(tmp_path)
    monkeypatch.setenv("VGRID_NU_CTL", "nos.secofs_ufs.vgrid.nu.in")
    (ctx.fixofs / "nos.secofs_ufs.vgrid.nu.in").write_text("vgrid_nu data\n")
    stage_schism_bare_names(ctx, "nowcast")
    assert (ctx.data / "vgrid_nu.in").read_text() == "vgrid_nu data\n"


def test_stage_schism_bare_names_copies_station_in(tmp_path, monkeypatch):
    """``$STA_OUT_CTL`` -> ``$DATA/station.in``."""
    ctx = _make_ctx(tmp_path)
    monkeypatch.setenv("STA_OUT_CTL", "nos.secofs_ufs.station.in")
    (ctx.fixofs / "nos.secofs_ufs.station.in").write_text("stations\n")
    stage_schism_bare_names(ctx, "nowcast")
    assert (ctx.data / "station.in").read_text() == "stations\n"


def test_stage_schism_bare_names_copies_optional_property_files(tmp_path):
    """Each present ``$PREFIXNOS.<bare>`` is copied to ``$DATA/<bare>``."""
    ctx = _make_ctx(tmp_path)
    # Drop a subset of the optional property files in $FIXofs.
    present = ("shapiro.gr3", "albedo.gr3", "TEM_nudge.gr3", "elev.ic")
    for bare in present:
        (ctx.fixofs / f"{ctx.prefixnos}.{bare}").write_text(f"data for {bare}\n")

    stage_schism_bare_names(ctx, "nowcast")

    for bare in present:
        assert (ctx.data / bare).is_file(), f"missing {bare}"
        assert (ctx.data / bare).read_text() == f"data for {bare}\n"


def test_stage_schism_bare_names_skips_absent_property_files(tmp_path):
    """Optional property files that aren't in $FIXofs are silently skipped."""
    ctx = _make_ctx(tmp_path)
    # Drop ONE property file in $FIXofs.
    (ctx.fixofs / f"{ctx.prefixnos}.shapiro.gr3").write_text("shap\n")

    stage_schism_bare_names(ctx, "nowcast")

    assert (ctx.data / "shapiro.gr3").is_file()
    # No other property file got copied.
    for bare in _SCHISM_PROPERTY_FILES:
        if bare != "shapiro.gr3":
            assert not (ctx.data / bare).exists(), f"unexpected {bare}"


def test_stage_schism_bare_names_returns_correct_count(tmp_path, monkeypatch):
    """Count matches the number of files actually copied."""
    ctx = _make_ctx(tmp_path)
    monkeypatch.setenv("VGRID_CTL", "nos.secofs_ufs.vgrid.in")
    monkeypatch.setenv("STA_OUT_CTL", "nos.secofs_ufs.station.in")
    (ctx.fixofs / f"{ctx.prefixnos}.hgrid.gr3").write_text("h\n")
    (ctx.fixofs / "nos.secofs_ufs.vgrid.in").write_text("v\n")
    (ctx.fixofs / "nos.secofs_ufs.station.in").write_text("s\n")
    (ctx.fixofs / f"{ctx.prefixnos}.shapiro.gr3").write_text("p\n")

    n = stage_schism_bare_names(ctx, "nowcast")

    # hgrid + vgrid + station + 1 property = 4
    assert n == 4


def test_stage_schism_bare_names_no_fixofs_is_noop(tmp_path):
    """``ctx.fixofs is None`` -> 0 staged, no error."""
    ctx = SchismRunContext(
        comout=tmp_path / "comout",
        data=tmp_path / "data",
        phase="nowcast",
        run="nos.secofs_ufs",
        cycle="t00z",
        fixofs=None,
        prefixnos="nos.secofs_ufs",
    )
    ctx.data.mkdir(parents=True, exist_ok=True)
    n = stage_schism_bare_names(ctx, "nowcast")
    assert n == 0


# ---------------------------------------------------------------------------
# stage_hotstart
# ---------------------------------------------------------------------------


def test_stage_hotstart_nowcast_uses_ini_file_nowcast(tmp_path):
    """``phase=nowcast`` + ``INI_FILE_NOWCAST`` exists -> stage that file."""
    ctx = _make_ctx(
        tmp_path,
        ini_file_nowcast="nos.secofs_ufs.t00z.20260512.init.nowcast.nc",
    )
    (ctx.comout / "nos.secofs_ufs.t00z.20260512.init.nowcast.nc").write_bytes(
        b"hotstart payload\n"
    )

    n = stage_hotstart(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "hotstart.nc").read_bytes() == b"hotstart payload\n"


def test_stage_hotstart_nowcast_falls_back_to_ini_file(tmp_path):
    """When ``INI_FILE_NOWCAST`` is missing, fall back to absolute
    ``INI_FILE`` (cold-start path)."""
    src = tmp_path / "external" / "cold_start.nc"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"cold start\n")
    ctx = _make_ctx(
        tmp_path,
        ini_file_nowcast="nope.nc",
        ini_file=str(src),
    )

    n = stage_hotstart(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "hotstart.nc").read_bytes() == b"cold start\n"


def test_stage_hotstart_forecast_uses_ini_file_forecast(tmp_path):
    """``phase=forecast`` prefers ``INI_FILE_FORECAST`` over ``RST_OUT_NOWCAST``."""
    ctx = _make_ctx(
        tmp_path,
        ini_file_forecast="ini.forecast.nc",
        rst_out_nowcast="rst.nowcast.nc",
    )
    (ctx.comout / "ini.forecast.nc").write_bytes(b"INI\n")
    (ctx.comout / "rst.nowcast.nc").write_bytes(b"RST\n")

    n = stage_hotstart(ctx, "forecast")

    assert n == 1
    assert (ctx.data / "hotstart.nc").read_bytes() == b"INI\n"


def test_stage_hotstart_forecast_falls_back_to_rst_out_nowcast(tmp_path):
    """``RST_OUT_NOWCAST`` is the forecast fallback when
    ``INI_FILE_FORECAST`` is missing."""
    ctx = _make_ctx(
        tmp_path,
        ini_file_forecast="missing.nc",
        rst_out_nowcast="rst.nowcast.nc",
    )
    (ctx.comout / "rst.nowcast.nc").write_bytes(b"RST\n")

    n = stage_hotstart(ctx, "forecast")

    assert n == 1
    assert (ctx.data / "hotstart.nc").read_bytes() == b"RST\n"


def test_stage_hotstart_nowcast_raises_when_all_sources_missing(tmp_path):
    """``phase=nowcast`` with no candidate sources -> FileNotFoundError."""
    ctx = _make_ctx(
        tmp_path,
        ini_file_nowcast="missing.nc",
        ini_file="/does/not/exist.nc",
    )
    with pytest.raises(FileNotFoundError) as ei:
        stage_hotstart(ctx, "nowcast")
    msg = str(ei.value)
    assert "phase=nowcast" in msg
    assert "missing.nc" in msg
    # The diagnostic must include the recovery hint.
    assert "NETCDF4_CLASSIC" in msg


def test_stage_hotstart_forecast_raises_when_all_sources_missing(tmp_path):
    """``phase=forecast`` with no candidate sources -> FileNotFoundError."""
    ctx = _make_ctx(
        tmp_path,
        ini_file_forecast="missing.nc",
        rst_out_nowcast="also_missing.nc",
    )
    with pytest.raises(FileNotFoundError):
        stage_hotstart(ctx, "forecast")


def test_stage_hotstart_unknown_phase_raises_value_error(tmp_path):
    """A phase string that isn't nowcast/forecast -> ValueError."""
    ctx = _make_ctx(tmp_path, ini_file_nowcast="x.nc")
    with pytest.raises(ValueError) as ei:
        stage_hotstart(ctx, "bogus")
    assert "bogus" in str(ei.value)


def test_stage_hotstart_empty_source_is_treated_as_missing(tmp_path):
    """Zero-byte source files don't count -- matches shell's ``[ -s "$src" ]``."""
    ctx = _make_ctx(
        tmp_path,
        ini_file_nowcast="empty.nc",
        ini_file=str(tmp_path / "also_empty.nc"),
    )
    (ctx.comout / "empty.nc").touch()
    (tmp_path / "also_empty.nc").touch()

    with pytest.raises(FileNotFoundError):
        stage_hotstart(ctx, "nowcast")


# ---------------------------------------------------------------------------
# stage_partition_props
# ---------------------------------------------------------------------------


def test_stage_partition_props_copies_all_present(tmp_path):
    """All three prop files staged from $FIXofs when present."""
    ctx = _make_ctx(tmp_path)
    for prop in _SCHISM_PARTITION_FILES:
        (ctx.fixofs / f"{ctx.prefixnos}.{prop}").write_text(f"{prop} data\n")

    n = stage_partition_props(ctx, "nowcast")

    assert n == len(_SCHISM_PARTITION_FILES)
    for prop in _SCHISM_PARTITION_FILES:
        assert (ctx.data / prop).read_text() == f"{prop} data\n"


def test_stage_partition_props_only_partition_prop(tmp_path, caplog):
    """Just partition.prop -- the critical ParMETIS bypass."""
    import logging
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.partition.prop").write_text("part\n")

    caplog.set_level(
        logging.INFO,
        logger="nos_workflow.runners.schism_ufs.stage_files",
    )
    n = stage_partition_props(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "partition.prop").is_file()
    # Must log the diagnostic noting the ParMETIS bypass.
    assert any(
        "ParMETIS" in rec.getMessage()
        for rec in caplog.records
    )


def test_stage_partition_props_silently_skips_when_absent(tmp_path):
    """No prefixed sources in $FIXofs -> no work, no error."""
    ctx = _make_ctx(tmp_path)
    n = stage_partition_props(ctx, "nowcast")
    assert n == 0
    for prop in _SCHISM_PARTITION_FILES:
        assert not (ctx.data / prop).exists()


def test_stage_partition_props_no_prefix_no_op(tmp_path):
    """Missing PREFIXNOS -> nothing happens (matches shell's
    ``[ -s "${FIXofs}/${PREFIXNOS}.${prop}" ]`` which evaluates to
    ``[ -s "/path/.tvd.prop" ]`` and would silently fail)."""
    ctx = SchismRunContext(
        comout=tmp_path / "comout",
        data=tmp_path / "data",
        phase="nowcast",
        run="nos.secofs_ufs",
        cycle="t00z",
        fixofs=tmp_path / "fix",
        prefixnos=None,
    )
    ctx.data.mkdir(parents=True, exist_ok=True)
    ctx.fixofs.mkdir(parents=True, exist_ok=True)
    n = stage_partition_props(ctx, "nowcast")
    assert n == 0


# ---------------------------------------------------------------------------
# stage_forecast_restart_outputs
# ---------------------------------------------------------------------------


def test_stage_forecast_restart_outputs_nowcast_is_noop(tmp_path):
    """``phase=nowcast`` -> 0 staged, no $DATA/outputs touched."""
    ctx = _make_ctx(tmp_path)
    n = stage_forecast_restart_outputs(ctx, "nowcast")
    assert n == 0
    # outputs/ should not be created by this no-op helper.
    assert not (ctx.data / "outputs").exists()


def test_stage_forecast_restart_outputs_copies_present_files(tmp_path):
    """All canonical files in the source dir are copied to $DATA/outputs/."""
    ctx = _make_ctx(tmp_path, phase="forecast")
    restart_src = ctx.comout / f"{ctx.run}.{ctx.cycle}.restart_outputs"
    restart_src.mkdir()
    (restart_src / "mirror.out").write_text("mirror\n")
    (restart_src / "flux.out").write_text("flux\n")
    for i in range(1, 4):
        (restart_src / f"staout_{i}").write_text(f"staout {i}\n")

    n = stage_forecast_restart_outputs(ctx, "forecast")

    # 2 (mirror+flux) + 3 staouts = 5 files copied
    assert n == 5
    out = ctx.data / "outputs"
    assert (out / "mirror.out").read_text() == "mirror\n"
    assert (out / "flux.out").read_text() == "flux\n"
    for i in range(1, 4):
        assert (out / f"staout_{i}").read_text() == f"staout {i}\n"


def test_stage_forecast_restart_outputs_creates_placeholders(tmp_path):
    """All canonical output names exist in $DATA/outputs/ after the call,
    even when the source dir is empty. The shell ``touch``-es them so
    SCHISM ``open(status='old')`` doesn't crash."""
    ctx = _make_ctx(tmp_path, phase="forecast")
    # No source dir at all.
    n = stage_forecast_restart_outputs(ctx, "forecast")

    assert n == 0
    out = ctx.data / "outputs"
    for f in ("mirror.out", "flux.out"):
        assert (out / f).is_file()
        assert (out / f).stat().st_size == 0
    for i in range(1, 10):
        assert (out / f"staout_{i}").is_file()


def test_stage_forecast_restart_outputs_does_not_truncate_existing(tmp_path):
    """If a file is already in ``$DATA/outputs/`` with content, the
    ``touch`` for placeholder creation must NOT truncate it."""
    ctx = _make_ctx(tmp_path, phase="forecast")
    out = ctx.data / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "mirror.out").write_text("prior content\n")

    stage_forecast_restart_outputs(ctx, "forecast")

    assert (out / "mirror.out").read_text() == "prior content\n"


def test_stage_forecast_restart_outputs_missing_src_logs_warning(
    tmp_path, caplog,
):
    """Missing ``$COMOUT/$RUN.$cycle.restart_outputs/`` -> WARNING +
    rc 0 (matches shell's "WARNING: restart_outputs not found")."""
    import logging
    ctx = _make_ctx(tmp_path, phase="forecast")
    caplog.set_level(
        logging.WARNING,
        logger="nos_workflow.runners.schism_ufs.stage_files",
    )
    n = stage_forecast_restart_outputs(ctx, "forecast")
    assert n == 0
    assert any(
        "restart_outputs" in rec.getMessage()
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# stage_bctides_in
# ---------------------------------------------------------------------------


def test_stage_bctides_in_nowcast_prefers_comout(tmp_path):
    """When ``$COMOUT/${PREFIXNOS}.bctides.in.nowcast`` exists, prefer it
    over the FIXofs fallback."""
    ctx = _make_ctx(tmp_path)
    (ctx.comout / "nos.secofs_ufs.bctides.in.nowcast").write_text("prep-generated\n")
    (ctx.fixofs / "nos.secofs_ufs.bctides.in").write_text("fix fallback\n")

    n = stage_bctides_in(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "bctides.in").read_text() == "prep-generated\n"


def test_stage_bctides_in_forecast_uses_forecast_suffix(tmp_path):
    """Phase=forecast reads from ``.forecast`` suffix."""
    ctx = _make_ctx(tmp_path, phase="forecast")
    (ctx.comout / "nos.secofs_ufs.bctides.in.forecast").write_text("forecast tides\n")

    n = stage_bctides_in(ctx, "forecast")

    assert n == 1
    assert (ctx.data / "bctides.in").read_text() == "forecast tides\n"


def test_stage_bctides_in_falls_back_to_fixofs(tmp_path, caplog):
    """When $COMOUT bctides.in is absent, fall back to $FIXofs and log a
    WARNING (matches shell line 621)."""
    import logging
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / "nos.secofs_ufs.bctides.in").write_text("fix fallback\n")
    caplog.set_level(
        logging.WARNING,
        logger="nos_workflow.runners.schism_ufs.stage_files",
    )

    n = stage_bctides_in(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "bctides.in").read_text() == "fix fallback\n"
    assert any("FIXofs bctides.in" in rec.getMessage() for rec in caplog.records)


def test_stage_bctides_in_no_sources_returns_zero(tmp_path):
    """Neither $COMOUT nor $FIXofs source present -> rc 0, no file staged."""
    ctx = _make_ctx(tmp_path)

    n = stage_bctides_in(ctx, "nowcast")

    assert n == 0
    assert not (ctx.data / "bctides.in").is_file()


def test_stage_bctides_in_prefers_ctx_cycle_stamped_basename(tmp_path):
    """Regression: reader must prefer ``ctx.bctides_in_nowcast`` (which
    compute_paths populates with the cycle-stamped filename
    ``secofs_ufs.tHHz.YYYYMMDD.bctides.in``) over the bare
    ``${PREFIXNOS}.bctides.in`` fallback.

    The prep stage writes the cycle-stamped name to $COMOUT.  Falling
    through to the bare-name basename would never match what's on disk
    and would silently downgrade every cycle to the FIXofs static file.
    """
    ctx = _make_ctx(
        tmp_path,
        bctides_in_nowcast="nos.secofs_ufs.t00z.20260511.bctides.in",
    )
    # Prep wrote the cycle-stamped file.
    (ctx.comout / "nos.secofs_ufs.t00z.20260511.bctides.in.nowcast").write_text(
        "prep-cycle-stamped\n"
    )
    # Bare-name version is intentionally NOT present -- this is the bug
    # condition where prep only writes cycle-stamped files.

    n = stage_bctides_in(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "bctides.in").read_text() == "prep-cycle-stamped\n"


def test_stage_bctides_in_forecast_prefers_ctx_cycle_stamped_basename(tmp_path):
    """Same regression as nowcast but for the forecast phase."""
    ctx = _make_ctx(
        tmp_path,
        phase="forecast",
        bctides_in_forecast="nos.secofs_ufs.t00z.20260511.bctides.in",
    )
    (ctx.comout / "nos.secofs_ufs.t00z.20260511.bctides.in.forecast").write_text(
        "forecast-stamped\n"
    )

    n = stage_bctides_in(ctx, "forecast")

    assert n == 1
    assert (ctx.data / "bctides.in").read_text() == "forecast-stamped\n"


def test_stage_bctides_in_honors_BCTIDES_IN_env(tmp_path, monkeypatch):
    """``$BCTIDES_IN`` env override is the basename (without phase
    suffix) -- shell line 612 / 614 inserts the phase suffix.  Only
    consulted when ctx.bctides_in_{phase} is None (legacy shell-direct
    callers)."""
    ctx = _make_ctx(tmp_path)  # ctx.bctides_in_nowcast intentionally None
    monkeypatch.setenv("BCTIDES_IN", "custom.bctides.in")
    (ctx.comout / "custom.bctides.in.nowcast").write_text("custom\n")

    n = stage_bctides_in(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "bctides.in").read_text() == "custom\n"


# ---------------------------------------------------------------------------
# fallback_nwm_files_from_fixofs
# ---------------------------------------------------------------------------


def test_nwm_fallback_stages_only_missing(tmp_path):
    """FIXofs fallback runs only for NWM files NOT already produced by
    the tar extraction."""
    ctx = _make_ctx(tmp_path)
    # Simulate vsource.th already staged by tar extraction.
    (ctx.data / "vsource.th").write_text("from tar\n")
    # FIXofs has fallback for everything; only the missing ones should copy.
    for fname in _NWM_FALLBACK_FILES:
        (ctx.fixofs / f"nos.secofs_ufs.{fname}").write_text(f"fix {fname}\n")

    n = fallback_nwm_files_from_fixofs(ctx, "nowcast")

    # 3 staged (source_sink.in, vsink.th, msource.th); vsource.th preserved
    assert n == 3
    assert (ctx.data / "vsource.th").read_text() == "from tar\n"
    assert (ctx.data / "source_sink.in").read_text() == "fix source_sink.in\n"
    assert (ctx.data / "vsink.th").read_text() == "fix vsink.th\n"
    assert (ctx.data / "msource.th").read_text() == "fix msource.th\n"


def test_nwm_fallback_no_prefix_is_noop(tmp_path):
    """Without PREFIXNOS, fallback can't construct source paths."""
    ctx = _make_ctx(tmp_path, prefixnos="")

    n = fallback_nwm_files_from_fixofs(ctx, "nowcast")

    assert n == 0


# ---------------------------------------------------------------------------
# rename_river_th_files
# ---------------------------------------------------------------------------


def test_rename_river_th_files_canonicalizes(tmp_path):
    """``schism_*.th`` -> SCHISM canonical names (TEM_1.th / flux.th /
    salt.th)."""
    ctx = _make_ctx(tmp_path)
    for src_name, _ in _RIVER_RENAMES:
        (ctx.data / src_name).write_text(f"content of {src_name}\n")

    n = rename_river_th_files(ctx, "nowcast")

    assert n == 3
    assert (ctx.data / "TEM_1.th").read_text() == "content of schism_temp.th\n"
    assert (ctx.data / "flux.th").read_text() == "content of schism_flux.th\n"
    assert (ctx.data / "salt.th").read_text() == "content of schism_salt.th\n"


def test_rename_river_th_files_silently_skips_missing(tmp_path):
    """No schism_*.th sources -> rc 0, no destination created."""
    ctx = _make_ctx(tmp_path)

    n = rename_river_th_files(ctx, "nowcast")

    assert n == 0
    assert not (ctx.data / "TEM_1.th").exists()


def test_rename_river_th_files_partial(tmp_path):
    """Only some sources present -> only those get renamed."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "schism_flux.th").write_text("flux data\n")

    n = rename_river_th_files(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "flux.th").read_text() == "flux data\n"
    assert not (ctx.data / "TEM_1.th").exists()
    assert not (ctx.data / "salt.th").exists()


# ---------------------------------------------------------------------------
# stage_st_lawrence_river (STOFS-3D-ATL only; gated)
# ---------------------------------------------------------------------------


def _seed_st_lawrence_comout(ctx: SchismRunContext) -> None:
    """Drop the prep-archived St. Lawrence individual files in $COMOUT."""
    prefix = f"{ctx.run}.{ctx.cycle}"
    (ctx.comout / f"{prefix}.riv.obs.flux.th").write_text("0 -1.0\n")
    (ctx.comout / f"{prefix}.riv.obs.tem_1.th").write_text("0 4.0\n")


def test_stage_st_lawrence_river_off_by_default(tmp_path, monkeypatch):
    """Without the opt-in flag the consumer is a no-op even when the
    source files are present (default-safe for SECOFS)."""
    monkeypatch.delenv("NOS_ARCHIVE_MANIFEST", raising=False)
    ctx = _make_ctx(tmp_path, run="nos.stofs_3d_atl",
                    prefixnos="nos.stofs_3d_atl")
    _seed_st_lawrence_comout(ctx)

    n = stage_st_lawrence_river(ctx, "nowcast")

    assert n == 0
    assert not (ctx.data / "flux.th").exists()
    assert not (ctx.data / "TEM_1.th").exists()


def test_stage_st_lawrence_river_secofs_noop_when_absent(
        tmp_path, monkeypatch):
    """SECOFS: flag ON but archive_to_comout never wrote the
    riv.obs.* files (st_lawrence_enabled=False) -> nothing staged."""
    monkeypatch.setenv("NOS_ARCHIVE_MANIFEST", "YES")
    ctx = _make_ctx(tmp_path)  # default run = nos.secofs_ufs
    # No _seed_st_lawrence_comout -> source files absent.

    n = stage_st_lawrence_river(ctx, "nowcast")

    assert n == 0
    assert not (ctx.data / "flux.th").exists()
    assert not (ctx.data / "TEM_1.th").exists()


def test_stage_st_lawrence_river_stofs_stages_files(
        tmp_path, monkeypatch):
    """STOFS: flag ON + source files present -> flux.th / TEM_1.th
    copied into $DATA from the operational riv.obs.* basenames."""
    monkeypatch.setenv("NOS_ARCHIVE_MANIFEST", "1")
    ctx = _make_ctx(tmp_path, run="nos.stofs_3d_atl",
                    prefixnos="nos.stofs_3d_atl")
    _seed_st_lawrence_comout(ctx)

    n = stage_st_lawrence_river(ctx, "nowcast")

    assert n == 2
    assert (ctx.data / "flux.th").read_text() == "0 -1.0\n"
    assert (ctx.data / "TEM_1.th").read_text() == "0 4.0\n"


def test_stage_st_lawrence_river_wins_over_river_rename(
        tmp_path, monkeypatch):
    """Sequencing invariant: when stage_st_lawrence_river runs AFTER
    rename_river_th_files (as wired in the staging sequence), the
    St. Lawrence climatology is authoritative -- it must NOT be
    clobbered by the schism_temp.th -> TEM_1.th / schism_flux.th ->
    flux.th rename."""
    monkeypatch.setenv("NOS_ARCHIVE_MANIFEST", "TRUE")
    ctx = _make_ctx(tmp_path, run="nos.stofs_3d_atl",
                    prefixnos="nos.stofs_3d_atl")
    # SECOFS-style river files that the rename step would canonicalize.
    (ctx.data / "schism_flux.th").write_text("RIVER flux\n")
    (ctx.data / "schism_temp.th").write_text("RIVER temp\n")
    # St. Lawrence climatology in $COMOUT.
    _seed_st_lawrence_comout(ctx)

    # Same order as stage_all_inputs: rename first, St. Lawrence after.
    rename_river_th_files(ctx, "nowcast")
    stage_st_lawrence_river(ctx, "nowcast")

    # St. Lawrence values win (not the river-rename values).
    assert (ctx.data / "flux.th").read_text() == "0 -1.0\n"
    assert (ctx.data / "TEM_1.th").read_text() == "0 4.0\n"


# ---------------------------------------------------------------------------
# stage_sflux_inputs_txt
# ---------------------------------------------------------------------------


def test_stage_sflux_inputs_txt_stages_when_present(tmp_path):
    """``$FIXofs/$PREFIXNOS.sflux_inputs.txt`` -> ``$DATA/sflux/sflux_inputs.txt``."""
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / "nos.secofs_ufs.sflux_inputs.txt").write_text("sflux config\n")

    n = stage_sflux_inputs_txt(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "sflux" / "sflux_inputs.txt").read_text() == "sflux config\n"


def test_stage_sflux_inputs_txt_absent_returns_zero(tmp_path):
    """Missing source returns 0 without creating the sflux subdir."""
    ctx = _make_ctx(tmp_path)

    n = stage_sflux_inputs_txt(ctx, "nowcast")

    assert n == 0


# ---------------------------------------------------------------------------
# copy_hgrid_to_outputs
# ---------------------------------------------------------------------------


def test_copy_hgrid_to_outputs_copies_when_present(tmp_path):
    """``$DATA/hgrid.gr3`` -> ``$DATA/outputs/hgrid.gr3``."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "hgrid.gr3").write_text("hgrid content\n")

    n = copy_hgrid_to_outputs(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "outputs" / "hgrid.gr3").read_text() == "hgrid content\n"


def test_copy_hgrid_to_outputs_skips_when_absent(tmp_path):
    """No ``$DATA/hgrid.gr3`` -> rc 0, no destination created."""
    ctx = _make_ctx(tmp_path)

    n = copy_hgrid_to_outputs(ctx, "nowcast")

    assert n == 0
