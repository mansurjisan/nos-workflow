"""Tests for the ``nos_uw`` CLI dispatcher and bash_compat helpers.

These don't depend on Agent B's registry or Agent C's yaml_to_env. Tests
that need those modules are marked xfail so they're a TODO list rather
than dead code.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from nos_workflow.bash_compat import cyc_str, preserve_preload
from nos_workflow.cli import build_parser, main
from nos_workflow.errors import ConfigError, OFSNotRegisteredError


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as info:
        parser.parse_args(["--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    # Spot-check that every subcommand we ship is named in --help.
    for sub in ("run", "list", "stages", "validate", "env"):
        assert sub in out


def test_module_help_runs_clean() -> None:
    """``python -m nos_workflow --help`` exits 0 and prints something."""
    proc = subprocess.run(
        [sys.executable, "-m", "nos_workflow", "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "nos_uw" in proc.stdout


def test_list_exits_zero() -> None:
    """``nos_uw list`` should exit 0 even before Agent B lands the registry."""
    rc = main(["list"])
    assert rc == 0


def test_run_without_ofs_emits_clean_fatal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No --ofs and no $OFS / $RUN should produce a one-line FATAL, not a stack trace."""
    rc = main(["run", "prep"])
    assert rc != 0
    out = capsys.readouterr().out
    assert out.startswith("FATAL:"), f"expected FATAL: prefix, got: {out!r}"
    # Operator-friendly: should NOT include a python traceback in stdout.
    assert "Traceback" not in out


def test_run_unknown_ofs_raises_ofs_not_registered() -> None:
    """Until Agent B lands the registry, run --ofs raises OFSNotRegisteredError."""
    os.environ["PDY"] = "20260510"
    os.environ["cyc"] = "12"
    os.environ["COMOUT"] = "/tmp/comout"
    os.environ["DATA"] = "/tmp/data"
    rc = main(["run", "prep", "--ofs", "secofs_ufs"])
    # Either a missing-registry import OFSNotRegisteredError (rc != 0)
    # OR a successful registry lookup that finds nothing (also rc != 0).
    # In both cases we want a clean FATAL exit.
    assert rc != 0


def test_cyc_zero_pad() -> None:
    """cyc=0 must always come out as '00'."""
    assert cyc_str(0) == "00"
    assert cyc_str("0") == "00"
    assert cyc_str("00") == "00"
    assert cyc_str(6) == "06"
    assert cyc_str("6") == "06"
    assert cyc_str(12) == "12"
    assert cyc_str("18") == "18"


def test_cyc_str_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        cyc_str(None)
    with pytest.raises(ValueError):
        cyc_str("")
    with pytest.raises(ValueError):
        cyc_str(24)
    with pytest.raises(ValueError):
        cyc_str("abc")


def test_preserve_preload_round_trip() -> None:
    """LD_PRELOAD save / unset / restore must round-trip cleanly."""
    sentinel = "/tmp/libnetcdff.so"
    os.environ["LD_PRELOAD"] = sentinel
    with preserve_preload():
        assert "LD_PRELOAD" not in os.environ
    assert os.environ.get("LD_PRELOAD") == sentinel


def test_preserve_preload_when_unset() -> None:
    """If LD_PRELOAD wasn't set, it stays unset after the context."""
    if "LD_PRELOAD" in os.environ:
        del os.environ["LD_PRELOAD"]
    with preserve_preload():
        assert "LD_PRELOAD" not in os.environ
    assert "LD_PRELOAD" not in os.environ


def test_preserve_preload_restores_on_exception() -> None:
    sentinel = "/usr/lib/libfoo.so"
    os.environ["LD_PRELOAD"] = sentinel
    with pytest.raises(RuntimeError):
        with preserve_preload():
            assert "LD_PRELOAD" not in os.environ
            raise RuntimeError("boom")
    assert os.environ.get("LD_PRELOAD") == sentinel


@pytest.mark.xfail(reason="Agent B has not landed the registry yet")
def test_run_dispatches_to_stage_module() -> None:
    """End-to-end happy path; will pass once Agent B's registry is in."""
    os.environ["PDY"] = "20260510"
    os.environ["cyc"] = "12"
    os.environ["COMOUT"] = "/tmp/comout"
    os.environ["DATA"] = "/tmp/data"
    rc = main(["run", "prep", "--ofs", "secofs_ufs"])
    assert rc == 0
