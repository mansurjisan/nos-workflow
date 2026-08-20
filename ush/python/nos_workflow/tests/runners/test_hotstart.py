"""Unit tests for ``nos_workflow.runners.schism_ufs.hotstart``.

Pins the behavior of the Python port of ``_schism_find_hotstart`` (lines
298-394 of ``ush/nos_run.sh``). All cases use ``tmp_path`` + monkeypatch
to build a synthetic ``$COMOUTroot`` tree -- no real WCOSS2 fixture
needed.

Coverage:

  - Walk-back semantics: locates a restart at 6h, 24h, 48h offset; honors
    BACK_SEARCH window; rejects partial / zero-byte files.
  - Cold-start fallback: empty $COMOUTroot returns ``cold_start="T"``
    with ``ini_file=$FIXofs/${prefix}.init.nc`` and ``rst_file=None``.
  - Stale-restart rejection: if the located restart is >= 48 hours old,
    the function falls back to the canonical cold-start init file
    (matches the shell's "too stale" branch on lines 331-335).
  - Decimal-day arithmetic: ``dstart_forecast = nh_nowcast / 24.0``.
  - Persistence: ``write_time_files`` creates ``time_hotstart.${cycle}``
    et al. with trailing-newline payload (shell ``echo`` semantics).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

from nos_workflow.env import NCOEnv
from nos_workflow.runners.schism_ufs.hotstart import (
    DEFAULT_BACK_SEARCH,
    STALE_RESTART_HOURS,
    HotstartResult,
    find_hotstart,
    write_time_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pdy: str = "20260512",
    cyc: str = "00",
    ofs: str = "secofs_ufs",
    run: Optional[str] = None,
    prefixnos: Optional[str] = None,
) -> NCOEnv:
    """Build an :class:`NCOEnv` rooted under ``tmp_path``.

    ``NCOEnv.from_env`` defaults ``COMOUTroot`` to ``comout.parent``,
    which equals ``tmp_path`` here -- so tests can drop restart files
    directly into ``tmp_path/{run}.YYYYMMDD/`` and the walk-back will
    find them via the default lookup path.

    ``run`` / ``prefixnos`` default to ``nos.{ofs}`` each (matching every
    non-wave system, where they coincide); pass them explicitly to build
    a fixture where they differ.
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
    monkeypatch.setenv("PREFIXNOS", prefixnos or f"nos.{ofs}")
    return NCOEnv.from_env(ofs=ofs)


def _seed_restart(
    comoutroot: Path,
    run: str,
    prefix: str,
    yyyymmddhh: str,
    *,
    content: bytes = b"\x89HDF\r\nfake restart\n",
) -> Path:
    """Drop a fake (nonzero-size) restart file into the expected
    ``{run}.YYYYMMDD/{prefix}.tHHz.YYYYMMDD.rst.nowcast.nc`` location.

    Returns the full path so tests can assert ``rst_file`` matches.
    """
    yyyymmdd = yyyymmddhh[:8]
    hh = yyyymmddhh[8:10]
    rst_dir = comoutroot / f"{run}.{yyyymmdd}"
    rst_dir.mkdir(parents=True, exist_ok=True)
    rst_path = rst_dir / f"{prefix}.t{hh}z.{yyyymmdd}.rst.nowcast.nc"
    rst_path.write_bytes(content)
    return rst_path


# ---------------------------------------------------------------------------
# Walk-back semantics: locate restart at various offsets
# ---------------------------------------------------------------------------


def test_find_hotstart_locates_restart_6h_back(tmp_path, monkeypatch):
    """Restart at 6h before time_nowcastend should be found and the
    result should carry ``cold_start="F"``."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    rst_path = _seed_restart(
        tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051118",
    )

    result = find_hotstart(env, phase="nowcast")

    assert result.cold_start == "F"
    assert result.rst_file == rst_path
    assert result.base_date == "2026051118"
    assert result.time_hotstart == "2026051118"


def test_find_hotstart_walkback_keys_restart_filename_on_run(
    tmp_path, monkeypatch,
):
    """The walk-back search must key the restart FILENAME on $RUN, not
    $PREFIXNOS, matching what execute._archive_restart actually writes.

    Regression pin for the wave-variant bug: a system with $RUN !=
    $PREFIXNOS (e.g. secofs_ufs_ww3, prefix=secofs_ufs) only archives
    rst.nowcast.nc under the $RUN name. Seeding the restart under $RUN
    only (never $PREFIXNOS) means this test can only pass if the
    walk-back searches by $RUN.
    """
    env = _make_env(
        tmp_path, monkeypatch, pdy="20260512", cyc="00",
        ofs="secofs_ufs_ww3", run="secofs_ufs_ww3", prefixnos="secofs_ufs",
    )
    rst_path = _seed_restart(
        tmp_path, "secofs_ufs_ww3", "secofs_ufs_ww3", "2026051118",
    )

    result = find_hotstart(env, phase="nowcast")

    assert result.cold_start == "F"
    assert result.rst_file == rst_path


def test_find_hotstart_locates_restart_24h_back(tmp_path, monkeypatch):
    """Walk-back must continue past 6h until a candidate is found."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    rst_path = _seed_restart(
        tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051100",
    )

    result = find_hotstart(env, phase="nowcast")

    assert result.cold_start == "F"
    assert result.rst_file == rst_path
    assert result.base_date == "2026051100"
    assert result.nh_nowcast == 24


def test_find_hotstart_prefers_most_recent_restart(tmp_path, monkeypatch):
    """When two restarts exist (e.g. 6h + 24h back), the more recent one
    wins -- the walk-back starts at the anchor and steps backward, so it
    encounters the closer-in-time restart first."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    # Older restart (24h back)
    _seed_restart(tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051100")
    # Newer restart (6h back) -- should be the one returned
    newer = _seed_restart(
        tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051118",
    )

    result = find_hotstart(env, phase="nowcast")

    assert result.rst_file == newer
    assert result.base_date == "2026051118"


# ---------------------------------------------------------------------------
# Cold-start fallback
# ---------------------------------------------------------------------------


def test_find_hotstart_no_restart_in_window_returns_cold_start(
        tmp_path, monkeypatch):
    """Empty $COMOUTroot -> cold_start="T", rst_file=None, ini_file
    points at $FIXofs/${prefix}.init.nc."""
    env = _make_env(tmp_path, monkeypatch)

    result = find_hotstart(env, phase="nowcast")

    assert result.cold_start == "T"
    assert result.rst_file is None
    assert result.ini_file == env.fixofs / "nos.secofs_ufs.init.nc"


def test_find_hotstart_cold_start_base_date_is_cycle_minus_nowcast(
        tmp_path, monkeypatch):
    """Cold-start fallback anchors BASE_DATE to cycle - LEN_NOWCAST so the
    Python port agrees with the nos-utils prep orchestrator (which writes
    cycle - nowcast_hours to $COMOUT/time_hotstart.${cycle}).

    Note: this replaces the older cycle - 48h anchor that was inherited
    from nos_run.sh:334 but was effectively dead code (the shell err_exits
    on cold start at line 325 before reaching that branch)."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")

    # Default LEN_NOWCAST is 6 -> cycle 20260512 00z - 6h = 20260511 18z
    result = find_hotstart(env, phase="nowcast", len_nowcast=6)

    assert result.base_date == "2026051118"
    assert result.time_hotstart == "2026051118"
    assert result.tide_start == "2026051118"


def test_find_hotstart_cold_start_honors_custom_len_nowcast(
        tmp_path, monkeypatch):
    """LEN_NOWCAST=12 -> base_date = cycle - 12h (regression check that the
    cold-start anchor uses the passed-in len_nowcast, not a hardcoded 6)."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")

    result = find_hotstart(env, phase="nowcast", len_nowcast=12)

    # 12h before 20260512 00z is 20260511 12z
    assert result.base_date == "2026051112"
    assert result.time_hotstart == "2026051112"


# ---------------------------------------------------------------------------
# BACK_SEARCH window
# ---------------------------------------------------------------------------


def test_find_hotstart_respects_custom_back_search(tmp_path, monkeypatch):
    """With back_search=12, a restart at 24h back is OUTSIDE the window
    and should NOT be found -> cold-start fallback."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_restart(tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051100")

    result = find_hotstart(env, phase="nowcast", back_search_hours=12)

    assert result.cold_start == "T", "24h-old restart should be outside 12h window"
    assert result.rst_file is None


def test_find_hotstart_default_back_search_is_49h(tmp_path, monkeypatch):
    """DEFAULT_BACK_SEARCH constant is 49 (matches BACK_SEARCH=49 in the
    shell). Confirm a restart at 47h back is reachable."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    # 47h before 2026-05-12 00z is 2026-05-10 01z
    rst_path = _seed_restart(
        tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051001",
    )

    result = find_hotstart(env, phase="nowcast")

    assert DEFAULT_BACK_SEARCH == 49
    assert result.rst_file == rst_path
    # 47h-old restart is below the >= 48 stale threshold, so warmstart.
    assert result.cold_start == "F"


# ---------------------------------------------------------------------------
# Stale-restart rejection (>= 48 hours old triggers cold-start fallback)
# ---------------------------------------------------------------------------


def test_find_hotstart_stale_restart_falls_back_to_cold_start(
        tmp_path, monkeypatch):
    """Restart exactly 48h old hits the stale threshold -> the function
    falls back to FIXofs/init.nc with cold_start='T'."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    # 48h before 2026-05-12 00z is 2026-05-10 00z -- inside the BACK_SEARCH=49
    # window but at the stale threshold (>=48).
    _seed_restart(tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051000")

    result = find_hotstart(env, phase="nowcast")

    assert STALE_RESTART_HOURS == 48
    assert result.cold_start == "T"
    assert result.rst_file is None
    assert result.ini_file == env.fixofs / "nos.secofs_ufs.init.nc"


# ---------------------------------------------------------------------------
# Partial-file rejection (zero-byte files)
# ---------------------------------------------------------------------------


def test_find_hotstart_skips_zero_byte_restart(tmp_path, monkeypatch):
    """Shell uses ``[ -s "$RST_FILE" ]`` which requires NONZERO size --
    a zero-byte file should be skipped just like a missing file."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    # Zero-byte restart at 6h back -- should be skipped
    _seed_restart(
        tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051118",
        content=b"",
    )
    # Usable restart at 12h back -- should be picked
    rst_path = _seed_restart(
        tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051112",
    )

    result = find_hotstart(env, phase="nowcast")

    assert result.rst_file == rst_path


# ---------------------------------------------------------------------------
# Derived field math
# ---------------------------------------------------------------------------


def test_find_hotstart_nstep_derived_from_delt_model(tmp_path, monkeypatch):
    """NSTEP_NOWCAST = NH_NOWCAST * 3600 / DELT_MODEL."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_restart(tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051118")

    result = find_hotstart(
        env, phase="nowcast",
        len_nowcast=6, len_forecast=48, delt_model=120.0,
    )

    # 6 hr * 3600 / 120 = 180 steps
    assert result.nh_nowcast == 6
    assert result.nstep_nowcast == 180
    assert result.ntimes_nowcast == 180
    # 48 hr / 120s timestep => NSTEP_FORECAST counted from BASE_DATE
    # NH_FORECAST = NHOUR(time_forecastend, base_date) = 6 + 48 = 54
    # NSTEP_FORECAST = 54 * 3600 / 120 = 1620
    assert result.nh_forecast == 54
    assert result.nstep_forecast == 1620


def test_find_hotstart_dstart_forecast_in_decimal_days(tmp_path, monkeypatch):
    """DSTART_FORECAST = NH_NOWCAST / 24.0 (DAY0=0 from synthetic
    time_initial.dat in the shell)."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_restart(tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051118")

    result = find_hotstart(env, phase="nowcast", len_nowcast=6)

    assert result.dstart_nowcast == 0.0
    assert result.dstart_forecast == pytest.approx(6 / 24.0)


def test_find_hotstart_nrrec_is_zero_for_warmstart(tmp_path, monkeypatch):
    """The shell sets NRREC=0 because the synthetic time_initial.dat
    always has NTIMES=0 (line 347: `echo $BASE_DATE 0 0.0 0.0d0`)."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    _seed_restart(tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051118")

    result = find_hotstart(env, phase="nowcast")

    assert result.nrrec == 0


# ---------------------------------------------------------------------------
# write_time_files persistence
# ---------------------------------------------------------------------------


def test_write_time_files_creates_expected_files(tmp_path):
    """All four ``time_*.${cycle}`` files exist with the right payload."""
    comout = tmp_path / "comout"
    comout.mkdir()
    result = HotstartResult(
        rst_file=None,
        ini_file=None,
        base_date="2026051118",
        time_hotstart="2026051118",
        time_nowcastend="2026051200",
        time_forecastend="2026051400",
        tide_start="2026051118",
        cold_start="F",
        dstart_nowcast=0.0,
        dstart_forecast=0.25,
        nh_nowcast=6,
        nh_forecast=54,
        nstep_nowcast=180,
        nstep_forecast=1620,
        ntimes_nowcast=180,
        ntimes_forecast=1620,
        ntimes=1620,
        nrrec=0,
    )

    write_time_files(result, comout, cycle="t00z")

    assert (comout / "time_hotstart.t00z").read_text() == "2026051118\n"
    assert (comout / "time_nowcastend.t00z").read_text() == "2026051200\n"
    assert (comout / "time_forecastend.t00z").read_text() == "2026051400\n"
    assert (comout / "base_date.t00z").read_text() == "2026051118\n"


def test_write_time_files_creates_comout_if_missing(tmp_path):
    """``write_time_files`` should ``mkdir -p`` $COMOUT (matches shell
    semantics where the J-job already created COMOUT, but defensive
    creation here keeps unit tests self-contained)."""
    comout = tmp_path / "fresh_comout" / "20260512"  # doesn't exist
    result = HotstartResult(
        rst_file=None, ini_file=None,
        base_date="2026051000", time_hotstart="2026051000",
        time_nowcastend="2026051200", time_forecastend="2026051400",
        tide_start="2026051000", cold_start="T",
        dstart_nowcast=0.0, dstart_forecast=2.0,
        nh_nowcast=48, nh_forecast=96,
        nstep_nowcast=1440, nstep_forecast=2880,
        ntimes_nowcast=1440, ntimes_forecast=2880,
        ntimes=2880, nrrec=0,
    )

    write_time_files(result, comout, cycle="t00z")

    assert (comout / "time_hotstart.t00z").is_file()


# ---------------------------------------------------------------------------
# HotstartResult schema invariant
# ---------------------------------------------------------------------------


def test_hotstart_result_is_frozen():
    """HotstartResult must be ``@dataclass(frozen=True)`` -- caller
    mutations are a bug, all fields baked at construction time."""
    from dataclasses import FrozenInstanceError

    result = HotstartResult(
        rst_file=None, ini_file=None,
        base_date="2026051000", time_hotstart="2026051000",
        time_nowcastend="2026051200", time_forecastend="2026051400",
        tide_start="2026051000", cold_start="T",
        dstart_nowcast=0.0, dstart_forecast=2.0,
        nh_nowcast=48, nh_forecast=96,
        nstep_nowcast=1440, nstep_forecast=2880,
        ntimes_nowcast=1440, ntimes_forecast=2880,
        ntimes=2880, nrrec=0,
    )

    with pytest.raises(FrozenInstanceError):
        result.cold_start = "F"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BACK_SEARCH env var override
# ---------------------------------------------------------------------------


def test_find_hotstart_reads_back_search_from_env(tmp_path, monkeypatch):
    """BACK_SEARCH env var overrides the DEFAULT_BACK_SEARCH constant
    when no explicit ``back_search_hours`` is passed."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    monkeypatch.setenv("BACK_SEARCH", "6")
    # Restart at 24h back -- outside 6h window
    _seed_restart(tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051100")

    result = find_hotstart(env, phase="nowcast")

    assert result.cold_start == "T"


# ---------------------------------------------------------------------------
# Explicit time_nowcastend override
# ---------------------------------------------------------------------------


def test_find_hotstart_honors_time_nowcastend_arg(tmp_path, monkeypatch):
    """Explicit ``time_nowcastend`` overrides both the env var and the
    PDY||cyc default. Useful when prep is testing forecast restarts."""
    env = _make_env(tmp_path, monkeypatch, pdy="20260512", cyc="00")
    # Seed restart at 2026-05-12 18z -- only reachable if the anchor is
    # later than 2026-05-12 18z.
    rst_path = _seed_restart(
        tmp_path, "nos.secofs_ufs", "nos.secofs_ufs", "2026051218",
    )

    # Default anchor (2026051200) cannot reach this restart (it's in the
    # FUTURE relative to the default anchor). The walk-back only goes
    # backward in time, so we override the anchor.
    result = find_hotstart(
        env, phase="nowcast",
        time_nowcastend="2026051300",  # 6h after the restart
    )

    assert result.rst_file == rst_path
    assert result.base_date == "2026051218"
