"""Python port of ``_schism_find_hotstart`` from ``ush/nos_run.sh``.

Walks backwards in time from ``time_nowcastend`` for up to
``back_search_hours`` (default 49) looking for a prior cycle's restart
file at::

    $COMOUTroot/${RUN}.YYYYMMDD/${PREFIXNOS}.tHHz.YYYYMMDD.rst.nowcast.nc

The shell function starts the walk at ``$NDATE -1 $time_nowcastend``
(one hour before the anchor) and steps an hour back each iteration
until the candidate falls on or beyond
``$NDATE -BACK_SEARCH $time_nowcastend``. If a file is found within
the window, a warmstart :class:`HotstartResult` is returned carrying
``RST_FILE``, ``INI_FILE``, ``BASE_DATE``, ``time_hotstart`` and the
derived NSTEP/NTIMES/DSTART values.

Edge case the shell handles (lines 331-335 of ``nos_run.sh``): if the
found restart is >= 48 hours old (i.e. ``NHOUR(time_nowcastend,
BASE_DATE) >= 48``), the prior cycle is considered too stale; the
function falls back to the canonical cold-start init file
(``$FIXofs/${PREFIXNOS}.init.nc``), sets ``COLD_START="T"``, and
re-anchors ``BASE_DATE = time_nowcastend - 48h``.

If the walk-back exits the BACK_SEARCH window without finding any
restart, the shell ``err_exit``s with "NO VALID RESTART FILE
AVAILABLE". The Python port mirrors that semantic by setting
``cold_start="T"`` and returning a cold-start result; the dispatcher
(the prep stage) decides whether to raise based on operator policy
(``KEEPDATA``/strict mode etc.).

The companion helper :func:`write_time_files` writes
``time_hotstart.${cycle}`` (and friends) text files into ``$COMOUT``
so downstream nowcast/forecast PBS jobs can recover the same anchor
values without re-running the COM walk-back.

Shell counterpart: lines 298-394 of ``ush/nos_run.sh``.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from . import _dateutils

if TYPE_CHECKING:
    from ...env import NCOEnv

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default back-search window (hours). Matches BACK_SEARCH=49 in the shell.
#
# 49 hours is one hour past the canonical 48-hour spin-up window; finding
# a restart exactly at 48 hours is rejected by the "too stale" check on
# lines 331-335 of nos_run.sh, so the effective walk-back lands at most
# at 47 hours.
# ---------------------------------------------------------------------------
DEFAULT_BACK_SEARCH = 49

# Threshold for "restart is too stale to use" -- when the candidate is
# this many hours or more before time_nowcastend, fall back to the
# canonical cold-start init file. Matches the >= 48 check on line 331.
STALE_RESTART_HOURS = 48


@dataclass(frozen=True)
class HotstartResult:
    """Result of walking back through ``$COMOUTroot`` for a usable restart.

    Mirrors the fields the shell ``_schism_find_hotstart`` exports to its
    caller (``BASE_DATE``, ``INI_FILE``, ``RST_FILE``, ``COLD_START``,
    ``time_hotstart``, ``NRREC``, ``NTIMES``, ``DSTART_*``,
    ``NSTEP_*``, ``NTIMES_*``, ``NH_*``, ``TIDE_START``).

    String fields stay as strings to preserve YYYYMMDDHH zero-padding;
    numeric anchors keep their typed forms because they're consumed
    by typed callers (the :class:`SchismRunContext` constructor).
    """

    # Restart file the walk-back found (None if the search hit the
    # BACK_SEARCH window without finding any candidate).
    rst_file: Optional[Path]
    # Where the restart should be staged in $DATA (i.e. the
    # INI_FILE_ROMS path: $DATA/${PREFIXNOS}.${cycle}.${PDY}.init.nowcast.nc).
    ini_file: Optional[Path]

    # YYYYMMDDHH strings for model clock + tidal forcing reference.
    base_date: str
    time_hotstart: str
    time_nowcastend: str
    time_forecastend: str
    tide_start: str

    # "T" if no restart found OR the restart was too stale (>= 48 hr old);
    # "F" if a usable warmstart was located.
    cold_start: str

    # Decimal-days offsets from BASE_DATE.
    dstart_nowcast: float
    dstart_forecast: float

    # Integer-hour offsets from BASE_DATE.
    nh_nowcast: int
    nh_forecast: int

    # Model-step counts (NH_* * 3600 / DELT_MODEL).
    nstep_nowcast: int
    nstep_forecast: int
    ntimes_nowcast: int
    ntimes_forecast: int
    ntimes: int

    # NRREC=0 if NTIMES==0 (cold or stub time_initial.dat); -1 otherwise.
    # The synthetic time_initial.dat the shell emits always has NTIMES=0
    # so the typical value here is 0.
    nrrec: int


def _candidate_restart_path(
    comoutroot: Path,
    run: str,
    prefix: str,
    candidate_time: str,
) -> Path:
    """Build the candidate restart path for a given YYYYMMDDHH anchor.

    Mirrors the shell formula on lines 308 + 320 of ``nos_run.sh``::

        $COMOUTroot/${RUN}.YYYYMMDD/${PREFIXNOS}.tHHz.YYYYMMDD.rst.nowcast.nc

    Note the YYYYMMDD appears twice (once in the directory name, once
    in the filename) -- intentional, not a typo. PR 6 preserves that
    so the parity drill matches byte-for-byte.
    """
    yyyymmdd = candidate_time[:8]
    hh = candidate_time[8:10]
    return (
        comoutroot
        / f"{run}.{yyyymmdd}"
        / f"{prefix}.t{hh}z.{yyyymmdd}.rst.nowcast.nc"
    )


def _is_usable_restart(path: Path) -> bool:
    """Match the shell's ``[ -s "$RST_FILE" ]`` semantics: file exists
    AND has nonzero size."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        # Symlinks pointing at removed targets etc. -- treat as unusable.
        return False


def find_hotstart(
    env: "NCOEnv",
    phase: str = "nowcast",
    back_search_hours: Optional[int] = None,
    len_nowcast: Optional[int] = None,
    len_forecast: Optional[int] = None,
    delt_model: Optional[float] = None,
    time_nowcastend: Optional[str] = None,
) -> HotstartResult:
    """Walk back through ``$COMOUTroot`` looking for a usable restart file.

    Args:
        env: :class:`NCOEnv` with ``run``, ``pdy``, ``cyc``, ``comoutroot``,
            ``data``, ``fixofs`` populated.
        phase: ``"nowcast"`` or ``"forecast"`` -- the shell function is
            only invoked from prep, so phase is informational here.
        back_search_hours: Override the BACK_SEARCH window. Defaults to
            the ``BACK_SEARCH`` env var if set (matches the shell's
            ``BACK_SEARCH=49`` local default).
        len_nowcast: Override the LEN_NOWCAST env var (hours).
        len_forecast: Override the LEN_FORECAST env var (hours).
        delt_model: Override the DELT_MODEL env var (seconds).
        time_nowcastend: Override the ``time_nowcastend`` anchor (defaults
            to ``$time_nowcastend`` from the env if set, else ``PDY||cyc``).

    Returns:
        :class:`HotstartResult` with ``cold_start="F"`` if a usable
        restart was located within the back-search window (and is no
        more than 48 hours stale), else ``cold_start="T"``.

    Side effects: none. Use :func:`write_time_files` to persist the
    anchor strings to ``$COMOUT`` for downstream PBS jobs.
    """
    # ---- Resolve overrides from env --------------------------------------
    if back_search_hours is None:
        try:
            back_search_hours = int(os.environ.get("BACK_SEARCH", DEFAULT_BACK_SEARCH))
        except (TypeError, ValueError):
            back_search_hours = DEFAULT_BACK_SEARCH

    if len_nowcast is None:
        len_nowcast = int(os.environ.get("LEN_NOWCAST", "6"))
    if len_forecast is None:
        len_forecast = int(os.environ.get("LEN_FORECAST", "48"))
    if delt_model is None:
        try:
            delt_model = float(os.environ.get("DELT_MODEL", "120"))
        except (TypeError, ValueError):
            delt_model = 120.0

    run = env.run
    prefix = os.environ.get("PREFIXNOS") or f"nos.{env.ofs}"
    comoutroot = env.comoutroot
    fixofs = env.fixofs
    data = env.data
    cycle = env.cycle

    # Anchor point: end of nowcast (== PDY||cyc unless overridden).
    if time_nowcastend is None:
        time_nowcastend = os.environ.get("time_nowcastend") or f"{env.pdy}{env.cyc}"

    # ---- Walk-back loop --------------------------------------------------
    #
    # The shell starts at -1h (line 301: CURRENTTIME=$NDATE -1 $time_nowcastend)
    # then decrements by one hour per loop iteration. Stop when CURRENTTIME
    # passes the BACK_SEARCH window (line 312: CURRENTTIME <= NDATE -49).
    # ----------------------------------------------------------------------
    found_anchor: Optional[str] = None
    found_path: Optional[Path] = None
    earliest_anchor = _dateutils.ndate(-back_search_hours, time_nowcastend)

    for hours_back in range(1, back_search_hours + 1):
        candidate_anchor = _dateutils.ndate(-hours_back, time_nowcastend)
        # The shell does `if CURRENTTIME <= NDATE -BACK_SEARCH break` -- in
        # string compare YYYYMMDDHH this matches integer ordering. Since we
        # iterate up to back_search_hours inclusive, this loop covers
        # exactly the same window as the shell.
        if candidate_anchor < earliest_anchor:
            break
        candidate_path = _candidate_restart_path(
            comoutroot, run, prefix, candidate_anchor,
        )
        if _is_usable_restart(candidate_path):
            found_anchor = candidate_anchor
            found_path = candidate_path
            logger.info(
                "find_hotstart: located restart at %s (offset=%dh from %s)",
                candidate_path, hours_back, time_nowcastend,
            )
            break

    # ---- Build common derived fields -------------------------------------
    time_forecastend = _dateutils.ndate(len_forecast, time_nowcastend)
    delt_int = int(delt_model)
    if delt_int <= 0:
        delt_int = 1  # defensive; shell uses ${DELT_MODEL%.*} (truncated int)

    # ---- Cold-start branch (no restart found in window) ------------------
    if found_anchor is None or found_path is None:
        logger.warning(
            "find_hotstart: no usable restart in %dh back-search window from %s; "
            "falling back to cold start (FIXofs/%s.init.nc)",
            back_search_hours, time_nowcastend, prefix,
        )
        # Cold-start anchor: 48h before time_nowcastend (matches the
        # "too stale" branch on lines 333-334 of nos_run.sh; the shell
        # err_exit's here in prep but the Python port returns the
        # cold-start result so the dispatcher can choose policy).
        base_date = _dateutils.ndate(-STALE_RESTART_HOURS, time_nowcastend)
        ini_file = fixofs / f"{prefix}.init.nc"
        nh_nowcast = _dateutils.nhour(time_nowcastend, base_date)
        nh_forecast = _dateutils.nhour(time_forecastend, base_date)
        nstep_nowcast = int(nh_nowcast * 3600 / delt_int)
        nstep_forecast = int(nh_forecast * 3600 / delt_int)
        return HotstartResult(
            rst_file=None,
            ini_file=ini_file,
            base_date=base_date,
            time_hotstart=base_date,
            time_nowcastend=time_nowcastend,
            time_forecastend=time_forecastend,
            tide_start=base_date,
            cold_start="T",
            dstart_nowcast=0.0,
            dstart_forecast=nh_nowcast / 24.0,
            nh_nowcast=nh_nowcast,
            nh_forecast=nh_forecast,
            nstep_nowcast=nstep_nowcast,
            nstep_forecast=nstep_forecast,
            ntimes_nowcast=nstep_nowcast,
            ntimes_forecast=nstep_forecast,
            ntimes=max(nstep_nowcast, nstep_forecast),
            nrrec=0,
        )

    # ---- Warmstart branch (restart located in window) --------------------
    base_date = found_anchor
    rst_file = found_path
    ini_file_root = data / f"{prefix}.{cycle}.{env.pdy}.init.nowcast.nc"

    # The shell "too stale" check (lines 331-335): if the restart we
    # just found is >= 48 hours behind time_nowcastend, treat it as a
    # cold start using the canonical init file from $FIXofs.
    nh_nowcast = _dateutils.nhour(time_nowcastend, base_date)
    cold_start = "F"
    if nh_nowcast >= STALE_RESTART_HOURS:
        logger.warning(
            "find_hotstart: restart at %s is %dh old (>= %dh stale threshold); "
            "falling back to cold start",
            rst_file, nh_nowcast, STALE_RESTART_HOURS,
        )
        cold_start = "T"
        base_date = _dateutils.ndate(-STALE_RESTART_HOURS, time_nowcastend)
        rst_file = None
        ini_file_root = fixofs / f"{prefix}.init.nc"
        nh_nowcast = _dateutils.nhour(time_nowcastend, base_date)

    nh_forecast = _dateutils.nhour(time_forecastend, base_date)
    nstep_nowcast = int(nh_nowcast * 3600 / delt_int)
    nstep_forecast = int(nh_forecast * 3600 / delt_int)

    # DSTART_FORECAST: shell does `echo "scale=4;$DAY0+${NH_NOWCAST}/24.0" | bc`
    # with DAY0=0 from the synthetic time_initial.dat (line 347), so this
    # collapses to NH_NOWCAST / 24.0.
    dstart_nowcast = 0.0
    dstart_forecast = nh_nowcast / 24.0

    return HotstartResult(
        rst_file=rst_file,
        ini_file=ini_file_root,
        base_date=base_date,
        time_hotstart=base_date,
        time_nowcastend=time_nowcastend,
        time_forecastend=time_forecastend,
        tide_start=base_date,
        cold_start=cold_start,
        dstart_nowcast=dstart_nowcast,
        dstart_forecast=dstart_forecast,
        nh_nowcast=nh_nowcast,
        nh_forecast=nh_forecast,
        nstep_nowcast=nstep_nowcast,
        nstep_forecast=nstep_forecast,
        ntimes_nowcast=nstep_nowcast,
        ntimes_forecast=nstep_forecast,
        ntimes=max(nstep_nowcast, nstep_forecast),
        nrrec=0,
    )


def write_time_files(
    result: HotstartResult,
    comout: Path,
    cycle: str,
) -> None:
    """Persist anchor strings to ``$COMOUT`` for downstream PBS jobs.

    Mirrors the shell's persistence block on lines 370-373 of
    ``nos_run.sh``::

        echo $time_nowcastend  > $COMOUT/time_nowcastend.${cycle}
        echo $time_hotstart    > $COMOUT/time_hotstart.${cycle}
        echo $time_forecastend > $COMOUT/time_forecastend.${cycle}
        echo $BASE_DATE        > $COMOUT/base_date.${cycle}

    The nowcast / forecast jobs run as separate PBS submissions; they
    read these files back to recover the anchors without re-running
    the walk-back (which would have raced against the new nowcast's
    own restart output landing in $COMOUTroot).
    """
    comout.mkdir(parents=True, exist_ok=True)
    payloads = {
        f"time_nowcastend.{cycle}":  result.time_nowcastend,
        f"time_hotstart.{cycle}":    result.time_hotstart,
        f"time_forecastend.{cycle}": result.time_forecastend,
        f"base_date.{cycle}":        result.base_date,
    }
    for name, value in payloads.items():
        path = comout / name
        # Shell `echo` adds a trailing newline; preserve that so the
        # downstream `read time_hotstart < ...` continues to work.
        path.write_text(f"{value}\n")
        logger.debug("write_time_files: wrote %s = %r", path, value)


__all__ = [
    "HotstartResult",
    "DEFAULT_BACK_SEARCH",
    "STALE_RESTART_HOURS",
    "find_hotstart",
    "write_time_files",
]
