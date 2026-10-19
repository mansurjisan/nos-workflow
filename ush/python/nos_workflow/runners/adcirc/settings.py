"""STOFS-2D-GLO settings and cycle context.

Adapted from Zach Cobell's StofsWorkflow (oceanmodeling/nos-workflow, branch
zcobell/stofs_2d_global), stofs_config.py: the knobs the ops run reads (ncpu_compute/writer,
atmospheric toggle), read from parm/systems/stofs_2d_glo.yaml and the NCO environment instead of his
standalone YAML and StofsConfig. Ops is the only mode; the single-run knobs were removed. MJ (10/19/26)
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from ...utils.yaml_to_env import load_yaml_with_inheritance

class AdcircConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdcircSettings:
    name: str
    ncpu_compute: int
    ncpu_writer: int
    atmospheric_forcing: bool
    grid_file: str
    attr_file: str
    padcirc: str
    adcprep: str
    exec_dir: Optional[str]
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_yaml(cls, path, env: Optional[Mapping[str, str]] = None) -> "AdcircSettings":
        env = os.environ if env is None else env
        path = Path(path)
        data = load_yaml_with_inheritance(path, path.parent.parent)
        ad = data.get("adcirc") or {}
        files = (data.get("grid") or {}).get("files") or {}
        execs = ad.get("executables") or {}

        def pick(name, cast=None):
            v = env.get(name)
            return cast(v) if (v not in (None, "") and cast) else v

        # Ops is the only mode: ADCIRC_MODE unset or ops is accepted, anything else stops here. MJ (10/19/26)
        mode = (pick("ADCIRC_MODE") or "ops").strip().lower()
        if mode != "ops":
            raise AdcircConfigError(f"ADCIRC_MODE={mode} was removed: STOFS-2D-GLO runs ops mode only (unset ADCIRC_MODE or set ADCIRC_MODE=ops)")

        ncpu = pick("NCPU", int) or ad["ncpu_compute"]
        writers = pick("NUM_WRITERS", int)
        if writers is None:
            writers = int(ad.get("ncpu_writer", 0))
        atmospheric = ad.get("atmospheric_forcing", True)
        if env.get("ATMOSPHERIC_FORCING", "") != "":
            atmospheric = env["ATMOSPHERIC_FORCING"].strip().lower() in ("1", "true", "yes")

        return cls(
            name=str(ad.get("name", "stofs2dglobal")),
            ncpu_compute=int(ncpu),
            ncpu_writer=int(writers),
            atmospheric_forcing=bool(atmospheric),
            grid_file=str(files.get("horizontal", "stofs_2d_glo_grid")),
            attr_file=str(files.get("attributes", "stofs_2d_glo_attr")),
            padcirc=str(execs.get("padcirc", "padcirc")),
            adcprep=str(execs.get("adcprep", "adcprep")),
            exec_dir=env.get("ADCIRC_EXEC_DIR") or execs.get("directory"),
            raw=data,
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
        )

    def cycle_dir(self, cycle_time: datetime, phase: str) -> Path:
        pdy = cycle_time.strftime("%Y%m%d")
        return (self.comoutroot / f"{self.run}.{pdy}"
                / f"{self.run}.t{cycle_time.hour:02d}z.{phase}")
