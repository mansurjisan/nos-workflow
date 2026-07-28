"""Tests for the geopkg worker (nos_workflow.post.products.geopkg).

Real (tiny) NetCDF fixtures on a 4-node/2-element mesh contoured through
the actual ``nos_utils.post.geopkg`` writer: the per-timestep canonical
names, the ops nowcast countdown, and the optional-dependency skip.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

gpd = pytest.importorskip("geopandas")
pytest.importorskip("matplotlib")
netCDF4 = pytest.importorskip("netCDF4")

# The repo's nos-utils submodule carries nos_utils.post; prefer it over
# any older nos_utils installed on the host.
_NOS_UTILS = Path(__file__).resolve().parents[2] / "nos-utils"
if str(_NOS_UTILS) not in sys.path:
    sys.path.insert(0, str(_NOS_UTILS))
pytest.importorskip("nos_utils.post.geopkg")

from nos_workflow.post.products import geopkg  # noqa: E402

X = [0.0, 1.0, 0.0, 1.0]
Y = [0.0, 0.0, 1.0, 1.0]
DEPTH = 5.0
ELEMS = [[1, 2, 3, -1], [2, 4, 3, -1]]


def _write_out2d(path: Path, hours) -> Path:
    """Scribe-shaped 2D stack: elevation + the mesh the contouring reads."""
    hours = list(hours)
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", 4)
        ds.createDimension("nSCHISM_hgrid_face", len(ELEMS))
        ds.createDimension("nMaxSCHISM_hgrid_face_nodes", 4)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-10 00:00:00"
        tv[:] = [h * 3600.0 for h in hours]
        ev = ds.createVariable(
            "elevation", "f8", ("time", "nSCHISM_hgrid_node")
        )
        for it, h in enumerate(hours):
            ev[it, :] = [0.2 + 0.4 * n + 0.01 * h for n in range(4)]
        ds.createVariable(
            "SCHISM_hgrid_node_x", "f8", ("nSCHISM_hgrid_node",)
        )[:] = X
        ds.createVariable(
            "SCHISM_hgrid_node_y", "f8", ("nSCHISM_hgrid_node",)
        )[:] = Y
        ds.createVariable("depth", "f8", ("nSCHISM_hgrid_node",))[:] = DEPTH
        fv = ds.createVariable(
            "SCHISM_hgrid_face_nodes", "i4",
            ("nSCHISM_hgrid_face", "nMaxSCHISM_hgrid_face_nodes"),
            fill_value=-1,
        )
        fv[:] = ELEMS
    return path


def _dirs(tmp_path: Path):
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    return staging, comout


def _run(staging: Path, comout: Path, tmp_path: Path, phase: str) -> dict:
    result_json = tmp_path / "gpkg_result.json"
    rc = geopkg.main([
        "--staging", str(staging),
        "--comout", str(comout),
        "--prefix", "secofs",
        "--cyc", "00",
        "--pdy", "20260710",
        "--phase", phase,
        "--result-json", str(result_json),
    ])
    assert rc == 0
    return json.loads(result_json.read_text())


def test_forecast_series_names_layer_and_crs(tmp_path):
    staging, comout = _dirs(tmp_path)
    _write_out2d(staging / "out2d_1.nc", hours=[1, 2])

    result = _run(staging, comout, tmp_path, "forecast")

    assert [Path(p).name for p in result["created"]] == [
        "secofs.t00z.20260710.disturbance.f001.gpkg",
        "secofs.t00z.20260710.disturbance.f002.gpkg",
    ]
    for p in result["created"]:
        assert Path(p).parent == comout
        assert list(gpd.list_layers(p)["name"]) == ["disturbance"]
        gdf = gpd.read_file(p, layer="disturbance")
        assert gdf.crs.to_epsg() == 4326
        assert len(gdf) >= 1
        assert set(gdf["verticalDatum"]) == {"XGEOID20B"}


def test_nowcast_numbering_counts_down_to_the_cycle_time(tmp_path):
    """Ops convention: the last nowcast record (the cycle time) is n000."""
    staging, comout = _dirs(tmp_path)
    _write_out2d(staging / "out2d_1.nc", hours=[1, 2])
    _write_out2d(staging / "out2d_2.nc", hours=[3, 4])

    result = _run(staging, comout, tmp_path, "nowcast")

    assert [Path(p).name for p in result["created"]] == [
        "secofs.t00z.20260710.disturbance.n003.gpkg",
        "secofs.t00z.20260710.disturbance.n002.gpkg",
        "secofs.t00z.20260710.disturbance.n001.gpkg",
        "secofs.t00z.20260710.disturbance.n000.gpkg",
    ]


def test_geometry_stack_unavailable_is_a_skip(tmp_path, capsys, monkeypatch):
    """geopandas/shapely/matplotlib missing at runtime warns and writes
    nothing -- it must not fail the worker."""
    import nos_utils.post.geopkg as nu_geopkg

    def boom(*args, **kwargs):
        raise ImportError("No module named 'geopandas'")

    monkeypatch.setattr(nu_geopkg, "write_disturbance_series", boom)

    staging, comout = _dirs(tmp_path)
    _write_out2d(staging / "out2d_1.nc", hours=[1, 2])

    result = _run(staging, comout, tmp_path, "forecast")

    assert result["created"] == []
    assert list(comout.glob("*.gpkg")) == []
    assert "geometry stack unavailable" in capsys.readouterr().out


def test_missing_staging_dir_returns_2(tmp_path):
    assert geopkg.main([
        "--staging", str(tmp_path / "nope"), "--comout", str(tmp_path),
        "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
        "--phase", "forecast",
    ]) == 2


def test_no_out2d_stacks_returns_3(tmp_path):
    staging, comout = _dirs(tmp_path)
    (staging / "temperature_1.nc").write_bytes(b"\x89HDF\r\n")
    assert geopkg.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
        "--phase", "forecast",
    ]) == 3


# ---------------------------------------------------------------------------
# Stage wiring (worker subprocess mocked)
# ---------------------------------------------------------------------------


def _post_env(tmp_path: Path) -> dict:
    from nos_workflow.tests.test_post_stage import _make_minimal_post_env

    env = _make_minimal_post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "geopkg"
    env["OFS_CONFIG"] = ""
    return env


def _run_stage(env: dict, fake_run):
    from nos_workflow.stages import post as post_stage
    from nos_workflow.tests.test_post_stage import _secofs_ufs_desc

    with patch.dict(os.environ, env, clear=False):
        with patch.object(post_stage.subprocess, "run", side_effect=fake_run):
            return post_stage.run(_secofs_ufs_desc(), object())


def _outputs_manifest(env: dict) -> dict:
    path = Path(env["COMOUT"]) / (
        f"{env['RUN']}.t{env['cyc']}z.{env['PDY']}.outputs.post.json"
    )
    return json.loads(path.read_text())


def test_product_runs_worker_per_staged_phase(tmp_path):
    env = _post_env(tmp_path)
    comout = Path(env["COMOUT"])
    for suffix in ("restart_outputs", "forecast_outputs"):
        staging = comout / f"{env['RUN']}.{env['cycle']}.{suffix}"
        staging.mkdir(parents=True)
        (staging / "out2d_1.nc").write_bytes(b"\x89HDF\r\n")

    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        args = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
        created = comout / (
            "nos.secofs_ufs.t00z.20260507.disturbance."
            f"{'n' if args['--phase'] == 'nowcast' else 'f'}001.gpkg"
        )
        created.write_bytes(b"GPKG")
        Path(args["--result-json"]).write_text(
            json.dumps({"created": [str(created)]})
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    assert _run_stage(env, fake_run) == 0
    assert len(calls) == 2
    assert all("nos_workflow.post.products.geopkg" in c for c in calls)
    assert [c[c.index("--phase") + 1] for c in calls] == [
        "nowcast", "forecast",
    ]
    by_name = {p["name"]: p for p in _outputs_manifest(env)["products"]}
    assert by_name["geopkg"]["status"] == "ok"
    assert by_name["geopkg"]["count"] == 2


def test_worker_writing_nothing_reads_as_skipped(tmp_path):
    """The optional-dependency path: the worker exits 0 having created
    nothing, and the product reports skipped rather than failed."""
    env = _post_env(tmp_path)
    staging = (
        Path(env["COMOUT"]) / f"{env['RUN']}.{env['cycle']}.forecast_outputs"
    )
    staging.mkdir(parents=True)
    (staging / "out2d_1.nc").write_bytes(b"\x89HDF\r\n")

    def fake_run(cmd, **kwargs):
        args = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
        Path(args["--result-json"]).write_text(json.dumps({"created": []}))
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    assert _run_stage(env, fake_run) == 0
    by_name = {p["name"]: p for p in _outputs_manifest(env)["products"]}
    assert by_name["geopkg"]["status"] == "skipped"
    # Detail comes from the shared empty_is_skipped path in worker_base;
    # assert the meaning, not the exact wording.
    assert "wrote nothing" in by_name["geopkg"]["detail"]


def test_naming_helper():
    from nos_workflow.post.naming import disturbance_gpkg_name

    assert disturbance_gpkg_name(
        "secofs", "00", "20260710", "nowcast", 0
    ) == "secofs.t00z.20260710.disturbance.n000.gpkg"
    assert disturbance_gpkg_name(
        "stofs_3d_atl_ufs", "12", "20260722", "forecast", 96
    ) == "stofs_3d_atl_ufs.t12z.20260722.disturbance.f096.gpkg"


def _write_empty_trailing_stack(path: Path) -> Path:
    """A leg's trailing stack as the model actually leaves it.

    The window closes before any record is written, so the file carries
    the mesh but no time records and no ``elevation`` variable at all --
    exactly what stack 2 (nowcast) and stack 9 (forecast) looked like on
    the 20260728 00z SECOFS cycle.
    """
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", 4)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-10 00:00:00"
    return path


def test_empty_trailing_stack_does_not_cost_the_phase_its_output(tmp_path):
    """One empty stack used to raise KeyError('elevation') out of the
    writer and zero the WHOLE phase, because every stack was handed
    through unfiltered."""
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    _write_out2d(staging / "out2d_1.nc", hours=range(1, 7))
    _write_empty_trailing_stack(staging / "out2d_2.nc")

    usable, dropped = geopkg._usable_out2d_stacks(
        geopkg._out2d_stacks(staging)
    )

    assert [p.name for p in usable] == ["out2d_1.nc"]
    assert len(dropped) == 1
    assert "out2d_2.nc" in dropped[0]
    # Named, never dropped silently.
    assert "skipped" in dropped[0]


def test_unreadable_stack_is_named_and_dropped(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    _write_out2d(staging / "out2d_1.nc", hours=range(1, 3))
    (staging / "out2d_2.nc").write_bytes(b"not a netcdf file")

    usable, dropped = geopkg._usable_out2d_stacks(
        geopkg._out2d_stacks(staging)
    )

    assert [p.name for p in usable] == ["out2d_1.nc"]
    assert "out2d_2.nc" in dropped[0] and "unreadable" in dropped[0]


def test_all_stacks_usable_drops_nothing(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    _write_out2d(staging / "out2d_1.nc", hours=range(1, 4))
    _write_out2d(staging / "out2d_2.nc", hours=range(4, 7))

    usable, dropped = geopkg._usable_out2d_stacks(
        geopkg._out2d_stacks(staging)
    )

    assert len(usable) == 2 and dropped == []


def test_geopkg_is_given_the_cores_the_job_has(tmp_path):
    """Serial contouring of a 1.69M-node mesh does not finish a cycle
    inside the post walltime; ops fanned the timesteps out."""
    from nos_workflow.post.registry import get_product
    from nos_workflow.stages.post import _post_max_workers

    # $NCPUS is what PBS allocated, not a preference, so anything asked
    # for explicitly outranks it.
    assert _post_max_workers({"NCPUS": "8"}, None) == "8"
    assert _post_max_workers({"NCPUS": "8"}, 4) == "4"
    assert _post_max_workers({"NCPUS": "8"}, "4") == "4"
    # Junk falls back rather than crashing the stage.
    assert _post_max_workers({"NCPUS": "8"}, "x") == "8"
    assert _post_max_workers({"NCPUS": "0"}, None) != "0"
    assert int(_post_max_workers({}, None)) >= 1

    from nos_workflow.post.base import ProductContext

    comout = tmp_path / "com"
    comout.mkdir(exist_ok=True)
    ctx = ProductContext(
        descriptor=None,
        shell_env={"NCPUS": "8", "LEN_NOWCAST": "6"},
        homenos=tmp_path,
        fixofs=tmp_path,
        comout=comout,
        data=tmp_path,
        pdy="20260728",
        cyc="00",
        cycle="t00z",
        run_name="secofs_ufs",
        prefix_nos="secofs_ufs",
        nc_hour="18",
        sta_in=tmp_path / "sta.in",
        combine_script=tmp_path / "combine.py",
        pgmout=str(tmp_path / "pgmout"),
    )
    staging = tmp_path / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    _write_out2d(staging / "out2d_1.nc", hours=range(1, 7))

    args = get_product("geopkg")().worker_args(
        ctx, "nowcast", staging, tmp_path
    )
    assert "--max-workers" in args
    assert args[args.index("--max-workers") + 1] == "8"
