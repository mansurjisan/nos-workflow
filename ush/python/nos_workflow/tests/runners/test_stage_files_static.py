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

from nos_workflow.runners.schism_ufs import _dateutils
from nos_workflow.runners.schism_ufs.context import SchismRunContext
from nos_workflow.runners.schism_ufs.forcing import (
    _NWM_PAYLOAD_NAMES,
    _OBC_PAYLOAD_NAMES,
)
from nos_workflow.runners.schism_ufs.stage_files import (
    _NWM_FALLBACK_FILES,
    _RIVER_RENAMES,
    _SCHISM_PARTITION_FILES,
    _SCHISM_PROPERTY_FILES,
    _UFS_AUX_FILES,
    _UFS_CONFIG_FILES,
    collect_staged_inputs,
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
    stage_wave_configs,
    stage_wave_restarts,
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
# stage_wave_configs (wave-coupled systems only; gated on WAV_TASKS)
# ---------------------------------------------------------------------------


def test_stage_wave_configs_noop_without_wav_tasks(tmp_path, monkeypatch):
    """WAV_TASKS unset (every non-wave system) -> rc 0, nothing staged.

    This is the primary safety property: a non-wave system's staging must
    be completely unaffected by the wave staging code path existing.
    """
    monkeypatch.delenv("WAV_TASKS", raising=False)
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.mod_def.ww3").write_bytes(b"MODDEF\n")
    (ctx.fixofs / "ww3_shel.nml").write_text("&domain_nml\n/\n")

    n = stage_wave_configs(ctx, "nowcast")

    assert n == 0
    assert not (ctx.data / "mod_def.ww3").exists()
    assert not (ctx.data / "ww3_shel.nml").exists()


def test_stage_wave_configs_stages_from_fixofs(tmp_path, monkeypatch):
    """WAV_TASKS>0: mod_def.ww3, the WAV mesh, the ocn->wav and wav->ocn
    regrid weights, ww3_shel.nml, and the PDLIB namelist all stage from
    $FIXofs to their run-dir names."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    monkeypatch.setenv("WAV_MESH", "secofs_ufs.mesh_wav.nc")
    monkeypatch.setenv("WAV_PDLIB_NML", "secofs_ufs_ww3.namelists_pdlib.nml")
    monkeypatch.setenv("WAV_OCN2WAV_WEIGHTS", "secofs_ufs.ocn2wav_weights.nc")
    monkeypatch.setenv("WAV_WAV2OCN_WEIGHTS", "secofs_ufs.wav2ocn_weights.nc")
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.mod_def.ww3").write_bytes(b"MODDEF\n")
    (ctx.fixofs / "secofs_ufs.mesh_wav.nc").write_bytes(b"MESH\n")
    (ctx.fixofs / "ww3_shel.nml").write_text("shel template\n")
    (ctx.fixofs / "secofs_ufs_ww3.namelists_pdlib.nml").write_text("&UNST /\n")
    (ctx.fixofs / "secofs_ufs.ocn2wav_weights.nc").write_bytes(b"WEIGHTS\n")
    (ctx.fixofs / "secofs_ufs.wav2ocn_weights.nc").write_bytes(b"WEIGHTS2\n")

    n = stage_wave_configs(ctx, "nowcast")

    assert n == 6
    assert (ctx.data / "mod_def.ww3").read_bytes() == b"MODDEF\n"
    assert (ctx.data / "secofs_ufs.mesh_wav.nc").read_bytes() == b"MESH\n"
    assert (ctx.data / "ww3_shel.nml").read_text() == "shel template\n"
    assert (ctx.data / "secofs_ufs_ww3.namelists_pdlib.nml").read_text() == "&UNST /\n"
    assert (ctx.data / "secofs_ufs.ocn2wav_weights.nc").read_bytes() == b"WEIGHTS\n"
    assert (ctx.data / "secofs_ufs.wav2ocn_weights.nc").read_bytes() == b"WEIGHTS2\n"


def test_stage_wave_configs_ocn2wav_weights_falls_back_to_prefixed_name(
    tmp_path, monkeypatch,
):
    """WAV_OCN2WAV_WEIGHTS unset -> defaults to <prefix>.ocn2wav_weights.nc,
    matching the WAV_MESH fallback convention."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    monkeypatch.delenv("WAV_OCN2WAV_WEIGHTS", raising=False)
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.ocn2wav_weights.nc").write_bytes(b"WEIGHTS\n")

    n = stage_wave_configs(ctx, "nowcast")

    assert n == 1
    assert (
        ctx.data / f"{ctx.prefixnos}.ocn2wav_weights.nc"
    ).read_bytes() == b"WEIGHTS\n"


def test_stage_wave_configs_wav2ocn_weights_falls_back_to_prefixed_name(
    tmp_path, monkeypatch,
):
    """WAV_WAV2OCN_WEIGHTS unset -> defaults to <prefix>.wav2ocn_weights.nc,
    matching the WAV_OCN2WAV_WEIGHTS fallback convention."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    monkeypatch.delenv("WAV_WAV2OCN_WEIGHTS", raising=False)
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.wav2ocn_weights.nc").write_bytes(b"WEIGHTS\n")

    n = stage_wave_configs(ctx, "nowcast")

    assert n == 1
    assert (
        ctx.data / f"{ctx.prefixnos}.wav2ocn_weights.nc"
    ).read_bytes() == b"WEIGHTS\n"


def test_stage_wave_configs_ww3_shel_falls_back_to_comout(tmp_path, monkeypatch):
    """ww3_shel.nml absent from $FIXofs falls back to the per-cycle
    $COMOUT/$RUN.$cycle.ww3_shel.nml basename."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    ctx = _make_ctx(tmp_path)
    prefix = f"{ctx.run}.{ctx.cycle}"
    (ctx.comout / f"{prefix}.ww3_shel.nml").write_text("comout shel\n")

    n = stage_wave_configs(ctx, "nowcast")

    assert n == 1
    assert (ctx.data / "ww3_shel.nml").read_text() == "comout shel\n"


def test_stage_wave_configs_pdlib_nml_skipped_when_unset(tmp_path, monkeypatch):
    """WAV_PDLIB_NML unset -> only ww3_shel.nml (and whatever else is
    present) is considered; no PDLIB namelist staged, no error."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    monkeypatch.delenv("WAV_PDLIB_NML", raising=False)
    monkeypatch.delenv("WAV_MESH", raising=False)
    monkeypatch.delenv("WAV_OCN2WAV_WEIGHTS", raising=False)
    monkeypatch.delenv("WAV_WAV2OCN_WEIGHTS", raising=False)
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / "ww3_shel.nml").write_text("shel\n")

    n = stage_wave_configs(ctx, "nowcast")

    # ww3_shel.nml + the WAV_MESH/WAV_OCN2WAV_WEIGHTS/WAV_WAV2OCN_WEIGHTS
    # fallback names (prefix.mesh_wav.nc / prefix.ocn2wav_weights.nc /
    # prefix.wav2ocn_weights.nc, all absent here) -- only ww3_shel.nml
    # actually lands.
    assert n == 1
    assert (ctx.data / "ww3_shel.nml").is_file()
    assert not any(ctx.data.glob("*namelists_pdlib*"))


def test_stage_wave_configs_stages_nest_ww3_from_comout_when_present(
    tmp_path, monkeypatch,
):
    """The per-cycle boundary file nest.ww3 stages from $COMOUT only
    (no $FIXofs fallback -- it's a per-cycle artifact, not a static)."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    ctx = _make_ctx(tmp_path)
    prefix = f"{ctx.run}.{ctx.cycle}"
    (ctx.comout / f"{prefix}.nest.ww3").write_bytes(b"NEST\n")

    n = stage_wave_configs(ctx, "nowcast")

    assert (ctx.data / "nest.ww3").read_bytes() == b"NEST\n"
    assert n >= 1


def test_stage_wave_configs_nest_ww3_absent_is_silent(tmp_path, monkeypatch):
    """No nest.ww3 in $COMOUT -> no error, no file created (SECOFS may not
    need an external nesting boundary at all)."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    ctx = _make_ctx(tmp_path)

    stage_wave_configs(ctx, "nowcast")

    assert not (ctx.data / "nest.ww3").exists()


# ---------------------------------------------------------------------------
# stage_wave_restarts (nowcast -> forecast wave restart handoff)
# ---------------------------------------------------------------------------


def _make_wave_restart_ctx(
    tmp_path: Path, *, phase: str = "forecast",
) -> SchismRunContext:
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    comout.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    return SchismRunContext(
        comout=comout,
        data=data,
        phase=phase,
        run="nos.secofs_ufs",
        cycle="t00z",
        time_nowcastend="2026051206",
        wav_rst_out_nowcast="ufs.cpld.ww3.r.2026-05-12-21600.nc",
        med_rst_out_nowcast="ufs.cpld.cpl.r.2026-05-12-21600.nc",
    )


def _seed_wave_restart_archive(ctx: SchismRunContext) -> Path:
    """Populate the archived $COMOUT wave_restart dir with all three
    artifacts, matching what execute._archive_wave_restarts writes."""
    archive_dir = ctx.comout / f"{ctx.run}.{ctx.cycle}.wave_restart"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / ctx.med_rst_out_nowcast).write_bytes(b"mediator")
    (archive_dir / ctx.wav_rst_out_nowcast).write_bytes(b"ww3")
    pointer_name = f"rpointer.cpl.{_dateutils.cmeps_restart_stamp(ctx.time_nowcastend)}"
    (archive_dir / pointer_name).write_text(f"RESTART/{ctx.med_rst_out_nowcast}\n")
    return archive_dir


def test_stage_wave_restarts_noop_without_wav_tasks(tmp_path, monkeypatch):
    """WAV_TASKS unset -> False, nothing staged (primary safety property)."""
    monkeypatch.delenv("WAV_TASKS", raising=False)
    ctx = _make_wave_restart_ctx(tmp_path)
    _seed_wave_restart_archive(ctx)

    assert stage_wave_restarts(ctx, "forecast") is False
    assert not (ctx.data / "RESTART").exists()


def test_stage_wave_restarts_noop_on_nowcast_phase(tmp_path, monkeypatch):
    """Nowcast never stages a wave restart in -- only forecast continues
    from the nowcast leg's own output."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    ctx = _make_wave_restart_ctx(tmp_path, phase="nowcast")
    _seed_wave_restart_archive(ctx)

    assert stage_wave_restarts(ctx, "nowcast") is False
    assert not (ctx.data / "RESTART").exists()


def test_stage_wave_restarts_restores_all_three_artifacts(tmp_path, monkeypatch):
    """All three artifacts land at their exact run-dir paths, with the
    pointer file's content preserved byte-for-byte."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    ctx = _make_wave_restart_ctx(tmp_path, phase="forecast")
    _seed_wave_restart_archive(ctx)

    result = stage_wave_restarts(ctx, "forecast")

    assert result is True
    assert (ctx.data / "RESTART" / ctx.med_rst_out_nowcast).read_bytes() == b"mediator"
    assert (ctx.data / ctx.wav_rst_out_nowcast).read_bytes() == b"ww3"
    pointer = ctx.data / "rpointer.cpl.2026-05-12-21600"
    assert pointer.read_text() == f"RESTART/{ctx.med_rst_out_nowcast}\n"


def test_stage_wave_restarts_cold_start_when_nothing_archived(
    tmp_path, monkeypatch, caplog,
):
    """Nothing archived at all (first-ever wave-coupled cycle) -> False,
    loud WARNING, no exception -- the caller (patch_ufs_configure) falls
    back to start_type=startup."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    ctx = _make_wave_restart_ctx(tmp_path, phase="forecast")

    caplog.set_level(
        "WARNING", logger="nos_workflow.runners.schism_ufs.stage_files",
    )
    result = stage_wave_restarts(ctx, "forecast")

    assert result is False
    assert not (ctx.data / "RESTART").exists()
    assert any("cold start" in r.getMessage() for r in caplog.records)


def test_stage_wave_restarts_partial_archive_raises(tmp_path, monkeypatch):
    """Only SOME of the three artifacts archived (e.g. a failed/partial
    nowcast-leg archive) is NOT a legitimate cold start -- must fail
    loudly rather than silently guessing and letting the model abort at
    full allocation."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    ctx = _make_wave_restart_ctx(tmp_path, phase="forecast")
    archive_dir = ctx.comout / f"{ctx.run}.{ctx.cycle}.wave_restart"
    archive_dir.mkdir(parents=True, exist_ok=True)
    # Only the mediator restart present; pointer + WW3 restart missing.
    (archive_dir / ctx.med_rst_out_nowcast).write_bytes(b"mediator")

    with pytest.raises(FileNotFoundError, match="partial archive"):
        stage_wave_restarts(ctx, "forecast")


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


# ---------------------------------------------------------------------------
# collect_staged_inputs (per-stage input manifest collector)
# ---------------------------------------------------------------------------


def _seed_staged_data(ctx: SchismRunContext, *, ufs: bool) -> None:
    """Drop the canonical run-dir names run_python resolves into $DATA."""
    # hotstart
    (ctx.data / "hotstart.nc").write_bytes(b"hs\n")
    # OBC tar payload
    for name in _OBC_PAYLOAD_NAMES:
        (ctx.data / name).write_bytes(b"obc\n")
    # NWM source/sink
    for name in _NWM_PAYLOAD_NAMES:
        (ctx.data / name).write_text("nwm\n")
    # river.th canonical names (post-rename)
    for _src, dst in _RIVER_RENAMES:
        (ctx.data / dst).write_text("river\n")
    # tidal
    (ctx.data / "bctides.in").write_text("tides\n")
    # SCHISM bare names + partition props
    (ctx.data / "hgrid.gr3").write_text("h\n")
    (ctx.data / "vgrid.in").write_text("v\n")
    (ctx.data / "station.in").write_text("s\n")
    (ctx.data / "shapiro.gr3").write_text("p\n")
    for prop in _SCHISM_PARTITION_FILES:
        (ctx.data / prop).write_text("prop\n")
    if ufs:
        for f in _UFS_CONFIG_FILES + _UFS_AUX_FILES:
            (ctx.data / f).write_text("cfg\n")
        datm = ctx.data / "INPUT"
        datm.mkdir(parents=True, exist_ok=True)
        (datm / "datm_forcing.nc").write_bytes(b"\x89HDF\r\n")
    else:
        sflux = ctx.data / "sflux"
        sflux.mkdir(parents=True, exist_ok=True)
        for i in (1, 2, 3):
            (sflux / f"sflux_air_{i}.nc").write_bytes(b"\x89HDF\r\n")


def test_collect_staged_inputs_ufs_maps_categories(tmp_path):
    """UFS: hotstart/OBC/NWM/river/tidal/FIX/UFS_CONFIG/DATM all surface
    with the cross-repo category/source labels and full $DATA paths."""
    ctx = _make_ctx(tmp_path)
    _seed_staged_data(ctx, ufs=True)

    collector = collect_staged_inputs(ctx, "nowcast", ufs=True)
    keyed = {(g["category"], g["source"]): g for g in collector.groups()}

    assert keyed[("hotstart", "HOTSTART")]["count"] == 1
    assert keyed[("hotstart", "HOTSTART")]["files"] == [
        str(ctx.data / "hotstart.nc")
    ]
    assert keyed[("ocean", "OBC")]["count"] == len(_OBC_PAYLOAD_NAMES)
    assert keyed[("river", "NWM")]["count"] == len(_NWM_PAYLOAD_NAMES)
    assert keyed[("river", "RIVER")]["count"] == len(_RIVER_RENAMES)
    assert keyed[("tidal", "TIDAL")]["count"] == 1
    # FIX: hgrid + vgrid + station + shapiro + 3 partition props = 7
    assert keyed[("static", "FIX")]["count"] == 7
    assert keyed[("static", "UFS_CONFIG")]["count"] == len(
        _UFS_CONFIG_FILES + _UFS_AUX_FILES
    )
    assert keyed[("datm", "DATM")]["count"] == 1
    # All file entries are full $DATA paths (str).
    for g in collector.groups():
        for f in g["files"]:
            assert isinstance(f, str)
            assert f.startswith(str(ctx.data))


def test_collect_staged_inputs_standalone_uses_met_not_datm(tmp_path):
    """Standalone (nws=2): met sflux_*.nc surface as atmospheric/MET; no
    DATM / UFS_CONFIG groups."""
    ctx = _make_ctx(tmp_path)
    _seed_staged_data(ctx, ufs=False)

    collector = collect_staged_inputs(ctx, "nowcast", ufs=False)
    keyed = {(g["category"], g["source"]): g for g in collector.groups()}

    assert keyed[("atmospheric", "MET")]["count"] == 3
    assert ("datm", "DATM") not in keyed
    assert ("static", "UFS_CONFIG") not in keyed


def test_collect_staged_inputs_wave_category_present_when_enabled(
    tmp_path, monkeypatch,
):
    """WAV_TASKS>0: a "wave"/"WW3" group surfaces the staged WW3 files."""
    monkeypatch.setenv("WAV_TASKS", "2606")
    monkeypatch.setenv("WAV_MESH", "secofs_ufs.mesh_wav.nc")
    monkeypatch.setenv("WAV_PDLIB_NML", "secofs_ufs_ww3.namelists_pdlib.nml")
    monkeypatch.setenv("WAV_OCN2WAV_WEIGHTS", "secofs_ufs.ocn2wav_weights.nc")
    monkeypatch.setenv("WAV_WAV2OCN_WEIGHTS", "secofs_ufs.wav2ocn_weights.nc")
    ctx = _make_ctx(tmp_path)
    _seed_staged_data(ctx, ufs=True)
    for name in ("mod_def.ww3", "ww3_shel.nml", "nest.ww3",
                 "secofs_ufs.mesh_wav.nc", "secofs_ufs_ww3.namelists_pdlib.nml",
                 "secofs_ufs.ocn2wav_weights.nc", "secofs_ufs.wav2ocn_weights.nc"):
        (ctx.data / name).write_bytes(b"x\n")

    collector = collect_staged_inputs(ctx, "nowcast", ufs=True)
    keyed = {(g["category"], g["source"]): g for g in collector.groups()}

    assert keyed[("wave", "WW3")]["count"] == 7
    for f in keyed[("wave", "WW3")]["files"]:
        assert f.startswith(str(ctx.data))


def test_collect_staged_inputs_no_wave_category_without_wav_tasks(
    tmp_path, monkeypatch,
):
    """WAV_TASKS unset -> no "wave" group at all (non-wave systems)."""
    monkeypatch.delenv("WAV_TASKS", raising=False)
    ctx = _make_ctx(tmp_path)
    _seed_staged_data(ctx, ufs=True)

    collector = collect_staged_inputs(ctx, "nowcast", ufs=True)
    keyed = {(g["category"], g["source"]): g for g in collector.groups()}

    assert ("wave", "WW3") not in keyed


def test_collect_staged_inputs_absent_files_yield_empty_groups(tmp_path):
    """Nothing staged -> every group present but empty (count 0)."""
    ctx = _make_ctx(tmp_path)

    collector = collect_staged_inputs(ctx, "nowcast", ufs=True)
    for g in collector.groups():
        assert g["count"] == 0
        assert g["files"] == []


def test_run_python_returns_rc_and_collector(tmp_path, monkeypatch):
    """run_python returns a ``(rc, collector)`` tuple. The heavy staging
    sub-steps (configure patches, forcing untars, ESMF mesh) are stubbed
    to no-ops; we pre-seed $DATA with the canonical bare names + tar
    payloads so the collector reports the real staged set."""
    import nos_workflow.runners.schism_ufs.configure as configure_mod
    import nos_workflow.runners.schism_ufs.forcing as forcing_mod
    import nos_workflow.runners.schism_ufs.mesh as mesh_mod
    import nos_workflow.runners.schism_ufs.stage_files as sf

    from nos_workflow.inputs_manifest import InputCollector

    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("UFS_EXEC_NAME", "pschism_WCOSS2")

    ctx = _make_ctx(tmp_path)
    # Pre-seed $DATA exactly as a completed staging pass would leave it.
    _seed_staged_data(ctx, ufs=False)
    # Stub orchestration sub-steps invoked by run_python; collection runs
    # against the pre-seeded $DATA above.
    monkeypatch.setattr(sf, "_stage_standalone_param_nml", lambda c: True)
    monkeypatch.setattr(sf, "stage_executable", lambda c, p: 0)
    monkeypatch.setattr(sf, "stage_schism_bare_names", lambda c, p: 0)
    monkeypatch.setattr(sf, "stage_partition_props", lambda c, p: 0)
    monkeypatch.setattr(sf, "stage_bctides_in", lambda c, p: 0)
    monkeypatch.setattr(sf, "stage_hotstart", lambda c, p: 1)
    monkeypatch.setattr(sf, "fallback_nwm_files_from_fixofs", lambda c, p: 0)
    monkeypatch.setattr(sf, "rename_river_th_files", lambda c, p: 0)
    monkeypatch.setattr(sf, "stage_st_lawrence_river", lambda c, p: 0)
    monkeypatch.setattr(sf, "stage_sflux_inputs_txt", lambda c, p: 0)
    monkeypatch.setattr(sf, "copy_hgrid_to_outputs", lambda c, p: 0)
    monkeypatch.setattr(sf, "stage_forecast_restart_outputs", lambda c, p: 0)
    monkeypatch.setattr(configure_mod, "patch_param_nml", lambda c, p: 0)
    monkeypatch.setattr(forcing_mod, "untar_nwm_source_sink", lambda c, p: 0)
    monkeypatch.setattr(forcing_mod, "untar_obc_forcing", lambda c, p: 0)
    monkeypatch.setattr(forcing_mod, "untar_river_forcing", lambda c, p: 0)
    monkeypatch.setattr(forcing_mod, "untar_met_sflux", lambda c, p: 0)
    monkeypatch.setattr(mesh_mod, "generate_esmf_mesh", lambda *a, **k: None)
    # param.nml already present so the bare-name copy block is a no-op.
    (ctx.data / "param.nml").write_text("&CORE\n/\n")

    result = sf.run_python(ctx, "nowcast")
    assert isinstance(result, tuple)
    rc, collector = result
    assert rc == 0
    assert isinstance(collector, InputCollector)

    keyed = {(g["category"], g["source"]): g for g in collector.groups()}
    # Bare-name statics seeded into $DATA.
    fix_files = keyed[("static", "FIX")]["files"]
    assert any(f.endswith("/hgrid.gr3") for f in fix_files)
    assert any(f.endswith("/vgrid.in") for f in fix_files)
    # hotstart + tidal + OBC tar payload all surface.
    assert keyed[("hotstart", "HOTSTART")]["count"] == 1
    assert keyed[("tidal", "TIDAL")]["count"] == 1
    assert keyed[("ocean", "OBC")]["count"] == len(_OBC_PAYLOAD_NAMES)
    # standalone -> met sflux, not DATM.
    assert keyed[("atmospheric", "MET")]["count"] == 3
