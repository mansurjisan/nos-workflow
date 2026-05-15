"""Tests for ``nos_workflow.runners.schism_ufs.context.SchismRunContext``.

Covers the schema extended in PR 3:

  - Minimal construction: only the 5 required PR-2 baseline fields.
  - ``from_env_and_phase`` populates fields from an env dict, leaving
    unset env vars as ``None``.
  - ``to_shell_env`` round-trips populated fields back to NCO env-var
    names; ``None`` fields are omitted.
  - Frozen dataclass: attempting to mutate raises ``FrozenInstanceError``.

These tests do NOT exercise the actual runners (archive, prepare_restart);
those are covered in ``test_archive.py`` and ``test_prepare_restart.py``.
This module isolates the schema so subsequent PRs (#5, #6, #7) can
extend the field set with confidence the round-trip stays correct.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from nos_workflow.runners.schism_ufs.context import SchismRunContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_env(tmp_path: Path) -> dict:
    """The 4 required env vars (COMOUT, DATA, RUN, cycle) plus nothing
    else. ``from_env_and_phase`` should yield a context with the 5
    baseline fields populated and every optional field as None."""
    return {
        "COMOUT": str(tmp_path / "comout"),
        "DATA":   str(tmp_path / "data"),
        "RUN":    "nos.secofs_ufs",
        "cycle":  "t00z",
    }


def _full_env(tmp_path: Path) -> dict:
    """A comprehensive env dict exercising every optional field. Each
    value is distinctive (e.g., includes the env var name) so a typo in
    the from_env_and_phase / to_shell_env mapping shows up as a string
    mismatch rather than a None."""
    return {
        # Baseline (required)
        "COMOUT":      str(tmp_path / "comout"),
        "DATA":        str(tmp_path / "data"),
        "RUN":         "nos.secofs_ufs",
        "cycle":       "t12z",
        # Identity / paths
        "PDY":         "20260507",
        "cyc":         "12",
        "PREFIXNOS":   "nos.secofs_ufs",
        "HOMEnos":     str(tmp_path / "home"),
        "FIXofs":      str(tmp_path / "fix"),
        "EXECnos":     str(tmp_path / "exec"),
        "USHnos":      str(tmp_path / "ush"),
        "COMOUTroot":  str(tmp_path / "comoutroot"),
        "DATAROOT":    str(tmp_path / "dataroot"),
        # Hotstart paths
        "INI_FILE_NOWCAST":  "nos.secofs_ufs.t12z.20260507.init.nowcast.nc",
        "INI_FILE_FORECAST": "nos.secofs_ufs.t12z.20260507.rst.nowcast.nc",
        "RST_OUT_NOWCAST":   "nos.secofs_ufs.t12z.20260507.rst.nowcast.nc",
        "RST_OUT_FORECAST":  "nos.secofs_ufs.t12z.20260507.rst.forecast.nc",
        "INI_FILE":          "init.nc",
        "RST_FILE":          "rst.nc",
        # Time anchors
        "BASE_DATE":         "2026050700",
        "time_hotstart":     "2026050700",
        "time_nowcastend":   "2026050712",
        "time_forecastend":  "2026051012",
        "DSTART_NOWCAST":    "0.0",
        "DSTART_FORECAST":   "0.5",
        "NSTEP_NOWCAST":     "432",
        "NSTEP_FORECAST":    "8640",
        "NTIMES_NOWCAST":    "432",
        "NTIMES_FORECAST":   "8640",
        "COLD_START":        "F",
        # Forcing artifact filenames
        "BCTIDES_IN_NOWCAST":         "bctides_nowcast.in",
        "BCTIDES_IN_FORECAST":        "bctides_forecast.in",
        "NWM_SOURCE_SINK_NOW":        "nwm_now.tar",
        "NWM_SOURCE_SINK_FORE":       "nwm_fore.tar",
        "OBC_FORCING_FILE_NOWCAST":   "obc_nowcast.tar",
        "OBC_FORCING_FILE_FORECAST":  "obc_forecast.tar",
        "RIVER_FORCING_FILE":         "river.th.tar",
        "MET_NETCDF_1_NOWCAST":       "met_nowcast.nc.tar",
        "MET_NETCDF_1_FORECAST":      "met_forecast.nc.tar",
        # Misc runtime control + timing
        "RUNTIME_CTL":  "param.nml",
        "STA_OUT_CTL":  "station.in",
        "DELT_MODEL":   "100.0",
        "LEN_NOWCAST":  "12",
        "LEN_FORECAST": "72",
    }


# ---------------------------------------------------------------------------
# Minimal construction (PR 2 baseline)
# ---------------------------------------------------------------------------


def test_context_minimal_construction(tmp_path):
    """All 5 required PR-2 fields can be passed positionally / by name;
    every other field defaults to None."""
    ctx = SchismRunContext(
        comout=tmp_path / "comout",
        data=tmp_path / "data",
        phase="nowcast",
        run="nos.secofs_ufs",
        cycle="t00z",
    )
    # 5 baseline fields populated
    assert ctx.comout == tmp_path / "comout"
    assert ctx.data == tmp_path / "data"
    assert ctx.phase == "nowcast"
    assert ctx.run == "nos.secofs_ufs"
    assert ctx.cycle == "t00z"
    # Spot-check that every optional field defaults to None
    for opt_field in (
        "pdy", "cyc", "prefixnos", "homenos", "fixofs",
        "execnos", "ushnos", "comoutroot", "dataroot",
        "ini_file_nowcast", "ini_file_forecast",
        "rst_out_nowcast", "rst_out_forecast", "ini_file", "rst_file",
        "base_date", "time_hotstart", "time_nowcastend", "time_forecastend",
        "dstart_nowcast", "dstart_forecast",
        "nstep_nowcast", "nstep_forecast",
        "ntimes_nowcast", "ntimes_forecast", "cold_start",
        "bctides_in_nowcast", "bctides_in_forecast",
        "nwm_source_sink_nowcast", "nwm_source_sink_forecast",
        "obc_forcing_file_nowcast", "obc_forcing_file_forecast",
        "river_forcing_file",
        "met_netcdf_nowcast", "met_netcdf_forecast",
        "runtime_ctl", "sta_out_ctl",
        "delt_model", "len_nowcast", "len_forecast",
    ):
        assert getattr(ctx, opt_field) is None, (
            f"expected field {opt_field!r} to default to None"
        )


# ---------------------------------------------------------------------------
# from_env_and_phase
# ---------------------------------------------------------------------------


def test_context_from_env_and_phase_minimal(tmp_path):
    """A minimal env dict populates the 5 baseline fields and leaves
    everything else as None."""
    env = _minimal_env(tmp_path)
    ctx = SchismRunContext.from_env_and_phase(env, phase="nowcast")

    # Baseline fields populated from env (paths are wrapped in Path)
    assert ctx.comout == Path(env["COMOUT"])
    assert ctx.data == Path(env["DATA"])
    assert ctx.run == "nos.secofs_ufs"
    assert ctx.cycle == "t00z"
    assert ctx.phase == "nowcast"

    # Everything else is None
    assert ctx.pdy is None
    assert ctx.homenos is None
    assert ctx.base_date is None
    assert ctx.time_hotstart is None
    assert ctx.bctides_in_nowcast is None
    assert ctx.delt_model is None


def test_context_from_env_and_phase_full(tmp_path):
    """A comprehensive env dict populates every documented field with
    the right type (Path for path fields, str for everything else)."""
    env = _full_env(tmp_path)
    ctx = SchismRunContext.from_env_and_phase(env, phase="nowcast")

    # Path-typed fields
    assert ctx.homenos == Path(env["HOMEnos"])
    assert ctx.fixofs == Path(env["FIXofs"])
    assert ctx.execnos == Path(env["EXECnos"])
    assert ctx.ushnos == Path(env["USHnos"])
    assert ctx.comoutroot == Path(env["COMOUTroot"])
    assert ctx.dataroot == Path(env["DATAROOT"])

    # String identity fields
    assert ctx.pdy == "20260507"
    assert ctx.cyc == "12"
    assert ctx.prefixnos == "nos.secofs_ufs"

    # Hotstart paths
    assert ctx.ini_file_nowcast == env["INI_FILE_NOWCAST"]
    assert ctx.ini_file_forecast == env["INI_FILE_FORECAST"]
    assert ctx.rst_out_nowcast == env["RST_OUT_NOWCAST"]
    assert ctx.rst_out_forecast == env["RST_OUT_FORECAST"]
    assert ctx.ini_file == "init.nc"
    assert ctx.rst_file == "rst.nc"

    # Time anchors
    assert ctx.base_date == "2026050700"
    assert ctx.time_hotstart == "2026050700"
    assert ctx.time_nowcastend == "2026050712"
    assert ctx.time_forecastend == "2026051012"
    assert ctx.dstart_nowcast == "0.0"
    assert ctx.dstart_forecast == "0.5"
    assert ctx.nstep_nowcast == "432"
    assert ctx.nstep_forecast == "8640"
    assert ctx.ntimes_nowcast == "432"
    assert ctx.ntimes_forecast == "8640"
    assert ctx.cold_start == "F"

    # Forcing artifact filenames (note: shell uses NWM_SOURCE_SINK_NOW
    # / _FORE without the _NOWCAST/_FORECAST suffix — verify the
    # mapping uses the shell name not the Python name)
    assert ctx.bctides_in_nowcast == "bctides_nowcast.in"
    assert ctx.bctides_in_forecast == "bctides_forecast.in"
    assert ctx.nwm_source_sink_nowcast == "nwm_now.tar"
    assert ctx.nwm_source_sink_forecast == "nwm_fore.tar"
    assert ctx.obc_forcing_file_nowcast == "obc_nowcast.tar"
    assert ctx.obc_forcing_file_forecast == "obc_forecast.tar"
    assert ctx.river_forcing_file == "river.th.tar"
    assert ctx.met_netcdf_nowcast == "met_nowcast.nc.tar"
    assert ctx.met_netcdf_forecast == "met_forecast.nc.tar"

    # Misc
    assert ctx.runtime_ctl == "param.nml"
    assert ctx.sta_out_ctl == "station.in"
    assert ctx.delt_model == "100.0"
    assert ctx.len_nowcast == "12"
    assert ctx.len_forecast == "72"

    # Phase passed positionally
    assert ctx.phase == "nowcast"


def test_context_from_env_treats_empty_string_as_none(tmp_path):
    """An empty-string env value (``export FOO=""``) is semantically
    ``unset`` in NCO. ``from_env_and_phase`` must yield ``None`` for
    those, not the empty string — otherwise downstream code that does
    ``if ctx.field is not None`` would mistakenly think the value was
    set."""
    env = _minimal_env(tmp_path)
    env["PDY"] = ""
    env["HOMEnos"] = ""
    env["BASE_DATE"] = ""

    ctx = SchismRunContext.from_env_and_phase(env, phase="nowcast")

    assert ctx.pdy is None
    assert ctx.homenos is None
    assert ctx.base_date is None


# ---------------------------------------------------------------------------
# to_shell_env
# ---------------------------------------------------------------------------


def test_context_to_shell_env_roundtrip(tmp_path):
    """env -> from_env_and_phase -> to_shell_env produces an env dict
    that contains every populated field, keyed by the original NCO
    env-var names."""
    env = _full_env(tmp_path)
    ctx = SchismRunContext.from_env_and_phase(env, phase="nowcast")
    out = ctx.to_shell_env()

    # Every key in the input must be present in the output with the
    # same value (phase is not in either — see test below).
    for ev_name, ev_value in env.items():
        assert ev_name in out, f"key {ev_name!r} missing from to_shell_env output"
        assert out[ev_name] == ev_value, (
            f"value mismatch for {ev_name!r}: expected {ev_value!r}, "
            f"got {out[ev_name]!r}"
        )


def test_context_to_shell_env_skips_none_fields(tmp_path):
    """Fields that are ``None`` must NOT appear in the to_shell_env
    output. NCO convention: "unset" is distinct from "set to empty
    string"; we mirror that."""
    env = _minimal_env(tmp_path)  # only 4 env vars
    ctx = SchismRunContext.from_env_and_phase(env, phase="nowcast")
    out = ctx.to_shell_env()

    # Required fields present
    assert "COMOUT" in out
    assert "DATA" in out
    assert "RUN" in out
    assert "cycle" in out

    # Every optional NCO env var must be absent
    for absent in (
        "PDY", "cyc", "PREFIXNOS",
        "HOMEnos", "FIXofs", "EXECnos", "USHnos", "COMOUTroot", "DATAROOT",
        "INI_FILE_NOWCAST", "INI_FILE_FORECAST",
        "RST_OUT_NOWCAST", "RST_OUT_FORECAST", "INI_FILE", "RST_FILE",
        "BASE_DATE", "time_hotstart", "time_nowcastend", "time_forecastend",
        "DSTART_NOWCAST", "DSTART_FORECAST",
        "NSTEP_NOWCAST", "NSTEP_FORECAST",
        "NTIMES_NOWCAST", "NTIMES_FORECAST", "COLD_START",
        "BCTIDES_IN_NOWCAST", "BCTIDES_IN_FORECAST",
        "NWM_SOURCE_SINK_NOW", "NWM_SOURCE_SINK_FORE",
        "OBC_FORCING_FILE_NOWCAST", "OBC_FORCING_FILE_FORECAST",
        "RIVER_FORCING_FILE",
        "MET_NETCDF_1_NOWCAST", "MET_NETCDF_1_FORECAST",
        "RUNTIME_CTL", "STA_OUT_CTL",
        "DELT_MODEL", "LEN_NOWCAST", "LEN_FORECAST",
    ):
        assert absent not in out, (
            f"None-valued field surfaced in to_shell_env as {absent!r}"
        )


def test_context_to_shell_env_does_not_serialize_phase(tmp_path):
    """``phase`` is a Python-only concept — the shell helpers receive
    it as a positional arg, not via env. ``to_shell_env`` must omit it."""
    env = _full_env(tmp_path)
    ctx = SchismRunContext.from_env_and_phase(env, phase="forecast")
    out = ctx.to_shell_env()
    assert "phase" not in out
    assert "PHASE" not in out


# ---------------------------------------------------------------------------
# Frozen-dataclass invariant
# ---------------------------------------------------------------------------


def test_context_is_frozen(tmp_path):
    """``SchismRunContext`` is ``@dataclass(frozen=True)`` — attempting
    to mutate any field must raise ``FrozenInstanceError``. This keeps
    one context instance as the immutable ground truth for one stage
    invocation; mutations belong in a fresh context built via
    ``dataclasses.replace``."""
    env = _minimal_env(tmp_path)
    ctx = SchismRunContext.from_env_and_phase(env, phase="nowcast")
    with pytest.raises(FrozenInstanceError):
        ctx.phase = "forecast"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ctx.pdy = "20260101"  # type: ignore[misc]
