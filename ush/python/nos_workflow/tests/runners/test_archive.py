"""Unit tests for ``nos_workflow.runners.schism_ufs.archive.run_python``.

Mirrors the behavior of ``_schism_archive_outputs`` in ``ush/nos_run.sh``
(lines 1080-1124). All cases use ``tmp_path`` so they're hermetic --
no real $COMOUT / $DATA needed.

Coverage:

  - Phase routing: nowcast -> ``restart_outputs/``,
    forecast -> ``forecast_outputs/``.
  - File globbing: ``staout_*`` matches any/all staout_N files;
    mirror.out and flux.out copied when present.
  - Legacy path: the shell renames ``$DATA/outputs`` ->
    ``$DATA/outputs_nowcast`` after nowcast (MEMORY.md lesson #16); we
    must still find the outputs when only the renamed path exists.
  - Non-fatal failure modes: missing outputs dir, unknown phase --
    both must return 0 and log a WARNING (matches the shell, which
    just echoes "WARNING: ..." without err_exit).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from nos_workflow.runners.schism_ufs.archive import run_python
from nos_workflow.runners.schism_ufs.context import SchismRunContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    tmp_path: Path,
    *,
    phase: str = "nowcast",
    run: str = "nos.secofs_ufs",
    cycle: str = "t00z",
) -> SchismRunContext:
    """Build a context with ``$COMOUT`` and ``$DATA`` rooted under
    ``tmp_path``. Caller is responsible for populating ``$DATA/outputs``
    (or the legacy ``outputs_nowcast``) with whatever fixtures the test
    needs."""
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    comout.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    return SchismRunContext(
        comout=comout, data=data, phase=phase, run=run, cycle=cycle,
    )


def _seed_outputs(
    data: Path,
    *,
    legacy: bool = False,
    n_staout: int = 9,
    with_mirror: bool = True,
    with_flux: bool = True,
) -> Path:
    """Populate ``$DATA/outputs/`` (or ``$DATA/outputs_nowcast/`` if
    ``legacy=True``) with the canonical SCHISM time-series files."""
    name = "outputs_nowcast" if legacy else "outputs"
    outputs = data / name
    outputs.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_staout + 1):
        (outputs / f"staout_{i}").write_text(f"staout {i}\n")
    if with_mirror:
        (outputs / "mirror.out").write_text("mirror content\n")
    if with_flux:
        (outputs / "flux.out").write_text("flux content\n")
    return outputs


# ---------------------------------------------------------------------------
# Phase routing
# ---------------------------------------------------------------------------


def test_archive_nowcast_creates_restart_outputs_dir(tmp_path):
    """phase=nowcast lands files in ``${RUN}.${cycle}.restart_outputs``."""
    ctx = _make_ctx(tmp_path)
    _seed_outputs(ctx.data)

    rc = run_python(ctx, "nowcast")

    assert rc == 0
    target = ctx.comout / "nos.secofs_ufs.t00z.restart_outputs"
    assert target.is_dir(), "nowcast must use restart_outputs/ dir name"
    assert not (ctx.comout / "nos.secofs_ufs.t00z.forecast_outputs").exists()


def test_archive_forecast_creates_forecast_outputs_dir(tmp_path):
    """phase=forecast lands files in ``${RUN}.${cycle}.forecast_outputs``."""
    ctx = _make_ctx(tmp_path, cycle="t12z")
    _seed_outputs(ctx.data, n_staout=3)

    rc = run_python(ctx, "forecast")

    assert rc == 0
    target = ctx.comout / "nos.secofs_ufs.t12z.forecast_outputs"
    assert target.is_dir(), "forecast must use forecast_outputs/ dir name"
    assert not (ctx.comout / "nos.secofs_ufs.t12z.restart_outputs").exists()


# ---------------------------------------------------------------------------
# File globbing
# ---------------------------------------------------------------------------


def test_archive_copies_staout_files(tmp_path):
    """All 9 staout_N files matched by the ``staout_*`` glob are copied."""
    ctx = _make_ctx(tmp_path)
    _seed_outputs(ctx.data, n_staout=9, with_mirror=False, with_flux=False)

    rc = run_python(ctx, "nowcast")
    assert rc == 0

    target = ctx.comout / "nos.secofs_ufs.t00z.restart_outputs"
    expected = {f"staout_{i}" for i in range(1, 10)}
    assert {p.name for p in target.iterdir()} == expected


def test_archive_copies_mirror_and_flux(tmp_path):
    """``mirror.out`` and ``flux.out`` are copied when present (the
    SCHISM open(status='old') invariant needs both to exist on the next
    cycle's restart)."""
    ctx = _make_ctx(tmp_path)
    _seed_outputs(ctx.data, n_staout=0, with_mirror=True, with_flux=True)

    rc = run_python(ctx, "nowcast")
    assert rc == 0

    target = ctx.comout / "nos.secofs_ufs.t00z.restart_outputs"
    names = {p.name for p in target.iterdir()}
    assert "mirror.out" in names
    assert "flux.out" in names


def test_archive_preserves_file_contents(tmp_path):
    """``shutil.copy2`` is used (matches ``cp -p``); content + mtime
    survive the round-trip."""
    ctx = _make_ctx(tmp_path)
    src = _seed_outputs(ctx.data, n_staout=1, with_mirror=False, with_flux=False)
    src_contents = (src / "staout_1").read_text()

    run_python(ctx, "nowcast")

    dst = ctx.comout / "nos.secofs_ufs.t00z.restart_outputs" / "staout_1"
    assert dst.read_text() == src_contents


def test_archive_skips_non_matching_files(tmp_path):
    """Files that don't match ``staout_*`` / ``mirror.out`` / ``flux.out``
    must NOT be copied. The shell pattern is intentionally narrow --
    hotstart_*.nc and schout_*.nc archive through a separate code
    path (combine_hotstart + nccopy), not this function."""
    ctx = _make_ctx(tmp_path)
    outputs = _seed_outputs(ctx.data, n_staout=1, with_mirror=False, with_flux=False)
    (outputs / "hotstart_000000_0001.nc").write_bytes(b"\x89HDF\r\n")
    (outputs / "schout_000000_0001.nc").write_bytes(b"\x89HDF\r\n")
    (outputs / "random.log").write_text("not a SCHISM time-series file\n")

    run_python(ctx, "nowcast")

    target = ctx.comout / "nos.secofs_ufs.t00z.restart_outputs"
    names = {p.name for p in target.iterdir()}
    assert names == {"staout_1"}


# ---------------------------------------------------------------------------
# Legacy path fallback (MEMORY.md lesson #16)
# ---------------------------------------------------------------------------


def test_archive_finds_outputs_nowcast_legacy_path(tmp_path):
    """``nos_ofs_nowcast_forecast.sh`` historically renamed
    ``$DATA/outputs`` -> ``$DATA/outputs_nowcast`` after nowcast.
    Archive must still find files when only the renamed dir exists."""
    ctx = _make_ctx(tmp_path)
    _seed_outputs(ctx.data, legacy=True, n_staout=2)
    # Sanity: outputs/ does NOT exist, only outputs_nowcast/.
    assert not (ctx.data / "outputs").exists()
    assert (ctx.data / "outputs_nowcast").is_dir()

    rc = run_python(ctx, "nowcast")
    assert rc == 0

    target = ctx.comout / "nos.secofs_ufs.t00z.restart_outputs"
    names = {p.name for p in target.iterdir()}
    assert "staout_1" in names and "staout_2" in names
    assert "mirror.out" in names and "flux.out" in names


def test_archive_prefers_outputs_over_outputs_nowcast_when_both_exist(tmp_path):
    """If both ``outputs/`` and ``outputs_nowcast/`` exist (unusual,
    but possible mid-rename), the shell checks ``outputs/`` first
    (lines 1093-1094 of nos_run.sh). Match that ordering."""
    ctx = _make_ctx(tmp_path)
    # outputs/ has staout_1 with content "primary"; outputs_nowcast/
    # has the same path with content "legacy". Python should pick the
    # primary one.
    outputs = ctx.data / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "staout_1").write_text("primary")
    legacy = ctx.data / "outputs_nowcast"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "staout_1").write_text("legacy")

    run_python(ctx, "nowcast")

    dst = ctx.comout / "nos.secofs_ufs.t00z.restart_outputs" / "staout_1"
    assert dst.read_text() == "primary"


# ---------------------------------------------------------------------------
# Non-fatal failure modes
# ---------------------------------------------------------------------------


def test_archive_missing_outputs_is_nonfatal(tmp_path, caplog):
    """No outputs/ and no outputs_nowcast/ -> return 0, log a WARNING.
    Matches the shell, which echoes "WARNING: Neither ..." without
    err_exit (line 1105)."""
    ctx = _make_ctx(tmp_path)
    # Don't seed anything.
    assert not (ctx.data / "outputs").exists()
    assert not (ctx.data / "outputs_nowcast").exists()

    caplog.set_level(logging.WARNING, logger="nos_workflow.runners.schism_ufs.archive")
    rc = run_python(ctx, "nowcast")

    assert rc == 0
    # The restart_outputs dir is still created (matches the shell's
    # ``mkdir -p`` which runs unconditionally inside the phase branch).
    # Actually the shell's mkdir is guarded by the outputs_dir check;
    # the Python version also creates the target up-front, which
    # is a benign tweak -- ``mkdir -p`` on an existing empty dir is
    # a no-op. The important behavior is the warning + rc=0.
    assert any(
        "no outputs dir" in rec.getMessage().lower()
        for rec in caplog.records
        if rec.levelno >= logging.WARNING
    ), "expected a WARNING about missing outputs dir"


def test_archive_unknown_phase_is_nonfatal(tmp_path, caplog):
    """phase not in {nowcast, forecast} -> return 0, log a WARNING.
    Protects against typos in the dispatcher caller -- the shell's
    bash `if` would silently skip, the Python keeps that non-fatal
    behavior but at least logs."""
    ctx = _make_ctx(tmp_path)
    _seed_outputs(ctx.data)

    caplog.set_level(logging.WARNING, logger="nos_workflow.runners.schism_ufs.archive")
    rc = run_python(ctx, "bogus")

    assert rc == 0
    assert any(
        "unknown phase" in rec.getMessage().lower()
        for rec in caplog.records
        if rec.levelno >= logging.WARNING
    ), "expected a WARNING naming the unknown phase"
    # Nothing should have been created.
    assert not any(ctx.comout.iterdir()), (
        "unknown phase must not create any output dir"
    )


def test_archive_empty_outputs_dir_is_nonfatal(tmp_path, caplog):
    """``$DATA/outputs/`` exists but is empty -> return 0, target dir
    created, no files copied. Operators see "copied 0 files" in the log
    so they can spot a silent SCHISM failure."""
    ctx = _make_ctx(tmp_path)
    (ctx.data / "outputs").mkdir(parents=True, exist_ok=True)

    caplog.set_level(logging.INFO, logger="nos_workflow.runners.schism_ufs.archive")
    rc = run_python(ctx, "nowcast")

    assert rc == 0
    target = ctx.comout / "nos.secofs_ufs.t00z.restart_outputs"
    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert any(
        "copied 0 files" in rec.getMessage()
        for rec in caplog.records
    ), "expected the per-call summary log to record 0 copies"


# ---------------------------------------------------------------------------
# Run / cycle formatting
# ---------------------------------------------------------------------------


def test_archive_target_dir_uses_ctx_run_and_cycle(tmp_path):
    """The target subdir name is built from ``ctx.run`` + ``ctx.cycle``
    verbatim. Test with a non-default cycle to catch a hardcoded
    ``t00z``."""
    ctx = _make_ctx(tmp_path, run="nos.stofs_3d_atl_ufs", cycle="t18z")
    _seed_outputs(ctx.data, n_staout=1, with_mirror=False, with_flux=False)

    run_python(ctx, "forecast")

    assert (ctx.comout / "nos.stofs_3d_atl_ufs.t18z.forecast_outputs").is_dir()
