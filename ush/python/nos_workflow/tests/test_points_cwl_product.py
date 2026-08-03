"""Tests for the points_cwl product (worker + stage registration).

Fixtures are synthetic but reproduce the real fix-file layout: the
staout-nc JSON with its ``stardard_name`` typo key, and the ';'-separated
station CSV whose ``lat``/``lon`` headers are swapped relative to its data
(the writer reads by header name, so ops ``x`` carries latitudes -- that
quirk is asserted here, not corrected).
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from nos_workflow.post.base import ProductContext
from nos_workflow.post.naming import points_cwl_name
from nos_workflow.post.registry import get_product
from nos_workflow.post.products import points_cwl
from nos_workflow.post.worker_base import fix_file
from nos_workflow.stages import post as post_stage

REPO_ROOT = Path(__file__).resolve().parents[4]


def _prefer_in_tree_nos_utils() -> None:
    """Import nos-utils from the pinned submodule when the installed copy
    predates ``nos_utils.post``.

    Development happens in git worktrees, where an editable install of
    the main checkout shadows the worktree's own (newer) submodule.
    """
    try:
        import nos_utils.post  # noqa: F401
        return
    except ImportError:
        pass
    submodule = Path(__file__).resolve().parents[2] / "nos-utils"
    if not (submodule / "nos_utils" / "post").is_dir():
        return
    for name in [m for m in sys.modules if m.split(".")[0] == "nos_utils"]:
        del sys.modules[name]
    sys.path.insert(0, str(submodule))
    importlib.invalidate_caches()


def _have(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ImportError:
        return False


_prefer_in_tree_nos_utils()

needs_writer = pytest.mark.skipif(
    not all(_have(m) for m in ("nos_utils.post", "scipy", "netCDF4")),
    reason="nos_utils.post / scipy / netCDF4 unavailable",
)

# Ops ATL variable set, in fix-file order (elev first defines the axis).
VAR_DEFS = {
    "elev": {
        "name": "zeta",
        "long_name": "water surface elevation above navd88",
        "stardard_name": "sea_surface_height_above_navd88",
        "units": "m",
        "staout_fname": "staout_1",
    },
    "temp": {
        "name": "temperature",
        "long_name": "temperature at water surface",
        "stardard_name": "sea_surface_temperature",
        "units": "degree_C",
        "staout_fname": "staout_5",
    },
    "salt": {
        "name": "salinity",
        "long_name": "salinity at water surface",
        "stardard_name": "sea_surface_salinity",
        "units": "psu",
        "staout_fname": "staout_6",
    },
    "uvel": {
        "name": "u",
        "long_name": "u component of surface velocity",
        "stardard_name": "eastward_surface_velocity",
        "units": "meters s-1",
        "staout_fname": "staout_7",
    },
    "vvel": {
        "name": "v",
        "long_name": "v component of surface velocity",
        "stardard_name": "northward_surface_velocity",
        "units": "meters s-1",
        "staout_fname": "staout_8",
    },
}

STAOUT_INDICES = (1, 5, 6, 7, 8)
TIMES = (0.0, 360.0, 720.0, 1080.0)
NSTATION = 3
# name, lon, lat -- as the data columns are actually ordered.
STATIONS = (
    ("PSBM1 SOUS41 8410140 ME Eastport", -66.9829080647, 44.9046093476),
    ("CASM1 SOUS41 8418150 ME Portland", -70.2441759693, 43.6580707255),
    ("BHBM3 SOUS41 8443970 MA Boston", -71.0502859522, 42.3539103827),
)
DATUM_CONSTANTS = (-0.30516, -0.32039, 0.00371)


def _value(idx: int, station: int, t: float) -> float:
    """Distinct, linear-in-time value so interpolation is exact."""
    return 100.0 * idx + 10.0 * station + t / 360.0


def _write_staout(staging: Path, idx: int) -> None:
    lines = [
        " ".join(
            [f"{t:.1f}"]
            + [f"{_value(idx, s, t):.6f}" for s in range(NSTATION)]
        )
        for t in TIMES
    ]
    (staging / f"staout_{idx}").write_text("\n".join(lines) + "\n")


def _stage_staout(staging: Path, indices=STAOUT_INDICES) -> Path:
    staging.mkdir(parents=True, exist_ok=True)
    for idx in indices:
        _write_staout(staging, idx)
    return staging


def _write_fix_pair(fixofs: Path, stem: str = "stofs_3d_atl") -> None:
    """The ops staout-nc JSON/CSV pair under their real ATL names."""
    fixofs.mkdir(parents=True, exist_ok=True)
    (fixofs / f"{stem}_staout_nc.json").write_text(json.dumps(VAR_DEFS))
    rows = [";station_info;lat;lon"] + [
        f"{i};{name};{lon};{lat}"
        for i, (name, lon, lat) in enumerate(STATIONS)
    ]
    (fixofs / f"{stem}_staout_nc.csv").write_text("\n".join(rows) + "\n")


def _write_nco(path: Path, constants=DATUM_CONSTANTS) -> Path:
    path.write_text(
        "\n".join(
            f"zeta(:,{i + 1})=zeta(:,{i + 1})-float({c});"
            for i, c in enumerate(constants)
        )
        + "\n"
    )
    return path


def _run_worker(staging: Path, comout: Path, tmp_path: Path, **extra) -> dict:
    fixofs = tmp_path / "fix"
    _write_fix_pair(fixofs)
    result_json = tmp_path / "result.json"
    argv = [
        "--staging", str(staging),
        "--comout", str(comout),
        "--prefix", "stofs_3d_atl_ufs",
        "--cyc", "12",
        "--pdy", "20260722",
        "--phase", "nowcast",
        "--base-date", "2026-07-22 06:00",
        "--var-defs", str(fixofs / "stofs_3d_atl_staout_nc.json"),
        "--station-meta", str(fixofs / "stofs_3d_atl_staout_nc.csv"),
        "--result-json", str(result_json),
    ]
    for flag, value in extra.items():
        argv += [f"--{flag.replace('_', '-')}", str(value)]
    rc = points_cwl.main(argv)
    assert rc == 0
    return json.loads(result_json.read_text())


# ---------------------------------------------------------------------------
# Naming / registration
# ---------------------------------------------------------------------------


def test_canonical_name_carries_stem_and_phase():
    assert points_cwl_name(
        "stofs_3d_atl_ufs", "12", "20260722", "forecast"
    ) == "stofs_3d_atl_ufs.t12z.20260722.points.cwl.forecast.nc"


def test_product_is_registered_for_both_phases():
    cls = get_product("points_cwl")
    assert cls is post_stage.PointsCwlProduct
    assert cls.worker == "nos_workflow.post.products.points_cwl"
    assert tuple(cls.phases) == ("nowcast", "forecast")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


@needs_writer
def test_publishes_canonical_nc_with_writer_values(tmp_path):
    import netCDF4
    import numpy as np

    # The writer interpolates staout via scipy before it writes.
    pytest.importorskip("scipy")

    comout = tmp_path / "comout"
    comout.mkdir()
    result = _run_worker(_stage_staout(tmp_path / "staging"), comout, tmp_path)

    out = comout / "stofs_3d_atl_ufs.t12z.20260722.points.cwl.nowcast.nc"
    assert result["created"] == [str(out)]
    assert out.is_file()

    with netCDF4.Dataset(out) as ds:
        assert ds.dimensions["station"].size == NSTATION
        assert ds.dimensions["namelen"].size == 50
        # 6-minute axis from the first sample to the last staout time.
        assert list(np.asarray(ds["time"][:])) == [360.0, 720.0, 1080.0]
        assert ds["time"].units == "seconds since 2026-07-22 06:00"
        assert sorted(
            v for v in ds.variables
            if v not in ("time", "station_name", "x", "y")
        ) == ["salinity", "temperature", "u", "v", "zeta"]

        for var, idx in (
            ("zeta", 1), ("temperature", 5), ("salinity", 6),
            ("u", 7), ("v", 8),
        ):
            expected = np.array([
                [_value(idx, s, t) for s in range(NSTATION)]
                for t in (360.0, 720.0, 1080.0)
            ])
            assert np.asarray(ds[var][:]) == pytest.approx(expected)

        assert ds["zeta"].standard_name == "sea_surface_height_above_navd88"
        assert ds["salinity"].units == "psu"

        names = [
            b"".join(row).decode().rstrip("\x00")
            for row in np.asarray(ds["station_name"][:])
        ]
        assert names == [s[0] for s in STATIONS]
        # Ops quirk preserved: the column headed "lon" holds latitudes.
        assert np.asarray(ds["x"][:]) == pytest.approx(
            [lat for _n, _lon, lat in STATIONS]
        )
        assert np.asarray(ds["y"][:]) == pytest.approx(
            [lon for _n, lon, _lat in STATIONS]
        )


@needs_writer
def test_datum_offsets_negate_the_nco_constants(tmp_path):
    import netCDF4
    import numpy as np

    # The writer interpolates staout via scipy before it writes.
    pytest.importorskip("scipy")

    comout = tmp_path / "comout"
    comout.mkdir()
    _run_worker(
        _stage_staout(tmp_path / "staging"), comout, tmp_path,
        datum_offsets=_write_nco(tmp_path / "xgeoid_to_navd.nco"),
    )

    out = comout / "stofs_3d_atl_ufs.t12z.20260722.points.cwl.nowcast.nc"
    with netCDF4.Dataset(out) as ds:
        # ops subtracts the .nco constant; the writer adds what we pass.
        expected = np.array([
            [_value(1, s, t) - DATUM_CONSTANTS[s] for s in range(NSTATION)]
            for t in (360.0, 720.0, 1080.0)
        ])
        assert np.asarray(ds["zeta"][:]) == pytest.approx(expected)
        # Only the elevation variable is shifted.
        assert np.asarray(ds["temperature"][:]) == pytest.approx(
            np.array([
                [_value(5, s, t) for s in range(NSTATION)]
                for t in (360.0, 720.0, 1080.0)
            ])
        )


def test_worker_skips_when_staout_1_absent(tmp_path):
    comout = tmp_path / "comout"
    comout.mkdir()
    fixofs = tmp_path / "fix"
    _write_fix_pair(fixofs)
    staging = _stage_staout(tmp_path / "staging", indices=(5, 6, 7, 8))

    rc = points_cwl.main([
        "--staging", str(staging),
        "--comout", str(comout),
        "--prefix", "stofs_3d_atl_ufs",
        "--cyc", "12", "--pdy", "20260722", "--phase", "nowcast",
        "--base-date", "2026-07-22 06:00",
        "--var-defs", str(fixofs / "stofs_3d_atl_staout_nc.json"),
        "--station-meta", str(fixofs / "stofs_3d_atl_staout_nc.csv"),
    ])

    assert rc == 3
    assert list(comout.iterdir()) == []


def test_worker_reports_missing_staging_and_metadata(tmp_path):
    comout = tmp_path / "comout"
    comout.mkdir()
    base = [
        "--comout", str(comout), "--prefix", "stofs_3d_atl_ufs",
        "--cyc", "12", "--pdy", "20260722", "--phase", "nowcast",
        "--base-date", "2026-07-22 06:00",
        "--station-meta", str(tmp_path / "nope.csv"),
    ]
    assert points_cwl.main(
        ["--staging", str(tmp_path / "nope"),
         "--var-defs", str(tmp_path / "nope.json")] + base
    ) == 2

    staging = _stage_staout(tmp_path / "staging")
    assert points_cwl.main(
        ["--staging", str(staging),
         "--var-defs", str(tmp_path / "nope.json")] + base
    ) == 5


def test_worker_rejects_a_partial_datum_file(tmp_path):
    """A gap in the .nco numbering must not silently half-shift zeta."""
    nco = tmp_path / "partial.nco"
    nco.write_text(
        "zeta(:,1)=zeta(:,1)-float(-0.30516);\n"
        "zeta(:,3)=zeta(:,3)-float(0.00371);\n"
    )
    with pytest.raises(ValueError, match="station"):
        points_cwl._nco_offsets(nco)

    empty = tmp_path / "empty.nco"
    empty.write_text("// nothing here\n")
    assert points_cwl._nco_offsets(empty) is None


# ---------------------------------------------------------------------------
# Product wiring
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path, fixofs: Path) -> ProductContext:
    comout = tmp_path / "comout"
    comout.mkdir(exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return ProductContext(
        descriptor=None,
        shell_env={},
        homenos=tmp_path,
        fixofs=fixofs,
        comout=comout,
        data=data,
        pdy="20260722",
        cyc="12",
        cycle="t12z",
        run_name="stofs_3d_atl_ufs",
        prefix_nos="stofs_3d_atl_ufs",
        nc_hour="06",
        sta_in=tmp_path / "station.in",
        combine_script=tmp_path / "combine.py",
        pgmout=str(tmp_path / "pgmout"),
    )


def _fake_worker(calls: list):
    def run(cmd, *, cwd, log_path, scrub_ld_preload):
        calls.append(cmd)
        result_json = Path(cmd[cmd.index("--result-json") + 1])
        result_json.write_text(
            json.dumps({"created": [str(result_json.parent / "out.nc")]})
        )
        return 0
    return run


def test_product_runs_both_phases_with_ops_prefixed_fix(tmp_path):
    fixofs = tmp_path / "fix"
    _write_fix_pair(fixofs)
    _write_nco(fixofs / "stofs_3d_atl_sta_cwl_xgeoid_to_navd.nco")
    ctx = _ctx(tmp_path, fixofs)
    for suffix in ("restart_outputs", "forecast_outputs"):
        _stage_staout(ctx.comout / f"stofs_3d_atl_ufs.t12z.{suffix}")

    calls: list = []
    with patch.object(
        post_stage, "_run_subprocess_appending", _fake_worker(calls)
    ):
        result = post_stage.PointsCwlProduct().produce(ctx)

    assert result.status == "ok"
    assert len(result.outputs) == 2
    assert [c[c.index("--phase") + 1] for c in calls] == [
        "nowcast", "forecast",
    ]
    args = calls[0]
    assert args[:3] == [
        "python3", "-m", "nos_workflow.post.products.points_cwl",
    ]
    # PREFIXNOS is stofs_3d_atl_ufs; the fix files carry the ops prefix.
    assert args[args.index("--var-defs") + 1] == str(
        fixofs / "stofs_3d_atl_staout_nc.json"
    )
    assert args[args.index("--station-meta") + 1] == str(
        fixofs / "stofs_3d_atl_staout_nc.csv"
    )
    assert args[args.index("--datum-offsets") + 1] == str(
        fixofs / "stofs_3d_atl_sta_cwl_xgeoid_to_navd.nco"
    )
    # cyc 12 - 6 h nowcast = same day 06Z (no midnight wrap here).
    # Seconds are present: ops units strings carry them.
    assert args[args.index("--base-date") + 1] == "2026-07-22 06:00:00"


def test_product_skips_a_phase_without_staout(tmp_path):
    fixofs = tmp_path / "fix"
    _write_fix_pair(fixofs)
    ctx = _ctx(tmp_path, fixofs)
    _stage_staout(ctx.comout / "stofs_3d_atl_ufs.t12z.restart_outputs")
    (ctx.comout / "stofs_3d_atl_ufs.t12z.forecast_outputs").mkdir()

    calls: list = []
    with patch.object(
        post_stage, "_run_subprocess_appending", _fake_worker(calls)
    ):
        result = post_stage.PointsCwlProduct().produce(ctx)

    assert result.status == "ok"
    assert [c[c.index("--phase") + 1] for c in calls] == ["nowcast"]
    # No datum file staged -> the flag is omitted entirely.
    assert "--datum-offsets" not in calls[0]


def test_product_skipped_when_fix_metadata_absent(tmp_path):
    """SECOFS has no staout-nc fix pair: skip, do not fail."""
    fixofs = tmp_path / "fix"
    fixofs.mkdir()
    ctx = _ctx(tmp_path, fixofs)
    for suffix in ("restart_outputs", "forecast_outputs"):
        _stage_staout(ctx.comout / f"stofs_3d_atl_ufs.t12z.{suffix}")

    calls: list = []
    with patch.object(
        post_stage, "_run_subprocess_appending", _fake_worker(calls)
    ):
        result = post_stage.PointsCwlProduct().produce(ctx)

    assert result.status == "skipped"
    assert calls == []


# ---------------------------------------------------------------------------
# Station coordinate plausibility (advisory; never rewrites values)
# ---------------------------------------------------------------------------


def _write_coord_nc(path: Path, coords, names=None):
    netCDF4 = pytest.importorskip("netCDF4")
    import numpy as np

    names = names or [f"S{i}" for i in range(len(coords))]
    with netCDF4.Dataset(path, "w", format="NETCDF4") as ds:
        ds.createDimension("station", len(coords))
        ds.createDimension("namelen", 24)
        xv = ds.createVariable("x", "f8", ("station",))
        yv = ds.createVariable("y", "f8", ("station",))
        xv[:] = [c[0] for c in coords]
        yv[:] = [c[1] for c in coords]
        nv = ds.createVariable("station_name", "S1", ("station", "namelen"))
        nv[:] = np.array(
            [list(n.ljust(24)[:24]) for n in names], dtype="S1"
        )


def test_transposed_station_is_named(tmp_path, capsys):
    """The ops ATL fix set keys 3 of its 108 rows the opposite way round
    to the rest; those stations publish transposed, silently."""
    nc = tmp_path / "p.nc"
    # x carries latitudes and y longitudes here, as the ops pair yields.
    coords = [(30.0 + i * 0.5, -80.0 - i * 0.5) for i in range(10)]
    # A station in the middle of the domain, keyed the other way round.
    coords.insert(5, (-82.0, 32.0))
    _write_coord_nc(nc, coords, names=[f"STA{i}" for i in range(11)])

    points_cwl._warn_transposed_coords(nc, "fix.csv")

    out = capsys.readouterr().out
    assert "1 of 11 stations" in out
    assert "STA5" in out
    assert "fix.csv" in out


def test_consistent_stations_are_not_flagged(tmp_path, capsys):
    nc = tmp_path / "p.nc"
    _write_coord_nc(nc, [(30.0 + i * 0.5, -80.0 - i * 0.5) for i in range(11)])

    points_cwl._warn_transposed_coords(nc, "fix.csv")

    assert "WARNING" not in capsys.readouterr().out


def test_far_flung_station_is_not_flagged_as_transposed(tmp_path, capsys):
    """An outlier only counts as transposed if the swap actually fits --
    a genuinely distant station must not be reported."""
    nc = tmp_path / "p.nc"
    coords = [(30.0 + i * 0.5, -80.0 - i * 0.5) for i in range(10)]
    coords.insert(5, (12.0, -140.0))  # far away, but not a swap
    _write_coord_nc(nc, coords)

    points_cwl._warn_transposed_coords(nc, "fix.csv")

    assert "WARNING" not in capsys.readouterr().out


def test_coordinate_check_never_raises_on_a_bad_file(tmp_path, capsys):
    missing = tmp_path / "nope.nc"
    points_cwl._warn_transposed_coords(missing, "fix.csv")
    assert "coordinate check skipped" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# STOFS-3D-AK: the fix pair shipped in the repo (fix/stofs_3d_ak_ufs/)
# ---------------------------------------------------------------------------

AK_FIXOFS = REPO_ROOT / "fix" / "stofs_3d_ak_ufs"
AK_JSON = AK_FIXOFS / "stofs_3d_ak_staout_nc.json"
AK_CSV = AK_FIXOFS / "stofs_3d_ak_staout_nc.csv"
AK_NSTATION = 22
# First/last row, straight from fix/stofs_3d_ak_ufs.station.in (22 stations,
# row order 1..22): row 1 is the first CO-OPS gauge, row 22 the last of the
# five synthetic "modulation" points with no real-world gauge.
AK_FIRST_STATION = ("CO-OPS 9459450 AK Sand Point", 199.496, 55.332)
AK_LAST_STATION = ("SYNTHETIC AK modulation5 (no gauge)", 184.621, 51.986)


def _ak_ctx(tmp_path: Path) -> ProductContext:
    comout = tmp_path / "comout"
    comout.mkdir(exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return ProductContext(
        descriptor=None,
        shell_env={},
        homenos=REPO_ROOT,
        fixofs=AK_FIXOFS,
        comout=comout,
        data=data,
        pdy="20260803",
        cyc="00",
        cycle="t00z",
        run_name="stofs_3d_ak_ufs",
        prefix_nos="stofs_3d_ak_ufs",
        nc_hour="00",
        sta_in=AK_FIXOFS / "stofs_3d_ak_ufs.station.in",
        combine_script=tmp_path / "combine.py",
        pgmout=str(tmp_path / "pgmout"),
    )


def test_ak_fix_pair_is_shipped_in_the_repo():
    """Both files exist in-tree, unlike the S3-fetched grid/mesh fix set."""
    assert AK_JSON.is_file()
    assert AK_CSV.is_file()


def test_ak_var_defs_json_is_valid_and_elev_defines_the_axis():
    var_defs = json.loads(AK_JSON.read_text())

    assert isinstance(var_defs, dict) and var_defs
    # First entry is elevation, exactly as the ATL ops file and the writer
    # both require (write_station_timeseries uses entry 0 for the axis).
    first_key, first_spec = next(iter(var_defs.items()))
    assert first_key == "elev"
    assert first_spec["staout_fname"] == "staout_1"

    # station.in flag order for stofs_3d_ak_ufs is "elev air pressure windx
    # windy T S u v w" -- identical to ATL's -- so temp/salt/u/v map to the
    # same staout indices ATL uses (5/6/7/8), skipping pressure/wind/w.
    by_name = {spec["name"]: spec["staout_fname"] for spec in var_defs.values()}
    assert by_name == {
        "zeta": "staout_1",
        "u": "staout_7",
        "v": "staout_8",
        "salinity": "staout_6",
        "temperature": "staout_5",
    }
    for spec in var_defs.values():
        assert {"name", "long_name", "units", "staout_fname"} <= spec.keys()
        assert "stardard_name" in spec or "standard_name" in spec

    # No datum-offset fix file ships for Alaska (yaml's obc.ssh_offset is
    # null, unverified) -- the metadata must not claim a shifted datum.
    assert "navd" not in var_defs["elev"]["long_name"].lower()
    assert "msl" not in var_defs["elev"]["long_name"].lower()


@needs_writer
def test_ak_station_csv_has_22_rows_in_station_in_order():
    from nos_utils.post.stations import load_station_csv

    rows = load_station_csv(AK_CSV)

    assert len(rows) == AK_NSTATION
    assert rows[0] == AK_FIRST_STATION
    assert rows[-1] == AK_LAST_STATION
    # 0-360 convention throughout (this domain spans the dateline; do not
    # expect -180..180 the way the ATL pair uses).
    for _name, lon, lat in rows:
        assert 150.0 <= lon <= 210.0
        assert 45.0 <= lat <= 70.0


def test_ak_fix_file_gate_resolves_both_files_under_the_ops_name(tmp_path):
    """The points_cwl gate (post.py PointsCwlProduct.worker_args) tries the
    ops-prefixed name first ('stofs_3d_ak', prefix_nos.split('_ufs')[0]) --
    the candidate our shipped files are named for."""
    ctx = _ak_ctx(tmp_path)
    ops = ctx.prefix_nos.split("_ufs")[0]
    assert ops == "stofs_3d_ak"

    var_defs = fix_file(ctx, "staout_nc.json", f"{ops}_staout_nc.json")
    meta = fix_file(ctx, "staout_nc.csv", f"{ops}_staout_nc.csv")

    assert var_defs == AK_JSON
    assert meta == AK_CSV


def _ak_write_staout(staging: Path, idx: int, times=(0.0, 360.0, 720.0)) -> None:
    def value(station: int, t: float) -> float:
        return 1000.0 * idx + 10.0 * station + t / 360.0

    lines = [
        " ".join([f"{t:.1f}"] + [f"{value(s, t):.6f}" for s in range(AK_NSTATION)])
        for t in times
    ]
    (staging / f"staout_{idx}").write_text("\n".join(lines) + "\n")


@needs_writer
def test_ak_product_publishes_22_stations_with_the_shipped_fix_pair(tmp_path):
    """End-to-end worker run against the real, in-repo AK fix pair (not a
    synthetic fixture): 22 fabricated staout columns in, one nowcast
    points.cwl.nc out, with the station dimension and canonical name the
    orchestrator expects for stofs_3d_ak_ufs."""
    import netCDF4
    import numpy as np
    pytest.importorskip("scipy")

    staging = tmp_path / "staging"
    staging.mkdir()
    for idx in (1, 5, 6, 7, 8):
        _ak_write_staout(staging, idx)

    comout = tmp_path / "comout"
    comout.mkdir()
    result_json = tmp_path / "result.json"
    rc = points_cwl.main([
        "--staging", str(staging),
        "--comout", str(comout),
        "--prefix", "stofs_3d_ak_ufs",
        "--cyc", "00",
        "--pdy", "20260803",
        "--phase", "nowcast",
        "--base-date", "2026-08-03 00:00",
        "--var-defs", str(AK_JSON),
        "--station-meta", str(AK_CSV),
        "--result-json", str(result_json),
    ])
    assert rc == 0

    out = comout / "stofs_3d_ak_ufs.t00z.20260803.points.cwl.nowcast.nc"
    assert json.loads(result_json.read_text())["created"] == [str(out)]
    assert out.is_file()

    with netCDF4.Dataset(out) as ds:
        assert ds.dimensions["station"].size == AK_NSTATION
        assert sorted(
            v for v in ds.variables
            if v not in ("time", "station_name", "x", "y")
        ) == ["salinity", "temperature", "u", "v", "zeta"]
        names = [
            b"".join(row).decode().rstrip("\x00")
            for row in np.asarray(ds["station_name"][:])
        ]
        assert names[0] == AK_FIRST_STATION[0]
        assert names[-1] == AK_LAST_STATION[0]
        # Correct keying (no ATL-style header/data swap): x is longitude.
        assert float(np.asarray(ds["x"][:])[0]) == pytest.approx(199.496)
        assert float(np.asarray(ds["y"][:])[0]) == pytest.approx(55.332)


def test_ak_product_wiring_omits_datum_offsets_and_warns(tmp_path, caplog):
    """No stofs_3d_ak(_ufs)_sta_cwl_xgeoid_to_{msl,navd}.nco ships yet, so
    the product must still run (gate satisfied by the json/csv pair alone)
    but must not pass --datum-offsets, and must log why."""
    ctx = _ak_ctx(tmp_path)
    for suffix in ("restart_outputs", "forecast_outputs"):
        staging = ctx.comout / f"stofs_3d_ak_ufs.t00z.{suffix}"
        staging.mkdir(parents=True, exist_ok=True)
        for idx in (1, 5, 6, 7, 8):
            _ak_write_staout(staging, idx)

    calls: list = []
    with patch.object(
        post_stage, "_run_subprocess_appending", _fake_worker(calls)
    ):
        with caplog.at_level("WARNING"):
            result = post_stage.PointsCwlProduct().produce(ctx)

    assert result.status == "ok"
    assert len(calls) == 2
    for args in calls:
        assert args[args.index("--var-defs") + 1] == str(AK_JSON)
        assert args[args.index("--station-meta") + 1] == str(AK_CSV)
        assert "--datum-offsets" not in args
    assert any("xgeoid" in r.message.lower() for r in caplog.records)
