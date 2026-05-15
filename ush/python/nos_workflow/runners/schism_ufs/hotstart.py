"""Walk back through $COMOUTroot looking for a usable prior-cycle restart file."""
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


DEFAULT_BACK_SEARCH = 49

# If the candidate is >= this many hours before time_nowcastend, fall back
# to cold start (matches the legacy COMF "too stale" threshold).
STALE_RESTART_HOURS = 48


@dataclass(frozen=True)
class HotstartResult:
    """Result of walking back through $COMOUTroot for a usable restart."""

    rst_file: Optional[Path]
    ini_file: Optional[Path]

    base_date: str
    time_hotstart: str
    time_nowcastend: str
    time_forecastend: str
    tide_start: str

    # "T" if no restart found or too stale; "F" if usable warmstart located.
    cold_start: str

    dstart_nowcast: float
    dstart_forecast: float

    nh_nowcast: int
    nh_forecast: int

    nstep_nowcast: int
    nstep_forecast: int
    ntimes_nowcast: int
    ntimes_forecast: int
    ntimes: int

    nrrec: int


def _candidate_restart_path(
    comoutroot: Path,
    run: str,
    prefix: str,
    candidate_time: str,
) -> Path:
    """Build $COMOUTroot/${RUN}.YYYYMMDD/${PREFIX}.tHHz.YYYYMMDD.rst.nowcast.nc.

    YYYYMMDD appears in both the directory and the filename (intentional).
    """
    yyyymmdd = candidate_time[:8]
    hh = candidate_time[8:10]
    return (
        comoutroot
        / f"{run}.{yyyymmdd}"
        / f"{prefix}.t{hh}z.{yyyymmdd}.rst.nowcast.nc"
    )


def _is_usable_restart(path: Path) -> bool:
    """File exists and has nonzero size."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
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
    """Walk back through $COMOUTroot looking for a usable restart file.

    Returns HotstartResult with cold_start="F" if a usable restart was
    located within the back-search window and is no more than 48 hours
    stale; else cold_start="T".
    """
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

    if time_nowcastend is None:
        time_nowcastend = os.environ.get("time_nowcastend") or f"{env.pdy}{env.cyc}"

    found_anchor: Optional[str] = None
    found_path: Optional[Path] = None
    earliest_anchor = _dateutils.ndate(-back_search_hours, time_nowcastend)

    for hours_back in range(1, back_search_hours + 1):
        candidate_anchor = _dateutils.ndate(-hours_back, time_nowcastend)
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

    time_forecastend = _dateutils.ndate(len_forecast, time_nowcastend)
    delt_int = int(delt_model)
    if delt_int <= 0:
        delt_int = 1

    if found_anchor is None or found_path is None:
        logger.warning(
            "find_hotstart: no usable restart in %dh back-search window from %s; "
            "falling back to cold start (FIXofs/%s.init.nc)",
            back_search_hours, time_nowcastend, prefix,
        )
        # Cold-start anchor: cycle - LEN_NOWCAST matches the nos-utils prep
        # orchestrator's time_hotstart.${cycle} contract.
        base_date = _dateutils.ndate(-len_nowcast, time_nowcastend)
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

    base_date = found_anchor
    rst_file = found_path
    ini_file_root = data / f"{prefix}.{cycle}.{env.pdy}.init.nowcast.nc"

    nh_nowcast = _dateutils.nhour(time_nowcastend, base_date)
    cold_start = "F"
    if nh_nowcast >= STALE_RESTART_HOURS:
        logger.warning(
            "find_hotstart: restart at %s is %dh old (>= %dh stale threshold); "
            "falling back to cold start",
            rst_file, nh_nowcast, STALE_RESTART_HOURS,
        )
        cold_start = "T"
        base_date = _dateutils.ndate(-len_nowcast, time_nowcastend)
        rst_file = None
        ini_file_root = fixofs / f"{prefix}.init.nc"
        nh_nowcast = _dateutils.nhour(time_nowcastend, base_date)

    nh_forecast = _dateutils.nhour(time_forecastend, base_date)
    nstep_nowcast = int(nh_nowcast * 3600 / delt_int)
    nstep_forecast = int(nh_forecast * 3600 / delt_int)

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
    """Persist anchor strings to $COMOUT/time_*.${cycle} for downstream PBS jobs."""
    comout.mkdir(parents=True, exist_ok=True)
    payloads = {
        f"time_nowcastend.{cycle}":  result.time_nowcastend,
        f"time_hotstart.{cycle}":    result.time_hotstart,
        f"time_forecastend.{cycle}": result.time_forecastend,
        f"base_date.{cycle}":        result.base_date,
    }
    for name, value in payloads.items():
        path = comout / name
        path.write_text(f"{value}\n")
        logger.debug("write_time_files: wrote %s = %r", path, value)


__all__ = [
    "HotstartResult",
    "DEFAULT_BACK_SEARCH",
    "STALE_RESTART_HOURS",
    "find_hotstart",
    "write_time_files",
]
