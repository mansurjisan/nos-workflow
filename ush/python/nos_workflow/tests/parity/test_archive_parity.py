"""Parity test: archive.py (Python) vs _schism_archive_outputs (shell).

PR 2 ships a structural-equivalence test (file presence, naming).
Full byte-diff parity against a captured $DATA/outputs fixture needs
the parity-fixture infra coming in PR 5; this test will be extended
then. For now, we synthesize a fake outputs/ tree, run Python, and
verify the produced $COMOUT layout matches what _schism_archive_outputs
would have produced (per the shell's mkdir + cp pattern).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nos_workflow.runners.schism_ufs.archive import run_python
from nos_workflow.runners.schism_ufs.context import SchismRunContext


def _build_fake_outputs(data: Path, n_staout: int = 9) -> Path:
    outputs = data / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_staout + 1):
        (outputs / f"staout_{i}").write_text(f"staout {i} content\n")
    (outputs / "mirror.out").write_text("mirror content\n")
    (outputs / "flux.out").write_text("flux content\n")
    # Add files that should NOT be copied (the shell pattern is specific).
    (outputs / "hotstart_000000_0001.nc").write_bytes(b"\x89HDF\r\n")
    (outputs / "schout_000000_0001.nc").write_bytes(b"\x89HDF\r\n")
    return outputs


def test_archive_nowcast_layout_matches_shell_expectation(tmp_path):
    data = tmp_path / "data"
    comout = tmp_path / "comout"
    comout.mkdir(parents=True, exist_ok=True)
    _build_fake_outputs(data)

    ctx = SchismRunContext(
        comout=comout, data=data, phase="nowcast",
        run="nos.secofs_ufs", cycle="t00z",
    )
    rc = run_python(ctx, "nowcast")
    assert rc == 0

    target = comout / "nos.secofs_ufs.t00z.restart_outputs"
    assert target.is_dir()
    expected = {"staout_1", "staout_2", "staout_3", "staout_4", "staout_5",
                "staout_6", "staout_7", "staout_8", "staout_9",
                "mirror.out", "flux.out"}
    actual = {p.name for p in target.iterdir()}
    assert actual == expected, f"unexpected files copied: {actual ^ expected}"


def test_archive_forecast_uses_forecast_outputs_dir(tmp_path):
    data = tmp_path / "data"
    comout = tmp_path / "comout"
    comout.mkdir(parents=True, exist_ok=True)
    _build_fake_outputs(data, n_staout=3)

    ctx = SchismRunContext(
        comout=comout, data=data, phase="forecast",
        run="nos.secofs_ufs", cycle="t12z",
    )
    run_python(ctx, "forecast")
    assert (comout / "nos.secofs_ufs.t12z.forecast_outputs").is_dir()
    assert not (comout / "nos.secofs_ufs.t12z.restart_outputs").exists()
