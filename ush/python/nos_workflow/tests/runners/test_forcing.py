"""Unit tests for ``runners.schism_ufs.forcing`` -- PR 7b phases 4-6.

Each test builds a synthetic tarball under ``tmp_path`` (using Python's
``tarfile`` module so we don't depend on a particular shell tar binary
for fixture-creation), drops it into a fake ``$COMOUT``, and then runs
the helper under test (which uses ``subprocess.run(['tar', ...])``
internally to match shell behavior).

Three categories:

  - :func:`untar_obc_forcing`        -- shell lines 703-712
  - :func:`untar_nwm_source_sink`    -- shell lines 670-683 (phase-aware)
  - :func:`untar_river_forcing`      -- shell lines 715-723

All tests skip if ``tar`` isn't on PATH (the helper would fail anyway,
and CI without coreutils wouldn't have anything to test against).
"""
from __future__ import annotations

import shutil
import tarfile
from pathlib import Path
from typing import Optional

import pytest

from nos_workflow.runners.schism_ufs.context import SchismRunContext
from nos_workflow.runners.schism_ufs.forcing import (
    _NWM_PAYLOAD_NAMES,
    _OBC_PAYLOAD_NAMES,
    _RIVER_PAYLOAD_NAMES,
    untar_nwm_source_sink,
    untar_obc_forcing,
    untar_river_forcing,
)

# Skip the module if tar isn't on PATH -- the helpers shell out to it.
_TAR_PATH = shutil.which("tar")
pytestmark = pytest.mark.skipif(
    _TAR_PATH is None,
    reason="tar not on PATH; forcing extraction tests need tar(1)",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_ctx(
    tmp_path: Path,
    *,
    phase: str = "nowcast",
    obc_nowcast: Optional[str] = None,
    obc_forecast: Optional[str] = None,
    nwm_nowcast: Optional[str] = None,
    nwm_forecast: Optional[str] = None,
    river: Optional[str] = None,
) -> SchismRunContext:
    """Construct a :class:`SchismRunContext` for forcing tests."""
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    for p in (comout, data):
        p.mkdir(parents=True, exist_ok=True)
    return SchismRunContext(
        comout=comout,
        data=data,
        phase=phase,
        run="nos.secofs_ufs",
        cycle="t00z",
        obc_forcing_file_nowcast=obc_nowcast,
        obc_forcing_file_forecast=obc_forecast,
        nwm_source_sink_nowcast=nwm_nowcast,
        nwm_source_sink_forecast=nwm_forecast,
        river_forcing_file=river,
    )


def _build_tar(
    tar_path: Path,
    files: dict,
) -> None:
    """Build a flat tarball at ``tar_path`` containing each
    ``{name: bytes-content}`` entry as a regular file at the top level
    (no directory prefix -- matches the shell's ``tar xf ... -C $DATA``
    extraction layout where everything lands at $DATA/<name>)."""
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "w") as tf:
        for name, content in files.items():
            data = content if isinstance(content, bytes) else content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            import io
            tf.addfile(info, io.BytesIO(data))


# ---------------------------------------------------------------------------
# untar_obc_forcing
# ---------------------------------------------------------------------------


def test_untar_obc_forcing_extracts_expected_files(tmp_path):
    """A tar with all 6 OBC payload files extracts them into $DATA."""
    ctx = _make_ctx(tmp_path, phase="nowcast", obc_nowcast="obc_nowcast.tar")
    payload = {name: f"contents of {name}" for name in _OBC_PAYLOAD_NAMES}
    _build_tar(ctx.comout / "obc_nowcast.tar", payload)

    n = untar_obc_forcing(ctx, "nowcast")

    assert n == 6  # all six payload files present
    for name in _OBC_PAYLOAD_NAMES:
        dst = ctx.data / name
        assert dst.is_file(), f"missing {name}"
        assert dst.read_text() == f"contents of {name}"


def test_untar_obc_forcing_missing_tar_returns_negative_one(tmp_path):
    """No tar => return -1 (non-fatal sentinel, not an exception)."""
    ctx = _make_ctx(
        tmp_path, phase="nowcast", obc_nowcast="absent_obc.tar",
    )
    n = untar_obc_forcing(ctx, "nowcast")
    assert n == -1


def test_untar_obc_forcing_empty_field_returns_negative_one(tmp_path):
    """Empty context field => return -1 (no work done)."""
    ctx = _make_ctx(tmp_path, phase="nowcast")  # no obc_nowcast set
    n = untar_obc_forcing(ctx, "nowcast")
    assert n == -1


def test_untar_obc_forcing_forecast_phase_uses_forecast_field(tmp_path):
    """``phase='forecast'`` reads ``obc_forcing_file_forecast``."""
    ctx = _make_ctx(
        tmp_path, phase="forecast",
        obc_nowcast="obc_nowcast.tar",   # should NOT be used
        obc_forecast="obc_forecast.tar",
    )
    # Build only the forecast tar.
    payload = {name: b"x" for name in _OBC_PAYLOAD_NAMES[:3]}
    _build_tar(ctx.comout / "obc_forecast.tar", payload)

    n = untar_obc_forcing(ctx, "forecast")

    assert n == 3
    # The nowcast tar was never built -- verify the function used the
    # forecast field and didn't accidentally fall back to nowcast.
    assert not (ctx.data / "obc_nowcast.tar").exists()


def test_untar_obc_forcing_unknown_phase_raises(tmp_path):
    """``phase='post'`` => ValueError."""
    ctx = _make_ctx(tmp_path)
    with pytest.raises(ValueError, match="unknown phase"):
        untar_obc_forcing(ctx, "post")


def test_untar_obc_forcing_partial_payload_counts_correctly(tmp_path):
    """A tar with only 2 of 6 payload files returns 2."""
    ctx = _make_ctx(tmp_path, phase="nowcast", obc_nowcast="obc_partial.tar")
    payload = {
        "elev2D.th.nc": b"elev",
        "TEM_3D.th.nc": b"tem",
        # ... rest absent
    }
    _build_tar(ctx.comout / "obc_partial.tar", payload)

    n = untar_obc_forcing(ctx, "nowcast")
    assert n == 2


def test_untar_obc_forcing_falls_back_to_combined_tar_when_phase_absent(
        tmp_path):
    """When the phase-specific OBC tar is absent in $COMOUT but the legacy
    combined ``{base}.obc.tar`` is present, ``untar_obc_forcing`` falls
    back to extracting the combined tar. Keeps backward-compat with prep
    runs that predate the phase-specific split.
    """
    base = "nos.secofs_ufs.t00z.20260512"
    ctx = _make_ctx(
        tmp_path, phase="forecast",
        obc_nowcast=f"{base}.obc.nowcast.tar",
        obc_forecast=f"{base}.obc.forecast.tar",
    )
    # Only seed the combined tar -- not the phase-specific forecast tar.
    payload = {name: f"combined {name}".encode() for name in _OBC_PAYLOAD_NAMES}
    _build_tar(ctx.comout / f"{base}.obc.tar", payload)

    n = untar_obc_forcing(ctx, "forecast")

    assert n == 6, "fallback to combined tar should extract all 6 payload files"
    # All payload files extracted from the combined tar.
    for name in _OBC_PAYLOAD_NAMES:
        assert (ctx.data / name).read_bytes() == f"combined {name}".encode()


def test_untar_obc_forcing_phase_specific_preferred_over_combined(tmp_path):
    """When BOTH the phase-specific and combined tars exist, the
    phase-specific one is used (no fallback triggered)."""
    base = "nos.secofs_ufs.t00z.20260512"
    ctx = _make_ctx(
        tmp_path, phase="forecast",
        obc_nowcast=f"{base}.obc.nowcast.tar",
        obc_forecast=f"{base}.obc.forecast.tar",
    )
    # Phase-specific payload carries a distinguishable marker.
    phase_payload = {
        name: f"phase-specific {name}".encode() for name in _OBC_PAYLOAD_NAMES
    }
    combined_payload = {
        name: f"combined {name}".encode() for name in _OBC_PAYLOAD_NAMES
    }
    _build_tar(ctx.comout / f"{base}.obc.forecast.tar", phase_payload)
    _build_tar(ctx.comout / f"{base}.obc.tar", combined_payload)

    n = untar_obc_forcing(ctx, "forecast")

    assert n == 6
    # Phase-specific contents should win; combined tar untouched.
    for name in _OBC_PAYLOAD_NAMES:
        assert (ctx.data / name).read_bytes() == (
            f"phase-specific {name}".encode()
        )


def test_untar_obc_forcing_no_fallback_when_field_is_legacy_combined(tmp_path):
    """If the context's OBC field is already a legacy ``{base}.obc.tar``
    name (not ``{base}.obc.{phase}.tar``), the fallback derivation must
    not synthesize a degenerate retry against the same path."""
    base = "nos.secofs_ufs.t00z.20260512"
    ctx = _make_ctx(
        tmp_path, phase="nowcast",
        # Legacy form -- both fields point at the combined tar.
        obc_nowcast=f"{base}.obc.tar",
        obc_forecast=f"{base}.obc.tar",
    )
    payload = {name: b"x" for name in _OBC_PAYLOAD_NAMES[:1]}
    _build_tar(ctx.comout / f"{base}.obc.tar", payload)

    n = untar_obc_forcing(ctx, "nowcast")
    assert n == 1


# ---------------------------------------------------------------------------
# untar_nwm_source_sink
# ---------------------------------------------------------------------------


def test_untar_nwm_source_sink_nowcast_phase_uses_nowcast_field(tmp_path):
    """nowcast phase reads ``nwm_source_sink_nowcast`` field."""
    ctx = _make_ctx(
        tmp_path, phase="nowcast",
        nwm_nowcast="nwm_nowcast.tar",
        nwm_forecast="nwm_forecast.tar",  # should NOT be used
    )
    payload = {name: b"data" for name in _NWM_PAYLOAD_NAMES}
    _build_tar(ctx.comout / "nwm_nowcast.tar", payload)

    n = untar_nwm_source_sink(ctx, "nowcast")

    assert n == 4
    for name in _NWM_PAYLOAD_NAMES:
        assert (ctx.data / name).is_file()
    # Forecast tar was never built -- verify nowcast field was used.
    assert not (ctx.data / "nwm_forecast.tar").exists()


def test_untar_nwm_source_sink_forecast_phase_uses_forecast_field(tmp_path):
    """forecast phase reads ``nwm_source_sink_forecast`` field."""
    ctx = _make_ctx(
        tmp_path, phase="forecast",
        nwm_nowcast="nwm_nowcast.tar",  # should NOT be used
        nwm_forecast="nwm_forecast.tar",
    )
    payload = {name: b"fcdata" for name in _NWM_PAYLOAD_NAMES}
    _build_tar(ctx.comout / "nwm_forecast.tar", payload)

    n = untar_nwm_source_sink(ctx, "forecast")

    assert n == 4
    assert not (ctx.data / "nwm_nowcast.tar").exists()


def test_untar_nwm_source_sink_missing_tar_returns_negative_one(tmp_path):
    """Missing tar => -1 sentinel; FIXofs fallback runs later."""
    ctx = _make_ctx(
        tmp_path, phase="nowcast", nwm_nowcast="absent_nwm.tar",
    )
    n = untar_nwm_source_sink(ctx, "nowcast")
    assert n == -1


def test_untar_nwm_source_sink_empty_field_returns_negative_one(tmp_path):
    """No nwm_source_sink_nowcast field => -1."""
    ctx = _make_ctx(tmp_path, phase="nowcast")
    n = untar_nwm_source_sink(ctx, "nowcast")
    assert n == -1


def test_untar_nwm_source_sink_unknown_phase_raises(tmp_path):
    """phase != nowcast/forecast => ValueError."""
    ctx = _make_ctx(tmp_path)
    with pytest.raises(ValueError, match="unknown phase"):
        untar_nwm_source_sink(ctx, "post")


# ---------------------------------------------------------------------------
# untar_river_forcing
# ---------------------------------------------------------------------------


def test_untar_river_forcing_extracts_all_payload(tmp_path):
    """All three river-forcing files extracted when tar is present."""
    ctx = _make_ctx(tmp_path, phase="nowcast", river="river.tar")
    payload = {name: f"river {name}" for name in _RIVER_PAYLOAD_NAMES}
    _build_tar(ctx.comout / "river.tar", payload)

    n = untar_river_forcing(ctx, "nowcast")

    assert n == 3
    for name in _RIVER_PAYLOAD_NAMES:
        assert (ctx.data / name).read_text() == f"river {name}"


def test_untar_river_forcing_optional_missing_is_nonfatal(tmp_path):
    """River tar is optional -- missing => -1, no exception."""
    ctx = _make_ctx(tmp_path, phase="nowcast", river="absent_river.tar")
    n = untar_river_forcing(ctx, "nowcast")
    assert n == -1


def test_untar_river_forcing_no_field_returns_negative_one(tmp_path):
    """No river_forcing_file field => -1."""
    ctx = _make_ctx(tmp_path, phase="nowcast")  # no river field
    n = untar_river_forcing(ctx, "nowcast")
    assert n == -1


def test_untar_river_forcing_phase_agnostic(tmp_path):
    """Forecast phase uses the same ``river_forcing_file`` field."""
    ctx = _make_ctx(tmp_path, phase="forecast", river="river.tar")
    payload = {name: b"x" for name in _RIVER_PAYLOAD_NAMES}
    _build_tar(ctx.comout / "river.tar", payload)

    n = untar_river_forcing(ctx, "forecast")
    assert n == 3
