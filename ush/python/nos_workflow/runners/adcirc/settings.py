"""STOFS-2D-GLO settings and cycle context.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/stofs_2d_global), stofs_config.py: same knobs (ncpu_compute/writer,
spin-up days, nowcast interval, forecast duration, atmospheric toggle), read
from parm/systems/stofs_2d_glo.yaml and the NCO environment instead of his
standalone YAML and StofsConfig.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ...utils.yaml_to_env import load_yaml_with_inheritance

PHASES = ("nowcast", "forecast")


class AdcircConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdcircSettings:
    name: str
    mesh_name: str
    dt: float
    ramp: float
    ncpu_compute: int
    ncpu_writer: int
    atmospheric_forcing: bool
    attributes: List[str]
    physics: Dict[str, Any]
    tide_constituents: List[str]
    nodal_reference: str
    coldstart_spinup_days: float
    nowcast_interval_hours: float
    forecast_duration_hours: float
    output_minutes: float
    wind_dt: int
    decomposition_cache: bool
    grid_file: str
    attr_file: str
    padcirc: str
    adcprep: str
    exec_dir: Optional[str]
    met_variables: List[str]
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)
    mode: str = "single"

    @classmethod
    def from_yaml(cls, path, env: Optional[Mapping[str, str]] = None) -> "AdcircSettings":
        env = os.environ if env is None else env
        path = Path(path)
        data = load_yaml_with_inheritance(path, path.parent.parent)
        ad = data.get("adcirc") or {}
        run = (data.get("model") or {}).get("run") or {}
        files = (data.get("grid") or {}).get("files") or {}
        execs = ad.get("executables") or {}
        atm = (data.get("forcing") or {}).get("atmospheric") or {}
        tidal = (data.get("forcing") or {}).get("tidal") or {}

        def pick(name, cast=None):
            v = env.get(name)
            return cast(v) if (v not in (None, "") and cast) else v

        ncpu = pick("NCPU", int) or ad["ncpu_compute"]
        writers = pick("NUM_WRITERS", int)
        if writers is None:
            writers = int(ad.get("ncpu_writer", 0))
        atmospheric = ad.get("atmospheric_forcing", True)
        if env.get("ATMOSPHERIC_FORCING", "") != "":
            atmospheric = env["ATMOSPHERIC_FORCING"].strip().lower() in ("1", "true", "yes")
        spinup = pick("COLDSTART_SPINUP_DAYS", float)
        if spinup is None:
            spinup = float(run.get("coldstart_spinup_days", 18.0))

        # NOWCAST_HOURS overrides the yaml (24 with a once-a-day 12z cycle, so the restart is
        # the previous day's 12z nowcast and nothing cold-starts). MJ (10/05/26)
        nowcast = pick("NOWCAST_HOURS", float)
        if nowcast is None:
            nowcast = float(run.get("nowcast_hours", 6))

        mode = (pick("ADCIRC_MODE") or "single").strip().lower()
        if mode not in ("single", "ops"):
            raise AdcircConfigError(f"ADCIRC_MODE must be single or ops, got {mode!r}")

        return cls(
            name=str(ad.get("name", "stofs2dglobal")),
            mesh_name=str(ad.get("name", "stofs2dglobal")),
            dt=float((data.get("model") or {}).get("physics", {}).get("dt", 6.0)),
            ramp=float(ad.get("ramp", 5.0)),
            ncpu_compute=int(ncpu),
            ncpu_writer=int(writers),
            atmospheric_forcing=bool(atmospheric),
            attributes=list(ad.get("attributes") or []),
            physics=dict(ad.get("physics") or {}),
            tide_constituents=[str(c).upper() for c in tidal.get("constituents") or []],
            nodal_reference=str(tidal.get("adcirc_nodal_reference", "midrun")),
            coldstart_spinup_days=spinup,
            nowcast_interval_hours=nowcast,
            forecast_duration_hours=float(run.get("forecast_hours", 180)),
            output_minutes=float(ad.get("output_minutes", 20.0)),
            wind_dt=int(ad.get("wind_dt", 3600)),
            decomposition_cache=bool(ad.get("decomposition_cache", True)),
            grid_file=str(files.get("horizontal", "stofs_2d_glo_grid")),
            attr_file=str(files.get("attributes", "stofs_2d_glo_attr")),
            padcirc=str(execs.get("padcirc", "padcirc")),
            adcprep=str(execs.get("adcprep", "adcprep")),
            exec_dir=env.get("ADCIRC_EXEC_DIR") or execs.get("directory"),
            met_variables=list(atm.get("variables") or []),
            raw=data,
            mode=mode,
        )

    def executable(self, which: str, execnos: Optional[Path] = None) -> str:
        """Resolve padcirc/adcprep: ADCIRC_EXEC_DIR or yaml directory, then $EXECnos, then PATH."""
        name = getattr(self, which)
        search = [Path(d) for d in (self.exec_dir, execnos) if d]
        for d in search:
            cand = d / name
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
        found = shutil.which(name)
        if found:
            return found
        raise AdcircConfigError(
            f"{name} not found in {[str(d) for d in search]} or PATH "
            f"(set ADCIRC_EXEC_DIR)")


@dataclass(frozen=True)
class CycleContext:
    settings: AdcircSettings
    run: str
    cycle_time: datetime
    comout: Path
    comoutroot: Path
    comges: Path
    fixofs: Path
    execnos: Optional[Path] = None
    comin_gfs: Optional[str] = None
    data: Optional[Path] = None
    stream: str = ""
    segment: str = ""
    coldstart: bool = False

    @classmethod
    def from_env(cls, settings: AdcircSettings, env: Optional[Mapping[str, str]] = None) -> "CycleContext":
        env = os.environ if env is None else env

        def need(key):
            v = env.get(key)
            if not v:
                raise AdcircConfigError(f"required env var {key!r} is not set")
            return v

        run = env.get("RUN") or "stofs_2d_glo"
        comout = Path(need("COMOUT"))
        root = Path(env.get("COMOUTroot") or comout.parent)
        cycle = datetime.strptime(f"{need('PDY')}{int(need('cyc')):02d}", "%Y%m%d%H")
        fixofs = Path(env.get("FIXofs") or Path(need("HOMEnos")) / "fix" / run)
        return cls(
            settings=settings,
            run=run,
            cycle_time=cycle,
            comout=comout,
            comoutroot=root,
            comges=Path(env.get("COMGES") or root / run),
            fixofs=fixofs,
            execnos=Path(env["EXECnos"]) if env.get("EXECnos") else None,
            comin_gfs=env.get("COMINgfs") or None,
            data=Path(env["DATA"]) if env.get("DATA") else None,
            stream=env.get("ADCIRC_STREAM", "").strip().lower(),
            segment=env.get("ADCIRC_SEGMENT", "").strip().lower(),
            coldstart=env.get("COLDSTART", "").strip().upper() == "YES",
        )

    @property
    def nowcast_start(self) -> datetime:
        return self.cycle_time - timedelta(hours=self.settings.nowcast_interval_hours)

    @property
    def forecast_end(self) -> datetime:
        return self.cycle_time + timedelta(hours=self.settings.forecast_duration_hours)

    def cycle_dir(self, cycle_time: datetime, phase: str) -> Path:
        pdy = cycle_time.strftime("%Y%m%d")
        return (self.comoutroot / f"{self.run}.{pdy}"
                / f"{self.run}.t{cycle_time.hour:02d}z.{phase}")

    def run_dir(self, phase: str) -> Path:
        return self.cycle_dir(self.cycle_time, phase)

    @property
    def prev_nowcast_dir(self) -> Path:
        prev = self.cycle_time - timedelta(hours=self.settings.nowcast_interval_hours)
        return self.cycle_dir(prev, "nowcast")
