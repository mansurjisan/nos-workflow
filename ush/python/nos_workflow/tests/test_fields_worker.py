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


def _write_combined_schout(
    path: Path,
    hours: "list[int]",
    n_nodes: int = 4,
    with_vectors: bool = False,
    nvrt: int = 3,
) -> None:
    """Minimal combined OLDIO stack: elev + time, as combine_output11 emits.

    ``with_vectors`` adds the OLDIO vector/3D variables (hvel,
    wind_speed, zcor, temp) in the combiner's (time, layers, node)
    layout with a trailing size-2 component axis for the vectors.
    """
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", n_nodes)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-10 00:00:00"
        tv[:] = [h * 3600.0 for h in hours]
        ev = ds.createVariable("elev", "f4", ("time", "nSCHISM_hgrid_node"))
        ev[:] = 0.25
        if with_vectors:
            ds.createDimension("nSCHISM_vgrid_layers", nvrt)
            ds.createDimension("two", 2)
            zc = ds.createVariable(
                "zcor", "f4",
                ("time", "nSCHISM_vgrid_layers", "nSCHISM_hgrid_node"),
            )
            zc[:] = -1.5
            tp = ds.createVariable(
                "temp", "f4",
                ("time", "nSCHISM_vgrid_layers", "nSCHISM_hgrid_node"),
            )
            tp[:] = 20.0
            hv = ds.createVariable(
                "hvel", "f4",
                ("time", "nSCHISM_vgrid_layers", "nSCHISM_hgrid_node", "two"),
            )
            hv[..., 0] = 0.5
            hv[..., 1] = -0.5
            ws = ds.createVariable(
                "wind_speed", "f4",
                ("time", "nSCHISM_hgrid_node", "two"),
            )
            ws[..., 0] = 3.0
            ws[..., 1] = -3.0


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


def test_combined_schout_vector_variables_split(tmp_path):
    """OLDIO vector/3D variables (hvel, wind_speed, zcor, temp) publish
    as the scribe-named families instead of being silently dropped."""
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_combined_schout(
        staging / "schout_1.nc", hours=[1, 2, 3], with_vectors=True
    )

    result = _run_worker(staging, comout, "nowcast", tmp_path)

    names = sorted(Path(p).name for p in result["created"])
    stem = "secofs.t00z.20260710.fields"
    assert f"{stem}.horizontalVelX.n001_003.nc" in names
    assert f"{stem}.horizontalVelY.n001_003.nc" in names
    assert f"{stem}.zCoordinates.n001_003.nc" in names
    assert f"{stem}.temperature.n001_003.nc" in names

    import numpy as np
    with netCDF4.Dataset(
        comout / f"{stem}.horizontalVelX.n001_003.nc"
    ) as ds:
        assert np.allclose(ds["horizontalVelX"][:], 0.5)
    with netCDF4.Dataset(
        comout / f"{stem}.horizontalVelY.n001_003.nc"
    ) as ds:
        assert np.allclose(ds["horizontalVelY"][:], -0.5)
    # Wind components land inside the out2d product.
    with netCDF4.Dataset(comout / f"{stem}.out2d.n001_003.nc") as ds:
        assert np.allclose(ds["windSpeedX"][:], 3.0)
        assert np.allclose(ds["windSpeedY"][:], -3.0)


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


def test_forecast_labels_phase_relative_continued_clock(tmp_path):
    """STOFS-3D-ATL standalone: the forecast leg continues the nowcast
    clock, so raw stack times start at hour 25. Labels must still be
    phase-relative (f001_012...), matching ops and SECOFS."""
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    # stacks 3 and 4 of a continued 24 h clock: hours 25-36 and 37-48
    _write_split_stack(staging / "out2d_3.nc", hours=list(range(25, 37)))
    _write_split_stack(staging / "out2d_4.nc", hours=list(range(37, 49)))

    result = fields.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "stofs_3d_atl_ufs", "--cyc", "12", "--pdy", "20260722",
        "--phase", "forecast", "--nowcast-hours", "24",
        "--result-json", str(tmp_path / "r.json"),
    ])
    assert result == 0
    names = sorted(p.name for p in comout.glob("*.nc"))
    assert names == [
        "stofs_3d_atl_ufs.t12z.20260722.fields.out2d.f001_012.nc",
        "stofs_3d_atl_ufs.t12z.20260722.fields.out2d.f013_024.nc",
    ]


def test_forecast_labels_unshifted_when_clock_restarts(tmp_path):
    """SECOFS: the forecast leg restarts the clock near zero, so no
    shift is applied even though --nowcast-hours is passed."""
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_split_stack(staging / "out2d_1.nc", hours=[1, 2, 3, 4, 5, 6])

    result = fields.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
        "--phase", "forecast", "--nowcast-hours", "6",
        "--result-json", str(tmp_path / "r.json"),
    ])
    assert result == 0
    assert (comout / "secofs.t00z.20260710.fields.out2d.f001_006.nc").is_file()


def test_nowcast_labels_never_shifted(tmp_path):
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_split_stack(staging / "out2d_1.nc", hours=list(range(1, 13)))

    result = fields.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "stofs_3d_atl_ufs", "--cyc", "12", "--pdy", "20260722",
        "--phase", "nowcast", "--nowcast-hours", "24",
        "--result-json", str(tmp_path / "r.json"),
    ])
    assert result == 0
    assert (comout / "stofs_3d_atl_ufs.t12z.20260722.fields.out2d.n001_012.nc").is_file()


def _write_compressed_stack(path: Path, hours: "list[int]", n_nodes: int = 64):
    """A stack SCHISM already deflated, as the 3D scribe files arrive."""
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", n_nodes)
        ds.createDimension("nSCHISM_vgrid_layers", 8)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-10 00:00:00"
        tv[:] = [h * 3600.0 for h in hours]
        vv = ds.createVariable(
            "temperature", "f4",
            ("time", "nSCHISM_hgrid_node", "nSCHISM_vgrid_layers"),
            zlib=True, complevel=4,
        )
        vv[:] = 20.0


def test_deflate_off_by_default_publishes_uncompressed(tmp_path):
    """The default matches ops, which publishes these stacks as-is."""
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_split_stack(staging / "out2d_1.nc", hours=[1, 2])

    result = _run_worker(staging, comout, "nowcast", tmp_path)

    published = Path(result["created"][0])
    with netCDF4.Dataset(published) as ds:
        assert not (ds["elevation"].filters() or {}).get("zlib")


def test_deflate_compresses_raw_stacks_preserving_values(tmp_path):
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_split_stack(staging / "out2d_1.nc", hours=[1, 2], n_nodes=512)

    with netCDF4.Dataset(staging / "out2d_1.nc") as ds:
        expected = ds["elevation"][...]

    rc = fields.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
        "--phase", "nowcast", "--deflate", "1",
        "--result-json", str(tmp_path / "r.json"),
    ])
    assert rc == 0

    published = comout / "secofs.t00z.20260710.fields.out2d.n001_002.nc"
    with netCDF4.Dataset(published) as ds:
        assert (ds["elevation"].filters() or {}).get("zlib")
        assert (ds["elevation"].filters() or {}).get("complevel") == 1
        assert (ds["elevation"][...] == expected).all()
        # Still a published product, not just a repacked file.
        assert ds.getncattr("product") == "fields_nc"


def test_deflate_links_stacks_schism_already_compressed(tmp_path):
    """Repacking an already-deflated stack costs a full rewrite to save
    nothing, so those are linked through even with --deflate on."""
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    src = staging / "temperature_1.nc"
    _write_compressed_stack(src, hours=[1, 2])

    rc = fields.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
        "--phase", "nowcast", "--deflate", "1",
        "--result-json", str(tmp_path / "r.json"),
    ])
    assert rc == 0

    published = comout / "secofs.t00z.20260710.fields.temperature.n001_002.nc"
    assert published.stat().st_ino == src.stat().st_ino
    with netCDF4.Dataset(published) as ds:
        assert (ds["temperature"].filters() or {}).get("complevel") == 4


def test_deflate_leaves_nothing_behind_when_repack_fails(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_split_stack(staging / "out2d_1.nc", hours=[1, 2], n_nodes=512)

    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(fields, "_repack_kwargs", boom)

    with pytest.raises(RuntimeError):
        fields.main([
            "--staging", str(staging), "--comout", str(comout),
            "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
            "--phase", "nowcast", "--deflate", "1",
            "--result-json", str(tmp_path / "r.json"),
        ])

    assert list(comout.iterdir()) == []


def test_deflate_preserves_a_classic_data_model(tmp_path):
    """Repacking is a storage change, not a format change: a
    NETCDF4_CLASSIC stack (what ops' SECOFS writer produces) must not be
    silently promoted to the full netCDF-4 model."""
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    src = staging / "out2d_1.nc"
    with netCDF4.Dataset(src, "w", format="NETCDF4_CLASSIC") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", 512)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-10 00:00:00"
        tv[:] = [3600.0, 7200.0]
        ds.createVariable(
            "elevation", "f4", ("time", "nSCHISM_hgrid_node")
        )[:] = 0.5

    rc = fields.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
        "--phase", "nowcast", "--deflate", "1",
        "--result-json", str(tmp_path / "r.json"),
    ])
    assert rc == 0

    published = comout / "secofs.t00z.20260710.fields.out2d.n001_002.nc"
    with netCDF4.Dataset(published) as ds:
        assert ds.data_model == "NETCDF4_CLASSIC"
        assert (ds["elevation"].filters() or {}).get("zlib")


@pytest.mark.parametrize("bad", ["10", "-1", "99", "notanumber"])
def test_deflate_rejects_out_of_range_levels(bad, tmp_path, capsys):
    """netCDF4 raises from inside createVariable on a bad level, naming
    nothing useful; catch it at the CLI instead."""
    with pytest.raises(SystemExit):
        fields.main([
            "--staging", str(tmp_path), "--comout", str(tmp_path),
            "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
            "--phase", "nowcast", "--deflate", bad,
        ])
    assert "--deflate" in capsys.readouterr().err


@pytest.mark.parametrize("level", ["0", "9"])
def test_deflate_accepts_the_range_bounds(level):
    args = fields._parse_args([
        "--staging", "s", "--comout", "c", "--prefix", "p",
        "--cyc", "00", "--pdy", "20260710", "--phase", "nowcast",
        "--deflate", level,
    ])
    assert args.deflate == int(level)
