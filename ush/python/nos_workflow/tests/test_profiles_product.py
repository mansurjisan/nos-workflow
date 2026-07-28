"""Tests for the station-profile product (worker + stage wiring).

Synthetic fixtures on the 4-node / 2-triangle mini mesh, run through the
real ``nos_utils.post.profiles`` writer: one station sits ON a node
(area coordinates 1, 0, 0) and one at an element centroid (equal
thirds), so every published value is hand-checkable.

The load-bearing case is ``outside``: the writer defaults to pylib's
nearest-node fallback, while the operational driver ``sys.exit``s on an
out-of-mesh station. Getting that wrong publishes another node's water
column under the misplaced station's name, so both the default and the
opt-out are pinned here.
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

from nos_workflow.post.base import ProductContext  # noqa: E402
from nos_workflow.post.naming import station_profile_name  # noqa: E402
from nos_workflow.post.products import profiles  # noqa: E402
from nos_workflow.post.registry import get_product  # noqa: E402
from nos_workflow.stages import post as post_stage  # noqa: E402

# Mini mesh: nodes 1(0,0) 2(1,0) 3(0,1) 4(1,1), elements (1,2,3) and
# (2,4,3), 5 m deep everywhere.
X = (0.0, 1.0, 0.0, 1.0)
Y = (0.0, 0.0, 1.0, 1.0)
DEPTH = 5.0
ELEMS = ((1, 2, 3), (2, 4, 3))
NVRT = 3
BASE = "2026-07-10 00:00:00"
FAMILIES_3D = (
    "salinity", "temperature", "horizontalVelX", "horizontalVelY",
    "zCoordinates",
)

# Station A is node 1 -> weights (1, 0, 0) -> node factor 1.
# Station B is the centroid of element 2 (nodes 2, 4, 3) -> equal thirds
# -> mean node factor (2 + 4 + 3) / 3 = 3.
STATIONS = (("STA_NODE", 0.0, 0.0), ("STA_CENTROID", 2 / 3, 2 / 3))
FACTOR = (1.0, 3.0)
OUTSIDE_STATION = ("STA_OFFSHORE", 9.0, 9.0)  # nearest node is 4 (factor 4)


def _elev(hour: float, node: int) -> float:
    """out2d fixture law: node_id + hour/100."""
    return (node + 1) + hour / 100.0


def _var3d(hour: float, node: int, k: int) -> float:
    """3D fixture law: node_id*10 + layer + hour/100."""
    return (node + 1) * 10.0 + k + hour / 100.0


def _write_out2d(path: Path, hours, base: str = BASE) -> None:
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", 4)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = f"seconds since {base}"
        tv[:] = [h * 3600.0 for h in hours]
        ev = ds.createVariable(
            "elevation", "f4", ("time", "nSCHISM_hgrid_node")
        )
        for it, h in enumerate(hours):
            ev[it, :] = [_elev(h, n) for n in range(4)]


def _write_var3d(path: Path, var: str, hours, nvrt: int = NVRT) -> None:
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("nSCHISM_hgrid_node", 4)
        ds.createDimension("nSCHISM_vgrid_layers", nvrt)
        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = f"seconds since {BASE}"
        tv[:] = [h * 3600.0 for h in hours]
        vv = ds.createVariable(
            var, "f4",
            ("time", "nSCHISM_hgrid_node", "nSCHISM_vgrid_layers"),
        )
        for it, h in enumerate(hours):
            for n in range(4):
                vv[it, n, :] = [_var3d(h, n, k) for k in range(nvrt)]


def _seed_stack(staging: Path, index: int, hours, base=BASE, families=None):
    """One stack index: out2d + the five 3D families (or a subset)."""
    staging.mkdir(parents=True, exist_ok=True)
    _write_out2d(staging / f"out2d_{index}.nc", hours, base)
    for var in FAMILIES_3D if families is None else families:
        _write_var3d(staging / f"{var}_{index}.nc", var, hours)


def _write_hgrid(path: Path) -> Path:
    lines = ["mini mesh", f"{len(ELEMS)} 4"]
    lines += [f"{i + 1} {X[i]} {Y[i]} {DEPTH}" for i in range(4)]
    lines += [
        f"{i + 1} 3 " + " ".join(str(n) for n in elem)
        for i, elem in enumerate(ELEMS)
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def _write_vgrid(path: Path, nvrt: int = NVRT) -> Path:
    """Only line 1 (ivcor) and line 2 (nvrt) are read."""
    path.write_text(f"1 !ivcor\n{nvrt}\n")
    return path


def _write_station_in(path: Path, stations=STATIONS) -> Path:
    """Ops-flavour station.in: 2 header lines, names with the sentinel ','."""
    lines = ["1 1 1 1 1 1 1 1 0 !on(1)|off(0) flags", str(len(stations))]
    lines += [
        f"{i + 1} {lon} {lat} 0 !{name},"
        for i, (name, lon, lat) in enumerate(stations)
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def _mesh_args(tmp_path: Path, stations=STATIONS, nvrt=NVRT) -> list:
    return [
        "--hgrid", str(_write_hgrid(tmp_path / "hgrid.gr3")),
        "--vgrid", str(_write_vgrid(tmp_path / "vgrid.in", nvrt)),
        "--station-in",
        str(_write_station_in(tmp_path / "station.in", stations)),
    ]


def _dirs(tmp_path: Path):
    staging, comout = tmp_path / "staging", tmp_path / "comout"
    staging.mkdir()
    comout.mkdir()
    return staging, comout


def _run(staging, comout, tmp_path, extra=(), stations=STATIONS, nvrt=NVRT):
    result_json = tmp_path / "r.json"
    rc = profiles.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "stofs_3d_atl_ufs", "--cyc", "12", "--pdy", "20260722",
        "--phase", "forecast",
        # Deliberately wrong: the stacks' own origin must win.
        "--base-date", "2001-01-01 00:00:00",
        *_mesh_args(tmp_path, stations, nvrt),
        "--result-json", str(result_json), *extra,
    ])
    return rc, result_json


# ---------------------------------------------------------------------------
# Naming / registration
# ---------------------------------------------------------------------------


def test_canonical_name_carries_stem_and_spelled_out_phase():
    """Ops writes {prefix}.t12z.{ncast,fcast}.station.profile.nc; ours
    keeps the per-leg split but uses the canonical stem + phase words."""
    assert station_profile_name(
        "stofs_3d_atl_ufs", "12", "20260722", "nowcast"
    ) == "stofs_3d_atl_ufs.t12z.20260722.station.profile.nowcast.nc"
    assert station_profile_name(
        "secofs", "00", "20260710", "forecast"
    ) == "secofs.t00z.20260710.station.profile.forecast.nc"


def test_product_is_registered_for_both_phases():
    cls = get_product("profiles")
    assert cls is post_stage.ProfilesProduct
    assert cls.worker == "nos_workflow.post.products.profiles"
    assert tuple(cls.phases) == ("nowcast", "forecast")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def test_profile_values_at_a_node_and_at_a_centroid(tmp_path):
    """Hand-computed interpolation: the node station takes node 1's value
    (weights 1, 0, 0), the centroid station the mean of nodes 2, 4, 3.

    Both stacks' times are concatenated in one call -- ops runs its
    extractor per stack and ncrcats the halves.
    """
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1, 2])
    _seed_stack(staging, 2, hours=[3, 4])

    rc, result_json = _run(staging, comout, tmp_path)
    assert rc == 0

    created = json.loads(result_json.read_text())["created"]
    assert [Path(p).name for p in created] == [
        "stofs_3d_atl_ufs.t12z.20260722.station.profile.forecast.nc"
    ]
    with netCDF4.Dataset(created[0]) as ds:
        assert ds.data_model == "NETCDF3_CLASSIC"
        assert len(ds.dimensions["station"]) == 2
        assert len(ds.dimensions["siglay"]) == NVRT
        assert list(np.asarray(ds["time"][:])) == [
            3600.0, 7200.0, 10800.0, 14400.0
        ]
        # Names come from station.in, with the ops sentinel comma chopped.
        assert [
            b"".join(row).decode().rstrip("\x00")
            for row in np.asarray(ds["station_name"][:])
        ] == ["STA_NODE", "STA_CENTROID"]

        np.testing.assert_allclose(
            ds["zeta"][:],
            [[f + h / 100.0 for f in FACTOR] for h in (1, 2, 3, 4)],
            rtol=1e-6,
        )
        expect3d = [
            [[f * 10 + k + h / 100.0 for k in range(NVRT)] for f in FACTOR]
            for h in (1, 2, 3, 4)
        ]
        for var in ("salinity", "temperature", "u", "v", "zCoordinates"):
            np.testing.assert_allclose(
                ds[var][:], expect3d, rtol=1e-6, err_msg=var
            )
        assert np.asarray(ds["depth"][:]) == pytest.approx([DEPTH, DEPTH])
        assert np.asarray(ds["lon"][:]) == pytest.approx(
            [s[1] for s in STATIONS]
        )


def test_base_date_is_inherited_from_the_stacks(tmp_path):
    """--base-date is only a fallback: the stamp comes from the data, so
    it cannot drift from it across phases or engines."""
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1], base="2026-07-21 12:00:00")

    rc, result_json = _run(staging, comout, tmp_path)
    assert rc == 0
    with netCDF4.Dataset(
        json.loads(result_json.read_text())["created"][0]
    ) as ds:
        # The writer formats to the hour and brands UTC, as ops does.
        assert ds["time"].units == "seconds since 2026-07-21 12:00:00 UTC"
        assert ds["time"].base_date == "2026-07-21 12:00:00 UTC"


def test_unparseable_stack_origin_falls_back_to_base_date(tmp_path):
    """This writer PARSES the base date (the others pass it through), so
    an origin in an unexpected shape must not sink the product."""
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1])
    with netCDF4.Dataset(staging / "out2d_1.nc", "a") as ds:
        ds["time"].units = "seconds since the beginning of time"

    rc, result_json = _run(staging, comout, tmp_path)
    assert rc == 0
    with netCDF4.Dataset(
        json.loads(result_json.read_text())["created"][0]
    ) as ds:
        assert ds["time"].units == "seconds since 2001-01-01 00:00:00 UTC"


def test_outside_error_is_the_default_and_reaches_the_writer(tmp_path):
    """Ops parity: the operational driver sys.exit()s on an out-of-mesh
    station, so the product must fail rather than quietly publish the
    nearest node's column under that station's name."""
    assert profiles._parse_args([
        "--staging", "s", "--comout", "c", "--prefix", "p", "--cyc", "12",
        "--pdy", "20260722", "--phase", "nowcast", "--base-date", "d",
        "--hgrid", "h", "--vgrid", "v", "--station-in", "i",
    ]).outside == "error"

    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1])

    # Fails, but with a diagnosis rather than a traceback: the base class
    # reads any non-zero rc as "failed", so the product outcome is
    # unchanged while the log now names the station and how far out it is.
    rc, _result_json = _run(
        staging, comout, tmp_path,
        stations=STATIONS + (OUTSIDE_STATION,),
    )
    assert rc == 6
    assert list(comout.iterdir()) == [], "a partial product survived"


def test_outside_error_names_the_offending_station(tmp_path, capsys):
    """A bad coordinate and a mismatched mesh look identical in the log
    unless the distance is reported."""
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1])

    _run(staging, comout, tmp_path,
         stations=STATIONS + (OUTSIDE_STATION,))

    out = capsys.readouterr().out
    assert "outside of domain" in out
    assert "nearest node" in out          # the discriminator
    assert "station(s) outside" in out


def test_outside_nearest_opts_into_the_pylib_fallback(tmp_path):
    """The escape hatch, and what it costs: the offshore station is
    published carrying node 4's water column."""
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1])

    rc, result_json = _run(
        staging, comout, tmp_path, extra=("--outside", "nearest"),
        stations=STATIONS + (OUTSIDE_STATION,),
    )
    assert rc == 0
    with netCDF4.Dataset(
        json.loads(result_json.read_text())["created"][0]
    ) as ds:
        np.testing.assert_allclose(
            ds["zeta"][:], [[1.01, 3.01, 4.01]], rtol=1e-6
        )


def test_incomplete_stack_is_named_and_dropped(tmp_path, capsys):
    """One family missing makes the whole index unusable (the writer
    indexes every family of every stack), but the complete indices still
    publish -- and the gap is announced, since it leaves a hole in the
    concatenated time axis."""
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1, 2])
    _seed_stack(
        staging, 2, hours=[3, 4],
        families=[f for f in FAMILIES_3D if f != "salinity"],
    )

    rc, result_json = _run(staging, comout, tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 (missing salinity)" in out

    with netCDF4.Dataset(
        json.loads(result_json.read_text())["created"][0]
    ) as ds:
        assert list(np.asarray(ds["time"][:])) == [3600.0, 7200.0]


def test_missing_staging_and_no_complete_stack_exit_codes(tmp_path):
    staging, comout = _dirs(tmp_path)
    rc, _ = _run(tmp_path / "nope", comout, tmp_path)
    assert rc == 2

    rc, _ = _run(staging, comout, tmp_path)
    assert rc == 3

    # out2d alone (a 2D-only cycle) is not enough either.
    _seed_stack(staging, 1, hours=[1], families=())
    rc, _ = _run(staging, comout, tmp_path)
    assert rc == 3
    assert list(comout.iterdir()) == []


def test_missing_fix_input_returns_5(tmp_path):
    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1])

    rc = profiles.main([
        "--staging", str(staging), "--comout", str(comout),
        "--prefix", "p", "--cyc", "12", "--pdy", "20260722",
        "--phase", "nowcast", "--base-date", "2026-07-22 06:00:00",
        "--hgrid", str(_write_hgrid(tmp_path / "hgrid.gr3")),
        "--vgrid", str(tmp_path / "absent.vgrid.in"),
        "--station-in", str(_write_station_in(tmp_path / "station.in")),
    ])
    assert rc == 5
    assert list(comout.iterdir()) == []


def test_a_failed_write_leaves_comout_clean(tmp_path):
    """A vgrid nvrt that disagrees with the stacks raises AFTER the output
    file has been created, so this exercises the atomic publish."""
    from nos_utils.post.profiles import stack_inputs, write_station_profiles

    staging, comout = _dirs(tmp_path)
    _seed_stack(staging, 1, hours=[1, 2])

    with pytest.raises(ValueError):
        _run(staging, comout, tmp_path, nvrt=NVRT + 1)
    assert list(comout.iterdir()) == []

    # Without the atomic publish the same failure leaves a truncated
    # product behind -- which is what makes the assertion above worth
    # making.
    direct = tmp_path / "direct.nc"
    with pytest.raises(ValueError):
        write_station_profiles(
            [stack_inputs(staging, 1)],
            tmp_path / "hgrid.gr3", tmp_path / "vgrid.in", direct,
            base_date="2026-07-10-00", station_file=tmp_path / "station.in",
        )
    assert direct.is_file()


# ---------------------------------------------------------------------------
# Product wiring
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path, fixofs: Path, prefix: str, sta_in=None,
         shell_env=None) -> ProductContext:
    comout = tmp_path / "com"
    data = tmp_path / "data"
    comout.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    return ProductContext(
        descriptor=None,
        shell_env=shell_env if shell_env is not None else {},
        homenos=tmp_path,
        fixofs=fixofs,
        comout=comout,
        data=data,
        pdy="20260722",
        cyc="12",
        cycle="t12z",
        run_name=prefix,
        prefix_nos=prefix,
        nc_hour="06",
        sta_in=sta_in if sta_in is not None else tmp_path / "absent.sta.in",
        combine_script=tmp_path / "combine.py",
        pgmout=str(tmp_path / "pgmout"),
    )


def _stage_stacks(ctx: ProductContext, *phases) -> None:
    for suffix in phases:
        d = ctx.comout / f"{ctx.run_name}.{ctx.cycle}.{suffix}"
        d.mkdir(parents=True, exist_ok=True)
        # Profiles gate on the vertical families, not just out2d: a
        # 2D-only run has nothing for them to extract.
        for var in ("out2d", "zCoordinates"):
            (d / f"{var}_1.nc").write_bytes(b"\x89HDF\r\n")


def _fake_worker(calls: list):
    def run(cmd, *, cwd, log_path, scrub_ld_preload):
        calls.append(cmd)
        result_json = Path(cmd[cmd.index("--result-json") + 1])
        result_json.write_text(
            json.dumps({"created": [str(result_json.parent / "p.nc")]})
        )
        return 0
    return run


@pytest.mark.parametrize(
    "prefix,names",
    [
        # ATL: the fix set carries the ops system prefix, ours the variant
        # suffix -- PREFIXNOS alone would never find these.
        ("stofs_3d_atl_ufs", (
            "stofs_3d_atl_hgrid.gr3", "stofs_3d_atl_vgrid.in",
            "stofs_3d_atl_station.in",
        )),
        # SECOFS: PREFIXNOS-dotted spelling.
        ("secofs_ufs", (
            "secofs_ufs.hgrid.gr3", "secofs_ufs.vgrid.in",
            "secofs_ufs.station.in",
        )),
    ],
    ids=["ops_prefixed", "prefix_dotted"],
)
def test_product_resolves_both_fix_spellings_and_passes_outside_error(
    tmp_path, prefix, names
):
    fixofs = tmp_path / "fix"
    fixofs.mkdir()
    for name in names:
        (fixofs / name).write_text("stub\n")
    ctx = _ctx(tmp_path, fixofs, prefix)
    _stage_stacks(ctx, "restart_outputs", "forecast_outputs")

    calls: list = []
    with patch.object(
        post_stage, "_run_subprocess_appending", _fake_worker(calls)
    ):
        result = post_stage.ProfilesProduct().produce(ctx)

    assert result.status == "ok"
    assert len(result.outputs) == 2
    assert [c[c.index("--phase") + 1] for c in calls] == [
        "nowcast", "forecast",
    ]
    args = calls[0]
    assert args[:3] == ["python3", "-m", "nos_workflow.post.products.profiles"]
    assert [args[args.index(f) + 1] for f in
            ("--hgrid", "--vgrid", "--station-in")] == [
        str(fixofs / n) for n in names
    ]
    # The parity argument that defaults wrong in the writer.
    assert args[args.index("--outside") + 1] == "error"
    assert args[args.index("--base-date") + 1] == "2026-07-22 06:00:00"


def test_product_falls_back_to_the_stage_resolved_station_list(tmp_path):
    """$STA_OUT_CTL may name the station list anything; the stage has
    already resolved it, so an unusual name still runs."""
    fixofs = tmp_path / "fix"
    fixofs.mkdir()
    for name in ("secofs_ufs.hgrid.gr3", "secofs_ufs.vgrid.in"):
        (fixofs / name).write_text("stub\n")
    sta_in = fixofs / "sta_out_ctl_oddly_named.in"
    sta_in.write_text("stub\n")
    ctx = _ctx(tmp_path, fixofs, "secofs_ufs", sta_in=sta_in)
    _stage_stacks(ctx, "restart_outputs")

    calls: list = []
    with patch.object(
        post_stage, "_run_subprocess_appending", _fake_worker(calls)
    ):
        result = post_stage.ProfilesProduct().produce(ctx)

    assert result.status == "ok"
    assert calls[0][calls[0].index("--station-in") + 1] == str(sta_in)


def test_product_skipped_when_the_mesh_fix_is_absent(tmp_path):
    """A system without the profile fix set skips -- it must not fail."""
    fixofs = tmp_path / "fix"
    fixofs.mkdir()
    (fixofs / "secofs_ufs.station.in").write_text("stub\n")  # no h/vgrid
    ctx = _ctx(tmp_path, fixofs, "secofs_ufs")
    _stage_stacks(ctx, "restart_outputs", "forecast_outputs")

    calls: list = []
    with patch.object(
        post_stage, "_run_subprocess_appending", _fake_worker(calls)
    ):
        result = post_stage.ProfilesProduct().produce(ctx)

    assert result.status == "skipped"
    assert calls == []


def test_outside_override_is_reachable_from_the_environment(tmp_path):
    fixofs = tmp_path / "fix"
    fixofs.mkdir()
    for name in ("secofs_ufs.hgrid.gr3", "secofs_ufs.vgrid.in",
                 "secofs_ufs.station.in"):
        (fixofs / name).write_text("stub\n")
    ctx = _ctx(tmp_path, fixofs, "secofs_ufs",
               shell_env={"NOS_PROFILES_OUTSIDE": "nearest"})
    _stage_stacks(ctx, "forecast_outputs")

    calls: list = []
    with patch.object(
        post_stage, "_run_subprocess_appending", _fake_worker(calls)
    ):
        assert post_stage.ProfilesProduct().produce(ctx).status == "ok"

    assert calls[0][calls[0].index("--outside") + 1] == "nearest"


# ---------------------------------------------------------------------------
# Stage wiring
# ---------------------------------------------------------------------------


def test_stage_runs_profiles_on_both_legs(tmp_path):
    from nos_workflow.tests.test_post_stage import (
        _make_minimal_post_env, _secofs_ufs_desc,
    )

    env = _make_minimal_post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "profiles"
    env["OFS_CONFIG"] = ""
    fixofs = Path(env["FIXofs"])
    _write_hgrid(fixofs / f"{env['PREFIXNOS']}.hgrid.gr3")
    _write_vgrid(fixofs / f"{env['PREFIXNOS']}.vgrid.in")
    comout = Path(env["COMOUT"])
    for sub in ("restart_outputs", "forecast_outputs"):
        d = comout / f"{env['RUN']}.{env['cycle']}.{sub}"
        d.mkdir(parents=True)
        for var in ("out2d", "zCoordinates"):
            (d / f"{var}_1.nc").write_bytes(b"\x89HDF\r\n")

    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        args = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
        Path(args["--result-json"]).write_text(
            json.dumps({"created": [str(comout / f"{args['--phase']}.nc")]})
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch.dict(os.environ, env, clear=False):
        with patch.object(post_stage.subprocess, "run", side_effect=fake_run):
            assert post_stage.run(_secofs_ufs_desc(), object()) == 0

    assert len(calls) == 2
    assert all("nos_workflow.post.products.profiles" in c for c in calls)
    # The stage already resolves station.in; it is reused here.
    assert calls[0][calls[0].index("--station-in") + 1] == str(
        fixofs / f"{env['PREFIXNOS']}.station.in"
    )
    manifest = json.loads(
        (comout / (
            f"{env['RUN']}.t{env['cyc']}z.{env['PDY']}.outputs.post.json"
        )).read_text()
    )
    entry = {p["name"]: p for p in manifest["products"]}["profiles"]
    assert entry["status"] == "ok"
    assert len(entry["outputs"]) == 2


def test_profiles_skips_a_2d_only_staging_dir(tmp_path):
    """A barotropic run stages out2d and nothing else. Reporting failure
    there would repeat the same error every cycle for a system that can
    never produce a vertical profile."""
    fixofs = tmp_path / "fix"
    fixofs.mkdir(exist_ok=True)
    ctx = _ctx(tmp_path, fixofs, "stofs_3d_atl_ufs")
    for suffix in ("restart_outputs", "forecast_outputs"):
        d = ctx.comout / f"{ctx.run_name}.{ctx.cycle}.{suffix}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "out2d_1.nc").write_bytes(b"\x89HDF\r\n")
    _write_hgrid(fixofs / f"{ctx.prefix_nos}.hgrid.gr3")
    _write_vgrid(fixofs / f"{ctx.prefix_nos}.vgrid.in")
    _write_station_in(fixofs / f"{ctx.prefix_nos}.station.in")

    result = get_product("profiles")().produce(ctx)

    assert result.status == "skipped"
    assert not result.outputs
