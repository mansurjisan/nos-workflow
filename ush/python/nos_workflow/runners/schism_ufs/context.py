"""SchismRunContext: typed state passed through the SCHISM-UFS runner chain."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional


# Mapping from snake_case Python attribute to NCO shell env var name.
# Drives both ``from_env_and_phase`` and ``to_shell_env``.

_PATH_FIELDS: dict = {
    "homenos":     "HOMEnos",
    "fixofs":      "FIXofs",
    "execnos":     "EXECnos",
    "ushnos":      "USHnos",
    "comoutroot":  "COMOUTroot",
    "dataroot":    "DATAROOT",
}

_STR_FIELDS: dict = {
    "run":                       "RUN",
    "cycle":                     "cycle",
    "pdy":                       "PDY",
    "cyc":                       "cyc",
    "prefixnos":                 "PREFIXNOS",
    "ini_file_nowcast":          "INI_FILE_NOWCAST",
    "ini_file_forecast":         "INI_FILE_FORECAST",
    "rst_out_nowcast":           "RST_OUT_NOWCAST",
    "rst_out_forecast":          "RST_OUT_FORECAST",
    "ini_file":                  "INI_FILE",
    "rst_file":                  "RST_FILE",
    "base_date":                 "BASE_DATE",
    "time_hotstart":             "time_hotstart",
    "time_nowcastend":           "time_nowcastend",
    "time_forecastend":          "time_forecastend",
    "dstart_nowcast":            "DSTART_NOWCAST",
    "dstart_forecast":           "DSTART_FORECAST",
    "nstep_nowcast":             "NSTEP_NOWCAST",
    "nstep_forecast":            "NSTEP_FORECAST",
    "ntimes_nowcast":            "NTIMES_NOWCAST",
    "ntimes_forecast":           "NTIMES_FORECAST",
    "cold_start":                "COLD_START",
    "bctides_in_nowcast":        "BCTIDES_IN_NOWCAST",
    "bctides_in_forecast":       "BCTIDES_IN_FORECAST",
    "nwm_source_sink_nowcast":   "NWM_SOURCE_SINK_NOW",
    "nwm_source_sink_forecast":  "NWM_SOURCE_SINK_FORE",
    "obc_forcing_file_nowcast":  "OBC_FORCING_FILE_NOWCAST",
    "obc_forcing_file_forecast": "OBC_FORCING_FILE_FORECAST",
    "river_forcing_file":        "RIVER_FORCING_FILE",
    "met_netcdf_nowcast":        "MET_NETCDF_1_NOWCAST",
    "met_netcdf_forecast":       "MET_NETCDF_1_FORECAST",
    "runtime_ctl":               "RUNTIME_CTL",
    "sta_out_ctl":               "STA_OUT_CTL",
    "delt_model":                "DELT_MODEL",
    "len_nowcast":               "LEN_NOWCAST",
    "len_forecast":              "LEN_FORECAST",
}


@dataclass(frozen=True)
class SchismRunContext:
    """Typed, immutable view of the SCHISM-UFS runner environment."""

    comout: Path
    data: Path
    phase: str
    run: str
    cycle: str

    pdy: Optional[str] = None
    cyc: Optional[str] = None
    prefixnos: Optional[str] = None
    homenos: Optional[Path] = None
    fixofs: Optional[Path] = None
    execnos: Optional[Path] = None
    ushnos: Optional[Path] = None
    comoutroot: Optional[Path] = None
    dataroot: Optional[Path] = None

    ini_file_nowcast: Optional[str] = None
    ini_file_forecast: Optional[str] = None
    rst_out_nowcast: Optional[str] = None
    rst_out_forecast: Optional[str] = None
    ini_file: Optional[str] = None
    rst_file: Optional[str] = None

    base_date: Optional[str] = None
    time_hotstart: Optional[str] = None
    time_nowcastend: Optional[str] = None
    time_forecastend: Optional[str] = None
    dstart_nowcast: Optional[str] = None
    dstart_forecast: Optional[str] = None
    nstep_nowcast: Optional[str] = None
    nstep_forecast: Optional[str] = None
    ntimes_nowcast: Optional[str] = None
    ntimes_forecast: Optional[str] = None
    cold_start: Optional[str] = None

    bctides_in_nowcast: Optional[str] = None
    bctides_in_forecast: Optional[str] = None
    nwm_source_sink_nowcast: Optional[str] = None
    nwm_source_sink_forecast: Optional[str] = None
    obc_forcing_file_nowcast: Optional[str] = None
    obc_forcing_file_forecast: Optional[str] = None
    river_forcing_file: Optional[str] = None
    met_netcdf_nowcast: Optional[str] = None
    met_netcdf_forecast: Optional[str] = None

    runtime_ctl: Optional[str] = None
    sta_out_ctl: Optional[str] = None
    delt_model: Optional[str] = None
    len_nowcast: Optional[str] = None
    len_forecast: Optional[str] = None

    @classmethod
    def from_env_and_phase(
        cls,
        env: dict,
        phase: str,
    ) -> "SchismRunContext":
        """Build a context from an env dict and phase string."""
        comout = Path(env["COMOUT"])
        data = Path(env["DATA"])
        run = env["RUN"]
        cycle = env["cycle"]

        path_kwargs = {
            py_name: (Path(env[ev_name]) if env.get(ev_name) else None)
            for py_name, ev_name in _PATH_FIELDS.items()
        }

        str_kwargs = {
            py_name: (env[ev_name] if env.get(ev_name) else None)
            for py_name, ev_name in _STR_FIELDS.items()
        }
        for dup in ("run", "cycle"):
            str_kwargs.pop(dup, None)

        return cls(
            comout=comout,
            data=data,
            phase=phase,
            run=run,
            cycle=cycle,
            **path_kwargs,
            **str_kwargs,
        )

    def to_shell_env(self) -> dict:
        """Serialize non-None fields to a dict keyed by NCO env var names."""
        out: dict = {}

        out["COMOUT"] = str(self.comout)
        out["DATA"] = str(self.data)
        out["RUN"] = self.run
        out["cycle"] = self.cycle

        for py_name, ev_name in _PATH_FIELDS.items():
            val = getattr(self, py_name)
            if val is not None:
                out[ev_name] = str(val)

        for py_name, ev_name in _STR_FIELDS.items():
            if py_name in ("run", "cycle"):
                continue
            val = getattr(self, py_name)
            if val is not None:
                out[ev_name] = val

        return out


__all__ = ["SchismRunContext"]
