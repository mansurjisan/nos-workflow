"""Hotstart resolution and handoff for the ADCIRC chain.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/stofs_2d_global), adcircmodel.py _resolve_hotstart and
__select_restart_file: the nowcast hotstarts from the previous cycle's nowcast
(or cold starts with a spin-up), and the forecast hotstarts from the nowcast
that just finished. fort.67.nc / fort.68.nc validity is checked against the
end time recorded in timing.json.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

TIMING = "timing.json"


@dataclass(frozen=True)
class HotstartInfo:
    unit: int
    coldstart_time: datetime
    start_time: datetime
    hotstart_file: Optional[str]

    @property
    def is_coldstart(self) -> bool:
        return self.unit == 0


def write_timing(run_dir: Path, coldstart: datetime, start: datetime, end: datetime,
                 hotstart_file: Optional[str]) -> dict:
    data = {
        "coldstart_time": coldstart.isoformat(),
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "hotstart_file": hotstart_file,
    }
    (run_dir / TIMING).write_text(json.dumps(data, indent=2) + "\n")
    return data


def read_timing(run_dir: Path) -> Optional[dict]:
    p = run_dir / TIMING
    return json.loads(p.read_text()) if p.is_file() else None


def file_time(path: Path) -> Optional[float]:
    import netCDF4

    ds = netCDF4.Dataset(path, "r")
    try:
        var = ds.variables["time"]
        if var.size == 0:
            log.warning("%s: time dimension is empty, skipping", path.name)
            return None
        data = var[:]
        fill = getattr(var, "_FillValue", None)
        # netCDF4 returns a masked element for a fill value. MJ (10/05/26)
        if np.ma.is_masked(data.flat[0]) or (fill is not None and data.flat[0] == fill):
            log.warning("%s: time contains fill value, skipping", path.name)
            return None
        return float(data.flat[0])
    finally:
        ds.close()


def select_restart_file(prev_dir: Path) -> Optional[Tuple[Path, int, datetime]]:
    """Latest valid fort.67/68.nc in ``prev_dir`` whose time matches its timing.json end."""
    timing = read_timing(prev_dir)
    if timing is None:
        return None
    coldstart = datetime.fromisoformat(timing["coldstart_time"])
    expected = (datetime.fromisoformat(timing["end_time"]) - coldstart).total_seconds()

    candidates = []
    for unit in (67, 68):
        path = prev_dir / f"fort.{unit}.nc"
        seconds = file_time(path) if path.exists() else None
        if seconds is not None:
            candidates.append((path, unit, seconds))
    if not candidates:
        return None

    candidates.sort(key=lambda c: c[2], reverse=True)
    best_path, best_unit, best_seconds = candidates[0]
    if abs(best_seconds - expected) > 1.0:
        raise RuntimeError(
            f"Restart file {best_path.name} time ({best_seconds:.1f}s) does not match "
            f"expected end_time ({expected:.1f}s from timing.json)")
    return best_path, best_unit, coldstart


def resolve_nowcast_hotstart(prev_dir: Path, cycle_time: datetime, nowcast_start: datetime,
                             spinup_days: float) -> HotstartInfo:
    found = select_restart_file(prev_dir)
    if found is not None:
        path, _unit, coldstart = found
        return HotstartInfo(67, coldstart, nowcast_start, str(path))
    coldstart = cycle_time - timedelta(days=spinup_days)
    return HotstartInfo(0, coldstart, coldstart, None)


def stage_hotstart(info: HotstartInfo, run_dir: Path) -> None:
    """Copy (never link: ADCIRC rewrites fort.67/68.nc) the restart into the run dir."""
    if info.hotstart_file is not None:
        shutil.copy2(info.hotstart_file, run_dir / "fort.67.nc")


def forecast_restart(nowcast_dir: Path) -> Tuple[Path, datetime]:
    found = select_restart_file(nowcast_dir)
    if found is None:
        raise RuntimeError(
            f"No valid restart file in {nowcast_dir}; forecast cannot run without a "
            "completed nowcast")
    path, _unit, coldstart = found
    return path, coldstart
