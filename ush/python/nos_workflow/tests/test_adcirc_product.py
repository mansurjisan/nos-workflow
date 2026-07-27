"""Tests for the adcirc product (worker + stage wiring).

Real (tiny) NetCDF fixtures on a 4-node/2-element mesh, run through the
actual ``nos_utils.post.adcirc`` writer: the masking scenario is
hand-computed against the ops order (junk fill -> dry fill -> reductions
-> inundation conversion -> small-disturbance fill), and the grouping
cases pin ops' 24 h pair merge, which is what the later AWIPS grib2 step
consumes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# The repo's nos-utils submodule carries nos_utils.post; prefer it over
# any older nos_utils installed on the host.
_NOS_UTILS = Path(__file__).resolve().parents[2] / "nos-utils"
if str(_NOS_UTILS) not in sys.path:
    sys.path.insert(0, str(_NOS_UTILS))

netCDF4 = pytest.importorskip("netCDF4")
import numpy as np  # noqa: E402

from nos_utils.post.adcirc import FILL_VALUE  # noqa: E402
from nos_workflow.post.products import adcirc  # noqa: E402

# 4-node unit square, two triangles.
X = [0.0, 1.0, 0.0, 1.0]
Y = [0.0, 0.0, 1.0, 1.0]
ELEMS = [[1, 2, 3, -1], [2, 4, 3, -1]]

# Hand-built masking scenario, hours [1, 2], with dryFlagNode:
#   node 0: city node just below the geoid (depth 0.05), wet throughout
#   node 1: land node, ground 1 m above the geoid, inundated at h2
#   node 2: ocean node whose first record is junk
#   node 3: land node, ground 3 m up, dry the whole run
SCEN_DEPTH = [0.05, -1.0, 5.0, -3.0]
SCEN_ELEV = [[0.1, 0.5, 9.0e5, -2.9],
             [0.2, 1.5, 0.2, -2.8]]
SCEN_DRY = [[0, 0, 0, 1],
            [0, 0, 0, 1]]
SCEN_CITY = [True, False, False, False]


def _stack(path, hours, elev, depth=5.0, dry=None,
           base="2026-07-22 06:00:00"):
    """A scribe-shaped out2d stack carrying what write_adcirc reads."""
    hours = list(hours)
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", 4)
        ds.createDimension("nSCHISM_hgrid_face", len(ELEMS))
        ds.createDimension("nMaxSCHISM_hgrid_face_nodes", 4)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = f"seconds since {base}"
        tv.base_date = base
        tv[:] = [h * 3600.0 for h in hours]
        ds.createVariable(
            "elevation", "f8", ("time", "nSCHISM_hgrid_node")
        )[:] = elev
        ds.createVariable(
            "SCHISM_hgrid_node_x", "f8", ("nSCHISM_hgrid_node",)
        )[:] = X
        ds.createVariable(
            "SCHISM_hgrid_node_y", "f8", ("nSCHISM_hgrid_node",)
        )[:] = Y
        ds.createVariable("depth", "f8", ("nSCHISM_hgrid_node",))[:] = depth
        fv = ds.createVariable(
            "SCHISM_hgrid_face_nodes", "i4",
            ("nSCHISM_hgrid_face", "nMaxSCHISM_hgrid_face_nodes"),
            fill_value=-1,
        )
        fv[:] = ELEMS
        if dry is not None:
            ds.createVariable(
                "dryFlagNode", "i4", ("time", "nSCHISM_hgrid_node")
            )[:] = dry
    return path


def _flat(hours, value):
    """Uniform elevation for every node at every record."""
    return [[value] * 4 for _ in hours]


def _dirs(tmp_path):
    staging, comout = tmp_path / "staging", tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    return staging, comout


def _city_file(path, mask=SCEN_CITY):
    """The ops fix format: one float per line, one per mesh node."""
    np.savetxt(path, np.asarray(mask, dtype=float))
    return path


def _run(staging, comout, tmp_path, *extra, phase="nowcast"):
    result = tmp_path / "r.json"
    rc = adcirc.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "stofs_3d_atl_ufs", "--cyc", "12", "--pdy", "20260722",
        "--phase", phase,
        "--base-date", "IGNORED-when-stacks-carry-units",
        "--result-json", str(result), *extra,
    ])
    return rc, result


def _created(result):
    return json.loads(result.read_text())["created"]


def test_groups_stacks_into_the_ops_24h_day(tmp_path):
    """Ops ncrcats its 12 h stacks in pairs before the python step, so a
    published file spans 24 h and its reductions cover the whole day --
    not one stack."""
    staging, comout = _dirs(tmp_path)
    _stack(staging / "out2d_1.nc", [1, 12], _flat([1, 12], 0.1))
    _stack(staging / "out2d_2.nc", [13, 24], [[0.3] * 4, [0.9] * 4])
    _stack(staging / "out2d_3.nc", [25, 36], _flat([25, 36], 0.4))

    rc, result = _run(staging, comout, tmp_path, phase="forecast")
    assert rc == 0

    created = _created(result)
    assert [Path(p).name for p in created] == [
        "stofs_3d_atl_ufs.t12z.20260722.adcirc.f001_024.nc",
        "stofs_3d_atl_ufs.t12z.20260722.adcirc.f025_036.nc",
    ]
    with netCDF4.Dataset(created[0]) as ds:
        ds.set_auto_mask(False)
        # Both stacks of the day are merged into the one file ...
        assert list(ds["time"][:]) == [3600.0, 43200.0, 46800.0, 86400.0]
        # ... so the day's max comes from the SECOND stack.
        assert np.allclose(ds["zeta_max"][:], 0.9)
        assert ds["element"][:].tolist() == [[1, 2, 3], [2, 4, 3]]


def test_group_hours_zero_publishes_one_file_per_stack(tmp_path):
    staging, comout = _dirs(tmp_path)
    _stack(staging / "out2d_1.nc", [1, 12], _flat([1, 12], 0.1))
    _stack(staging / "out2d_2.nc", [13, 24], _flat([13, 24], 0.2))

    rc, result = _run(
        staging, comout, tmp_path, "--group-hours", "0", phase="forecast"
    )
    assert rc == 0
    assert [Path(p).name for p in _created(result)] == [
        "stofs_3d_atl_ufs.t12z.20260722.adcirc.f001_012.nc",
        "stofs_3d_atl_ufs.t12z.20260722.adcirc.f013_024.nc",
    ]


def test_masking_follows_the_ops_order(tmp_path):
    """Junk and dry records are filled BEFORE the reductions; the
    inundation conversion then runs on normally-dry (land or city) nodes
    and only afterwards are small disturbances masked there."""
    staging, comout = _dirs(tmp_path)
    _stack(staging / "out2d_1.nc", [1, 2], SCEN_ELEV,
           depth=SCEN_DEPTH, dry=SCEN_DRY)
    city = _city_file(tmp_path / "city.txt")

    rc, result = _run(staging, comout, tmp_path, "--city-nodes", str(city))
    assert rc == 0

    created = _created(result)
    assert [Path(p).name for p in created] == [
        "stofs_3d_atl_ufs.t12z.20260722.adcirc.n001_002.nc"
    ]
    with netCDF4.Dataset(created[0]) as ds:
        ds.set_auto_mask(False)
        # Junk (9e5) and dry records are filled in zeta itself ...
        assert ds["zeta"][0, 2] == FILL_VALUE
        assert np.allclose(ds["zeta"][:, 3], FILL_VALUE)
        # ... so the reductions skip them: node 2's max is its clean
        # record, and always-dry node 3's max is the fill.
        assert np.allclose(ds["zeta_max"][:3], [0.2, 1.5, 0.2])
        assert ds["zeta_max"][3] == FILL_VALUE
        # time_of_zeta_max is never filled; the all-fill tie takes the
        # first record.
        assert np.allclose(ds["time_of_zeta_max"][:],
                           [7200.0, 7200.0, 7200.0, 3600.0])
        # City node: converted to inundation depth 0.2 + 0.05 = 0.25,
        # then masked as small. Land node: 1.5 - 1.0 = 0.5, kept. Ocean
        # node: no conversion, and a SMALL ocean disturbance is kept
        # (ops has that fill commented out). Always-dry land: clamps to
        # 0, then masked.
        dmax = ds["disturbance_max"][:]
        assert dmax[0] == FILL_VALUE
        assert np.isclose(dmax[1], 0.5)
        assert np.isclose(dmax[2], 0.2)
        assert dmax[3] == FILL_VALUE


def test_publishes_without_a_city_mask(tmp_path, capsys):
    """A missing urban mask is a logged degradation, never a failure:
    the same node then behaves as plain ocean (no conversion, no small
    -disturbance fill)."""
    staging, comout = _dirs(tmp_path)
    _stack(staging / "out2d_1.nc", [1, 2], SCEN_ELEV,
           depth=SCEN_DEPTH, dry=SCEN_DRY)

    rc, result = _run(staging, comout, tmp_path)
    assert rc == 0

    with netCDF4.Dataset(_created(result)[0]) as ds:
        ds.set_auto_mask(False)
        assert np.isclose(ds["disturbance_max"][0], 0.2)
    assert "urban masking off" in capsys.readouterr().out


def test_a_missing_city_file_path_is_not_fatal(tmp_path, capsys):
    staging, comout = _dirs(tmp_path)
    _stack(staging / "out2d_1.nc", [1, 2], SCEN_ELEV,
           depth=SCEN_DEPTH, dry=SCEN_DRY)

    rc, result = _run(
        staging, comout, tmp_path, "--city-nodes", str(tmp_path / "nope.txt")
    )

    assert rc == 0
    assert len(_created(result)) == 1
    assert "city node-id file missing" in capsys.readouterr().out


def test_time_stamp_is_inherited_from_the_stacks(tmp_path):
    """--base-date is only a fallback: ops copies the input file's own
    ``units``/``base_date`` through, so the stamp cannot drift from the
    data across phases or engines."""
    staging, comout = _dirs(tmp_path)
    _stack(staging / "out2d_1.nc", [1, 2], _flat([1, 2], 0.5),
           base="2026-07-21 12:00:00")

    rc, result = _run(staging, comout, tmp_path)
    assert rc == 0

    with netCDF4.Dataset(_created(result)[0]) as ds:
        assert ds["time"].units == "seconds since 2026-07-21 12:00:00"
        assert ds["time"].base_date == "2026-07-21 12:00:00"


def test_forecast_labels_are_phase_relative(tmp_path):
    """STOFS-3D-ATL standalone continues the nowcast clock, so raw stack
    times start at hour 25; labels stay phase-relative like fields_nc,
    which is also what keeps the grib2 step's forecast hours aligned."""
    staging, comout = _dirs(tmp_path)
    _stack(staging / "out2d_3.nc", [25, 36], _flat([25, 36], 0.1))
    _stack(staging / "out2d_4.nc", [37, 48], _flat([37, 48], 0.2))

    rc, _result = _run(
        staging, comout, tmp_path,
        "--nowcast-hours", "24", phase="forecast",
    )

    assert rc == 0
    assert [p.name for p in comout.glob("*.nc")] == [
        "stofs_3d_atl_ufs.t12z.20260722.adcirc.f001_024.nc"
    ]


def test_missing_staging_and_empty_staging_exit_codes(tmp_path):
    comout = tmp_path / "c"
    comout.mkdir()
    assert adcirc.main([
        "--staging", str(tmp_path / "nope"), "--comout", str(comout),
        "--prefix", "p", "--cyc", "12", "--pdy", "20260722",
        "--phase", "forecast", "--base-date", "2026-07-22 06:00:00",
    ]) == 2

    empty = tmp_path / "empty"
    empty.mkdir()
    assert adcirc.main([
        "--staging", str(empty), "--comout", str(comout),
        "--prefix", "p", "--cyc", "12", "--pdy", "20260722",
        "--phase", "forecast", "--base-date", "2026-07-22 06:00:00",
    ]) == 3
    assert list(comout.iterdir()) == []


def test_comout_is_clean_when_the_writer_raises_mid_write(tmp_path):
    """A writer that dies after opening its output must leave NOTHING in
    COMOUT -- not the published name, not the staging temp."""
    staging, comout = _dirs(tmp_path)
    _stack(staging / "out2d_1.nc", [1, 2], _flat([1, 2], 0.5))

    import nos_utils.post.adcirc as nu_adcirc

    def boom(out2d_files, out_path, **kwargs):
        Path(out_path).write_bytes(b"\x89HDF\r\n truncated")
        raise RuntimeError("no space left on device")

    with patch.object(nu_adcirc, "write_adcirc", boom):
        rc, result = _run(staging, comout, tmp_path)

    assert rc == 5, "every write failing must not read as success"
    assert _created(result) == []
    assert list(comout.iterdir()) == []


# ---------------------------------------------------------------------------
# Stage wiring
# ---------------------------------------------------------------------------


def _post_env(tmp_path: Path) -> dict:
    from nos_workflow.tests.test_post_stage import _make_minimal_post_env

    env = _make_minimal_post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "adcirc"
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


def test_stage_runs_both_legs_with_canonical_args(tmp_path):
    env = _post_env(tmp_path)
    # PREFIXNOS drives both the product name and the fix lookup; point it
    # at the ATL system so the ops-prefixed fix name is the real one.
    fixofs = Path(env["FIXofs"])
    env["PREFIXNOS"] = "stofs_3d_atl_ufs"
    (fixofs / "stofs_3d_atl_ufs.station.in").write_text(
        "h1\nh2\n1 -76.5 38.5 0\n"
    )
    city = fixofs / "stofs_3d_atl_node_id_city_poly_adcirc.txt"
    _city_file(city)

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
            json.dumps({"created": [str(comout / f"{args['--phase']}.nc")]})
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    assert _run_stage(env, fake_run) == 0

    assert len(calls) == 2, "both legs are published (names carry the phase)"
    per_phase = {}
    for cmd in calls:
        assert "nos_workflow.post.products.adcirc" in cmd
        args = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
        per_phase[args["--phase"]] = args
    assert set(per_phase) == {"nowcast", "forecast"}
    assert per_phase["nowcast"]["--prefix"] == "stofs_3d_atl_ufs"
    assert per_phase["nowcast"]["--nowcast-hours"] == "6.0"
    # Ops fix name resolved through the ops-prefix fallback.
    assert per_phase["forecast"]["--city-nodes"] == str(city)
    # Nowcast leg begins LEN_NOWCAST before the cycle, date included.
    assert per_phase["nowcast"]["--base-date"] == "2026-05-06 18:00:00"
    # Coupled forecast restarts the model clock at the cycle time.
    assert per_phase["forecast"]["--base-date"] == "2026-05-07 00:00:00"
    assert _manifest(env)["products"][0]["status"] == "ok"


def test_stage_omits_city_nodes_when_no_fix_file_exists(tmp_path, caplog):
    caplog.set_level("INFO", logger="nos_workflow.stages.post")
    env = _post_env(tmp_path)
    comout = Path(env["COMOUT"])
    d = comout / f"{env['RUN']}.{env['cycle']}.forecast_outputs"
    d.mkdir(parents=True)
    (d / "out2d_1.nc").write_bytes(b"\x89HDF\r\n")

    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    assert _run_stage(env, fake_run) == 0
    assert len(calls) == 1
    assert "--city-nodes" not in calls[0]
    assert "urban" in caplog.text


def test_stage_skips_adcirc_when_no_stacks_are_staged(tmp_path):
    env = _post_env(tmp_path)
    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    assert _run_stage(env, fake_run) == 0
    assert calls == []
    assert _manifest(env)["products"][0]["status"] == "skipped"


def test_published_name_carries_the_phase_so_both_legs_are_safe():
    """The mirror of the maxele guard: adcirc runs on BOTH legs, which is
    only safe while the name distinguishes them. Dropping the phase token
    would make the forecast leg silently overwrite the nowcast one."""
    from nos_workflow.post.naming import adcirc_name
    from nos_workflow.stages.post import AdcircProduct

    assert len(AdcircProduct.phases) == 2
    assert adcirc_name("p", "12", "20260722", "nowcast", 1, 24) != \
        adcirc_name("p", "12", "20260722", "forecast", 1, 24)


def test_naming_helper():
    from nos_workflow.post.naming import adcirc_name

    assert adcirc_name(
        "stofs_3d_atl_ufs", "12", "20260722", "forecast", 25, 48
    ) == "stofs_3d_atl_ufs.t12z.20260722.adcirc.f025_048.nc"
    assert adcirc_name(
        "secofs", "00", "20260710", "nowcast", 1, 6
    ) == "secofs.t00z.20260710.adcirc.n001_006.nc"
