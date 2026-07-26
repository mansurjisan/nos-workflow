"""A failed product write must leave nothing in COMOUT.

Writers open their output before filling it, so a mid-write raise used
to leave a structurally valid but truncated file under the PUBLISHED
name: the product reported "failed" with zero outputs while a consumer
globbing COMOUT read a product missing most of its variables. The
manifest and the directory disagreed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_NOS_UTILS = Path(__file__).resolve().parents[2] / "nos-utils"
if str(_NOS_UTILS) not in sys.path:
    sys.path.insert(0, str(_NOS_UTILS))

netCDF4 = pytest.importorskip("netCDF4")

from nos_workflow.post.worker_base import atomic_publish  # noqa: E402


def test_atomic_publish_removes_the_partial_on_failure(tmp_path):
    out = tmp_path / "product.nc"

    with pytest.raises(RuntimeError):
        with atomic_publish(out) as tmp:
            with netCDF4.Dataset(tmp, "w") as ds:
                ds.createDimension("x", 2)
                ds.createVariable("partial", "f4", ("x",))[:] = [1.0, 2.0]
            raise RuntimeError("writer failed after creating the file")

    assert not out.exists(), "published name must not exist after a failure"
    assert list(tmp_path.iterdir()) == [], "temp residue left behind"


def test_atomic_publish_moves_into_place_on_success(tmp_path):
    out = tmp_path / "product.nc"

    with atomic_publish(out) as tmp:
        with netCDF4.Dataset(tmp, "w") as ds:
            ds.createDimension("x", 2)
            ds.createVariable("v", "f4", ("x",))[:] = [3.0, 4.0]

    assert out.is_file()
    assert [p.name for p in tmp_path.iterdir()] == ["product.nc"]
    with netCDF4.Dataset(out) as ds:
        assert list(ds["v"][:]) == [3.0, 4.0]


def test_partial_is_invisible_to_a_glob_while_being_written(tmp_path):
    """The staging name is dotted, so a COMOUT poller cannot pick it up."""
    out = tmp_path / "product.nc"
    seen = []

    with atomic_publish(out) as tmp:
        tmp.write_bytes(b"partial")
        seen = sorted(p.name for p in tmp_path.glob("*.nc"))

    assert seen == [], "in-flight write matched a *.nc glob"
    assert out.is_file()


def test_points_cwl_leaves_nothing_when_the_writer_raises(tmp_path):
    """End-to-end: a staout whose station count disagrees with the CSV
    raises inside the writer, after the output has been created."""
    pytest.importorskip("nos_utils.post.stations")
    from nos_workflow.post.products import points_cwl

    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()

    defs = tmp_path / "defs.json"
    defs.write_text(json.dumps({
        "elev": {"name": "zeta", "long_name": "wl",
                 "stardard_name": "sea_surface_height", "units": "m",
                 "staout_fname": "staout_1"},
        "temp": {"name": "temperature", "long_name": "t",
                 "stardard_name": "t", "units": "C",
                 "staout_fname": "staout_5"},
    }))
    meta = tmp_path / "meta.csv"
    meta.write_text(";station_info;lat;lon\n" + "".join(
        f"{i};S{i} name;-70.{i};40.{i}\n" for i in range(4)))
    (staging / "staout_1").write_text(
        "".join(f"{t * 360.:.1f} 0.1 0.2 0.3 0.4\n" for t in (1, 2, 3)))
    # Three station columns where the CSV declares four.
    (staging / "staout_5").write_text(
        "".join(f"{t * 360.:.1f} 1.0 2.0 3.0\n" for t in (1, 2, 3)))

    with pytest.raises(ValueError):
        points_cwl.main([
            "--staging", str(staging), "--comout", str(comout),
            "--prefix", "p", "--cyc", "12", "--pdy", "20260722",
            "--phase", "forecast", "--base-date", "2026-07-22 06:00:00",
            "--var-defs", str(defs), "--station-meta", str(meta),
        ])

    assert list(comout.iterdir()) == [], (
        "a truncated product survived a failed write"
    )
