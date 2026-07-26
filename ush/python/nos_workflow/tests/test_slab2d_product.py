"""Tests for the slab2d worker (nos_workflow.post.products.slab2d).

Real (tiny) NetCDF fixtures on a 4-node/2-element mesh, run through the
actual ``nos_utils.post.slab2d`` writer: the vertical columns are
crafted so one interpolated velocity is exactly hand-checkable, and one
case drops a required family to pin the skip-the-index behavior.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

netCDF4 = pytest.importorskip("netCDF4")
import numpy as np  # noqa: E402

# The repo's nos-utils submodule carries nos_utils.post; prefer it over
# any older nos_utils installed on the host.
_NOS_UTILS = Path(__file__).resolve().parents[2] / "nos-utils"
if str(_NOS_UTILS) not in sys.path:
    sys.path.insert(0, str(_NOS_UTILS))
pytest.importorskip("nos_utils.post.slab2d")

from nos_workflow.post.products import slab2d  # noqa: E402

# 4-node unit square, two triangles, 5 m deep everywhere.
X = [0.0, 1.0, 0.0, 1.0]
Y = [0.0, 0.0, 1.0, 1.0]
DEPTH = 5.0
ELEMS = [[1, 2, 3, -1], [2, 4, 3, -1]]
KBP1 = 1  # 1-based bottom level: the whole column is active

# z levels (bottom -> surface) and velocities chosen so the 3 m target
# lands exactly halfway between levels 0 and 1: 0.5*1 + 0.5*3 = 2.0.
Z_LEVELS = [-4.0, -2.0, 0.0]
INTERP_DEPTH = 3.0
EXPECT_UVEL3 = 2.0


def _u(k: int) -> float:
    return 1.0 + 2.0 * k


def _t(node: int, k: int) -> float:
    return 10.0 * (node + 1) + k


def _write_out2d(path: Path, hours, n_nodes: int = 4) -> Path:
    """Scribe-shaped 2D stack incl. the mesh vars write_slab2d reads."""
    hours = list(hours)
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", n_nodes)
        ds.createDimension("nSCHISM_hgrid_face", len(ELEMS))
        ds.createDimension("nMaxSCHISM_hgrid_face_nodes", 4)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-10 00:00:00"
        tv[:] = [h * 3600.0 for h in hours]
        ev = ds.createVariable(
            "elevation", "f8", ("time", "nSCHISM_hgrid_node")
        )
        ev[:] = 0.0
        ds.createVariable(
            "SCHISM_hgrid_node_x", "f8", ("nSCHISM_hgrid_node",)
        )[:] = X[:n_nodes]
        ds.createVariable(
            "SCHISM_hgrid_node_y", "f8", ("nSCHISM_hgrid_node",)
        )[:] = Y[:n_nodes]
        ds.createVariable("depth", "f8", ("nSCHISM_hgrid_node",))[:] = DEPTH
        fv = ds.createVariable(
            "SCHISM_hgrid_face_nodes", "i4",
            ("nSCHISM_hgrid_face", "nMaxSCHISM_hgrid_face_nodes"),
            fill_value=-1,
        )
        fv[:] = ELEMS
        ds.createVariable(
            "bottom_index_node", "i4", ("nSCHISM_hgrid_node",)
        )[:] = KBP1
    return path


def _write_var3d(path: Path, var: str, hours, value_fn, n_nodes: int = 4):
    """Scribe-shaped 3D stack: (time, node, layer)."""
    hours = list(hours)
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", n_nodes)
        ds.createDimension("nSCHISM_vgrid_layers", len(Z_LEVELS))
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = "seconds since 2026-07-10 00:00:00"
        tv[:] = [h * 3600.0 for h in hours]
        vv = ds.createVariable(
            var, "f8",
            ("time", "nSCHISM_hgrid_node", "nSCHISM_vgrid_layers"),
        )
        for it in range(len(hours)):
            for n in range(n_nodes):
                vv[it, n, :] = [
                    value_fn(n, k) for k in range(len(Z_LEVELS))
                ]
    return path


def _seed_stack(staging: Path, index: int, hours, families=None) -> None:
    """Write one complete (or deliberately partial) stack index."""
    families = families or slab2d.SLAB_FAMILIES
    builders = {
        "out2d": lambda p: _write_out2d(p, hours),
        "zCoordinates": lambda p: _write_var3d(
            p, "zCoordinates", hours, lambda n, k: Z_LEVELS[k]
        ),
        "temperature": lambda p: _write_var3d(
            p, "temperature", hours, _t
        ),
        "salinity": lambda p: _write_var3d(
            p, "salinity", hours, lambda n, k: 30.0 + k
        ),
        "horizontalVelX": lambda p: _write_var3d(
            p, "horizontalVelX", hours, lambda n, k: _u(k)
        ),
        "horizontalVelY": lambda p: _write_var3d(
            p, "horizontalVelY", hours, lambda n, k: -_u(k)
        ),
    }
    for family in families:
        builders[family](staging / f"{family}_{index}.nc")


def _run(staging: Path, comout: Path, tmp_path: Path, *extra) -> dict:
    result_json = tmp_path / "slab_result.json"
    rc = slab2d.main([
        "--staging", str(staging),
        "--comout", str(comout),
        "--prefix", "secofs",
        "--cyc", "00",
        "--pdy", "20260710",
        "--phase", "nowcast",
        "--base-date", "2026-07-10 00:00",
        "--depths", str(INTERP_DEPTH),
        "--result-json", str(result_json),
        *extra,
    ])
    assert rc == 0
    return json.loads(result_json.read_text())


def _dirs(tmp_path: Path):
    staging = tmp_path / "staging"
    comout = tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    return staging, comout


def test_publishes_one_field2d_per_stack(tmp_path):
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1, 2])
    _seed_stack(staging, 2, hours=[3, 4])

    result = _run(staging, comout, tmp_path)

    assert [Path(p).name for p in result["created"]] == [
        "secofs.t00z.20260710.field2d.n001_002.nc",
        "secofs.t00z.20260710.field2d.n003_004.nc",
    ]
    with netCDF4.Dataset(result["created"][0]) as ds:
        ds.set_auto_mask(False)
        np.testing.assert_allclose(ds["time"][:], [3600.0, 7200.0])
        # The product inherits the STACKS' own time origin (ops behaviour)
        # rather than the --base-date argument, so the stamp cannot drift
        # from the data across phases or engines. Fixture units are
        # "seconds since 2026-07-10 00:00:00".
        assert ds["time"].base_date == "2026-07-10 00:00:00"
        np.testing.assert_allclose(ds["x"][:], X)
        np.testing.assert_array_equal(ds["element"][:], [[1, 2, 3], [2, 4, 3]])
        np.testing.assert_allclose(ds["zeta"][:], 0.0)
        # Hand-checked column interpolation: 3 m below the free surface
        # sits midway between z=-4 (u=1) and z=-2 (u=3).
        np.testing.assert_allclose(ds["uvel3"][:], EXPECT_UVEL3)
        np.testing.assert_allclose(ds["vvel3"][:], -EXPECT_UVEL3)
        # Native slabs: surface is the top level, T/S bottom is kbp,
        # velocity bottom one level above it.
        np.testing.assert_allclose(
            ds["temp_surface"][0, :], [_t(n, 2) for n in range(4)]
        )
        np.testing.assert_allclose(
            ds["temp_bottom"][0, :], [_t(n, 0) for n in range(4)]
        )
        np.testing.assert_allclose(ds["uvel_surface"][:], _u(2))
        np.testing.assert_allclose(ds["uvel_bottom"][:], _u(1))


def test_incomplete_stack_index_is_skipped(tmp_path, capsys):
    """A stack index missing one family is skipped by name; the complete
    indices still publish."""
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1, 2])
    _seed_stack(
        staging, 2, hours=[3, 4],
        families=[f for f in slab2d.SLAB_FAMILIES if f != "salinity"],
    )

    result = _run(staging, comout, tmp_path)

    assert [Path(p).name for p in result["created"]] == [
        "secofs.t00z.20260710.field2d.n001_002.nc"
    ]
    assert not (comout / "secofs.t00z.20260710.field2d.n003_004.nc").exists()
    out = capsys.readouterr().out
    assert "stack 2 incomplete" in out
    assert "salinity" in out


def test_out2d_without_mesh_vars_is_skipped(tmp_path, capsys):
    """A stack whose out2d lacks the mesh variables warns and is skipped
    (no partial product left in COMOUT)."""
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1, 2])
    with netCDF4.Dataset(staging / "out2d_1.nc", "a") as ds:
        ds.renameVariable("bottom_index_node", "bottom_index_node_old")

    result = _run(staging, comout, tmp_path)

    assert result["created"] == []
    assert list(comout.glob("*.nc")) == []
    assert "bottom_index_node" in capsys.readouterr().out


def test_forecast_labels_are_phase_relative(tmp_path):
    """STOFS-3D-ATL standalone continues the nowcast clock, so raw stack
    times start at hour 25; labels stay phase-relative like fields_nc."""
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 3, hours=[25, 26])

    rc = slab2d.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "stofs_3d_atl_ufs", "--cyc", "12", "--pdy", "20260722",
        "--phase", "forecast", "--base-date", "2026-07-21 12:00",
        "--nowcast-hours", "24", "--depths", str(INTERP_DEPTH),
    ])

    assert rc == 0
    assert [p.name for p in comout.glob("*.nc")] == [
        "stofs_3d_atl_ufs.t12z.20260722.field2d.f001_002.nc"
    ]


def test_default_depths_match_ops(tmp_path):
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1])

    rc = slab2d.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
        "--phase", "nowcast", "--base-date", "2026-07-10 00:00",
    ])

    assert rc == 0
    with netCDF4.Dataset(
        comout / "secofs.t00z.20260710.field2d.n001_001.nc"
    ) as ds:
        assert {"uvel0.5", "vvel0.5", "uvel4.5", "vvel4.5"} <= set(
            ds.variables
        )


def test_missing_staging_dir_returns_2(tmp_path):
    assert slab2d.main([
        "--staging", str(tmp_path / "nope"), "--comout", str(tmp_path),
        "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
        "--phase", "nowcast", "--base-date", "2026-07-10 00:00",
    ]) == 2


def test_empty_staging_dir_returns_3(tmp_path):
    staging, comout = _dirs(tmp_path)
    assert slab2d.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "secofs", "--cyc", "00", "--pdy", "20260710",
        "--phase", "nowcast", "--base-date", "2026-07-10 00:00",
    ]) == 3


# ---------------------------------------------------------------------------
# Stage wiring (worker subprocess mocked)
# ---------------------------------------------------------------------------


def _post_env(tmp_path: Path) -> dict:
    from nos_workflow.tests.test_post_stage import _make_minimal_post_env

    env = _make_minimal_post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "slab2d"
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


def test_product_passes_canonical_worker_args(tmp_path):
    env = _post_env(tmp_path)
    staging = (
        Path(env["COMOUT"]) / f"{env['RUN']}.{env['cycle']}.forecast_outputs"
    )
    staging.mkdir(parents=True)
    (staging / "out2d_1.nc").write_bytes(b"\x89HDF\r\n")

    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    assert _run_stage(env, fake_run) == 0
    assert len(calls) == 1  # only the forecast leg was staged
    cmd = calls[0]
    assert "nos_workflow.post.products.slab2d" in cmd
    args = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
    assert args["--phase"] == "forecast"
    # Forecast leg on a coupled system: the model clock RESTARTS at the
    # cycle time (ihot=1), so that is the origin -- not the nowcast begin.
    assert args["--base-date"] == "2026-05-07 00:00:00"
    assert args["--nowcast-hours"] == "6.0"
    assert args["--prefix"] == env["PREFIXNOS"]


def test_product_skips_without_staged_stacks(tmp_path):
    env = _post_env(tmp_path)
    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    assert _run_stage(env, fake_run) == 0
    assert calls == []
    by_name = {p["name"]: p for p in _outputs_manifest(env)["products"]}
    assert by_name["slab2d"]["status"] == "skipped"


def test_naming_helper():
    from nos_workflow.post.naming import field2d_stack_name

    assert field2d_stack_name(
        "secofs", "00", "20260710", "nowcast", 1, 6
    ) == "secofs.t00z.20260710.field2d.n001_006.nc"
    assert field2d_stack_name(
        "stofs_3d_atl_ufs", "12", "20260722", "forecast", 25, 48
    ) == "stofs_3d_atl_ufs.t12z.20260722.field2d.f025_048.nc"


def test_base_date_nowcast_rolls_the_date_back_over_midnight(tmp_path):
    """cyc 00 with a 6 h nowcast begins on the PREVIOUS day.

    Computing the hour as ``(cyc - LEN_NOWCAST) % 24`` and pasting it onto
    PDY yields 18:00 of the SAME day -- a silent 24 h error in every
    product's time units. This pins the corrected arithmetic, and the
    forecast counterpart above pins the phase distinction.
    """
    from nos_workflow.stages.post import _product_base_date

    class Ctx:
        pdy = "20260507"
        cyc = "00"
        shell_env = {"LEN_NOWCAST": "6"}

    assert _product_base_date(Ctx(), "nowcast") == "2026-05-06 18:00:00"
    # Standalone forecast continues the nowcast clock -> same origin.
    Ctx.shell_env = {"LEN_NOWCAST": "6", "USE_DATM": "false"}
    assert _product_base_date(Ctx(), "forecast") == "2026-05-06 18:00:00"
    # Coupled forecast restarts it -> cycle time.
    Ctx.shell_env = {"LEN_NOWCAST": "6", "USE_DATM": "true"}
    assert _product_base_date(Ctx(), "forecast") == "2026-05-07 00:00:00"
