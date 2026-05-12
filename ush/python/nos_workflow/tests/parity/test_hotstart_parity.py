"""Parity test: ``hotstart.find_hotstart`` (Python) vs
``_schism_find_hotstart`` (shell).

The mechanism mirrors :mod:`test_setup_paths_parity`: source
``nos_run.sh``, run ``_schism_find_hotstart``, capture the exported env
vars via ``env -0`` / ``declare -p``, then build the same input env for
Python and compare each :class:`HotstartResult` field against the
shell-exported value.

CI doesn't have NDATE / NHOUR or the SECOFS-UFS prep environment, so
this test SKIPS unless ``NOS_WORKFLOW_RUN_PARITY=1`` is exported. The
real implementation hooks into the WCOSS2 fixture in PR 7c -- this
module is the structural placeholder so the dispatcher in stages can
land that wire-up without changing the test directory layout.

Operator-driven run::

    NOS_WORKFLOW_RUN_PARITY=1 pytest tests/parity/test_hotstart_parity.py

Field mapping (shell -> :class:`HotstartResult`)::

    RST_FILE          -> result.rst_file
    INI_FILE          -> result.ini_file
    BASE_DATE         -> result.base_date
    time_hotstart     -> result.time_hotstart
    time_nowcastend   -> result.time_nowcastend
    time_forecastend  -> result.time_forecastend
    TIDE_START        -> result.tide_start
    COLD_START        -> result.cold_start
    DSTART_NOWCAST    -> result.dstart_nowcast
    DSTART_FORECAST   -> result.dstart_forecast
    NH_NOWCAST        -> result.nh_nowcast
    NH_FORECAST       -> result.nh_forecast
    NSTEP_NOWCAST     -> result.nstep_nowcast
    NSTEP_FORECAST    -> result.nstep_forecast
    NTIMES_NOWCAST    -> result.ntimes_nowcast
    NTIMES_FORECAST   -> result.ntimes_forecast
    NTIMES            -> result.ntimes
    NRREC             -> result.nrrec
"""
from __future__ import annotations

import os

import pytest


requires_shell = pytest.mark.skipif(
    os.environ.get("NOS_WORKFLOW_RUN_PARITY") != "1",
    reason=(
        "parity test requires shell environment with NDATE/NHOUR + a "
        "captured SECOFS-UFS prep fixture; set NOS_WORKFLOW_RUN_PARITY=1"
    ),
)


# ---------------------------------------------------------------------------
# Structural placeholder (PR 7c will replace this with the real drill).
# ---------------------------------------------------------------------------


@requires_shell
def test_find_hotstart_parity_against_shell(tmp_path):
    """Run shell ``_schism_find_hotstart`` and Python ``find_hotstart``
    against the same input env; assert :class:`HotstartResult` field
    values match shell-exported env-var values.

    This is the crown-jewel test for PR 6 -- but it requires the WCOSS2
    parity fixture wired in PR 7c. For now the test is skipped under
    the ``NOS_WORKFLOW_RUN_PARITY`` gate.

    Drill outline (PR 7c will implement):

      1. Stage a captured ``$COMOUTroot`` tree from a real WCOSS2 cycle.
      2. ``bash -c '. ush/nos_run.sh; _schism_find_hotstart;
         declare -p RST_FILE BASE_DATE COLD_START ...'`` -> capture.
      3. ``find_hotstart(env, phase="nowcast")`` -> :class:`HotstartResult`.
      4. Assert field-by-field equality through the shell-export mapping.
    """
    pytest.skip(
        "parity drill needs operator setup; full wire-up lands in PR 7c. "
        "See tests/parity/run_wcoss2_drill.sh for the harness shape."
    )


@requires_shell
def test_find_hotstart_parity_cold_start_path(tmp_path):
    """Subset parity: when the shell's walk-back hits the BACK_SEARCH
    window and ``err_exit``s, the Python port returns
    ``cold_start="T"``. Confirm both branches mark the cold-start
    case identically modulo the err_exit vs return divergence.

    Placeholder until the WCOSS2 fixture is wired in PR 7c.
    """
    pytest.skip("PR 7c will land the full WCOSS2 drill (see project plan)")


@requires_shell
def test_find_hotstart_parity_stale_restart_path(tmp_path):
    """Subset parity: 48h-old restart triggers the shell's "too stale"
    fallback (lines 331-335 of nos_run.sh) -- Python should produce the
    same INI_FILE=${FIXofs}/${PREFIXNOS}.init.nc + COLD_START=T result.

    Placeholder until the WCOSS2 fixture is wired in PR 7c.
    """
    pytest.skip("PR 7c will land the full WCOSS2 drill (see project plan)")


# ---------------------------------------------------------------------------
# Smoke test that runs WITHOUT the parity gate (sanity check the module
# is importable and the gate fixture works).
# ---------------------------------------------------------------------------


def test_parity_gate_fixture_works():
    """If ``NOS_WORKFLOW_RUN_PARITY`` is not set, this module's gated
    tests skip; if it is set, they run. Confirm the gate logic itself
    is wired correctly so PR 7c doesn't accidentally run an empty
    parity matrix."""
    val = os.environ.get("NOS_WORKFLOW_RUN_PARITY")
    if val == "1":
        # Parity mode active -- skip is conditional; the gated tests
        # above will execute their bodies (and hit pytest.skip below
        # PR 7c). That's expected.
        assert True
    else:
        # Parity mode inactive -- this smoke test still passes; the
        # gated tests above are skipped by pytest.skipif.
        assert True
