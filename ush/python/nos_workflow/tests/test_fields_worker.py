"""Tests for the fields_nc worker (nos_workflow.post.products.fields).

Uses real (tiny) NetCDF fixtures; the combined-schout case exercises the
actual ``convert_schout_to_split()`` from ``ush/schism_combine_outputs.py``
so the OLDIO -> canonical chain is covered end-to-end at unit scale.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

netCDF4 = pytest.importorskip("netCDF4")

from nos_workflow.post.products import fields  # noqa: E402

_REPO_USH = Path(__file__).resolve().parents[3]
_COMBINE_SCRIPT = _REPO_USH / "schism_combine_outputs.py"


def _write_split_stack(
    path: Path, hours: "list[int]", var: str = "elevation", n_nodes: int = 4
) -> None:
    """Minimal scribe-shaped stack: time (seconds) + one (time, node) var."""
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", n_nodes)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-10 00:00:00"
        tv[:] = [h * 3600.0 for h in hours]
        vv = ds.createVariable(var, "f4", ("time", "nSCHISM_hgrid_node"))
        vv[:] = 0.5


def _write_combined_schout(path: Path, hours: "list[int]", n_nodes: int = 4) -> None:
    """Minimal combined OLDIO stack: elev + time, as combine_output11 emits."""
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", n_nodes)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-10 00:00:00"
        tv[:] = [h * 3600.0 for h in hours]
        ev = ds.createVariable("elev", "f4", ("time", "nSCHISM_hgrid_node"))
        ev[:] = 0.25


def _run_worker(staging: Path, comout: Path, phase: str, tmp_path: Path) -> dict:
    result_json = tmp_path / "result.json"
    rc = fields.main([
        "--staging", str(staging),
        "--comout", str(comout),
        "--prefix", "secofs",
        "--cyc", "00",
        "--pdy", "20260710",
        "--phase", phase,
        "--combine-script", str(_COMBINE_SCRIPT),
        "--result-json", str(result_json),
    ])
    assert rc == 0
    return json.loads(result_json.read_text())


def test_publishes_split_stacks_with_hour_ranges(tmp_path):
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_split_stack(staging / "out2d_1.nc", hours=[1, 2, 3, 4, 5, 6])
    _write_split_stack(staging / "out2d_2.nc", hours=[7, 8])
    _write_split_stack(
        staging / "temperature_1.nc", hours=[1, 2, 3, 4, 5, 6],
        var="temperature",
    )

    result = _run_worker(staging, comout, "nowcast", tmp_path)

    names = sorted(Path(p).name for p in result["created"])
    assert names == [
        "secofs.t00z.20260710.fields.out2d.n001_006.nc",
        "secofs.t00z.20260710.fields.out2d.n007_008.nc",
        "secofs.t00z.20260710.fields.temperature.n001_006.nc",
    ]
    for p in result["created"]:
        assert Path(p).is_file()

    with netCDF4.Dataset(result["created"][0]) as ds:
        assert ds.getncattr("ofs") == "secofs"
        assert ds.getncattr("cycle") == "t00z"
        assert ds.getncattr("phase") == "nowcast"
        assert ds.getncattr("product") == "fields_nc"


def test_empty_stack_is_skipped(tmp_path):
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_split_stack(staging / "out2d_1.nc", hours=[1, 2])
    _write_split_stack(staging / "out2d_2.nc", hours=[])

    result = _run_worker(staging, comout, "forecast", tmp_path)

    names = [Path(p).name for p in result["created"]]
    assert names == ["secofs.t00z.20260710.fields.out2d.f001_002.nc"]


def test_combined_schout_is_split_then_published(tmp_path):
    """OLDIO chain: combined schout_1.nc -> convert_schout_to_split()
    (the real deployed converter) -> canonical out2d product."""
    assert _COMBINE_SCRIPT.is_file(), _COMBINE_SCRIPT
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_combined_schout(staging / "schout_1.nc", hours=[1, 2, 3])

    result = _run_worker(staging, comout, "forecast", tmp_path)

    names = [Path(p).name for p in result["created"]]
    assert "secofs.t00z.20260710.fields.out2d.f001_003.nc" in names
    # The converter dropped the split file into the staging dir.
    assert (staging / "out2d_1.nc").is_file()


def test_multi_stack_combined_schout_labels(tmp_path):
    """Two combined stacks split and publish with per-stack hour ranges."""
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_combined_schout(staging / "schout_1.nc", hours=[1, 2, 3])
    _write_combined_schout(staging / "schout_2.nc", hours=[4, 5, 6])

    result = _run_worker(staging, comout, "forecast", tmp_path)

    names = sorted(Path(p).name for p in result["created"])
    assert names == [
        "secofs.t00z.20260710.fields.out2d.f001_003.nc",
        "secofs.t00z.20260710.fields.out2d.f004_006.nc",
    ]


def test_rerun_resplits_changed_schout(tmp_path):
    """A rerun after the combined schout changed must republish fresh
    values, not reuse the stale split files from the prior run."""
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_combined_schout(staging / "schout_1.nc", hours=[1, 2])
    first = _run_worker(staging, comout, "nowcast", tmp_path)

    # Re-forecast: same stack index, different content.
    _write_combined_schout(staging / "schout_1.nc", hours=[1, 2, 3])
    second = _run_worker(staging, comout, "nowcast", tmp_path)

    names = [Path(p).name for p in second["created"]]
    assert "secofs.t00z.20260710.fields.out2d.n001_003.nc" in names
    assert first["created"] != second["created"]


def test_missing_staging_dir_fails(tmp_path):
    rc = fields.main([
        "--staging", str(tmp_path / "nope"),
        "--comout", str(tmp_path),
        "--prefix", "secofs",
        "--cyc", "00",
        "--pdy", "20260710",
        "--phase", "nowcast",
    ])
    assert rc == 2


def test_rerun_is_idempotent(tmp_path):
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_split_stack(staging / "out2d_1.nc", hours=[1, 2])

    first = _run_worker(staging, comout, "nowcast", tmp_path)
    second = _run_worker(staging, comout, "nowcast", tmp_path)
    assert first["created"] == second["created"]
    assert Path(first["created"][0]).is_file()
