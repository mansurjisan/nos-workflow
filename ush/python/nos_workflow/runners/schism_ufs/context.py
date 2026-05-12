"""SchismRunContext: typed state passed through the SCHISM-UFS runner chain.

This is the Python replacement for the bag of 50+ env vars that
``_schism_setup_paths`` exports in ``ush/nos_run.sh``. Each runner helper
takes a ``SchismRunContext`` instance and reads typed fields instead of
fishing values out of ``os.environ``.

PR 2 shipped the minimal stub (just the fields ``archive_outputs``
needed: comout, data, phase, run, cycle). PR 3 expands to the full
schema with ``from_env_and_phase`` + ``to_shell_env`` round-trip
support; subsequent PRs (#5, #6, #7) populate and consume the full
field set.

The field set is grouped by purpose:

  - Identity + paths (PR 2 fields + NCO directory roots)
  - Hotstart paths (from ``_schism_find_hotstart``: INI_FILE_*, RST_*)
  - Time anchors (BASE_DATE, time_hotstart, dstart_*, nstep_*, ...)
  - Forcing artifacts (BCTIDES_IN_*, NWM_SOURCE_SINK_*, OBC/river/met)
  - Misc (runtime_ctl, sta_out_ctl, delt_model, len_*)

All fields except the 5 identity ones from PR 2 default to ``None``;
``from_env_and_phase`` populates non-empty values from the env dict and
``to_shell_env`` round-trips the populated fields back to the original
NCO env var names (preserving the original casing — ``HOMEnos`` not
``homenos``, ``FIXofs`` not ``fixofs``, ``BASE_DATE`` not ``base_date``).
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional


# ----------------------------------------------------------------------
# Field <-> shell env var mapping.
#
# Keys are the snake_case Python attribute names; values are the
# corresponding NCO env var names that ``_schism_setup_paths`` (and
# its callers) export to the shell. The mapping drives both
# ``from_env_and_phase`` and ``to_shell_env`` so the two stay in sync.
#
# Fields not in this mapping (comout, data, phase) are handled
# explicitly because they have different semantics (Path vs str, or
# they're computed rather than read from a single env var).
# ----------------------------------------------------------------------

# Identity + path fields (Path-typed; serialized as str via str(Path))
_PATH_FIELDS: dict = {
    "homenos":     "HOMEnos",
    "fixofs":      "FIXofs",
    "execnos":     "EXECnos",
    "ushnos":      "USHnos",
    "comoutroot":  "COMOUTroot",
    "dataroot":    "DATAROOT",
}

# String-typed fields (1:1 NCO env-var mapping)
_STR_FIELDS: dict = {
    # Identity
    "run":                       "RUN",
    "cycle":                     "cycle",
    "pdy":                       "PDY",
    "cyc":                       "cyc",
    "prefixnos":                 "PREFIXNOS",
    # Hotstart paths (filenames inside COMOUT/DATA, not absolute paths)
    "ini_file_nowcast":          "INI_FILE_NOWCAST",
    "ini_file_forecast":         "INI_FILE_FORECAST",
    "rst_out_nowcast":           "RST_OUT_NOWCAST",
    "rst_out_forecast":          "RST_OUT_FORECAST",
    "ini_file":                  "INI_FILE",
    "rst_file":                  "RST_FILE",
    # Time anchors (YYYYMMDDHH strings — keep as str to preserve zero-padding)
    "base_date":                 "BASE_DATE",
    "time_hotstart":             "time_hotstart",
    "time_nowcastend":           "time_nowcastend",
    "time_forecastend":          "time_forecastend",
    # Numeric anchors kept as str (shell exports them as strings; the
    # consumer scripts re-parse with bc / expr)
    "dstart_nowcast":            "DSTART_NOWCAST",
    "dstart_forecast":           "DSTART_FORECAST",
    "nstep_nowcast":             "NSTEP_NOWCAST",
    "nstep_forecast":            "NSTEP_FORECAST",
    "ntimes_nowcast":            "NTIMES_NOWCAST",
    "ntimes_forecast":           "NTIMES_FORECAST",
    "cold_start":                "COLD_START",
    # Forcing artifact filenames
    "bctides_in_nowcast":        "BCTIDES_IN_NOWCAST",
    "bctides_in_forecast":       "BCTIDES_IN_FORECAST",
    "nwm_source_sink_nowcast":   "NWM_SOURCE_SINK_NOW",
    "nwm_source_sink_forecast":  "NWM_SOURCE_SINK_FORE",
    "obc_forcing_file_nowcast":  "OBC_FORCING_FILE_NOWCAST",
    "obc_forcing_file_forecast": "OBC_FORCING_FILE_FORECAST",
    "river_forcing_file":        "RIVER_FORCING_FILE",
    "met_netcdf_nowcast":        "MET_NETCDF_1_NOWCAST",
    "met_netcdf_forecast":       "MET_NETCDF_1_FORECAST",
    # Misc runtime control + timing
    "runtime_ctl":               "RUNTIME_CTL",
    "sta_out_ctl":               "STA_OUT_CTL",
    "delt_model":                "DELT_MODEL",
    "len_nowcast":               "LEN_NOWCAST",
    "len_forecast":              "LEN_FORECAST",
}


@dataclass(frozen=True)
class SchismRunContext:
    """Typed, immutable view of the SCHISM-UFS runner environment.

    Construct via ``SchismRunContext.from_env_and_phase(env, phase)`` to
    pull values from an env dict (typically ``dict(os.environ)``) and
    convert them to the typed field set. Serialize back to a shell-env
    dict via ``ctx.to_shell_env()`` when invoking sub-scripts.

    The 5 fields below (``comout``, ``data``, ``phase``, ``run``,
    ``cycle``) are the PR 2 baseline — they're required and have no
    sensible default. Every other field is optional and defaults to
    ``None`` so PR 3 ships an empty-but-typed schema that subsequent
    PRs can fill in incrementally.
    """

    # ---- PR 2 baseline (required, no defaults) ------------------------
    comout: Path           # $COMOUT
    data: Path             # $DATA
    phase: str             # "nowcast" or "forecast"
    run: str               # $RUN (e.g., "nos.secofs_ufs")
    cycle: str             # $cycle (e.g., "t00z")

    # ---- Identity / paths (optional, defaulted to None) ---------------
    pdy: Optional[str] = None                    # $PDY (YYYYMMDD)
    cyc: Optional[str] = None                    # $cyc (HH, zero-padded)
    prefixnos: Optional[str] = None              # $PREFIXNOS
    homenos: Optional[Path] = None               # $HOMEnos
    fixofs: Optional[Path] = None                # $FIXofs
    execnos: Optional[Path] = None               # $EXECnos
    ushnos: Optional[Path] = None                # $USHnos
    comoutroot: Optional[Path] = None            # $COMOUTroot
    dataroot: Optional[Path] = None              # $DATAROOT

    # ---- Hotstart paths (from _schism_find_hotstart) -----------------
    ini_file_nowcast: Optional[str] = None       # $INI_FILE_NOWCAST
    ini_file_forecast: Optional[str] = None      # $INI_FILE_FORECAST
    rst_out_nowcast: Optional[str] = None        # $RST_OUT_NOWCAST
    rst_out_forecast: Optional[str] = None       # $RST_OUT_FORECAST
    ini_file: Optional[str] = None               # $INI_FILE
    rst_file: Optional[str] = None               # $RST_FILE

    # ---- Time anchors -------------------------------------------------
    base_date: Optional[str] = None              # $BASE_DATE (YYYYMMDDHH)
    time_hotstart: Optional[str] = None          # YYYYMMDDHH
    time_nowcastend: Optional[str] = None        # YYYYMMDDHH
    time_forecastend: Optional[str] = None       # YYYYMMDDHH
    dstart_nowcast: Optional[str] = None         # float days from BASE_DATE
    dstart_forecast: Optional[str] = None        # float days from BASE_DATE
    nstep_nowcast: Optional[str] = None          # int model timesteps
    nstep_forecast: Optional[str] = None         # int model timesteps
    ntimes_nowcast: Optional[str] = None         # int
    ntimes_forecast: Optional[str] = None        # int
    cold_start: Optional[str] = None             # $COLD_START ("T"/"F")

    # ---- Forcing artifact filenames ----------------------------------
    bctides_in_nowcast: Optional[str] = None     # $BCTIDES_IN_NOWCAST
    bctides_in_forecast: Optional[str] = None    # $BCTIDES_IN_FORECAST
    nwm_source_sink_nowcast: Optional[str] = None   # $NWM_SOURCE_SINK_NOW
    nwm_source_sink_forecast: Optional[str] = None  # $NWM_SOURCE_SINK_FORE
    obc_forcing_file_nowcast: Optional[str] = None  # $OBC_FORCING_FILE_NOWCAST
    obc_forcing_file_forecast: Optional[str] = None # $OBC_FORCING_FILE_FORECAST
    river_forcing_file: Optional[str] = None     # $RIVER_FORCING_FILE
    met_netcdf_nowcast: Optional[str] = None     # $MET_NETCDF_1_NOWCAST
    met_netcdf_forecast: Optional[str] = None    # $MET_NETCDF_1_FORECAST

    # ---- Misc runtime control + timing -------------------------------
    runtime_ctl: Optional[str] = None            # $RUNTIME_CTL
    sta_out_ctl: Optional[str] = None            # $STA_OUT_CTL
    delt_model: Optional[str] = None             # $DELT_MODEL (float seconds)
    len_nowcast: Optional[str] = None            # $LEN_NOWCAST (hours)
    len_forecast: Optional[str] = None           # $LEN_FORECAST (hours)

    # ------------------------------------------------------------------
    # Constructors / serializers
    # ------------------------------------------------------------------

    @classmethod
    def from_env_and_phase(
        cls,
        env: dict,
        phase: str,
    ) -> "SchismRunContext":
        """Build a context from an env dict + phase.

        Args:
            env: Mapping of shell env-var name -> value. Typically
                ``dict(os.environ)``. Missing keys and empty strings
                are treated as ``None``.
            phase: ``"nowcast"`` or ``"forecast"``.

        Returns:
            Fully-populated ``SchismRunContext`` (with ``None`` for any
            env vars that weren't set).

        Raises:
            KeyError: if one of the 5 required identity fields
                (``COMOUT``, ``DATA``, ``RUN``, ``cycle``) is missing
                from ``env``.
        """
        # Required (the 5 PR-2 baseline fields)
        comout = Path(env["COMOUT"])
        data = Path(env["DATA"])
        run = env["RUN"]
        cycle = env["cycle"]

        # Optional Path-typed fields
        path_kwargs = {
            py_name: (Path(env[ev_name]) if env.get(ev_name) else None)
            for py_name, ev_name in _PATH_FIELDS.items()
        }

        # Optional str-typed fields
        str_kwargs = {
            py_name: (env[ev_name] if env.get(ev_name) else None)
            for py_name, ev_name in _STR_FIELDS.items()
        }
        # The 5 baseline fields are also in _STR_FIELDS for round-trip;
        # remove duplicates so we don't pass run/cycle twice.
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
        """Serialize non-None fields back to a ``dict[str, str]`` keyed
        by the original NCO env var names.

        Suitable for merging into a child-process env or comparing
        against ``os.environ`` for round-trip verification. ``None``
        fields are omitted from the result (the shell convention is
        "unset" rather than "set to empty string", and the round-trip
        tests rely on that distinction).

        Phase is NOT serialized — it's a Python-only concept; the shell
        passes phase as a positional arg to each helper, not via env.
        """
        out: dict = {}

        # The 5 baseline identity fields
        out["COMOUT"] = str(self.comout)
        out["DATA"] = str(self.data)
        out["RUN"] = self.run
        out["cycle"] = self.cycle

        # Optional Path fields
        for py_name, ev_name in _PATH_FIELDS.items():
            val = getattr(self, py_name)
            if val is not None:
                out[ev_name] = str(val)

        # Optional str fields (skip the duplicates baked into _STR_FIELDS
        # for round-trip — run/cycle were already written above)
        for py_name, ev_name in _STR_FIELDS.items():
            if py_name in ("run", "cycle"):
                continue
            val = getattr(self, py_name)
            if val is not None:
                out[ev_name] = val

        return out


__all__ = ["SchismRunContext"]
