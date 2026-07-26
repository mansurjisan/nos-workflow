"""Tests for the maxele product (worker + stage wiring).

maxele is the reference implementation for the shared
``NosUtilsProduct`` base and the only product restricting ``phases`` to
a single leg, so it is worth exercising directly rather than trusting
the base's other users.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_NOS_UTILS = Path(__file__).resolve().parents[2] / "nos-utils"
if str(_NOS_UTILS) not in sys.path:
    sys.path.insert(0, str(_NOS_UTILS))

netCDF4 = pytest.importorskip("netCDF4")
import numpy as np  # noqa: E402

from nos_workflow.post.products import maxele  # noqa: E402


def _stack(path: Path, hours, elev, base="2026-07-22 06:00:00", n_nodes=4):
    """A scribe-shaped out2d stack; ``elev`` may be scalar or per-node."""
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", n_nodes)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = f"seconds since {base}"
        tv[:] = [h * 3600.0 for h in hours]
        ev = ds.createVariable("elevation", "f4",
                               ("time", "nSCHISM_hgrid_node"))
        ev[:] = elev
        for name, vals in (("SCHISM_hgrid_node_x", [0.0, 1.0, 0.0, 1.0]),
                           ("SCHISM_hgrid_node_y", [0.0, 0.0, 1.0, 1.0])):
            ds.createVariable(name, "f8", ("nSCHISM_hgrid_node",))[:] = vals
        ds.createVariable("depth", "f4", ("nSCHISM_hgrid_node",))[:] = 5.0


def _run(staging, comout, tmp_path, extra=()):
    result = tmp_path / "r.json"
    rc = maxele.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "stofs_3d_atl_ufs", "--cyc", "12", "--pdy", "20260722",
        "--base-date", "IGNORED-when-stacks-carry-units",
        "--result-json", str(result), *extra,
    ])
    return rc, result


def test_reduces_the_global_max_across_stacks(tmp_path):
    """The max is over ALL stacks and ALL records, per node -- not a
    per-stack maximum and not a domain scalar."""
    staging, comout = tmp_path / "s", tmp_path / "c"
    staging.mkdir()
    comout.mkdir()
    # Per-node peaks land in different stacks, so a per-stack reduction
    # or a last-stack-wins bug would show up.
    _stack(staging / "out2d_1.nc", [1, 2], [[0.1, 0.9, 0.2, 0.3],
                                            [0.2, 0.4, 0.3, 0.4]])
    _stack(staging / "out2d_2.nc", [3, 4], [[0.8, 0.3, 0.1, 0.2],
                                            [0.4, 0.5, 0.7, 0.6]])

    rc, result = _run(staging, comout, tmp_path)
    assert rc == 0

    created = json.loads(result.read_text())["created"]
    assert [Path(p).name for p in created] == [
        "stofs_3d_atl_ufs.t12z.20260722.fields.cwl.maxele.nc"
    ]
    with netCDF4.Dataset(created[0]) as ds:
        assert np.allclose(ds["zeta_max"][:], [0.8, 0.9, 0.7, 0.6])
        assert len(ds.dimensions["node"]) == 4


def test_window_is_derived_from_data_by_default(tmp_path):
    """Ops' (90000, 432000) constant describes ops' own 5-day run; on a
    run of a different length it would advertise a window the data does
    not cover, so the default is data-derived."""
    staging, comout = tmp_path / "s", tmp_path / "c"
    staging.mkdir()
    comout.mkdir()
    _stack(staging / "out2d_1.nc", [25, 30], 0.5)
    _stack(staging / "out2d_2.nc", [126, 132], 0.6)

    rc, result = _run(staging, comout, tmp_path)
    assert rc == 0
    with netCDF4.Dataset(json.loads(result.read_text())["created"][0]) as ds:
        assert list(ds["time"][:]) == [25 * 3600.0, 132 * 3600.0]


def test_ops_window_can_be_opted_into(tmp_path):
    staging, comout = tmp_path / "s", tmp_path / "c"
    staging.mkdir()
    comout.mkdir()
    _stack(staging / "out2d_1.nc", [25, 30], 0.5)

    rc, result = _run(staging, comout, tmp_path, extra=("--ops-window",))
    assert rc == 0
    with netCDF4.Dataset(json.loads(result.read_text())["created"][0]) as ds:
        assert list(ds["time"][:]) == list(maxele.OPS_WINDOW_SECONDS)


def test_base_date_is_inherited_from_the_stacks(tmp_path):
    """--base-date is only a fallback: the stamp comes from the data, so
    it cannot drift from it across phases or engines."""
    staging, comout = tmp_path / "s", tmp_path / "c"
    staging.mkdir()
    comout.mkdir()
    _stack(staging / "out2d_1.nc", [1, 2], 0.5, base="2026-07-21 12:00:00")

    rc, result = _run(staging, comout, tmp_path)
    assert rc == 0
    with netCDF4.Dataset(json.loads(result.read_text())["created"][0]) as ds:
        assert ds["time"].units == "seconds since 2026-07-21 12:00:00"


def test_missing_staging_and_empty_staging_exit_codes(tmp_path):
    comout = tmp_path / "c"
    comout.mkdir()
    assert maxele.main([
        "--staging", str(tmp_path / "nope"), "--comout", str(comout),
        "--prefix", "p", "--cyc", "12", "--pdy", "20260722",
        "--base-date", "2026-07-22 06:00:00",
    ]) == 2

    empty = tmp_path / "empty"
    empty.mkdir()
    assert maxele.main([
        "--staging", str(empty), "--comout", str(comout),
        "--prefix", "p", "--cyc", "12", "--pdy", "20260722",
        "--base-date", "2026-07-22 06:00:00",
    ]) == 3
    assert list(comout.iterdir()) == []


# ---------------------------------------------------------------------------
# Stage wiring
# ---------------------------------------------------------------------------


def _post_env(tmp_path: Path) -> dict:
    from nos_workflow.tests.test_post_stage import _make_minimal_post_env

    env = _make_minimal_post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "maxele"
    env["OFS_CONFIG"] = ""
    return env


def _run_stage(env: dict, fake_run):
    from nos_workflow.stages import post as post_stage
    from nos_workflow.tests.test_post_stage import _secofs_ufs_desc

    with patch.dict(os.environ, env, clear=False):
        with patch.object(post_stage.subprocess, "run", side_effect=fake_run):
            return post_stage.run(_secofs_ufs_desc(), object())


def _manifest(env: dict) -> dict:
    path = Path(env["COMOUT"]) / (
        f"{env['RUN']}.t{env['cyc']}z.{env['PDY']}.outputs.post.json"
    )
    return json.loads(path.read_text())


def test_stage_runs_maxele_on_the_forecast_leg_only(tmp_path):
    """Ops reduces the forecast stacks; staging BOTH legs must still
    produce exactly one worker call."""
    env = _post_env(tmp_path)
    comout = Path(env["COMOUT"])
    for sub in ("restart_outputs", "forecast_outputs"):
        d = comout / f"{env['RUN']}.{env['cycle']}.{sub}"
        d.mkdir(parents=True)
        (d / "out2d_1.nc").write_bytes(b"\x89HDF\r\n")

    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        args = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
        Path(args["--result-json"]).write_text(
            json.dumps({"created": [str(comout / "m.nc")]})
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    assert _run_stage(env, fake_run) == 0
    assert len(calls) == 1, "maxele must not run on the nowcast leg"
    assert "nos_workflow.post.products.maxele" in calls[0]
    assert _manifest(env)["products"][0]["status"] == "ok"


def test_stage_skips_maxele_when_no_stacks_are_staged(tmp_path):
    env = _post_env(tmp_path)
    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    assert _run_stage(env, fake_run) == 0
    assert calls == []
    entry = _manifest(env)["products"][0]
    assert entry["status"] == "skipped"


def test_published_name_has_no_phase_token_so_phases_must_stay_single():
    """Guard on a one-line footgun: the base class invites widening
    ``phases``, but the maxele name carries no phase token, so both legs
    would write the SAME COMOUT file and the second would silently
    overwrite the first."""
    from nos_workflow.stages.post import MaxeleProduct

    assert len(MaxeleProduct.phases) == 1, (
        "maxele publishes a phase-agnostic name; widening phases would "
        "make the legs collide -- add a phase token to the name first"
    )
