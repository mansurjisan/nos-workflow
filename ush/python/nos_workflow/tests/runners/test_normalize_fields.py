"""Tests for the OLDIO field-output normalization step."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from nos_workflow.runners.schism_ufs import normalize_fields
from nos_workflow.runners.schism_ufs.context import SchismRunContext


def _make_ctx(tmp_path: Path) -> SchismRunContext:
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    ushnos = tmp_path / "ush"
    for p in (comout, data, ushnos):
        p.mkdir(parents=True, exist_ok=True)
    (ushnos / "nos_run.sh").write_text("# stub\n")
    return SchismRunContext(
        comout=comout, data=data, phase="nowcast",
        run="nos.secofs_ufs", cycle="t00z", ushnos=ushnos,
    )


def _env(tmp_path: Path, flag: str) -> dict:
    return {
        "NOS_ARCHIVE_FIELDS": flag,
        "USHnos": str(tmp_path / "ush"),
        "OFS_CONFIG": "",
    }


def test_flag_off_is_noop(tmp_path):
    ctx = _make_ctx(tmp_path)
    (ctx.data / "outputs").mkdir()
    (ctx.data / "outputs" / "schout_000000_1.nc").write_bytes(b"x")

    with patch.dict(os.environ, _env(tmp_path, "no"), clear=False):
        with patch.object(normalize_fields, "run_shell_function") as rsf:
            rc = normalize_fields.normalize_field_outputs(ctx, "nowcast")

    assert rc == 0
    rsf.assert_not_called()


def test_scribed_outputs_skip_combine(tmp_path):
    ctx = _make_ctx(tmp_path)
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "out2d_1.nc").write_bytes(b"x")
    (outputs / "schout_000000_1.nc").write_bytes(b"x")

    with patch.dict(os.environ, _env(tmp_path, "yes"), clear=False):
        with patch.object(normalize_fields, "run_shell_function") as rsf:
            rc = normalize_fields.normalize_field_outputs(ctx, "nowcast")

    assert rc == 0
    rsf.assert_not_called()


def test_per_rank_schout_dispatches_shell_combine(tmp_path):
    ctx = _make_ctx(tmp_path)
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "schout_000000_1.nc").write_bytes(b"x")
    (outputs / "schout_000001_1.nc").write_bytes(b"x")

    with patch.dict(os.environ, _env(tmp_path, "yes"), clear=False):
        with patch.object(
            normalize_fields, "run_shell_function", return_value=0
        ) as rsf:
            rc = normalize_fields.normalize_field_outputs(ctx, "forecast")

    assert rc == 0
    rsf.assert_called_once()
    kwargs = rsf.call_args.kwargs
    assert kwargs["function"] == "_schism_run_combine_fields"
    assert kwargs["args"] == ("forecast",)


def test_missing_outputs_dir_is_noop(tmp_path):
    ctx = _make_ctx(tmp_path)

    with patch.dict(os.environ, _env(tmp_path, "yes"), clear=False):
        with patch.object(normalize_fields, "run_shell_function") as rsf:
            rc = normalize_fields.normalize_field_outputs(ctx, "nowcast")

    assert rc == 0
    rsf.assert_not_called()


def test_combined_schout_alone_is_noop(tmp_path):
    """Already-combined ``schout_<stack>.nc`` needs no further combine."""
    ctx = _make_ctx(tmp_path)
    outputs = ctx.data / "outputs"
    outputs.mkdir()
    (outputs / "schout_1.nc").write_bytes(b"x")

    with patch.dict(os.environ, _env(tmp_path, "yes"), clear=False):
        with patch.object(normalize_fields, "run_shell_function") as rsf:
            rc = normalize_fields.normalize_field_outputs(ctx, "nowcast")

    assert rc == 0
    rsf.assert_not_called()


def test_per_rank_detection():
    assert normalize_fields._PER_RANK_SCHOUT_RE.match("schout_000000_12.nc")
    assert not normalize_fields._PER_RANK_SCHOUT_RE.match("schout_1.nc")
